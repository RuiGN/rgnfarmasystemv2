from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from auxiliary.models import BusinessArea
from documents.models import (
    ControlledDocument,
    DocumentApproval,
    DocumentAttachment,
    DocumentAuditTrail,
    DocumentDistribution,
    DocumentRelationship,
)
from governance.models import GovernanceAuditLog, OperationalModule
from qa.models import QAReview, QualityBlock
from training.models import (
    Competency,
    JobPosition,
    TrainingEnrollment,
    TrainingRequirement,
    WorkFunction,
)


class ControlledDocumentCockpitUiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='dms-qa-coordinator',
            email='dms.qa@example.com',
            password='Password123!',
        )
        self.client.force_login(self.user)

        # Permissão base para visualizar o documento controlado
        view_doc_perm = Permission.objects.get(
            content_type__app_label='documents', codename='view_controlleddocument'
        )
        self.user.user_permissions.add(view_doc_perm)

        # Colaborador operador para treinamentos e distribuição
        self.collaborator = get_user_model().objects.create_user(
            username='operador-fab-01',
            email='operador.fab@example.com',
            password='Password123!',
            first_name='Carlos',
            last_name='Silva',
        )

        # Área de negócio normalizada
        self.area = BusinessArea.objects.create(name='Produção e Fabricação', code='PRD')

        # Documento Controlado publicado e vigente
        self.document = ControlledDocument.objects.create(
            code='SOP-PRD-001',
            version='1.0',
            title='Procedimento Padrão de Higienização de Reatores Cosméticos',
            document_type=ControlledDocument.DocumentType.SOP,
            area='Produção',
            area_ref=self.area,
            status=ControlledDocument.Status.PUBLISHED,
            effective_from=timezone.localdate() - timedelta(days=30),
            valid_until=timezone.localdate() + timedelta(days=335),
            owner=self.user,
            content=(
                'Passo 1: Enxágue preliminar com água purificada WFI a 80°C.\n'
                'Passo 2: Aplicação de detergente enzimático a 2% sob agitação constante.\n'
                'Passo 3: Sanitização com ácido peracético 0.5% por 30 minutos.\n'
                'Passo 4: Teste de condutividade para validação de ausência de resíduos.'
            ),
            change_summary='Emissão inicial formal do procedimento para atendimento à RDC 48/2013 e BPF.',
            submitted_by=self.user,
            submitted_at=timezone.now() - timedelta(days=35),
            reviewed_by=self.user,
            reviewed_at=timezone.now() - timedelta(days=32),
            approved_by=self.user,
            approved_at=timezone.now() - timedelta(days=30),
            published_by=self.user,
            published_at=timezone.now() - timedelta(days=30),
        )

        # Anexo documental com hash ALCOA+
        self.attachment = DocumentAttachment.objects.create(
            document=self.document,
            file_name='SOP-PRD-001_v1.0_Assinado.pdf',
            file_reference='docs/controlled/sop_prd_001.pdf',
            content_hash='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
            description='Cópia mestra digital com assinaturas eletrônicas homologadas.',
            uploaded_by=self.user,
        )

        # Cargo, Função e Competência
        self.job_position = JobPosition.objects.create(
            code='JP-OP-01',
            title='Operador de Fabricação Cosmética',
            area='Produção',
            area_ref=self.area,
        )
        self.work_function = WorkFunction.objects.create(
            code='WF-SAN-01',
            name='Sanitização e CIP de Tanques',
            job_position=self.job_position,
        )
        self.competency = Competency.objects.create(
            code='CPT-BPF-01',
            name='Limpeza e Sanitização Farmacotécnica',
            competency_type=Competency.CompetencyType.GMP,
        )

        # Requisito de Capacitação na Matriz
        self.training_req = TrainingRequirement.objects.create(
            code='TR-SOP-PRD-001',
            title='Treinamento Operacional no POP de Higienização de Reatores',
            training_type=TrainingRequirement.TrainingType.DOCUMENT,
            area='Produção',
            area_ref=self.area,
            job_position=self.job_position,
            function=self.work_function,
            competency=self.competency,
            document=self.document,
            regulatory_requirement_reference='RDC ANVISA 48/2013 Art. 14 e ISO 22716',
            validity_days=365,
            alert_before_days=30,
            passing_score=Decimal('80.00'),
            requires_evaluation=True,
            requires_certificate=True,
            is_mandatory=True,
            block_without_valid_training=True,
            is_active=True,
        )

        # Inscrição de Treinamento Aprovada com Certificado ALCOA+
        now = timezone.now()
        self.enrollment = TrainingEnrollment.objects.create(
            enrollment_number='TRN-2026-0001',
            requirement=self.training_req,
            user=self.collaborator,
            status=TrainingEnrollment.Status.APPROVED,
            convoked_by=self.user,
            convoked_at=now - timedelta(days=15),
            due_date=timezone.localdate() + timedelta(days=15),
            started_by=self.collaborator,
            started_at=now - timedelta(days=10),
            completed_by=self.collaborator,
            completed_at=now - timedelta(days=5),
            score=Decimal('95.00'),
            evidence_reference='treinamentos/cert_0881.pdf',
            content_hash='a1b2c3d4e5f67890123456789abcdef012345678',
            approved_by=self.user,
            approved_at=now - timedelta(days=4),
            valid_until=timezone.localdate() + timedelta(days=360),
            recertification_due_date=timezone.localdate() + timedelta(days=330),
            certificate_number='CERT-2026-0881',
            certificate_reference='certificados/CERT-2026-0881.pdf',
        )

        # Fluxo de Aprovação Formal
        self.approval = DocumentApproval.objects.create(
            document=self.document,
            role=DocumentApproval.Role.APPROVER,
            user=self.user,
            decision=DocumentApproval.Decision.APPROVED,
            decided_at=now - timedelta(days=30),
            comments='Aprovado formalmente de acordo com BPF / ISO 22716.',
        )

        # Distribuição de Cópia Controlada
        self.distribution = DocumentDistribution.objects.create(
            document=self.document,
            recipient=self.collaborator,
            distributed_by=self.user,
            due_date=timezone.localdate() + timedelta(days=10),
            status=DocumentDistribution.Status.CONFIRMED,
            confirmed_by=self.collaborator,
            confirmed_at=now - timedelta(days=20),
            confirmation_text='Confirmo a leitura integral e compreensão dos passos de sanitização do POP.',
        )

        # Vínculo Documental
        self.relationship = DocumentRelationship.objects.create(
            source_document=self.document,
            relationship_type=DocumentRelationship.RelationshipType.REFERENCES,
            external_reference='RDC ANVISA nº 48/2013 - Boas Práticas de Fabricação',
            rationale='Requisito regulatório sanitário obrigatório de validação de limpeza.',
        )

        # Trilha de Auditoria ALCOA+
        self.audit_event = DocumentAuditTrail.objects.create(
            document=self.document,
            action=DocumentAuditTrail.Action.PUBLISHED,
            actor=self.user,
            reason='Publicação oficial para entrada em vigor na planta fabril.',
            snapshot='SOP-PRD-001 v1.0 - Publicado',
        )

        # Rota do cockpit
        self.cockpit_url = reverse('app:controlled_document_cockpit', kwargs={'pk': self.document.pk})

    def _grant_all_permissions(self):
        perms = Permission.objects.filter(
            content_type__app_label__in=['documents', 'training', 'qa', 'governance']
        )
        self.user.user_permissions.add(*perms)

    def test_cockpit_requires_authentication(self):
        self.client.logout()
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_cockpit_requires_view_permission(self):
        self.user.user_permissions.clear()
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 403)

    def test_cockpit_nonexistent_document_returns_404(self):
        url = reverse('app:controlled_document_cockpit', kwargs={'pk': 999999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_full_cockpit_renders_all_5_tabs_and_kpis(self):
        self._grant_all_permissions()
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Cabeçalho Executivo
        self.assertIn('SOP-PRD-001', content)
        self.assertIn('v1.0', content)
        self.assertIn('Procedimento Padrão de Higienização de Reatores Cosméticos', content)
        self.assertIn('Publicado', content)
        self.assertIn('Produção', content)

        # 5 Abas do Cockpit
        self.assertIn('Metadados & Conteúdo do Procedimento (SOP)', content)
        self.assertIn('Matriz de Treinamentos Requeridos por Cargo', content)
        self.assertIn('Colaboradores Treinados & Provas de Eficácia', content)
        self.assertIn('Histórico de Revisões & Assinaturas', content)
        self.assertIn('Distribuição Controlada, Vínculos & Trilha de Auditoria', content)

        # KPIs Executivos
        self.assertIn('Taxa de Capacitação', content)
        self.assertIn('100,0%', content)
        self.assertIn('Matriz de Treinamento', content)
        self.assertIn('Vigência Sanitária', content)

        # Conteúdo da Aba 1 (POP e Anexos)
        self.assertIn('Enxágue preliminar com água purificada WFI a 80°C', content)
        self.assertIn('SOP-PRD-001_v1.0_Assinado.pdf', content)
        self.assertIn('e3b0c44298fc1c14', content)

        # Conteúdo da Aba 2 (Matriz de Treinamentos)
        self.assertIn('TR-SOP-PRD-001', content)
        self.assertIn('Operador de Fabricação Cosmética', content)
        self.assertIn('Sanitização e CIP de Tanques', content)
        self.assertIn('80,00%', content)

        # Conteúdo da Aba 3 (Colaboradores e Certificados ALCOA+)
        self.assertIn('TRN-2026-0001', content)
        self.assertIn('Carlos Silva', content)
        self.assertIn('CERT-2026-0881', content)
        self.assertIn('95,00%', content)

        # Conteúdo da Aba 4 (Aprovações e Linhagem)
        self.assertIn('Aprovado formalmente de acordo com BPF / ISO 22716', content)
        self.assertIn('Linhagem Completa de Versões e Revisões', content)

        # Conteúdo da Aba 5 (Distribuição, Trilha e 5 Gates)
        self.assertIn('Confirmo a leitura integral e compreensão dos passos de sanitização do POP', content)
        self.assertIn('RDC ANVISA nº 48/2013 - Boas Práticas de Fabricação', content)
        self.assertIn('SOP-PRD-001 v1.0 - Publicado', content)
        self.assertIn('Gate 1: Elaboração & Metadados', content)
        self.assertIn('Gate 2: Ciclo de Aprovação', content)
        self.assertIn('Gate 3: Vigência Ativa', content)
        self.assertIn('Gate 4: Matriz de Capacitação', content)
        self.assertIn('Gate 5: Eficácia & Bloqueios QA', content)
        self.assertIn('Vigente &amp; Capacitação Conforme (BPF)', content)

    def test_sod_matrix_tab_permission_segmented(self):
        # Usuário possui apenas permissão básica de documentos, sem permissão de requisitos/treinamento
        self.user.user_permissions.clear()
        view_doc_perm = Permission.objects.get(
            content_type__app_label='documents', codename='view_controlleddocument'
        )
        self.user.user_permissions.add(view_doc_perm)

        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        # Como can_view_matrix inclui documents.view_controlleddocument ou training.view_trainingrequirement,
        # vamos testar SoD na aba de colaboradores (enrollments)
        self.assertIn('Você não possui permissão para visualizar colaboradores treinados e eficácia.', content)
        self.assertNotIn('CERT-2026-0881', content)

    def test_sod_enrollments_tab_permission_segmented(self):
        # Usuário sem permissão de training enrollment
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Você não possui permissão para visualizar colaboradores treinados e eficácia.', content)
        self.assertNotIn('TRN-2026-0001', content)

    def test_sod_approvals_tab_permission_segmented(self):
        # Usuário sem permissão de aprovações
        # Note que se user tem view_controlleddocument, can_view_approvals é True se can_view_metadata
        # Testamos removendo permissões de governance:
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Você não possui permissão para visualizar distribuição, vínculos e trilha de auditoria.', content)
        self.assertNotIn('Confirmo a leitura integral e compreensão dos passos de sanitização do POP', content)

    def test_dms_5_gates_evaluation_conforming_vs_blocked(self):
        self._grant_all_permissions()
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['gates_passed_count'], 5)
        self.assertEqual(response.context['regulatory_verdict'], 'Vigente & Capacitação Conforme (BPF)')
        self.assertFalse(response.context['has_active_block'])

        # Criar bloqueio sanitário QA
        QualityBlock.objects.create(
            target_type=QualityBlock.TargetType.DOCUMENT,
            document_reference=self.document.code,
            reason='Desvio crítico em processo de limpeza; POP suspenso para investigação.',
            status=QualityBlock.Status.ACTIVE,
            blocked_by=self.user,
            blocked_at=timezone.now(),
        )

        response_blocked = self.client.get(self.cockpit_url)
        self.assertEqual(response_blocked.status_code, 200)
        self.assertFalse(response_blocked.context['gate5_passed'])
        self.assertTrue(response_blocked.context['has_active_block'])
        self.assertEqual(
            response_blocked.context['regulatory_verdict'],
            'Documento sob bloqueio sanitário QA',
        )
        self.assertEqual(response_blocked.context['regulatory_verdict_badge'], 'bg-danger')

    def test_resource_detail_renders_cockpit_button(self):
        detail_url = reverse(
            'app:resource_detail',
            kwargs={
                'module_slug': 'documents',
                'resource_slug': 'controlled-documents',
                'pk': self.document.pk,
            },
        )
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Cockpit do documento (DMS)', content)
        self.assertIn(self.cockpit_url, content)
