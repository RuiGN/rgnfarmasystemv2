import hashlib
import tempfile
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from auxiliary.models import City, StateProvince
from base.roles import OperationalRole
from documents.models import ControlledDocument
from fiscal.models import FiscalCompany, FiscalDocument
from masters.models import BusinessPartner


User = get_user_model()


def create_user(email):
    return User.objects.create_user(username=email, email=email, password='S3curePass!123')


def create_partner(suffix='001'):
    return BusinessPartner.objects.create(
        code=f'PAR-ARQ-{suffix}',
        legal_name=f'Parceiro Arquivo {suffix}',
        partner_type=BusinessPartner.PartnerType.SUPPLIER,
        qualification_status=BusinessPartner.QualificationStatus.QUALIFIED,
        qualification_valid_until=timezone.localdate() + timedelta(days=365),
        document=f'12345678000{suffix}',
    )


def create_fiscal_document(suffix='001'):
    state = StateProvince.objects.create(
        name=f'Pernambuco Arquivos {suffix}',
    )
    city = City.objects.create(
        name='Recife',
        state=state,
    )
    company = FiscalCompany.objects.create(
        legal_name=f'RGN Farma Arquivos {suffix}',
        document=f'98765432000{suffix}',
        tax_regime=FiscalCompany.TaxRegime.LUCRO_REAL,
        state_ref=state,
        city_ref=city,
    )
    return FiscalDocument.objects.create(
        company=company,
        partner=create_partner(suffix=suffix),
        document_type=FiscalDocument.DocumentType.INBOUND,
        operation_type=FiscalDocument.OperationType.PURCHASE,
        number=f'NF-ARQ-{suffix}',
        series='1',
        issue_date=timezone.localdate(),
        operation_date=timezone.localdate(),
        total_products='100.0000',
        total_amount='100.0000',
    )


def create_controlled_document(owner, suffix='001'):
    return ControlledDocument.objects.create(
        document_type=ControlledDocument.DocumentType.REPORT,
        code=f'RPT-ARQ-{suffix}',
        title=f'Relatório protegido {suffix}',
        area='Garantia da Qualidade',
        version='1.0',
        effective_from=timezone.localdate(),
        valid_until=timezone.localdate() + timedelta(days=365),
        owner=owner,
        content='Registro controlado para evidência protegida.',
        change_summary='Emissão inicial.',
    )


class ProtectedFileModelTests(TestCase):
    def test_rf25_classifies_fiscal_attachment_secures_link_and_records_audit(self):
        from files.models import (
            ProtectedFile,
            ProtectedFileAccessRule,
            ProtectedFileAuditTrail,
            SecureFileLink,
        )

        owner = create_user('owner.files@example.com')
        viewer = create_user('viewer.files@example.com')
        intruder = create_user('intruder.files@example.com')
        fiscal_document = create_fiscal_document()
        protected_file = ProtectedFile.objects.create(
            source_module=ProtectedFile.SourceModule.FISCAL,
            source_model='FiscalDocument',
            source_record_id=str(fiscal_document.id),
            fiscal_document=fiscal_document,
            file_type=ProtectedFile.FileType.FISCAL_DOCUMENT,
            origin=ProtectedFile.Origin.UPLOAD,
            criticality=ProtectedFile.Criticality.HIGH,
            confidentiality=ProtectedFile.Confidentiality.RESTRICTED,
            title='XML da nota fiscal',
            file_name='nf-arq-001.xml',
            file_reference='fiscal/notas/nf-arq-001.xml',
            mime_type='application/xml',
            file_size=2048,
            content_hash='sha256:xml-001',
            valid_until=timezone.localdate() + timedelta(days=365),
            responsible=owner,
            uploaded_by=owner,
        )

        with pytest.raises(ValidationError) as denied:
            protected_file.generate_secure_link(
                user=intruder, purpose=SecureFileLink.Purpose.DOWNLOAD, expires_in_minutes=10
            )

        ProtectedFileAccessRule.objects.create(
            protected_file=protected_file,
            rule_type=ProtectedFileAccessRule.RuleType.USER,
            user=viewer,
            permission=ProtectedFileAccessRule.Permission.DOWNLOAD,
        )
        link = protected_file.generate_secure_link(
            user=viewer, purpose=SecureFileLink.Purpose.DOWNLOAD, expires_in_minutes=10
        )
        stale_link = SecureFileLink.objects.get(pk=link.pk)
        reference = link.use(user=viewer)
        with pytest.raises(ValidationError):
            stale_link.use(user=viewer)
        protected_file.record_access(user=viewer, action=ProtectedFileAuditTrail.Action.VIEW)
        replacement_content = b'<xml>retificada</xml>'
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            replacement = protected_file.replace(
                new_file_reference='',
                new_file_name='nf-arq-001-retificada.xml',
                content_hash=f'sha256:{hashlib.sha256(replacement_content).hexdigest()}',
                user=owner,
                reason='XML retificado aprovado pelo fiscal.',
                file_size=len(replacement_content),
                mime_type='application/xml',
                content=replacement_content,
            )
        protected_file.refresh_from_db()
        protected_file.delete_secure(
            reason='Expurgo controlado do arquivo substituído.', user=owner
        )

        assert 'permission' in denied.value.message_dict
        assert reference == 'fiscal/notas/nf-arq-001.xml'
        assert link.token
        assert link.used_at is not None
        assert link.use_count == 1
        assert replacement.supersedes == protected_file
        assert replacement.content_hash == (
            f'sha256:{hashlib.sha256(replacement_content).hexdigest()}'
        )
        assert replacement.is_encrypted
        assert protected_file.status == ProtectedFile.Status.DELETED
        assert protected_file.deleted_by == owner
        assert ProtectedFileAuditTrail.objects.filter(
            protected_file=protected_file,
            action=ProtectedFileAuditTrail.Action.ACCESS_DENIED,
            actor=intruder,
        ).exists()
        assert set(
            ProtectedFileAuditTrail.objects.filter(protected_file=protected_file).values_list(
                'action', flat=True
            )
        ) >= {
            ProtectedFileAuditTrail.Action.LINK_GENERATED,
            ProtectedFileAuditTrail.Action.DOWNLOAD,
            ProtectedFileAuditTrail.Action.VIEW,
            ProtectedFileAuditTrail.Action.REPLACE,
            ProtectedFileAuditTrail.Action.DELETE,
        }

    def test_rf25_role_record_rules_and_expiration_cover_all_required_domains(self):
        from files.models import ProtectedFile, ProtectedFileAccessRule, ProtectedFileAuditTrail

        owner = create_user('owner.quality.files@example.com')
        quality_user = create_user('quality.files@example.com')
        record_user = create_user('record.files@example.com')
        quality_group, _ = Group.objects.get_or_create(name=OperationalRole.QUALITY)
        quality_user.groups.add(quality_group)
        controlled_document = create_controlled_document(owner)
        protected_file = ProtectedFile.objects.create(
            source_module=ProtectedFile.SourceModule.QUALITY,
            source_model='ControlledDocument',
            source_record_id=str(controlled_document.id),
            controlled_document=controlled_document,
            file_type=ProtectedFile.FileType.REPORT,
            origin=ProtectedFile.Origin.SYSTEM,
            criticality=ProtectedFile.Criticality.CRITICAL,
            confidentiality=ProtectedFile.Confidentiality.CONFIDENTIAL,
            title='Relatório de qualidade protegido',
            file_name='rpt-qualidade.pdf',
            file_reference='quality/reports/rpt-qualidade.pdf',
            mime_type='application/pdf',
            file_size=8192,
            content_hash='sha256:rpt-qualidade',
            responsible=owner,
            uploaded_by=owner,
        )
        ProtectedFileAccessRule.objects.create(
            protected_file=protected_file,
            rule_type=ProtectedFileAccessRule.RuleType.ROLE,
            role=OperationalRole.QUALITY,
            permission=ProtectedFileAccessRule.Permission.VIEW,
        )
        ProtectedFileAccessRule.objects.create(
            protected_file=protected_file,
            rule_type=ProtectedFileAccessRule.RuleType.RECORD,
            source_module=ProtectedFile.SourceModule.QUALITY,
            source_model='ControlledDocument',
            source_record_id=str(controlled_document.id),
            permission=ProtectedFileAccessRule.Permission.DOWNLOAD,
        )

        protected_file.expire(user=owner)
        protected_file.refresh_from_db()

        assert set(ProtectedFile.SourceModule.values) >= {
            'operational',
            'financial',
            'fiscal',
            'quality',
            'regulatory',
            'administrative',
        }
        assert (
            protected_file.user_can_access(
                quality_user, permission=ProtectedFileAccessRule.Permission.VIEW
            )
            is True
        )
        assert (
            protected_file.user_can_access(
                quality_user, permission=ProtectedFileAccessRule.Permission.DOWNLOAD
            )
            is False
        )
        assert (
            protected_file.user_can_access(
                record_user,
                permission=ProtectedFileAccessRule.Permission.DOWNLOAD,
                source_module=ProtectedFile.SourceModule.QUALITY,
                source_model='ControlledDocument',
                source_record_id=str(controlled_document.id),
            )
            is True
        )
        assert protected_file.status == ProtectedFile.Status.EXPIRED
        assert ProtectedFileAuditTrail.objects.filter(
            protected_file=protected_file,
            action=ProtectedFileAuditTrail.Action.EXPIRE,
            actor=owner,
        ).exists()


@pytest.mark.legacy_api_permissions
class ProtectedFileApiTests(TestCase):
    def test_rf25_api_uses_global_scope_and_executes_secure_link_flow(self):
        from files.models import ProtectedFile, ProtectedFileAccessRule, ProtectedFileAuditTrail

        user = create_user('api.files@example.com')
        fiscal_document = create_fiscal_document()
        other_fiscal_document = create_fiscal_document(suffix='999')
        ProtectedFile.objects.create(
            source_module=ProtectedFile.SourceModule.FISCAL,
            source_model='FiscalDocument',
            source_record_id=str(other_fiscal_document.id),
            fiscal_document=other_fiscal_document,
            file_type=ProtectedFile.FileType.FISCAL_DOCUMENT,
            origin=ProtectedFile.Origin.UPLOAD,
            criticality=ProtectedFile.Criticality.LOW,
            confidentiality=ProtectedFile.Confidentiality.INTERNAL,
            title='Arquivo secundario',
            file_name='nf-outro.xml',
            file_reference='fiscal/notas/nf-outro.xml',
            content_hash='sha256:outro',
            uploaded_by=create_user('api.files.other@example.com'),
        )
        client = APIClient()
        client.force_authenticate(user)

        invalid_response = client.post(
            '/api/files/protected-files/',
            {
                'source_module': ProtectedFile.SourceModule.FISCAL,
                'source_model': 'FiscalDocument',
                'source_record_id': str(other_fiscal_document.id),
                'fiscal_document': other_fiscal_document.id,
                'file_type': ProtectedFile.FileType.FISCAL_DOCUMENT,
                'origin': ProtectedFile.Origin.UPLOAD,
                'criticality': ProtectedFile.Criticality.HIGH,
                'confidentiality': ProtectedFile.Confidentiality.RESTRICTED,
                'title': 'XML secundario',
                'file_name': 'nf-invalida.xml',
                'file_reference': 'fiscal/notas/nf-invalida.xml',
                'content_hash': 'sha256:invalida',
            },
        )
        create_response = client.post(
            '/api/files/protected-files/',
            {
                'source_module': ProtectedFile.SourceModule.FISCAL,
                'source_model': 'FiscalDocument',
                'source_record_id': str(fiscal_document.id),
                'fiscal_document': fiscal_document.id,
                'file_type': ProtectedFile.FileType.FISCAL_DOCUMENT,
                'origin': ProtectedFile.Origin.UPLOAD,
                'criticality': ProtectedFile.Criticality.HIGH,
                'confidentiality': ProtectedFile.Confidentiality.RESTRICTED,
                'title': 'XML da nota fiscal',
                'file_name': 'nf-arq-api.xml',
                'file_reference': 'fiscal/notas/nf-arq-api.xml',
                'mime_type': 'application/xml',
                'file_size': 1024,
                'content_hash': 'sha256:api',
                'responsible': user.id,
            },
        )
        file_id = create_response.json()['id']
        access_response = client.post(
            '/api/files/access-rules/',
            {
                'protected_file': file_id,
                'rule_type': ProtectedFileAccessRule.RuleType.USER,
                'user': user.id,
                'permission': ProtectedFileAccessRule.Permission.DOWNLOAD,
            },
        )
        link_response = client.post(
            f'/api/files/protected-files/{file_id}/generate_link/',
            {'purpose': 'download', 'expires_in_minutes': 10},
        )
        link_id = link_response.json()['id']
        use_response = client.post(f'/api/files/secure-links/{link_id}/use/')
        api_content = b'<xml>api-retificada</xml>'
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            replace_response = client.post(
                f'/api/files/protected-files/{file_id}/replace/',
                {
                    'new_file_name': 'nf-arq-api-retificada.xml',
                    'content_hash': f'sha256:{hashlib.sha256(api_content).hexdigest()}',
                    'reason': 'Substituição controlada pelo fiscal.',
                    'file_size': len(api_content),
                    'mime_type': 'application/xml',
                    'file': SimpleUploadedFile('retificada.xml', api_content),
                },
                format='multipart',
            )
        delete_response = client.post(
            f'/api/files/protected-files/{replace_response.json()["id"]}/delete_secure/',
            {'reason': 'Expurgo aprovado.'},
        )
        list_response = client.get('/api/files/protected-files/')
        audit_response = client.get('/api/files/audit-trail/')

        assert invalid_response.status_code == 201
        assert create_response.status_code == 201
        assert create_response.json()['uploaded_by'] == user.id
        assert access_response.status_code == 201
        assert link_response.status_code == 201
        assert link_response.json()['token']
        assert use_response.status_code == 200
        assert 'file_reference' not in use_response.json()
        assert use_response.json()['file_name'] == 'nf-arq-api.xml'
        assert replace_response.status_code == 201
        assert delete_response.status_code == 200
        assert delete_response.json()['status'] == ProtectedFile.Status.DELETED
        assert 'Arquivo secundario' not in {
            item['title'] for item in list_response.json()['results']
        }
        assert set(ProtectedFileAuditTrail.objects.values_list('action', flat=True)) >= {
            ProtectedFileAuditTrail.Action.UPLOAD,
            ProtectedFileAuditTrail.Action.LINK_GENERATED,
            ProtectedFileAuditTrail.Action.DOWNLOAD,
            ProtectedFileAuditTrail.Action.REPLACE,
            ProtectedFileAuditTrail.Action.DELETE,
        }
        assert audit_response.status_code == 200
