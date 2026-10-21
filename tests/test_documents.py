from datetime import timedelta
import re

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient


User = get_user_model()


def assert_executed_sql_orders_newest_then_pk(sql, model, timestamp_column):
    normalized = ' '.join(str(sql).lower().translate(str.maketrans('', '', '"`[]')).split())
    expected_table = re.escape(model._meta.db_table.lower())
    expected_pk_column = re.escape(model._meta.pk.column.lower())
    order_pattern = (
        rf'\border by\s+{expected_table}\.{re.escape(timestamp_column)}\s+desc\s*,\s*'
        rf'{expected_table}\.{expected_pk_column}\s+desc\b'
    )
    assert re.search(order_pattern, normalized), normalized
    return normalized


def create_document_users(suffix='001'):
    owner = User.objects.create_user(
        username=f'owner-{suffix}@example.com',
        email=f'owner-{suffix}@example.com',
        password='S3curePass!123',
    )
    approver = User.objects.create_user(
        username=f'approver-{suffix}@example.com',
        email=f'approver-{suffix}@example.com',
        password='S3curePass!123',
    )
    reader = User.objects.create_user(
        username=f'reader-{suffix}@example.com',
        email=f'reader-{suffix}@example.com',
        password='S3curePass!123',
    )
    return owner, approver, reader


def create_controlled_document(owner, suffix='001'):
    from documents.models import ControlledDocument

    return ControlledDocument.objects.create(
        document_type=ControlledDocument.DocumentType.SOP,
        code=f'POP-QA-{suffix}',
        title=f'Procedimento de limpeza {suffix}',
        area='Garantia da Qualidade',
        version='1.0',
        effective_from=timezone.localdate(),
        valid_until=timezone.localdate() + timedelta(days=365),
        owner=owner,
        content='Registro íntegro, contemporâneo, legível, original e preciso.',
        change_summary='Emissão inicial.',
    )


class ControlledDocumentModelTests(TestCase):
    def test_audit_adapter_is_immutable_ordered_limited_and_avoids_n_plus_one(self):
        from base.ui.audit import get_audit_entries
        from base.ui.presentation import AuditEntry
        from documents.models import DocumentAuditTrail

        owner, _approver, _reader = create_document_users(suffix='audit-adapter')
        owner.first_name = 'Carla'
        owner.last_name = 'Mendes'
        owner.save(update_fields=['first_name', 'last_name'])
        document = create_controlled_document(owner, suffix='audit-adapter')
        created_rows = []
        for number in range(30):
            created_rows.append(
                DocumentAuditTrail.objects.create(
                    document=document,
                    action=DocumentAuditTrail.Action.REVIEWED,
                    actor=owner,
                    snapshot=f'{{"sequência": {number}, "status": "reviewed"}}',
                    reason=f'Revisão {number}.',
                )
            )
        tied_at = timezone.now() + timedelta(days=1)
        DocumentAuditTrail.objects.filter(pk__in=(created_rows[-2].pk, created_rows[-1].pk)).update(
            created_at=tied_at
        )

        with CaptureQueriesContext(connection) as queries:
            entries = get_audit_entries(document, limit=100)
        with CaptureQueriesContext(connection) as custom_limit_queries:
            custom_entries = get_audit_entries(document, limit=3)

        assert len(entries) == 25
        assert len(custom_entries) == 3
        assert all(isinstance(entry, AuditEntry) for entry in entries)
        assert entries[0].occurred_at >= entries[-1].occurred_at
        assert entries[0].actor_label == 'Carla Mendes'
        assert entries[0].details == '{"sequência": 29, "status": "reviewed"}'
        assert entries[0].reason == 'Revisão 29.'
        assert custom_entries[1].reason == 'Revisão 28.'
        assert len(queries) == 1
        assert len(custom_limit_queries) == 1
        limit_25_sql = assert_executed_sql_orders_newest_then_pk(
            queries[0]['sql'], DocumentAuditTrail, 'created_at'
        )
        limit_3_sql = assert_executed_sql_orders_newest_then_pk(
            custom_limit_queries[0]['sql'], DocumentAuditTrail, 'created_at'
        )
        assert re.search(r'\blimit\s+25\b', limit_25_sql), limit_25_sql
        assert re.search(r'\blimit\s+3\b', limit_3_sql), limit_3_sql

    def test_non_positive_audit_limits_return_empty_tuple_without_query(self):
        from base.ui.audit import get_audit_entries

        owner, _approver, _reader = create_document_users(suffix='audit-zero')
        document = create_controlled_document(owner, suffix='audit-zero')

        with CaptureQueriesContext(connection) as queries:
            zero_entries = get_audit_entries(document, limit=0)
            negative_entries = get_audit_entries(document, limit=-8)

        assert zero_entries == ()
        assert negative_entries == ()
        assert len(queries) == 0

    def test_document_workflow_locks_published_document_and_creates_revision_with_audit_trail(self):
        from documents.models import (
            ControlledDocument,
            DocumentApproval,
            DocumentAttachment,
            DocumentAuditTrail,
            DocumentRelationship,
        )

        owner, approver, _reader = create_document_users()
        document = create_controlled_document(owner)
        related = create_controlled_document(owner, suffix='002')
        attachment = DocumentAttachment.objects.create(
            document=document,
            file_name='pop-limpeza.pdf',
            file_reference='documentos/pop-limpeza.pdf',
            content_hash='sha256:abc123',
            uploaded_by=owner,
        )
        relationship = DocumentRelationship.objects.create(
            source_document=document,
            related_document=related,
            relationship_type=DocumentRelationship.RelationshipType.REFERENCES,
            rationale='Procedimento relacionado à limpeza de área.',
        )

        document.submit_for_review(user=owner)
        document.review(user=approver, comments='Revisão técnica concluída.')
        document.approve(user=approver, comments='Aprovado para publicação.')
        document.publish(user=approver)
        document.refresh_from_db()

        assert attachment.document == document
        assert relationship.related_document == related
        assert document.status == ControlledDocument.Status.PUBLISHED
        assert document.published_by == approver
        assert (
            DocumentApproval.objects.filter(
                document=document, decision=DocumentApproval.Decision.APPROVED
            ).count()
            == 2
        )
        assert set(
            DocumentAuditTrail.objects.filter(document=document).values_list('action', flat=True)
        ) >= {
            DocumentAuditTrail.Action.SUBMITTED,
            DocumentAuditTrail.Action.REVIEWED,
            DocumentAuditTrail.Action.APPROVED,
            DocumentAuditTrail.Action.PUBLISHED,
        }

        document.title = 'Alteração direta indevida'
        with pytest.raises(ValidationError) as error:
            document.save()

        revision = document.create_revision(
            user=owner, change_summary='Atualização periódica programada.'
        )

        assert 'status' in error.value.message_dict
        assert revision.status == ControlledDocument.Status.DRAFT
        assert revision.code == document.code
        assert revision.version == '2.0'
        assert revision.supersedes == document
        assert revision.owner == owner

    def test_distribution_confirms_reading_and_rejects_wrong_user(self):
        from documents.models import DocumentDistribution

        owner, approver, reader = create_document_users()
        other_user = User.objects.create_user(
            username='outro@example.com', email='outro@example.com', password='S3curePass!123'
        )
        document = create_controlled_document(owner)
        document.submit_for_review(user=owner)
        document.review(user=approver, comments='Conforme.')
        document.approve(user=approver, comments='Aprovado.')
        document.publish(user=approver)
        distribution = DocumentDistribution.objects.create(
            document=document,
            recipient=reader,
            distributed_by=owner,
            due_date=timezone.localdate() + timedelta(days=7),
        )

        with pytest.raises(ValidationError) as error:
            distribution.confirm_read(user=other_user, confirmation_text='Li.')

        distribution.confirm_read(
            user=reader, confirmation_text='Li, compreendi e aceito seguir o documento.'
        )

        assert 'recipient' in error.value.message_dict
        assert distribution.status == DocumentDistribution.Status.CONFIRMED
        assert distribution.confirmed_by == reader
        assert distribution.confirmed_at is not None
        assert distribution.confirmation_text.startswith('Li, compreendi')


@pytest.mark.django_db
@pytest.mark.legacy_api_permissions
class TestControlledDocumentApi:
    def test_regulated_document_cannot_be_physically_deleted_through_api(self):
        from documents.models import ControlledDocument

        owner, _approver, _reader = create_document_users()
        document = create_controlled_document(owner)
        client = APIClient()
        client.force_authenticate(owner)

        response = client.delete(f'/api/documents/controlled-documents/{document.id}/')

        assert response.status_code == 403
        assert ControlledDocument.objects.filter(pk=document.pk).exists()

    def test_document_api_uses_global_scope_and_enforces_published_revision_flow(self):
        from documents.models import ControlledDocument

        owner, approver, _reader = create_document_users()
        other_owner, _other_approver, _other_reader = create_document_users(suffix='999')
        create_controlled_document(other_owner, suffix='999')
        client = APIClient()
        client.force_authenticate(owner)

        invalid_response = client.post(
            '/api/documents/controlled-documents/',
            {
                'document_type': ControlledDocument.DocumentType.SOP,
                'code': 'POP-QA-API-X',
                'title': 'Documento inválido',
                'area': 'Garantia da Qualidade',
                'version': '1.0',
                'effective_from': str(timezone.localdate()),
                'valid_until': str(timezone.localdate() + timedelta(days=365)),
                'owner': other_owner.id,
                'content': 'Conteúdo controlado.',
                'change_summary': 'Emissão inicial.',
            },
        )
        create_response = client.post(
            '/api/documents/controlled-documents/',
            {
                'document_type': ControlledDocument.DocumentType.SOP,
                'code': 'POP-QA-API',
                'title': 'Procedimento API',
                'area': 'Garantia da Qualidade',
                'version': '1.0',
                'effective_from': str(timezone.localdate()),
                'valid_until': str(timezone.localdate() + timedelta(days=365)),
                'owner': owner.id,
                'content': 'Conteúdo controlado.',
                'change_summary': 'Emissão inicial.',
            },
        )
        document_id = create_response.json()['id']
        submit_response = client.post(
            f'/api/documents/controlled-documents/{document_id}/submit_for_review/',
        )
        review_response = client.post(
            f'/api/documents/controlled-documents/{document_id}/review/',
            {'comments': 'Conforme.'},
        )
        client.force_authenticate(approver)
        approve_response = client.post(
            f'/api/documents/controlled-documents/{document_id}/approve/',
            {'comments': 'Aprovado.'},
        )
        publish_response = client.post(
            f'/api/documents/controlled-documents/{document_id}/publish/',
        )
        blocked_edit_response = client.patch(
            f'/api/documents/controlled-documents/{document_id}/',
            {'title': 'Alteração direta'},
        )
        revision_response = client.post(
            f'/api/documents/controlled-documents/{document_id}/create_revision/',
            {'change_summary': 'Nova revisão controlada.'},
        )
        list_response = client.get('/api/documents/controlled-documents/')

        assert invalid_response.status_code == 201
        assert create_response.status_code == 201
        first_document = invalid_response.json()
        second_document = create_response.json()
        assert first_document['code'] == f'DOC-{first_document["id"]}'
        assert second_document['code'] == f'DOC-{second_document["id"]}'
        assert submit_response.status_code == 200
        assert review_response.status_code == 200
        assert approve_response.status_code == 200
        assert publish_response.status_code == 200
        assert publish_response.json()['status'] == ControlledDocument.Status.PUBLISHED
        assert blocked_edit_response.status_code == 400
        assert 'status' in blocked_edit_response.json()
        assert revision_response.status_code == 201
        assert revision_response.json()['version'] == '2.0'
        assert {item['code'] for item in list_response.json()['results']} == {
            first_document['code'],
            second_document['code'],
            'POP-QA-999',
        }

    def test_distribution_api_confirms_reading_for_authenticated_recipient(self):
        from documents.models import DocumentDistribution

        owner, approver, reader = create_document_users()
        document = create_controlled_document(owner)
        document.submit_for_review(user=owner)
        document.review(user=approver, comments='Conforme.')
        document.approve(user=approver, comments='Aprovado.')
        document.publish(user=approver)
        distribution = DocumentDistribution.objects.create(
            document=document,
            recipient=reader,
            distributed_by=owner,
            due_date=timezone.localdate() + timedelta(days=7),
        )
        client = APIClient()
        client.force_authenticate(reader)

        confirm_response = client.post(
            f'/api/documents/distributions/{distribution.id}/confirm_read/',
            {'confirmation_text': 'Li e compreendi o documento.'},
        )

        assert confirm_response.status_code == 200
        assert confirm_response.json()['status'] == DocumentDistribution.Status.CONFIRMED
        assert confirm_response.json()['confirmed_by'] == reader.id
