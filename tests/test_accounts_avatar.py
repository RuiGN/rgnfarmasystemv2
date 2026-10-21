import tempfile
from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
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

    def test_authenticated_user_can_update_own_avatar(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('accounts:avatar'),
            {'avatar': self.avatar_upload()},
        )

        assert response.status_code == 302
        assert response['Location'] == reverse('accounts:avatar')
        self.user.refresh_from_db()
        assert self.user.avatar.name.startswith('avatars/user-')
        assert self.user.avatar.name.endswith('.png')

    def test_avatar_form_requires_login_and_renders_current_avatar(self):
        anonymous_response = self.client.get(reverse('accounts:avatar'))
        assert anonymous_response.status_code == 302
        assert anonymous_response['Location'].startswith('/accounts/login/')

        self.user.avatar = 'avatars/user-existing.png'
        self.user.save(update_fields=['avatar'])
        self.client.force_login(self.user)

        response = self.client.get(reverse('accounts:avatar'))

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Trocar avatar' in content
        assert 'Tirar selfie' in content
        assert 'name="avatar"' in content
        assert 'accept="image/*"' in content
        assert 'capture="user"' in content
        assert 'avatars/user-existing.png' in content
        assert 'data-icon=' not in content
        assert 'resource-input-group' not in content
        assert 'data-field-icon=' not in content

    def test_avatar_validation_errors_use_project_markup(self):
        self.client.force_login(self.user)

        response = self.client.post(
            reverse('accounts:avatar'),
            {'avatar': SimpleUploadedFile('avatar.txt', b'text', content_type='text/plain')},
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert 'id="id_avatar_errors"' in content
        assert 'class="invalid-feedback d-block"' in content
        assert 'role="alert"' in content
        assert 'aria-invalid="true"' in content
        assert 'aria-describedby="id_avatar_errors id_avatar_help"' in content
        assert 'feather-upload' in content

    def test_base_layout_and_current_user_api_expose_uploaded_avatar(self):
        self.user.avatar = 'avatars/user-existing.png'
        self.user.save(update_fields=['avatar'])
        self.client.force_login(self.user)

        app_response = self.client.get('/app/')
        assert app_response.status_code == 200
        app_content = app_response.content.decode()
        assert 'avatars/user-existing.png' in app_content
        assert f'href="{reverse("accounts:avatar")}"' in app_content
        assert 'Alterar avatar' in app_content
        assert 'vendor/duralux/images/1.png' not in app_content

        api_client = APIClient()
        api_client.force_authenticate(self.user)
        api_response = api_client.get('/api/accounts/me/')

        assert api_response.status_code == 200
        assert api_response.json()['avatar_url'].endswith('/media/avatars/user-existing.png')
