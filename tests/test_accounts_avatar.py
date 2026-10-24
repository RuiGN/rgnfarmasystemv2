import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from PIL import Image
from rest_framework.test import APIClient

from accounts.models import user_avatar_path


def png_1x1():
    buffer = BytesIO()
    Image.new('RGB', (1, 1), color=(52, 84, 209)).save(buffer, format='PNG')
    return buffer.getvalue()


class UserAvatarTests(TestCase):
    def setUp(self):
        self.media_root = tempfile.TemporaryDirectory()
        self.override = override_settings(MEDIA_ROOT=self.media_root.name)
        self.override.enable()
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username='Avatar User',
            email='avatar@example.com',
            password='S3curePass!123',
        )

    def tearDown(self):
        self.override.disable()
        self.media_root.cleanup()

    def avatar_upload(self, name='avatar.png'):
        return SimpleUploadedFile(name, png_1x1(), content_type='image/png')

    def test_avatar_path_for_unsaved_users_uses_unique_reference(self):
        first_path = user_avatar_path(self.User(username='First User'), 'avatar.png')
        second_path = user_avatar_path(self.User(username='Second User'), 'avatar.png')

        assert first_path.startswith('avatars/user-')
        assert first_path.endswith('.png')
        assert second_path.startswith('avatars/user-')
        assert second_path.endswith('.png')
        assert 'user-new' not in first_path
        assert 'user-new' not in second_path
        assert first_path != second_path

    def test_base_layout_and_current_user_api_expose_uploaded_avatar(self):
        self.user.avatar = 'avatars/user-existing.png'
        self.user.save(update_fields=['avatar'])
        self.client.force_login(self.user)

        app_response = self.client.get('/app/')
        assert app_response.status_code == 200
        app_content = app_response.content.decode()
        assert 'avatars/user-existing.png' in app_content
        # A troca de avatar foi removida: o avatar é exibido, não editável.
        assert 'Alterar avatar' not in app_content
        assert 'Trocar avatar' not in app_content
        assert '/accounts/avatar/' not in app_content
        assert 'vendor/duralux/images/1.png' not in app_content

        api_client = APIClient()
        api_client.force_authenticate(self.user)
        api_response = api_client.get('/api/accounts/me/')

        assert api_response.status_code == 200
        assert api_response.json()['avatar_url'].endswith('/media/avatars/user-existing.png')
