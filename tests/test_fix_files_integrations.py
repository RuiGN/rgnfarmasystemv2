import hashlib
import tempfile
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import RequestFactory, TestCase, override_settings
from rest_framework.test import APIClient

from files.models import (
    ProtectedFile,
    ProtectedFileAccessRule,
    ProtectedFileAuditTrail,
    SecureFileLink,
)


User = get_user_model()


def create_user(email):
    return User.objects.create_user(username=email, email=email, password='S3curePass!123')


def create_file(owner):
    return ProtectedFile.objects.create(
        source_module=ProtectedFile.SourceModule.OPERATIONAL,
        source_model='FixTest',
        source_record_id='1',
        file_type=ProtectedFile.FileType.REPORT,
        origin=ProtectedFile.Origin.UPLOAD,
        title='Arquivo de teste',
        file_name='teste.xml',
        file_reference='pending',
        mime_type='application/xml',
        file_size=0,
        content_hash='sha256:pending',
        responsible=owner,
        uploaded_by=owner,
    )


class SecureLinkUseTests(TestCase):
    def setUp(self):
        self.owner = create_user('fix.owner@example.com')
        self.intruder = create_user('fix.intruder@example.com')
        self.file = create_file(self.owner)

    def test_denial_audit_persists_after_failed_use(self):
        link = self.file.generate_secure_link(user=self.owner, expires_in_minutes=10)
        with pytest.raises(ValidationError):
            link.use(user=self.intruder, ip_address='203.0.113.5')
        denied = ProtectedFileAuditTrail.objects.filter(
            protected_file=self.file,
            action=ProtectedFileAuditTrail.Action.ACCESS_DENIED,
            actor=self.intruder,
            secure_link=link,
        )
        assert denied.count() == 1
        link.refresh_from_db()
        assert link.use_count == 0

    def test_max_uses_enforced_and_denial_audited(self):
        link = self.file.generate_secure_link(user=self.owner, expires_in_minutes=10)
        stale = SecureFileLink.objects.get(pk=link.pk)
        link.use(user=self.owner)
        with pytest.raises(ValidationError) as error:
            stale.use(user=self.owner)
        assert 'token' in error.value.message_dict
        link.refresh_from_db()
        assert link.use_count == link.max_uses
        assert ProtectedFileAuditTrail.objects.filter(
            protected_file=self.file,
            action=ProtectedFileAuditTrail.Action.ACCESS_DENIED,
            secure_link=link,
        ).exists()

    def test_token_hidden_from_non_requester(self):
        link = self.file.generate_secure_link(user=self.owner, expires_in_minutes=10)
        ProtectedFileAccessRule.objects.create(
            protected_file=self.file,
            rule_type=ProtectedFileAccessRule.RuleType.USER,
            user=self.intruder,
            permission=ProtectedFileAccessRule.Permission.VIEW,
        )
        from files.serializers import SecureFileLinkSerializer

        factory = RequestFactory()
        for user, expected in ((self.owner, True), (self.intruder, False)):
            request = factory.get('/')
            request.user = user
            data = SecureFileLinkSerializer(link, context={'request': request}).data
            assert ('token' in data) is expected


class ReplaceTests(TestCase):
    def setUp(self):
        self.owner = create_user('fix.replace@example.com')
        self.file = create_file(self.owner)
        self.content = b'<xml>novo</xml>'
        self.digest = f'sha256:{hashlib.sha256(self.content).hexdigest()}'

    def test_rejects_non_canonical_reference(self):
        with pytest.raises(ValidationError) as error:
            self.file.replace(
                'fiscal/notas/arbitrario.xml', 'novo.xml', self.digest, user=self.owner
            )
        assert 'new_file_reference' in error.value.message_dict

    def test_rejects_missing_blob(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            with pytest.raises(ValidationError) as error:
                self.file.replace(
                    'protected/ARQ-X/abc.enc', 'novo.xml', self.digest, user=self.owner
                )
        assert 'new_file_reference' in error.value.message_dict

    def test_rejects_mismatched_hash_and_size_with_content(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            with pytest.raises(ValidationError) as bad_hash:
                self.file.replace(
                    '', 'novo.xml', 'sha256:deadbeef', user=self.owner, content=self.content
                )
            with pytest.raises(ValidationError) as bad_size:
                self.file.replace(
                    '',
                    'novo.xml',
                    self.digest,
                    user=self.owner,
                    file_size=1,
                    content=self.content,
                )
        assert 'content_hash' in bad_hash.value.message_dict
        assert 'file_size' in bad_size.value.message_dict
        self.file.refresh_from_db()
        assert self.file.status == ProtectedFile.Status.ACTIVE

    def test_content_replacement_is_encrypted_and_verified_server_side(self):
        with tempfile.TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            replacement = self.file.replace(
                '', 'novo.xml', self.digest, user=self.owner, content=self.content
            )
        assert replacement.is_encrypted
        assert replacement.content_hash == self.digest
        assert replacement.file_size == len(self.content)
        assert replacement.encrypted_size > 0


class ApiCallLoggingMiddlewareTests(TestCase):
    def test_logs_when_api_call_log_fails(self):
        user = create_user('fix.mw@example.com')
        client = APIClient()
        client.force_authenticate(user)
        with (
            mock.patch('integrations.middleware.logger') as logger,
            mock.patch(
                'integrations.middleware.ApiCallLog.record', side_effect=RuntimeError('boom')
            ),
        ):
            response = client.get('/api/files/protected-files/')
        assert response.status_code < 500
        assert logger.exception.called

    def test_x_forwarded_for_ignored_without_trusted_proxy_flag(self):
        from integrations.middleware import ApiCallLoggingMiddleware

        middleware = ApiCallLoggingMiddleware(lambda request: None)
        request = RequestFactory().get(
            '/api/x/', REMOTE_ADDR='203.0.113.1', HTTP_X_FORWARDED_FOR='198.51.100.9, 10.0.0.1'
        )
        assert middleware._remote_addr(request) == '203.0.113.1'
        with override_settings(USE_X_FORWARDED_FOR=True):
            assert middleware._remote_addr(request) == '198.51.100.9'
