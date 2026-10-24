import hashlib
import logging
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import REDIRECT_FIELD_NAME
from django.core.cache import cache
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import LoginView, LogoutView
from django.shortcuts import redirect
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic.edit import FormView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.serializers import CurrentUserSerializer


logger = logging.getLogger(__name__)


def admin_login_redirect(request):
    next_url = request.GET.get(REDIRECT_FIELD_NAME, '/admin/')
    if not (
        next_url.startswith('/admin/')
        and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=request.is_secure(),
        )
    ):
        next_url = '/admin/'

    query = urlencode({REDIRECT_FIELD_NAME: next_url}, safe='/')
    return redirect(f'{reverse("accounts:login")}?{query}')


class UsernameLoginView(LoginView):
    template_name = 'registration/login.html'
    redirect_authenticated_user = True

    def post(self, request, *args, **kwargs):
        rate_limit_keys = self._rate_limit_keys(request)
        max_attempts = settings.LOGIN_MAX_ATTEMPTS
        window_seconds = settings.LOGIN_WINDOW_SECONDS
        try:
            is_blocked = any(int(cache.get(key, 0) or 0) >= max_attempts for key in rate_limit_keys)
        except Exception:
            logger.exception('Login rate-limit cache is unavailable.')
            return self._service_unavailable_response()
        if is_blocked:
            form = self.get_form()
            form.add_error(None, 'Muitas tentativas. Aguarde antes de tentar novamente.')
            response = self.render_to_response(self.get_context_data(form=form), status=429)
            response['Retry-After'] = str(window_seconds)
            return response

        response = super().post(request, *args, **kwargs)
        try:
            if 300 <= response.status_code < 400:
                cache.delete_many(rate_limit_keys)
            else:
                for key in rate_limit_keys:
                    if not cache.add(key, 1, timeout=window_seconds):
                        try:
                            cache.incr(key)
                        except ValueError:
                            cache.set(key, 1, timeout=window_seconds)
        except Exception:
            logger.exception('Could not update login rate-limit counters.')
            return self._service_unavailable_response()
        return response

    def form_valid(self, form):
        return super().form_valid(form)

    def _service_unavailable_response(self):
        form = self.get_form()
        form.add_error(
            None, 'Autenticação temporariamente indisponível. Tente novamente em instantes.'
        )
        response = self.render_to_response(self.get_context_data(form=form), status=503)
        response['Retry-After'] = '60'
        return response

    def _rate_limit_keys(self, request):
        username = str(request.POST.get('username', '')).strip().casefold()
        ip_address = str(request.META.get('REMOTE_ADDR', '') or 'unknown')
        username_digest = hashlib.sha256(username.encode('utf-8')).hexdigest()
        ip_digest = hashlib.sha256(ip_address.encode('utf-8')).hexdigest()
        return (
            f'login:username:{username_digest}',
            f'login:ip:{ip_digest}',
        )

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields['username'].label = 'Nome do usuário'
        form.fields['username'].widget.attrs.update(
            {
                'autocomplete': 'username',
                'autofocus': True,
            }
        )
        for field in form.fields.values():
            classes = field.widget.attrs.get('class', '').split()
            if 'form-control' not in classes:
                classes.append('form-control')
            field.widget.attrs['class'] = ' '.join(classes)
        return form


class EmailLogoutView(LogoutView):
    pass


class CurrentUserAPIView(APIView):
    serializer_class = CurrentUserSerializer
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        serializer = CurrentUserSerializer(request.user, context={'request': request})
        return Response(serializer.data)
