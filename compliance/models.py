import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from base.modules import OperationalModule
from base.models import SingleInstanceModel
from base.sequences import AutoCodeMixin
from governance.models import GovernanceAuditLog
from integrations.models import sanitize_safe_context


def validation_error_to_text(error):
    if hasattr(error, 'message_dict'):
        return '; '.join(
            f'{field}: {", ".join(messages)}' for field, messages in error.message_dict.items()
        )
    if hasattr(error, 'messages'):
        return '; '.join(str(message) for message in error.messages)
    return str(error)


class TransversalRequirementPolicy(AutoCodeMixin, SingleInstanceModel):
    CODE_PREFIX = 'TRP'

    class EnforcementLevel(models.TextChoices):
        MONITORING = 'monitoring', 'Monitoramento'
        WARNING = 'warning', 'Alerta'
        BLOCKING = 'blocking', 'Bloqueante'

    code = models.CharField('codigo', max_length=80, blank=True)
    title = models.CharField('titulo', max_length=180)
    description = models.TextField('descricao', blank=True)
    source_module = models.CharField('modulo', max_length=40, choices=OperationalModule.choices)
    source_module_ref = models.ForeignKey(
        'auxiliary.SystemModule',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='modulo normalizado',
    )
    enforcement_level = models.CharField(
        'nivel de exigencia',
        max_length=24,
        choices=EnforcementLevel.choices,
        default=EnforcementLevel.WARNING,
    )
    require_single_instance_scope = models.BooleanField(
        'exige escopo single-instance', default=True
    )
    require_permission_check = models.BooleanField('exige permissao', default=True)
    require_audit_log = models.BooleanField('exige auditoria', default=True)
    require_status_history = models.BooleanField('exige historico de status', default=True)
    require_transaction = models.BooleanField('exige transacao', default=True)
    require_ptbr_messages = models.BooleanField('exige mensagens pt-BR', default=True)
    is_active = models.BooleanField('ativo', default=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='owned_transversal_policies',
        null=True,
        blank=True,
        verbose_name='responsavel',
    )

    class Meta:
        ordering = ['source_module', 'code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_transversal_policy_code'),
        ]
        indexes = [
            models.Index(fields=['source_module', 'is_active']),
            models.Index(fields=['enforcement_level']),
            models.Index(fields=['owner']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'politica transversal'
        verbose_name_plural = 'politicas transversais'

    def save(self, *args, **kwargs):
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if not self.code.strip():
            errors['code'] = 'Informe o codigo da politica.'
        if not self.title.strip():
            errors['title'] = 'Informe o titulo da politica.'
        if self.enforcement_level == self.EnforcementLevel.BLOCKING:
            enforced = [
                self.require_single_instance_scope,
                self.require_permission_check,
                self.require_audit_log,
                self.require_status_history,
                self.require_transaction,
                self.require_ptbr_messages,
            ]
            if not any(enforced):
                errors['enforcement_level'] = (
                    'Politica bloqueante deve exigir ao menos um controle transversal.'
                )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.code} - {self.title}'


class RecordStatusHistory(SingleInstanceModel):
    source_module = models.CharField('modulo', max_length=40, choices=OperationalModule.choices)
    source_module_ref = models.ForeignKey(
        'auxiliary.SystemModule',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='modulo normalizado',
    )
    target_model = models.CharField('modelo alvo', max_length=120)
    target_model_ref = models.ForeignKey(
        'auxiliary.SystemModel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='model alvo normalizado',
    )
    target_record_id = models.CharField('registro alvo', max_length=120)
    previous_status = models.CharField('status anterior', max_length=80)
    new_status = models.CharField('novo status', max_length=80)
    action = models.CharField('acao', max_length=120)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='record_status_history',
        null=True,
        blank=True,
        verbose_name='usuario',
    )
    reason = models.TextField('motivo', blank=True)
    metadata = models.JSONField('metadados', default=dict, blank=True)
    occurred_at = models.DateTimeField('ocorrido em', default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-occurred_at', '-created_at']
        indexes = [
            models.Index(fields=['source_module', 'target_model', 'target_record_id']),
            models.Index(fields=['new_status']),
            models.Index(fields=['actor']),
            models.Index(fields=['occurred_at']),
        ]
        verbose_name = 'historico de status'
        verbose_name_plural = 'historicos de status'

    def save(self, *args, **kwargs):
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        for field in (
            'target_model',
            'target_record_id',
            'previous_status',
            'new_status',
            'action',
        ):
            if not str(getattr(self, field, '')).strip():
                errors[field] = 'Informe um valor nao vazio.'
        if self.previous_status == self.new_status:
            errors['new_status'] = 'Historico exige mudanca real de status.'
        if not isinstance(self.metadata or {}, dict):
            errors['metadata'] = 'Os metadados devem ser um objeto chave/valor.'
        if errors:
            raise ValidationError(errors)

    @classmethod
    def record_transition(
        cls, *, instance, previous_status, new_status, action, actor=None, reason='', metadata=None
    ):
        source_module = getattr(instance._meta, 'app_label', '')
        history = cls.objects.create(
            source_module=source_module,
            target_model=instance.__class__.__name__,
            target_record_id=str(instance.pk),
            previous_status=previous_status,
            new_status=new_status,
            action=action,
            actor=actor,
            reason=reason,
            metadata=sanitize_safe_context(metadata or {}),
        )
        GovernanceAuditLog.record(
            log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
            severity=GovernanceAuditLog.Severity.INFO,
            module=source_module,
            action='status.transition',
            target_model=history.target_model,
            target_record_id=history.target_record_id,
            user=actor,
            message=reason or 'Transicao de status registrada.',
            safe_context={
                'previous_status': previous_status,
                'new_status': new_status,
                'action': action,
                'metadata': metadata or {},
            },
        )
        return history

    def __str__(self):
        return (
            f'{self.target_model}:{self.target_record_id} {self.previous_status}->{self.new_status}'
        )


class CriticalActionExecution(SingleInstanceModel):
    class Status(models.TextChoices):
        RUNNING = 'running', 'Executando'
        SUCCEEDED = 'succeeded', 'Concluido'
        FAILED = 'failed', 'Falhou'

    action_code = models.CharField('codigo da acao', max_length=120)
    source_module = models.CharField('modulo', max_length=40, choices=OperationalModule.choices)
    source_module_ref = models.ForeignKey(
        'auxiliary.SystemModule',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='modulo normalizado',
    )
    target_model = models.CharField('modelo alvo', max_length=120, blank=True)
    target_model_ref = models.ForeignKey(
        'auxiliary.SystemModel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='model alvo normalizado',
    )
    target_record_id = models.CharField('registro alvo', max_length=120, blank=True)
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.RUNNING
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='critical_action_executions',
        null=True,
        blank=True,
        verbose_name='usuario',
    )
    requires_transaction = models.BooleanField('exige transacao', default=True)
    transaction_id = models.CharField(
        'id da transacao', max_length=64, unique=True, default='', blank=True
    )
    message = models.TextField('mensagem')
    safe_context = models.JSONField('contexto seguro', default=dict, blank=True)
    started_at = models.DateTimeField('iniciado em', default=timezone.now, db_index=True)
    completed_at = models.DateTimeField('concluido em', null=True, blank=True)
    error_message = models.TextField('erro', blank=True)

    class Meta:
        ordering = ['-started_at', '-created_at']
        indexes = [
            models.Index(fields=['source_module', 'status']),
            models.Index(fields=['actor']),
            models.Index(fields=['target_model', 'target_record_id']),
            models.Index(fields=['transaction_id']),
        ]
        verbose_name = 'execução de ação crítica'
        verbose_name_plural = 'execuções de ações críticas'

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = uuid.uuid4().hex
        self.safe_context = sanitize_safe_context(self.safe_context or {})
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if not self.action_code.strip():
            errors['action_code'] = 'Informe o codigo da acao critica.'
        if not self.message.strip():
            errors['message'] = 'Informe a mensagem da acao critica.'
        if not isinstance(self.safe_context or {}, dict):
            errors['safe_context'] = 'O contexto seguro deve ser um objeto chave/valor.'
        if self.status == self.Status.SUCCEEDED and not self.completed_at:
            errors['completed_at'] = 'Acao concluida exige data de conclusao.'
        if self.status == self.Status.FAILED and not self.error_message:
            errors['error_message'] = 'Acao com falha exige mensagem de erro.'
        if errors:
            raise ValidationError(errors)

    @classmethod
    def run_action(
        cls,
        *,
        action_code,
        source_module,
        message,
        callback,
        target=None,
        actor=None,
        safe_context=None,
        requires_transaction=True,
    ):
        execution = cls.objects.create(
            action_code=action_code,
            source_module=source_module,
            target_model=target.__class__.__name__ if target is not None else '',
            target_record_id=str(getattr(target, 'pk', '') or ''),
            actor=actor,
            requires_transaction=requires_transaction,
            message=message,
            safe_context=safe_context or {},
        )
        try:
            if requires_transaction:
                with transaction.atomic():
                    callback(execution)
            else:
                callback(execution)
        except Exception as error:
            execution.status = cls.Status.FAILED
            execution.completed_at = timezone.now()
            execution.error_message = validation_error_to_text(error)
            execution.save(update_fields=['status', 'completed_at', 'error_message', 'updated_at'])
            GovernanceAuditLog.record(
                log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
                severity=GovernanceAuditLog.Severity.ERROR,
                module=source_module,
                action='critical_action.failed',
                target_model=execution.target_model,
                target_record_id=execution.target_record_id,
                user=actor,
                message=execution.error_message,
                safe_context={
                    'action_code': action_code,
                    'transaction_id': execution.transaction_id,
                },
            )
            raise
        execution.status = cls.Status.SUCCEEDED
        execution.completed_at = timezone.now()
        execution.error_message = ''
        execution.save(update_fields=['status', 'completed_at', 'error_message', 'updated_at'])
        GovernanceAuditLog.record(
            log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
            severity=GovernanceAuditLog.Severity.INFO,
            module=source_module,
            action='critical_action.succeeded',
            target_model=execution.target_model,
            target_record_id=execution.target_record_id,
            user=actor,
            message=message,
            safe_context={'action_code': action_code, 'transaction_id': execution.transaction_id},
        )
        return execution

    def __str__(self):
        return f'{self.action_code} - {self.get_status_display()}'


class ComplianceChecklistItem(SingleInstanceModel):
    class CheckType(models.TextChoices):
        SINGLE_INSTANCE_SCOPE = 'single_instance_scope', 'Single-instance'
        PERMISSION = 'permission', 'Permissao'
        AUDIT = 'audit', 'Auditoria'
        STATUS_HISTORY = 'status_history', 'Historico de status'
        TRANSACTION = 'transaction', 'Transacao'
        PTBR_MESSAGES = 'ptbr_messages', 'Mensagens pt-BR'
        DOCS = 'docs', 'Documentacao'
        MENU = 'menu', 'Menu'
        TESTS = 'tests', 'Testes'
        API = 'api', 'API'

    class Status(models.TextChoices):
        PASS = 'pass', 'Aprovado'
        WARNING = 'warning', 'Alerta'
        FAIL = 'fail', 'Falhou'

    source_module = models.CharField('modulo', max_length=40, choices=OperationalModule.choices)
    source_module_ref = models.ForeignKey(
        'auxiliary.SystemModule',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='modulo normalizado',
    )
    check_type = models.CharField('tipo de check', max_length=32, choices=CheckType.choices)
    status = models.CharField('status', max_length=16, choices=Status.choices)
    evidence = models.TextField('evidencia')
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='compliance_checks',
        null=True,
        blank=True,
        verbose_name='verificado por',
    )
    checked_at = models.DateTimeField('verificado em', default=timezone.now, db_index=True)

    class Meta:
        ordering = ['source_module', 'check_type']
        constraints = [
            models.UniqueConstraint(
                fields=['source_module', 'check_type'],
                name='unique_module_compliance_check',
            ),
        ]
        indexes = [
            models.Index(fields=['source_module', 'status']),
            models.Index(fields=['check_type']),
            models.Index(fields=['checked_by']),
        ]
        verbose_name = 'item de checklist transversal'
        verbose_name_plural = 'itens de checklist transversal'

    def save(self, *args, **kwargs):
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if not self.evidence.strip():
            errors['evidence'] = 'Informe a evidencia do check.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.source_module} - {self.check_type}: {self.status}'
