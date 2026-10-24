import logging
import time

from django.conf import settings
from django.utils import timezone

from integrations.models import (
    ApiCallLog,
    ApiClientApplication,
    SENSITIVE_CONTEXT_KEYS,
    sanitize_safe_context,
)

logger = logging.getLogger(__name__)


class ApiCallLoggingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith('/api/'):
            return self.get_response(request)

        started_at = time.monotonic()
        try:
            response = self.get_response(request)
        except Exception as error:
            self._record(request, 500, started_at, error_message=str(error))
            raise

        self._record(request, getattr(response, 'status_code', 500), started_at)
        return response

    def _record(self, request, status_code, started_at, error_message=''):
        try:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            client_application = self._resolve_client_application(request)
            if client_application:
                client_application.last_used_at = timezone.now()
                client_application.save(update_fields=['last_used_at', 'updated_at'])
            ApiCallLog.record(
                method=request.method,
                path=request.path,
                status_code=status_code,
                user=getattr(request, 'user', None),
                api_version=self._api_version(request.path),
                endpoint_name=self._endpoint_name(request),
                request_id=request.headers.get('X-Request-ID', ''),
                client_application=client_application,
                remote_addr=self._remote_addr(request),
                user_agent=request.META.get('HTTP_USER_AGENT', ''),
                duration_ms=duration_ms,
                safe_context=self._safe_context(request),
                error_message=error_message,
            )
        except Exception:
            logger.exception('Falha ao registrar ApiCallLog para %s', request.path)
            return

    def _resolve_client_application(self, request):
        client_id = request.headers.get('X-API-Client-ID', '')
        if not client_id:
            return None
        return ApiClientApplication.objects.filter(
            client_id=client_id,
            status=ApiClientApplication.Status.ACTIVE,
        ).first()

    def _api_version(self, path):
        parts = path.strip('/').split('/')
        if len(parts) >= 2 and parts[0] == 'api' and parts[1].startswith('v'):
            return parts[1]
        return 'legacy'

    def _endpoint_name(self, request):
        resolver_match = getattr(request, 'resolver_match', None)
        if resolver_match is None:
            return ''
        return resolver_match.view_name or resolver_match.url_name or ''

    def _remote_addr(self, request):
        forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
        # X-Forwarded-For é forjável: só é considerado atrás de proxy confiável.
        # O nginx usa $proxy_add_x_forwarded_for (anexa ao valor do cliente),
        # então apenas o último salto, adicionado pelo proxy, é confiável.
        if forwarded_for and getattr(settings, 'USE_X_FORWARDED_FOR', False):
            return forwarded_for.rsplit(',', 1)[-1].strip()
        return request.META.get('REMOTE_ADDR') or None

    def _safe_context(self, request):
        query_params = {}
        for key, values in request.GET.lists():
            if any(sensitive in key.lower() for sensitive in SENSITIVE_CONTEXT_KEYS):
                continue
            query_params[key] = [str(value) for value in values]
        return sanitize_safe_context({'query_params': query_params})
