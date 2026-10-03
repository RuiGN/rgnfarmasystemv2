from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from base.models import SingleInstanceModel


SENSITIVE_CONTEXT_KEYS = {
    'api_key',
    'authorization',
    'cookie',
    'password',
    'secret',
    'token',
}


def sanitize_safe_context(context):
    if not isinstance(context or {}, dict):
        return {}

    sanitized = {}
    for key, value in (context or {}).items():
        key_text = str(key)
        if any(sensitive in key_text.lower() for sensitive in SENSITIVE_CONTEXT_KEYS):
            continue
        if isinstance(value, dict):
            nested = sanitize_safe_context(value)
            if nested:
                sanitized[key_text] = nested
            continue
        if isinstance(value, (list, tuple)):
            filtered = []
            for item in value:
                if isinstance(item, dict):
                    nested = sanitize_safe_context(item)
                    if nested:
                        filtered.append(nested)
                else:
                    filtered.append(str(item))
            sanitized[key_text] = filtered
            continue
        sanitized[key_text] = (
            value if isinstance(value, (bool, int, float)) or value is None else str(value)
        )
    return sanitized


class LabelPrinterSettings(SingleInstanceModel):
    class Protocol(models.TextChoices):
        TSPL2 = 'tspl2', 'Argox TSPL2'

    name = models.CharField('nome', max_length=120, default='Argox principal')
    host = models.CharField('IP ou hostname', max_length=255, blank=True)
    port = models.PositiveIntegerField('porta TCP', default=9100)
    protocol = models.CharField(
        'protocolo', max_length=16, choices=Protocol.choices, default=Protocol.TSPL2
    )
    width_mm = models.PositiveSmallIntegerField('largura (mm)', default=40)
    height_mm = models.PositiveSmallIntegerField('altura (mm)', default=30)
    is_active = models.BooleanField('ativo', default=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['name']
        constraints = [
            models.UniqueConstraint(
                fields=('is_active',),
                condition=models.Q(is_active=True),
                name='unique_active_label_printer',
            )
        ]
        verbose_name = 'configuração de impressora de etiquetas'
        verbose_name_plural = 'configurações de impressoras de etiquetas'

    def clean(self):
        super().clean()
        self.host = str(self.host or '').strip()
        errors = {}
        if self.is_active and not self.host:
            errors['host'] = 'Informe o IP ou hostname da impressora ativa.'
        if not 1 <= int(self.port or 0) <= 65535:
            errors['port'] = 'Informe uma porta TCP entre 1 e 65535.'
        if int(self.width_mm or 0) <= 0:
            errors['width_mm'] = 'A largura da etiqueta deve ser positiva.'
        if int(self.height_mm or 0) <= 0:
            errors['height_mm'] = 'A altura da etiqueta deve ser positiva.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class IntegrationConnector(SingleInstanceModel):
    class ProviderType(models.TextChoices):
        ERP = 'erp', 'ERP externo'
        FISCAL_SYSTEM = 'fiscal_system', 'Sistema fiscal'
        LABORATORY = 'laboratory', 'Laboratorio'
        EMAIL_PROVIDER = 'email_provider', 'Provedor de email'
        OPENAI = 'openai', 'OpenAI'
        BI = 'bi', 'BI'

    class AuthType(models.TextChoices):
        NONE = 'none', 'Sem autenticacao'
        API_KEY = 'api_key', 'API key'
        OAUTH2 = 'oauth2', 'OAuth2'
        BASIC = 'basic', 'Basic auth'
        TOKEN = 'token', 'Token'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        ACTIVE = 'active', 'Ativo'
        SUSPENDED = 'suspended', 'Suspenso'
        ERROR = 'error', 'Erro'
        ARCHIVED = 'archived', 'Arquivado'

    code = models.CharField('codigo', max_length=80)
    name = models.CharField('nome', max_length=180)
    provider_type = models.CharField(
        'tipo de provedor', max_length=32, choices=ProviderType.choices
    )
    base_url = models.URLField('URL base', max_length=500, blank=True)
    auth_type = models.CharField(
        'tipo de autenticacao', max_length=32, choices=AuthType.choices, default=AuthType.NONE
    )
    secret_reference = models.CharField('referencia segura do segredo', max_length=255, blank=True)
    configuration = models.JSONField('configuracao segura', default=dict, blank=True)
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='integration_connectors',
        null=True,
        blank=True,
        verbose_name='responsavel',
    )
    status = models.CharField('status', max_length=32, choices=Status.choices, default=Status.DRAFT)
    is_active = models.BooleanField('ativo', default=True)
    last_tested_at = models.DateTimeField('ultimo teste em', null=True, blank=True)
    last_error = models.TextField('ultimo erro', blank=True)

    class Meta:
        ordering = ['provider_type', 'code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_integration_connector_code'),
        ]
        indexes = [
            models.Index(fields=['provider_type', 'status', 'is_active']),
            models.Index(fields=['responsible']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'conector de integração'
        verbose_name_plural = 'conectores de integração'

    def save(self, *args, **kwargs):
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if not isinstance(self.configuration or {}, dict):
            errors['configuration'] = 'A configuracao deve ser um objeto chave/valor.'
        if self.auth_type != self.AuthType.NONE and not self.secret_reference:
            missing_reference_message = 'Informe a referencia segura do segredo para autenticacao.'
            errors['secret_reference'] = missing_reference_message
        if self.provider_type != self.ProviderType.EMAIL_PROVIDER and not self.base_url:
            errors['base_url'] = 'Informe a URL base do provedor.'
        if self.provider_type == self.ProviderType.FISCAL_SYSTEM:
            from integrations.fiscal_security import validate_fiscal_destination

            try:
                validate_fiscal_destination(self.base_url, self.secret_reference)
            except ValidationError as error:
                errors.update(error.message_dict)
        if errors:
            raise ValidationError(errors)

    def validate_fiscal_management(self, user, attrs):
        effective_type = attrs.get('provider_type', self.provider_type)
        fiscal = (
            self.provider_type == self.ProviderType.FISCAL_SYSTEM
            or effective_type == self.ProviderType.FISCAL_SYSTEM
        )
        if fiscal and not (user and user.is_authenticated and user.is_active and user.is_staff):
            raise ValidationError(
                {
                    'permission': 'Gestão de conectores fiscais exige usuário staff e permissão de modelo.'
                }
            )

    def activate(self, user=None):
        self.status = self.Status.ACTIVE
        self.is_active = True
        self.last_error = ''
        self.save(update_fields=['status', 'is_active', 'last_error', 'updated_at'])
        self.record_event(
            IntegrationEvent.EventType.ACTIVATED, actor=user, message='Conector ativado.'
        )
        return self

    def suspend(self, reason='', user=None):
        self.status = self.Status.SUSPENDED
        self.is_active = False
        self.last_error = reason or ''
        self.save(update_fields=['status', 'is_active', 'last_error', 'updated_at'])
        self.record_event(
            IntegrationEvent.EventType.SUSPENDED,
            actor=user,
            message=reason or 'Conector suspenso.',
        )
        return self

    def record_test_success(self, details=None):
        self.status = self.Status.ACTIVE
        self.is_active = True
        self.last_tested_at = timezone.now()
        self.last_error = ''
        self.save(
            update_fields=['status', 'is_active', 'last_tested_at', 'last_error', 'updated_at']
        )
        self.record_event(
            IntegrationEvent.EventType.TEST_SUCCESS,
            message='Teste de integracao executado com sucesso.',
            safe_context=details or {},
        )
        return self

    def record_test_failure(self, error_message, details=None):
        self.status = self.Status.ERROR
        self.last_tested_at = timezone.now()
        self.last_error = error_message or 'Falha no teste de integracao.'
        self.save(update_fields=['status', 'last_tested_at', 'last_error', 'updated_at'])
        self.record_event(
            IntegrationEvent.EventType.TEST_FAILURE,
            message=self.last_error,
            safe_context=details or {},
        )
        return self

    def record_event(
        self, event_type, actor=None, message='', safe_context=None, api_client_application=None
    ):
        return IntegrationEvent.objects.create(
            connector=self,
            api_client_application=api_client_application,
            event_type=event_type,
            actor=actor,
            message=message,
            safe_context=sanitize_safe_context(safe_context or {}),
        )

    def __str__(self):
        return f'{self.code} - {self.name}'


class ApiClientApplication(SingleInstanceModel):
    class Status(models.TextChoices):
        ACTIVE = 'active', 'Ativo'
        SUSPENDED = 'suspended', 'Suspenso'
        REVOKED = 'revoked', 'Revogado'

    code = models.CharField('codigo', max_length=80)
    name = models.CharField('nome', max_length=180)
    client_id = models.CharField('client id', max_length=120)
    secret_hash = models.CharField('hash do segredo', max_length=255, blank=True)
    scopes = models.JSONField('escopos', default=list)
    status = models.CharField(
        'status', max_length=32, choices=Status.choices, default=Status.ACTIVE
    )
    expires_at = models.DateTimeField('expira em', null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_api_client_applications',
        null=True,
        blank=True,
        verbose_name='criado por',
    )
    last_used_at = models.DateTimeField('ultimo uso em', null=True, blank=True)

    class Meta:
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_api_client_code'),
            models.UniqueConstraint(fields=['client_id'], name='unique_api_client_id'),
        ]
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['created_by']),
            models.Index(fields=['client_id']),
        ]
        verbose_name = 'cliente de API'
        verbose_name_plural = 'clientes de API'

    def save(self, *args, **kwargs):
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if not isinstance(self.scopes or [], list) or not self.scopes:
            errors['scopes'] = 'Informe ao menos um escopo em formato de lista.'
        elif any(not isinstance(scope, str) or not scope.strip() for scope in self.scopes):
            errors['scopes'] = 'Todos os escopos devem ser textos nao vazios.'
        if (
            self.expires_at
            and self.expires_at <= timezone.now()
            and self.status == self.Status.ACTIVE
        ):
            errors['expires_at'] = 'Cliente ativo nao pode estar expirado.'
        if errors:
            raise ValidationError(errors)

    def has_scope(self, scope):
        return scope in (self.scopes or []) and self.status == self.Status.ACTIVE

    def rotate_secret(self, raw_secret, user=None):
        if not raw_secret:
            missing_value_message = 'Informe o novo segredo.'
            raise ValidationError({'secret': missing_value_message})
        self.secret_hash = make_password(raw_secret)
        self.save(update_fields=['secret_hash', 'updated_at'])
        self.record_event(
            IntegrationEvent.EventType.SECRET_ROTATED,
            actor=user,
            message='Segredo do cliente de API rotacionado.',
        )
        return self

    def record_event(self, event_type, actor=None, message='', safe_context=None, connector=None):
        return IntegrationEvent.objects.create(
            connector=connector,
            api_client_application=self,
            event_type=event_type,
            actor=actor,
            message=message,
            safe_context=sanitize_safe_context(safe_context or {}),
        )

    def __str__(self):
        return f'{self.code} - {self.name}'


class ApiCallLog(SingleInstanceModel):
    class Outcome(models.TextChoices):
        SUCCESS = 'success', 'Sucesso'
        ERROR = 'error', 'Erro'

    request_id = models.CharField('id da requisicao', max_length=120, blank=True, db_index=True)
    api_version = models.CharField('versao da API', max_length=32, default='legacy', db_index=True)
    method = models.CharField('metodo', max_length=16)
    path = models.CharField('caminho', max_length=500)
    endpoint_name = models.CharField('endpoint', max_length=180, blank=True)
    status_code = models.PositiveIntegerField('status HTTP', db_index=True)
    outcome = models.CharField('resultado', max_length=16, choices=Outcome.choices)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='api_call_logs',
        null=True,
        blank=True,
        verbose_name='usuario',
    )
    client_application = models.ForeignKey(
        ApiClientApplication,
        on_delete=models.SET_NULL,
        related_name='api_call_logs',
        null=True,
        blank=True,
        verbose_name='cliente de API',
    )
    remote_addr = models.GenericIPAddressField('IP remoto', null=True, blank=True)
    user_agent = models.CharField('user agent', max_length=500, blank=True)
    duration_ms = models.PositiveIntegerField('duracao ms', default=0)
    safe_context = models.JSONField('contexto seguro', default=dict, blank=True)
    error_message = models.TextField('mensagem de erro', blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['api_version', 'path']),
            models.Index(fields=['user', 'status_code']),
            models.Index(fields=['outcome', 'status_code']),
            models.Index(fields=['request_id']),
        ]
        verbose_name = 'log de chamada de API'
        verbose_name_plural = 'logs de chamadas de API'

    def save(self, *args, **kwargs):
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if not isinstance(self.safe_context or {}, dict):
            errors['safe_context'] = 'Contexto seguro deve ser um objeto chave/valor.'
        if errors:
            raise ValidationError(errors)

    @classmethod
    def record(
        cls,
        *,
        method,
        path,
        status_code,
        user=None,
        api_version='legacy',
        endpoint_name='',
        request_id='',
        client_application=None,
        remote_addr=None,
        user_agent='',
        duration_ms=0,
        safe_context=None,
        error_message='',
    ):
        outcome = cls.Outcome.ERROR if status_code >= 400 else cls.Outcome.SUCCESS
        return cls.objects.create(
            request_id=request_id or '',
            api_version=api_version or 'legacy',
            method=(method or '').upper(),
            path=path,
            endpoint_name=endpoint_name or '',
            status_code=status_code,
            outcome=outcome,
            user=user if getattr(user, 'is_authenticated', False) else None,
            client_application=client_application,
            remote_addr=remote_addr,
            user_agent=(user_agent or '')[:500],
            duration_ms=max(int(duration_ms or 0), 0),
            safe_context=sanitize_safe_context(safe_context or {}),
            error_message=error_message or '',
        )

    def __str__(self):
        return f'{self.method} {self.path} {self.status_code}'


class IntegrationEvent(SingleInstanceModel):
    class EventType(models.TextChoices):
        CONFIGURED = 'configured', 'Configurado'
        ACTIVATED = 'activated', 'Ativado'
        SUSPENDED = 'suspended', 'Suspenso'
        TEST_SUCCESS = 'test_success', 'Teste com sucesso'
        TEST_FAILURE = 'test_failure', 'Teste com falha'
        SECRET_ROTATED = 'secret_rotated', 'Segredo rotacionado'
        CALL_LOGGED = 'call_logged', 'Chamada registrada'
        ERROR = 'error', 'Erro'

    connector = models.ForeignKey(
        IntegrationConnector,
        on_delete=models.SET_NULL,
        related_name='events',
        null=True,
        blank=True,
        verbose_name='conector',
    )
    api_client_application = models.ForeignKey(
        ApiClientApplication,
        on_delete=models.SET_NULL,
        related_name='events',
        null=True,
        blank=True,
        verbose_name='cliente de API',
    )
    event_type = models.CharField('tipo de evento', max_length=32, choices=EventType.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='integration_events',
        null=True,
        blank=True,
        verbose_name='ator',
    )
    occurred_at = models.DateTimeField('ocorrido em', default=timezone.now, db_index=True)
    message = models.TextField('mensagem', blank=True)
    safe_context = models.JSONField('contexto seguro', default=dict, blank=True)

    class Meta:
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['event_type', 'occurred_at']),
            models.Index(fields=['connector', 'occurred_at']),
            models.Index(fields=['api_client_application', 'occurred_at']),
            models.Index(fields=['actor', 'occurred_at']),
        ]
        verbose_name = 'evento de integração'
        verbose_name_plural = 'eventos de integração'

    def save(self, *args, **kwargs):
        self.safe_context = sanitize_safe_context(self.safe_context or {})
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if not isinstance(self.safe_context or {}, dict):
            errors['safe_context'] = 'Contexto seguro deve ser um objeto chave/valor.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.get_event_type_display()} - {self.occurred_at:%Y-%m-%d %H:%M}'
