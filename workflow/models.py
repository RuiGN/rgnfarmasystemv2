from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import models
from django.utils import timezone

from base.models import SingleInstanceModel
from base.sequences import AutoCodeMixin, IdentifierSpec, sequence_code
from base.roles import OperationalRole, user_has_operational_role


ZERO_AMOUNT = Decimal('0.00')


def _sequence_code(model, *args):
    if len(args) == 3:
        _legacy_scope, field_name, prefix = args
    else:
        field_name, prefix = args
    return sequence_code(model, field_name, prefix)


class WorkflowNotification(SingleInstanceModel):
    class SourceModule(models.TextChoices):
        PRODUCTION = 'production', 'Produção'
        MRP = 'mrp', 'MRP'
        INVENTORY = 'inventory', 'Estoque'
        TRACEABILITY = 'traceability', 'Rastreabilidade'
        COSTING = 'costing', 'Custos'
        FINANCE = 'finance', 'Financeiro'
        FISCAL = 'fiscal', 'Fiscal'
        QUALITY = 'quality', 'Qualidade'
        AUDIT = 'audit', 'Auditoria'
        CAPA = 'capa', 'CAPA'
        DEVIATIONS = 'deviations', 'Desvios'
        RISKS = 'risks', 'Riscos'
        ADMINISTRATIVE = 'administrative', 'Administrativo'

    class Category(models.TextChoices):
        PENDING = 'pending', 'Pendência'
        APPROVAL = 'approval', 'Aprovação'
        ALERT = 'alert', 'Alerta'
        DUE_DATE = 'due_date', 'Vencimento'
        DELAY = 'delay', 'Atraso'
        REJECTION = 'rejection', 'Reprovação'
        TASK_COMPLETED = 'task_completed', 'Tarefa concluída'

    class Channel(models.TextChoices):
        INTERNAL = 'internal', 'Interna'
        EMAIL = 'email', 'Email'

    class Criticality(models.TextChoices):
        LOW = 'low', 'Baixa'
        MEDIUM = 'medium', 'Média'
        HIGH = 'high', 'Alta'
        CRITICAL = 'critical', 'Crítica'

    class Status(models.TextChoices):
        UNREAD = 'unread', 'Não lida'
        SENT = 'sent', 'Enviada'
        READ = 'read', 'Lida'
        ARCHIVED = 'archived', 'Arquivada'
        FAILED = 'failed', 'Falhou'

    category = models.CharField('categoria', max_length=32, choices=Category.choices)
    channel = models.CharField(
        'canal', max_length=24, choices=Channel.choices, default=Channel.INTERNAL
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='workflow_notifications',
        verbose_name='destinatário',
    )
    title = models.CharField('título', max_length=180)
    message = models.TextField('mensagem')
    source_module = models.CharField(
        'módulo de origem', max_length=32, choices=SourceModule.choices
    )
    source_module_ref = models.ForeignKey(
        'auxiliary.SystemModule',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='módulo de origem normalizado',
    )
    source_model = models.CharField('modelo de origem', max_length=120, blank=True)
    source_model_ref = models.ForeignKey(
        'auxiliary.SystemModel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='model de origem normalizado',
    )
    source_record_id = models.CharField('registro de origem', max_length=80, blank=True)
    criticality = models.CharField(
        'criticidade', max_length=24, choices=Criticality.choices, default=Criticality.MEDIUM
    )
    criticality_ref = models.ForeignKey(
        'auxiliary.ImpactLevel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='criticidade normalizada',
    )
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.UNREAD
    )
    due_at = models.DateTimeField('vence em', null=True, blank=True)
    sent_at = models.DateTimeField('enviada em', null=True, blank=True)
    read_at = models.DateTimeField('lida em', null=True, blank=True)
    archived_at = models.DateTimeField('arquivada em', null=True, blank=True)
    error_message = models.TextField('erro', blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'status']),
            models.Index(fields=['category', 'criticality']),
            models.Index(fields=['source_module', 'source_model', 'source_record_id']),
            models.Index(fields=['due_at']),
        ]
        verbose_name = 'notificação de workflow'
        verbose_name_plural = 'notificações de workflow'

    def save(self, *args, **kwargs):
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def send(self):
        try:
            if self.channel == self.Channel.EMAIL:
                send_mail(
                    self.title,
                    self.message,
                    getattr(settings, 'DEFAULT_FROM_EMAIL', None),
                    [self.recipient.email],
                    fail_silently=False,
                )
            self.status = self.Status.SENT
            self.sent_at = timezone.now()
            self.error_message = ''
            self.save(update_fields=['status', 'sent_at', 'error_message', 'updated_at'])
            self.record_history(WorkflowHistory.Action.SENT, actor=self.recipient)
        except Exception as exc:
            self.status = self.Status.FAILED
            self.error_message = str(exc)
            self.save(update_fields=['status', 'error_message', 'updated_at'])
            self.record_history(
                WorkflowHistory.Action.FAILED,
                actor=self.recipient,
                details={'error': self.error_message},
            )
            raise

    def mark_read(self, user=None):
        if user and user.pk != self.recipient_id:
            raise ValidationError(
                {'permission': 'Somente o destinatário pode marcar a notificação como lida.'}
            )
        self.status = self.Status.READ
        self.read_at = timezone.now()
        self.save(update_fields=['status', 'read_at', 'updated_at'])
        self.record_history(WorkflowHistory.Action.READ, actor=user or self.recipient)

    def archive(self, user=None):
        if user and user.pk != self.recipient_id:
            raise ValidationError(
                {'permission': 'Somente o destinatário pode arquivar a notificação.'}
            )
        self.status = self.Status.ARCHIVED
        self.archived_at = timezone.now()
        self.save(update_fields=['status', 'archived_at', 'updated_at'])
        self.record_history(WorkflowHistory.Action.ARCHIVED, actor=user or self.recipient)

    def record_history(self, action, actor=None, details=None):
        return WorkflowHistory.objects.create(
            notification=self,
            action=action,
            actor=actor,
            snapshot=f'{self.get_category_display()}: {self.title}',
            details=details or {},
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.status == self.Status.READ and not self.read_at:
            errors['read_at'] = 'Notificação lida exige data de leitura.'
        if self.status == self.Status.ARCHIVED and not self.archived_at:
            errors['archived_at'] = 'Notificação arquivada exige data de arquivamento.'
        if self.status == self.Status.SENT and not self.sent_at:
            errors['sent_at'] = 'Notificação enviada exige data de envio.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


class ApprovalQueue(AutoCodeMixin, SingleInstanceModel):
    CODE_PREFIX = 'APV'
    code = models.CharField('código', max_length=80, blank=True)
    name = models.CharField('nome', max_length=180)
    module = models.CharField(
        'módulo', max_length=32, choices=WorkflowNotification.SourceModule.choices
    )
    module_ref = models.ForeignKey(
        'auxiliary.SystemModule',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='módulo normalizado',
    )
    area = models.CharField('área', max_length=120, blank=True)
    area_ref = models.ForeignKey(
        'auxiliary.BusinessArea',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='área normalizada',
    )
    profile_role = models.CharField('perfil', max_length=32, choices=OperationalRole.choices)
    role_ref = models.ForeignKey(
        'auxiliary.OrganizationalRole',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='perfil normalizado',
    )
    criticality = models.CharField(
        'criticidade', max_length=24, choices=WorkflowNotification.Criticality.choices, blank=True
    )
    criticality_ref = models.ForeignKey(
        'auxiliary.ImpactLevel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='criticidade normalizada',
    )
    approval_limit = models.DecimalField(
        'alçada', max_digits=14, decimal_places=2, null=True, blank=True
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_approval_queues',
        null=True,
        blank=True,
        verbose_name='criada por',
    )
    is_active = models.BooleanField('ativa', default=True)
    description = models.TextField('descrição', blank=True)

    class Meta:
        ordering = ['module', 'area', 'code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_approval_queue_code'),
        ]
        indexes = [
            models.Index(fields=['module', 'area', 'profile_role', 'is_active']),
            models.Index(fields=['criticality']),
            models.Index(fields=['created_by']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'fila de aprovação'
        verbose_name_plural = 'filas de aprovação'

    def save(self, *args, **kwargs):
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def matches(self, user, module, area='', criticality='', amount=None):
        if not self.is_active or not user or not getattr(user, 'is_authenticated', False):
            return False
        if not user.is_active:
            return False
        if self.module != module:
            return False
        if self.area and self.area != area:
            return False
        if self.criticality and self.criticality != criticality:
            return False
        amount = Decimal(str(amount or ZERO_AMOUNT))
        if self.approval_limit is not None and amount > self.approval_limit:
            return False
        return user_has_operational_role(user, self.profile_role)

    def clean(self):
        super().clean()
        errors = {}
        if self.approval_limit is not None and self.approval_limit < ZERO_AMOUNT:
            errors['approval_limit'] = 'A alçada não pode ser negativa.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.code} - {self.name}'


class ApprovalTask(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('task_number', 'WF'),)

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        APPROVED = 'approved', 'Aprovada'
        REJECTED = 'rejected', 'Reprovada'
        CANCELLED = 'cancelled', 'Cancelada'

    task_number = models.CharField('tarefa', max_length=80, blank=True)
    queue = models.ForeignKey(
        ApprovalQueue, on_delete=models.PROTECT, related_name='tasks', verbose_name='fila'
    )
    title = models.CharField('título', max_length=180)
    description = models.TextField('descrição', blank=True)
    source_module = models.CharField(
        'módulo de origem', max_length=32, choices=WorkflowNotification.SourceModule.choices
    )
    source_module_ref = models.ForeignKey(
        'auxiliary.SystemModule',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='módulo de origem normalizado',
    )
    source_model = models.CharField('modelo de origem', max_length=120)
    source_model_ref = models.ForeignKey(
        'auxiliary.SystemModel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='model de origem normalizado',
    )
    source_record_id = models.CharField('registro de origem', max_length=80)
    area = models.CharField('área', max_length=120, blank=True)
    area_ref = models.ForeignKey(
        'auxiliary.BusinessArea',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='área normalizada',
    )
    criticality = models.CharField(
        'criticidade',
        max_length=24,
        choices=WorkflowNotification.Criticality.choices,
        default=WorkflowNotification.Criticality.MEDIUM,
    )
    criticality_ref = models.ForeignKey(
        'auxiliary.ImpactLevel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='criticidade normalizada',
    )
    amount = models.DecimalField(
        'valor/alçada', max_digits=14, decimal_places=2, default=ZERO_AMOUNT
    )
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.PENDING
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='requested_approval_tasks',
        null=True,
        blank=True,
        verbose_name='solicitada por',
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='assigned_approval_tasks',
        null=True,
        blank=True,
        verbose_name='atribuída a',
    )
    due_at = models.DateTimeField('vence em', null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='decided_approval_tasks',
        null=True,
        blank=True,
        verbose_name='decidida por',
    )
    decided_at = models.DateTimeField('decidida em', null=True, blank=True)
    decision_comments = models.TextField('comentários da decisão', blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['task_number'], name='unique_approval_task_number'),
        ]
        indexes = [
            models.Index(fields=['queue', 'status']),
            models.Index(fields=['assigned_to', 'status']),
            models.Index(fields=['requested_by']),
            models.Index(fields=['source_module', 'source_model', 'source_record_id']),
            models.Index(fields=['criticality', 'due_at']),
        ]
        verbose_name = 'tarefa de aprovação'
        verbose_name_plural = 'tarefas de aprovação'

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if not self.task_number:
            self.task_number = _sequence_code(ApprovalTask, 'task_number', 'WF')
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)
        if is_new:
            self.record_history(WorkflowHistory.Action.CREATED, actor=self.requested_by)
            self._notify_assignee()

    def _notify_assignee(self):
        if not self.assigned_to:
            return
        WorkflowNotification.objects.create(
            category=WorkflowNotification.Category.APPROVAL,
            channel=WorkflowNotification.Channel.INTERNAL,
            recipient=self.assigned_to,
            title=f'Aprovação pendente: {self.title}',
            message=self.description or self.title,
            source_module=self.source_module,
            source_model=self.source_model,
            source_record_id=self.source_record_id,
            criticality=self.criticality,
            due_at=self.due_at,
        )

    def active_delegation_for(self, user):
        if not self.assigned_to_id:
            return None
        now = timezone.now()
        return (
            WorkflowDelegation.objects.filter(
                from_user=self.assigned_to,
                to_user=user,
                is_active=True,
                starts_at__lte=now,
                ends_at__gte=now,
            )
            .filter(models.Q(module='') | models.Q(module=self.source_module))
            .first()
        )

    def validate_sensitive_changes(self, user, attrs):
        sensitive = {
            'queue',
            'assigned_to',
            'requested_by',
            'amount',
            'area',
            'criticality',
            'source_module',
            'source_model',
            'source_record_id',
            'source_module_ref',
            'source_model_ref',
            'area_ref',
            'criticality_ref',
        }
        changed = any(name in attrs and attrs[name] != getattr(self, name) for name in sensitive)
        if changed and not (
            user and user.is_active and user.has_perm('workflow.change_approvalqueue')
        ):
            raise ValidationError(
                {'permission': 'Alteração sensível exige gestão da fila de aprovação.'}
            )

    def can_approve(self, user):
        if not user or not user.is_authenticated or not user.is_active:
            return False
        if user.pk == self.requested_by_id:
            return False
        if user.is_superuser:
            return self.queue.matches(
                user, self.source_module, self.area, self.criticality, self.amount
            )
        if self.assigned_to_id:
            if user.pk == self.assigned_to_id:
                return self.queue.matches(
                    user, self.source_module, self.area, self.criticality, self.amount
                )
            if self.assigned_to_id == self.requested_by_id:
                return False
            delegation = self.active_delegation_for(user)
            return delegation is not None and self.queue.matches(
                delegation.from_user, self.source_module, self.area, self.criticality, self.amount
            )
        return self.queue.matches(
            user, self.source_module, self.area, self.criticality, self.amount
        )

    def approve(self, user=None, comments=''):
        if self.status != self.Status.PENDING:
            raise ValidationError({'status': 'Somente tarefas pendentes podem ser aprovadas.'})
        if not self.can_approve(user):
            raise ValidationError(
                {'permission': 'Usuário sem permissão ou alçada para aprovar esta tarefa.'}
            )
        self.status = self.Status.APPROVED
        self.decided_by = user
        self.decided_at = timezone.now()
        self.decision_comments = comments
        self.save(
            update_fields=['status', 'decided_by', 'decided_at', 'decision_comments', 'updated_at']
        )
        self.record_history(
            WorkflowHistory.Action.APPROVED, actor=user, details={'comments': comments}
        )
        self._notify_completion(
            WorkflowNotification.Category.TASK_COMPLETED, f'Tarefa aprovada: {self.title}'
        )

    def reject(self, user=None, comments=''):
        if self.status != self.Status.PENDING:
            raise ValidationError({'status': 'Somente tarefas pendentes podem ser reprovadas.'})
        if not self.can_approve(user):
            raise ValidationError(
                {'permission': 'Usuário sem permissão ou alçada para reprovar esta tarefa.'}
            )
        if not comments:
            raise ValidationError({'comments': 'Informe a justificativa da reprovação.'})
        self.status = self.Status.REJECTED
        self.decided_by = user
        self.decided_at = timezone.now()
        self.decision_comments = comments
        self.save(
            update_fields=['status', 'decided_by', 'decided_at', 'decision_comments', 'updated_at']
        )
        self.record_history(
            WorkflowHistory.Action.REJECTED, actor=user, details={'comments': comments}
        )
        self._notify_completion(
            WorkflowNotification.Category.REJECTION, f'Tarefa reprovada: {self.title}'
        )

    def cancel(self, user=None, comments=''):
        if self.status != self.Status.PENDING:
            raise ValidationError({'status': 'Somente tarefas pendentes podem ser canceladas.'})
        self.status = self.Status.CANCELLED
        self.decided_by = user
        self.decided_at = timezone.now()
        self.decision_comments = comments
        self.save(
            update_fields=['status', 'decided_by', 'decided_at', 'decision_comments', 'updated_at']
        )
        self.record_history(
            WorkflowHistory.Action.CANCELLED, actor=user, details={'comments': comments}
        )

    def _notify_completion(self, category, title):
        if self.requested_by:
            WorkflowNotification.objects.create(
                category=category,
                channel=WorkflowNotification.Channel.INTERNAL,
                recipient=self.requested_by,
                title=title,
                message=self.decision_comments or title,
                source_module=self.source_module,
                source_model=self.source_model,
                source_record_id=self.source_record_id,
                criticality=self.criticality,
            )

    def add_comment(self, author, comment):
        if not comment:
            raise ValidationError({'comment': 'Comentário é obrigatório.'})
        entry = WorkflowComment.objects.create(task=self, author=author, comment=comment)
        self.record_history(
            WorkflowHistory.Action.COMMENTED, actor=author, details={'comment': comment}
        )
        return entry

    def attach_file(self, file_name, file_reference, content_hash, uploaded_by=None):
        attachment = WorkflowAttachment.objects.create(
            task=self,
            file_name=file_name,
            file_reference=file_reference,
            content_hash=content_hash,
            uploaded_by=uploaded_by,
        )
        self.record_history(
            WorkflowHistory.Action.ATTACHED, actor=uploaded_by, details={'file_name': file_name}
        )
        return attachment

    def record_history(self, action, actor=None, details=None):
        return WorkflowHistory.objects.create(
            task=self,
            action=action,
            actor=actor,
            snapshot=f'{self.task_number} - {self.get_status_display()}',
            details=details or {},
        )

    def clean(self):
        super().clean()
        errors = {}
        for field in ('requested_by', 'assigned_to', 'decided_by'):
            pass
        if self.queue_id:
            if self.queue.module != self.source_module:
                errors['source_module'] = 'A tarefa deve pertencer ao módulo da fila.'
            if self.queue.area and self.queue.area != self.area:
                errors['area'] = 'A área da tarefa deve pertencer à área da fila.'
            if self.queue.criticality and self.queue.criticality != self.criticality:
                errors['criticality'] = (
                    'A criticidade da tarefa deve pertencer à criticidade da fila.'
                )
            if self.queue.approval_limit is not None and self.amount > self.queue.approval_limit:
                errors['amount'] = 'Valor da tarefa excede a alçada da fila.'
        if self.amount < ZERO_AMOUNT:
            errors['amount'] = 'Valor/alçada não pode ser negativo.'
        if (
            self.status in {self.Status.APPROVED, self.Status.REJECTED, self.Status.CANCELLED}
            and not self.decided_by
        ):
            errors['decided_by'] = 'Decisão exige usuário responsável.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.task_number


class WorkflowDelegation(SingleInstanceModel):
    from_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='workflow_delegations_from',
        verbose_name='substituído',
    )
    to_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='workflow_delegations_to',
        verbose_name='substituto',
    )
    module = models.CharField(
        'módulo', max_length=32, choices=WorkflowNotification.SourceModule.choices, blank=True
    )
    module_ref = models.ForeignKey(
        'auxiliary.SystemModule',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='módulo normalizado',
    )
    starts_at = models.DateTimeField('início')
    ends_at = models.DateTimeField('fim')
    reason = models.TextField('motivo')
    is_active = models.BooleanField('ativa', default=True)

    class Meta:
        ordering = ['-starts_at']
        indexes = [
            models.Index(fields=['from_user', 'to_user', 'is_active']),
            models.Index(fields=['module', 'starts_at', 'ends_at']),
        ]
        verbose_name = 'delegação de workflow'
        verbose_name_plural = 'delegações de workflow'

    def save(self, *args, **kwargs):
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def validate_actor(self, user, attrs):
        targets = [attrs['from_user']] if 'from_user' in attrs else [self.from_user]
        if self.pk:
            targets.append(self.from_user)
        manager = user and user.is_active and user.has_perm('workflow.change_approvalqueue')
        if not manager and (
            not user or not user.is_active or any(target.pk != user.pk for target in targets)
        ):
            raise ValidationError(
                {'permission': 'Somente o substituído ou gestor da fila pode delegar.'}
            )

    def applies_to(self, task):
        now = timezone.now()
        return (
            self.is_active
            and task.assigned_to_id == self.from_user_id
            and self.starts_at <= now <= self.ends_at
            and (not self.module or self.module == task.source_module)
        )

    def clean(self):
        super().clean()
        errors = {}
        for field in ('from_user', 'to_user'):
            pass
        if self.from_user_id and self.to_user_id and self.from_user_id == self.to_user_id:
            errors['to_user'] = 'Usuário substituto deve ser diferente do substituído.'
        if self.ends_at and self.starts_at and self.ends_at <= self.starts_at:
            errors['ends_at'] = 'Fim da delegação deve ser posterior ao início.'
        if not self.reason:
            errors['reason'] = 'Delegação exige justificativa.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.from_user} -> {self.to_user}'


class WorkflowComment(SingleInstanceModel):
    task = models.ForeignKey(
        ApprovalTask, on_delete=models.CASCADE, related_name='comments', verbose_name='tarefa'
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='workflow_comments',
        verbose_name='autor',
    )
    comment = models.TextField('comentário')
    is_internal = models.BooleanField('interno', default=True)

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['task']),
            models.Index(fields=['author']),
        ]
        verbose_name = 'comentário de workflow'
        verbose_name_plural = 'comentários de workflow'

    def clean(self):
        super().clean()
        errors = {}
        if not self.comment:
            errors['comment'] = 'Comentário é obrigatório.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.comment[:80]


class WorkflowAttachment(SingleInstanceModel):
    task = models.ForeignKey(
        ApprovalTask, on_delete=models.CASCADE, related_name='attachments', verbose_name='tarefa'
    )
    file_name = models.CharField('arquivo', max_length=180)
    file_reference = models.CharField('referência', max_length=255)
    content_hash = models.CharField('hash do conteúdo', max_length=128)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='workflow_attachments',
        null=True,
        blank=True,
        verbose_name='enviado por',
    )

    class Meta:
        ordering = ['task', 'file_name']
        indexes = [
            models.Index(fields=['task']),
            models.Index(fields=['uploaded_by']),
            models.Index(fields=['content_hash']),
        ]
        verbose_name = 'anexo de workflow'
        verbose_name_plural = 'anexos de workflow'

    def clean(self):
        super().clean()
        errors = {}
        if not self.content_hash:
            errors['content_hash'] = 'Anexo exige hash para integridade ALCOA+.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.file_name


class AsyncJobStatus(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('job_number', 'JOB'),)

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        RUNNING = 'running', 'Executando'
        COMPLETED = 'completed', 'Concluída'
        FAILED = 'failed', 'Falhou'
        CANCELLED = 'cancelled', 'Cancelada'

    job_number = models.CharField('job', max_length=80, blank=True)
    task_name = models.CharField('tarefa', max_length=160)
    task_id = models.CharField('id da tarefa', max_length=160, blank=True)
    title = models.CharField('título', max_length=180)
    loading_message = models.CharField('mensagem de carregamento', max_length=255)
    message = models.CharField('mensagem atual', max_length=255, blank=True)
    source_module = models.CharField(
        'módulo de origem', max_length=32, choices=WorkflowNotification.SourceModule.choices
    )
    source_module_ref = models.ForeignKey(
        'auxiliary.SystemModule',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='módulo de origem normalizado',
    )
    source_model = models.CharField('modelo de origem', max_length=120, blank=True)
    source_model_ref = models.ForeignKey(
        'auxiliary.SystemModel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='model de origem normalizado',
    )
    source_record_id = models.CharField('registro de origem', max_length=80, blank=True)
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.PENDING
    )
    progress_percent = models.PositiveSmallIntegerField('progresso', default=0)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='requested_async_jobs',
        null=True,
        blank=True,
        verbose_name='solicitado por',
    )
    started_at = models.DateTimeField('iniciada em', null=True, blank=True)
    completed_at = models.DateTimeField('concluída em', null=True, blank=True)
    result_reference = models.CharField('resultado', max_length=255, blank=True)
    error_message = models.TextField('erro', blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['job_number'], name='unique_async_job_number'),
        ]
        indexes = [
            models.Index(fields=['status', 'requested_by']),
            models.Index(fields=['source_module', 'source_model', 'source_record_id']),
            models.Index(fields=['task_name']),
            models.Index(fields=['task_id']),
        ]
        verbose_name = 'job assíncrono'
        verbose_name_plural = 'jobs assíncronos'

    def save(self, *args, **kwargs):
        if not self.job_number:
            self.job_number = _sequence_code(AsyncJobStatus, 'job_number', 'JOB')
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def start(self, task_id=''):
        if self.status != self.Status.PENDING:
            raise ValidationError({'status': 'Somente jobs pendentes podem iniciar.'})
        self.status = self.Status.RUNNING
        self.task_id = task_id
        self.started_at = timezone.now()
        self.message = self.loading_message
        self.save(update_fields=['status', 'task_id', 'started_at', 'message', 'updated_at'])
        self.record_history(WorkflowHistory.Action.STARTED, actor=self.requested_by)

    def update_progress(self, progress_percent, message=''):
        if self.status != self.Status.RUNNING:
            raise ValidationError({'status': 'Somente jobs em execução podem atualizar progresso.'})
        progress_percent = int(progress_percent)
        if progress_percent < 0 or progress_percent > 100:
            raise ValidationError({'progress_percent': 'Progresso deve estar entre 0 e 100.'})
        self.progress_percent = progress_percent
        self.message = message or self.message
        self.save(update_fields=['progress_percent', 'message', 'updated_at'])
        self.record_history(
            WorkflowHistory.Action.UPDATED,
            actor=self.requested_by,
            details={'progress_percent': progress_percent},
        )

    def complete(self, result_reference='', message=''):
        if self.status not in {self.Status.PENDING, self.Status.RUNNING}:
            raise ValidationError({'status': 'Job não pode ser concluído neste status.'})
        self.status = self.Status.COMPLETED
        self.progress_percent = 100
        self.completed_at = timezone.now()
        self.result_reference = result_reference
        self.message = message or 'Tarefa concluída.'
        self.error_message = ''
        self.save(
            update_fields=[
                'status',
                'progress_percent',
                'completed_at',
                'result_reference',
                'message',
                'error_message',
                'updated_at',
            ]
        )
        self.record_history(WorkflowHistory.Action.COMPLETED, actor=self.requested_by)
        self.notify_completion()

    def fail(self, error_message, message=''):
        if not error_message:
            raise ValidationError({'error_message': 'Informe o erro da tarefa.'})
        self.status = self.Status.FAILED
        self.completed_at = timezone.now()
        self.error_message = error_message
        self.message = message or 'Tarefa falhou.'
        self.save(
            update_fields=['status', 'completed_at', 'error_message', 'message', 'updated_at']
        )
        self.record_history(
            WorkflowHistory.Action.FAILED, actor=self.requested_by, details={'error': error_message}
        )

    def notify_completion(self):
        if not self.requested_by:
            return
        WorkflowNotification.objects.create(
            category=WorkflowNotification.Category.TASK_COMPLETED,
            channel=WorkflowNotification.Channel.INTERNAL,
            recipient=self.requested_by,
            title=f'Tarefa concluída: {self.title}',
            message=self.message or self.title,
            source_module=self.source_module,
            source_model=self.source_model or 'AsyncJobStatus',
            source_record_id=str(self.id),
            criticality=WorkflowNotification.Criticality.LOW,
        )

    def record_history(self, action, actor=None, details=None):
        return WorkflowHistory.objects.create(
            async_job=self,
            action=action,
            actor=actor,
            snapshot=f'{self.job_number} - {self.get_status_display()}',
            details=details or {},
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.progress_percent < 0 or self.progress_percent > 100:
            errors['progress_percent'] = 'Progresso deve estar entre 0 e 100.'
        if self.status == self.Status.RUNNING and not self.started_at:
            errors['started_at'] = 'Job em execução exige data de início.'
        if (
            self.status in {self.Status.COMPLETED, self.Status.FAILED, self.Status.CANCELLED}
            and not self.completed_at
        ):
            errors['completed_at'] = 'Job encerrado exige data de conclusão.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.job_number


class WorkflowHistory(SingleInstanceModel):
    class Action(models.TextChoices):
        CREATED = 'created', 'Criado'
        SENT = 'sent', 'Enviado'
        READ = 'read', 'Lido'
        ARCHIVED = 'archived', 'Arquivado'
        COMMENTED = 'commented', 'Comentado'
        ATTACHED = 'attached', 'Anexado'
        APPROVED = 'approved', 'Aprovado'
        REJECTED = 'rejected', 'Reprovado'
        DELEGATED = 'delegated', 'Delegado'
        STARTED = 'started', 'Iniciado'
        UPDATED = 'updated', 'Atualizado'
        COMPLETED = 'completed', 'Concluído'
        FAILED = 'failed', 'Falhou'
        CANCELLED = 'cancelled', 'Cancelado'

    task = models.ForeignKey(
        ApprovalTask,
        on_delete=models.CASCADE,
        related_name='history',
        null=True,
        blank=True,
        verbose_name='tarefa',
    )
    notification = models.ForeignKey(
        WorkflowNotification,
        on_delete=models.CASCADE,
        related_name='history',
        null=True,
        blank=True,
        verbose_name='notificação',
    )
    async_job = models.ForeignKey(
        AsyncJobStatus,
        on_delete=models.CASCADE,
        related_name='history',
        null=True,
        blank=True,
        verbose_name='job assíncrono',
    )
    action = models.CharField('ação', max_length=32, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='workflow_history',
        null=True,
        blank=True,
        verbose_name='usuário',
    )
    occurred_at = models.DateTimeField('ocorrido em', default=timezone.now)
    snapshot = models.CharField('snapshot', max_length=255)
    details = models.JSONField('detalhes', default=dict, blank=True)

    class Meta:
        ordering = ['-occurred_at', '-created_at']
        indexes = [
            models.Index(fields=['task', 'action']),
            models.Index(fields=['notification', 'action']),
            models.Index(fields=['async_job', 'action']),
            models.Index(fields=['actor']),
            models.Index(fields=['occurred_at']),
        ]
        verbose_name = 'histórico de workflow'
        verbose_name_plural = 'históricos de workflow'

    def clean(self):
        super().clean()
        errors = {}
        for field in ('task', 'notification', 'async_job'):
            pass
        if not any((self.task_id, self.notification_id, self.async_job_id)):
            errors['task'] = 'Histórico exige tarefa, notificação ou job assíncrono.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.get_action_display()} - {self.snapshot}'
