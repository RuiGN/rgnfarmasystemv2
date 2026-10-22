from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient


User = get_user_model()


def create_training_users(suffix='001'):
    trainee = User.objects.create_user(
        username=f'trainee-{suffix}@example.com',
        email=f'trainee-{suffix}@example.com',
        password='S3curePass!123',
    )
    trainer = User.objects.create_user(
        username=f'trainer-{suffix}@example.com',
        email=f'trainer-{suffix}@example.com',
        password='S3curePass!123',
    )
    approver = User.objects.create_user(
        username=f'approver-{suffix}@example.com',
        email=f'approver-{suffix}@example.com',
        password='S3curePass!123',
    )
    return trainee, trainer, approver


def create_training_document(owner, suffix='001'):
    from documents.models import ControlledDocument

    return ControlledDocument.objects.create(
        document_type=ControlledDocument.DocumentType.SOP,
        code=f'POP-TRN-{suffix}',
        title=f'Procedimento crítico de treinamento {suffix}',
        area='Garantia da Qualidade',
        version='1.0',
        effective_from=timezone.localdate(),
        valid_until=timezone.localdate() + timedelta(days=365),
        owner=owner,
        content='Procedimento controlado para atividade crítica.',
        change_summary='Emissão inicial.',
    )


class TrainingModelTests(TestCase):
    def test_enrollment_number_is_persisted_during_partial_update(self):
        from training.models import TrainingEnrollment, TrainingRequirement

        trainee, _trainer, _approver = create_training_users('partial-identifier')
        requirement = TrainingRequirement.objects.create(
            code='TR-PARTIAL-IDENTIFIER',
            title='Treinamento legado',
            training_type=TrainingRequirement.TrainingType.REGULATORY,
            area='Garantia da Qualidade',
        )
        enrollment = TrainingEnrollment.objects.create(
            enrollment_number='REGISTRO-LEGADO',
            requirement=requirement,
            user=trainee,
        )
        TrainingEnrollment.objects.filter(pk=enrollment.pk).update(enrollment_number='')
        enrollment.refresh_from_db()

        enrollment.due_date = timezone.localdate() + timedelta(days=10)
        enrollment.save(update_fields=['due_date', 'updated_at'])
        enrollment.refresh_from_db()

        assert enrollment.enrollment_number.startswith('TRN-')

    def test_certificate_number_is_unique_when_filled(self):
        from training.models import TrainingEnrollment, TrainingRequirement

        first_user, second_user, _approver = create_training_users('certificate')
        requirement = TrainingRequirement.objects.create(
            code='TR-CERTIFICATE-001',
            title='Treinamento com certificado',
            training_type=TrainingRequirement.TrainingType.REGULATORY,
            area='Garantia da Qualidade',
        )
        TrainingEnrollment.objects.create(
            requirement=requirement,
            user=first_user,
            certificate_number='CERTIFICADO-ÚNICO-001',
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            TrainingEnrollment.objects.create(
                requirement=requirement,
                user=second_user,
                certificate_number='CERTIFICADO-ÚNICO-001',
            )

    def test_rf24_training_matrix_lifecycle_certificate_and_critical_activity_block(self):
        from training.models import (
            Competency,
            CriticalActivityRule,
            JobPosition,
            TrainingEnrollment,
            TrainingMatrixRequirement,
            TrainingRequirement,
            TrainingSession,
            WorkFunction,
        )

        trainee, trainer, approver = create_training_users()
        document = create_training_document(approver)
        position = JobPosition.objects.create(
            code='POS-OP-PROD',
            title='Operador de produção',
            area='Produção',
            department='Sólidos',
        )
        function = WorkFunction.objects.create(
            code='FUNC-COMPRESSAO',
            name='Operar compressora',
            job_position=position,
            area='Produção',
            process='Compressão',
            is_critical=True,
        )
        competency = Competency.objects.create(
            code='COMP-GMP-COMP',
            name='BPF aplicada à compressão',
            competency_type=Competency.CompetencyType.GMP,
        )
        requirement = TrainingRequirement.objects.create(
            code='TRN-COMP-001',
            title='Operação segura de compressora',
            training_type=TrainingRequirement.TrainingType.CRITICAL_ACTIVITY,
            area='Produção',
            process='Compressão',
            job_position=position,
            function=function,
            competency=competency,
            document=document,
            module_code='production',
            regulatory_requirement_reference='RDC-658/2022',
            validity_days=180,
            alert_before_days=30,
            passing_score=80,
            requires_evaluation=True,
            requires_certificate=True,
            block_without_valid_training=True,
        )
        matrix_entry = TrainingMatrixRequirement.objects.create(
            job_position=position,
            function=function,
            competency=competency,
            requirement=requirement,
            is_mandatory=True,
            priority=TrainingMatrixRequirement.Priority.CRITICAL,
        )
        rule = CriticalActivityRule.objects.create(
            activity_code='PROD-COMP-START',
            name='Iniciar compressão de lote',
            requirement=requirement,
            enforcement_mode=CriticalActivityRule.EnforcementMode.BLOCK,
            area='Produção',
            process='Compressão',
            module_code='production',
        )

        with pytest.raises(ValidationError) as blocked_without_training:
            rule.authorize_user(trainee)

        session = TrainingSession.objects.create(
            requirement=requirement,
            title='Turma de compressão',
            scheduled_start=timezone.now() + timedelta(days=1),
            scheduled_end=timezone.now() + timedelta(days=1, hours=2),
            instructor=trainer,
        )
        enrollment = session.convocate(
            user=trainee, convoked_by=approver, due_date=timezone.localdate() + timedelta(days=7)
        )
        enrollment.start(user=trainee)

        with pytest.raises(ValidationError) as low_score:
            enrollment.complete(
                score=70,
                evidence_reference='training/evidencias/comp.pdf',
                content_hash='sha256:comp',
                user=trainer,
            )

        enrollment.complete(
            score=95,
            evidence_reference='training/evidencias/comp.pdf',
            content_hash='sha256:comp',
            user=trainer,
        )
        enrollment.approve(user=approver, certificate_reference='training/certificados/comp.pdf')
        enrollment.refresh_from_db()

        assert 'training' in blocked_without_training.value.message_dict
        assert 'score' in low_score.value.message_dict
        assert matrix_entry.requirement == requirement
        assert enrollment.status == TrainingEnrollment.Status.APPROVED
        assert enrollment.valid_until == timezone.localdate() + timedelta(days=180)
        assert enrollment.recertification_due_date == enrollment.valid_until - timedelta(days=30)
        assert enrollment.certificate_number.startswith('CERT-')
        assert rule.authorize_user(trainee) is True

        enrollment.valid_until = timezone.localdate() - timedelta(days=1)
        enrollment.save(update_fields=['valid_until', 'updated_at'])
        with pytest.raises(ValidationError):
            rule.authorize_user(trainee)

    def test_rf24_supports_required_links_and_generates_compliance_indicators(self):
        from training.models import (
            Competency,
            JobPosition,
            TrainingEnrollment,
            TrainingIndicatorReport,
            TrainingRequirement,
            TrainingSession,
            WorkFunction,
        )

        trainee, trainer, approver = create_training_users()
        late_user = User.objects.create_user(
            username='late-training@example.com',
            email='late-training@example.com',
            password='S3curePass!123',
        )
        document = create_training_document(approver)
        position = JobPosition.objects.create(
            code='POS-CQ', title='Analista CQ', area='Controle de Qualidade'
        )
        function = WorkFunction.objects.create(
            code='FUNC-HPLC',
            name='Operar HPLC',
            job_position=position,
            area='CQ',
            process='Análise',
        )
        competency = Competency.objects.create(
            code='COMP-HPLC',
            name='Análise cromatográfica',
            competency_type=Competency.CompetencyType.TECHNICAL,
        )
        requirement = TrainingRequirement.objects.create(
            code='TRN-HPLC-001',
            title='Treinamento HPLC',
            training_type=TrainingRequirement.TrainingType.CRITICAL_ACTIVITY,
            area='CQ',
            process='Análise',
            job_position=position,
            function=function,
            competency=competency,
            document=document,
            module_code='quality',
            regulatory_requirement_reference='ICH Q2(R2)',
            validity_days=90,
            alert_before_days=30,
            passing_score=80,
            requires_evaluation=True,
            requires_certificate=True,
        )
        session = TrainingSession.objects.create(
            requirement=requirement,
            title='Turma HPLC',
            scheduled_start=timezone.now() - timedelta(days=1),
            scheduled_end=timezone.now() - timedelta(days=1, hours=-2),
            instructor=trainer,
        )
        approved = session.convocate(
            user=trainee, convoked_by=approver, due_date=timezone.localdate() - timedelta(days=1)
        )
        approved.start(user=trainee)
        approved.complete(
            score=90,
            evidence_reference='training/hplc/evidencia.pdf',
            content_hash='sha256:hplc',
            user=trainer,
        )
        approved.approve(user=approver, certificate_reference='training/hplc/certificado.pdf')
        approved.valid_until = timezone.localdate() + timedelta(days=10)
        approved.recertification_due_date = timezone.localdate()
        approved.save(update_fields=['valid_until', 'recertification_due_date', 'updated_at'])
        TrainingEnrollment.objects.create(
            requirement=requirement,
            session=session,
            user=late_user,
            status=TrainingEnrollment.Status.CONVOKED,
            convoked_by=approver,
            convoked_at=timezone.now() - timedelta(days=10),
            due_date=timezone.localdate() - timedelta(days=1),
        )
        report = TrainingIndicatorReport.objects.create(
            report_type=TrainingIndicatorReport.ReportType.COMPLIANCE,
            title='Aderência de treinamentos CQ',
            area='CQ',
            period_start=timezone.now() - timedelta(days=30),
            period_end=timezone.now(),
        )
        report.generate(user=approver, content_reference='training/reports/cq.pdf')

        assert requirement.document == document
        assert requirement.module_code == 'quality'
        assert requirement.regulatory_requirement_reference == 'ICH Q2(R2)'
        assert report.status == TrainingIndicatorReport.Status.GENERATED
        assert report.total_required == 2
        assert report.total_valid == 1
        assert report.overdue_trainings == 1
        assert report.due_soon_trainings == 1
        assert report.compliance_rate == 50


@pytest.mark.django_db
@pytest.mark.legacy_api_permissions
class TestTrainingApi:
    def test_training_api_uses_global_scope_and_executes_required_workflow(self):
        from training.models import (
            Competency,
            CriticalActivityRule,
            TrainingEnrollment,
            TrainingIndicatorReport,
            TrainingRequirement,
        )

        trainee, trainer, approver = create_training_users(suffix='api')
        other_trainee, _other_trainer, other_approver = create_training_users(suffix='api999')
        document = create_training_document(approver, suffix='api')
        other_document = create_training_document(other_approver, suffix='api999')
        client = APIClient()
        client.force_authenticate(approver)

        position_response = client.post(
            '/api/training/job-positions/',
            {
                'code': 'POS-API',
                'title': 'Operador API',
                'area': 'Produção',
                'department': 'Sólidos',
            },
        )
        position_id = position_response.json()['id']
        function_response = client.post(
            '/api/training/functions/',
            {
                'code': 'FUNC-API',
                'name': 'Operar processo crítico API',
                'job_position': position_id,
                'area': 'Produção',
                'process': 'Compressão',
                'is_critical': True,
            },
        )
        function_id = function_response.json()['id']
        competency_response = client.post(
            '/api/training/competencies/',
            {
                'code': 'COMP-API',
                'name': 'Competência API',
                'competency_type': Competency.CompetencyType.GMP,
            },
        )
        competency_id = competency_response.json()['id']
        invalid_requirement_response = client.post(
            '/api/training/requirements/',
            {
                'code': 'TRN-API-X',
                'title': 'Treinamento inválido',
                'training_type': TrainingRequirement.TrainingType.DOCUMENT,
                'area': 'Produção',
                'process': 'Compressão',
                'document': other_document.id,
                'validity_days': 365,
                'passing_score': 80,
            },
        )
        requirement_response = client.post(
            '/api/training/requirements/',
            {
                'code': 'TRN-API-001',
                'title': 'Treinamento API',
                'training_type': TrainingRequirement.TrainingType.CRITICAL_ACTIVITY,
                'area': 'Produção',
                'process': 'Compressão',
                'job_position': position_id,
                'function': function_id,
                'competency': competency_id,
                'document': document.id,
                'module_code': 'production',
                'regulatory_requirement_reference': 'RDC-658/2022',
                'validity_days': 365,
                'alert_before_days': 45,
                'passing_score': 80,
                'requires_evaluation': True,
                'requires_certificate': True,
                'block_without_valid_training': True,
            },
        )
        requirement_id = requirement_response.json()['id']
        matrix_response = client.post(
            '/api/training/matrix/',
            {
                'job_position': position_id,
                'function': function_id,
                'competency': competency_id,
                'requirement': requirement_id,
                'is_mandatory': True,
                'priority': 'critical',
            },
        )
        session_response = client.post(
            '/api/training/sessions/',
            {
                'requirement': requirement_id,
                'title': 'Turma API',
                'scheduled_start': (timezone.now() + timedelta(days=1)).isoformat(),
                'scheduled_end': (timezone.now() + timedelta(days=1, hours=2)).isoformat(),
                'instructor': trainer.id,
                'capacity': 20,
            },
        )
        session_id = session_response.json()['id']
        convocate_response = client.post(
            f'/api/training/sessions/{session_id}/convocate/',
            {'user': trainee.id, 'due_date': str(timezone.localdate() + timedelta(days=7))},
        )
        enrollment_id = convocate_response.json()['id']
        start_response = client.post(f'/api/training/enrollments/{enrollment_id}/start/')
        complete_response = client.post(
            f'/api/training/enrollments/{enrollment_id}/complete/',
            {
                'score': 95,
                'evidence_reference': 'training/api/evidencia.pdf',
                'content_hash': 'sha256:api',
            },
        )
        approve_response = client.post(
            f'/api/training/enrollments/{enrollment_id}/approve/',
            {'certificate_reference': 'training/api/certificado.pdf'},
        )
        rule_response = client.post(
            '/api/training/critical-activities/',
            {
                'activity_code': 'API-CRIT-001',
                'name': 'Atividade crítica API',
                'requirement': requirement_id,
                'enforcement_mode': CriticalActivityRule.EnforcementMode.BLOCK,
                'area': 'Produção',
                'process': 'Compressão',
                'module_code': 'production',
            },
        )
        rule_id = rule_response.json()['id']
        authorize_response = client.post(
            f'/api/training/critical-activities/{rule_id}/authorize/',
            {'user': trainee.id},
        )
        unauthorized_response = client.post(
            f'/api/training/critical-activities/{rule_id}/authorize/',
            {'user': other_trainee.id},
        )
        report_response = client.post(
            '/api/training/reports/',
            {
                'report_type': TrainingIndicatorReport.ReportType.COMPLIANCE,
                'title': 'Indicadores API',
                'area': 'Produção',
                'period_start': (timezone.now() - timedelta(days=1)).isoformat(),
                'period_end': timezone.now().isoformat(),
            },
        )
        report_id = report_response.json()['id']
        generate_response = client.post(
            f'/api/training/reports/{report_id}/generate/',
            {'content_reference': 'training/api/report.pdf'},
        )
        list_response = client.get('/api/training/requirements/')

        assert position_response.status_code == 201
        assert function_response.status_code == 201
        assert competency_response.status_code == 201
        assert invalid_requirement_response.status_code == 201
        assert requirement_response.status_code == 201
        assert matrix_response.status_code == 201
        assert session_response.status_code == 201
        assert convocate_response.status_code == 200
        assert start_response.status_code == 200
        assert complete_response.status_code == 200
        assert approve_response.status_code == 200
        assert rule_response.status_code == 201
        assert authorize_response.status_code == 200
        assert unauthorized_response.status_code == 200
        assert report_response.status_code == 201
        assert generate_response.status_code == 200
        assert list_response.status_code == 200
        created_requirement = requirement_response.json()
        assert created_requirement['code'] == f'TR-{created_requirement["id"]}'
        assert created_requirement['code'] in {
            item['code'] for item in list_response.json()['results']
        }
        assert (
            TrainingEnrollment.objects.get(id=enrollment_id).status
            == TrainingEnrollment.Status.APPROVED
        )
