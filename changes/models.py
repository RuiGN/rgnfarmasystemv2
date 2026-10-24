from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from base.models import SingleInstanceModel
from base.modules import OperationalModule
from base.sequences import IdentifierSpec, sequence_code
from masters.models import BusinessPartner


def _record_change_audit(action, message, instance, user=None, **context):
    from governance.models import GovernanceAuditLog

    return GovernanceAuditLog.record(
        log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
        severity=GovernanceAuditLog.Severity.INFO,
        module=OperationalModule.CHANGES,
        action=action,
        message=message,
        target_model=type(instance).__name__,
        target_record_id=str(instance.pk),
        user=user,
        safe_context=context,
    )


ZERO_QUANTITY = Decimal('0.0000')


def _sequence_code(model, *args):
    if len(args) == 3:
        _legacy_scope, field_name, prefix = args
    else:
        field_name, prefix = args
    return sequence_code(model, field_name, prefix)


class ChangeControl(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('change_number', 'MUD'),)

    class ChangeType(models.TextChoices):
        PERMANENT = 'permanent', 'Permanente'
        TEMPORARY = 'temporary', 'Temporária'
        EMERGENCY = 'emergency', 'Emergencial'
        ADMINISTRATIVE = 'administrative', 'Administrativa'
        PROCESS = 'process', 'Processo'
        SYSTEM = 'system', 'Sistema'
        DOCUMENT = 'document', 'Documento'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        UNDER_ASSESSMENT = 'under_assessment', 'Em avaliação'
        APPROVED = 'approved', 'Aprovada'
        IN_IMPLEMENTATION = 'in_implementation', 'Em implementação'
        CLOSED = 'closed', 'Encerrada'
        CANCELLED = 'cancelled', 'Cancelada'

    change_number = models.CharField('mudança', max_length=80, blank=True)
    change_type = models.CharField('tipo', max_length=32, choices=ChangeType.choices)
    title = models.CharField('título', max_length=180)
    scope = models.TextField('escopo')
    justification = models.TextField('justificativa')
    affected_areas = models.TextField('áreas afetadas')
    system_reference = models.CharField('sistema', max_length=120, blank=True)
    validation_plan = models.TextField('plano de validação', blank=True)
    training_plan = models.TextField('plano de treinamento', blank=True)
    regulatory_strategy = models.TextField('estratégia regulatória', blank=True)
    impact_summary = models.TextField('resumo de impacto', blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='owned_changes',
        verbose_name='responsável',
    )
    due_date = models.DateField('prazo')
    status = models.CharField('status', max_length=32, choices=Status.choices, default=Status.DRAFT)
    requires_stock_assessment = models.BooleanField('exige avaliação de estoque', default=False)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='requested_changes',
        null=True,
        blank=True,
        verbose_name='solicitada por',
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='submitted_changes',
        null=True,
        blank=True,
        verbose_name='submetida por',
    )
    submitted_at = models.DateTimeField('submetida em', null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='authorized_changes',
        null=True,
        blank=True,
        verbose_name='aprovada por',
    )
    approved_at = models.DateTimeField('aprovada em', null=True, blank=True)
    implementation_started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='started_change_implementations',
        null=True,
        blank=True,
        verbose_name='implementação iniciada por',
    )
    implementation_started_at = models.DateTimeField(
        'implementação iniciada em', null=True, blank=True
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='closed_changes',
        null=True,
        blank=True,
        verbose_name='encerrada por',
    )
    closed_at = models.DateTimeField('encerrada em', null=True, blank=True)
    closure_summary = models.TextField('resumo de encerramento', blank=True)
    cancel_reason = models.TextField('motivo do cancelamento', blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['change_number'], name='unique_change_number'),
        ]
        indexes = [
            models.Index(fields=['change_type', 'status']),
            models.Index(fields=['owner']),
            models.Index(fields=['due_date']),
            models.Index(fields=['change_number']),
        ]
        verbose_name = 'controle de mudança'
        verbose_name_plural = 'controles de mudança'

    def save(self, *args, **kwargs):
        if not self.change_number:
            self.change_number = _sequence_code(ChangeControl, 'change_number', 'MUD')
        super().save(*args, **kwargs)

    def submit(self, user=None):
        if self.status != self.Status.DRAFT:
            raise ValidationError({'status': 'Somente mudanças em rascunho podem ser submetidas.'})
        self.status = self.Status.UNDER_ASSESSMENT
        self.submitted_by = user or self.submitted_by
        self.submitted_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'submitted_by', 'submitted_at', 'updated_at'])

    def approve_for_implementation(self, user=None):
        if self.status != self.Status.UNDER_ASSESSMENT:
            raise ValidationError(
                {'status': 'Somente mudanças em avaliação podem ser aprovadas para implementação.'}
            )
        if (
            not self.assessments.exists()
            or self.assessments.exclude(status=ChangeAssessment.Status.COMPLETED).exists()
        ):
            raise ValidationError(
                {'assessments': 'Aprovação exige todas as análises multidisciplinares concluídas.'}
            )
        has_required_approval = self.approvals.filter(required=True).exists()
        has_pending_required_approval = (
            self.approvals.filter(required=True)
            .exclude(decision=ChangeApproval.Decision.APPROVED)
            .exists()
        )
        if not has_required_approval or has_pending_required_approval:
            raise ValidationError(
                {'approvals': 'Aprovação exige aprovações obrigatórias aprovadas.'}
            )
        if user is not None and self.submitted_by_id and user.pk == self.submitted_by_id:
            raise ValidationError(
                {'approved_by': 'Segregação de funções: quem submeteu não pode aprovar a mudança.'}
            )
        self.status = self.Status.APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.full_clean()
        with transaction.atomic():
            self.save(update_fields=['status', 'approved_by', 'approved_at', 'updated_at'])
            _record_change_audit(
                'changes.change.approved_for_implementation',
                'Mudança aprovada para implementação.',
                self,
                user,
                to_status=self.status,
            )

    def start_implementation(self, user=None):
        if self.status != self.Status.APPROVED:
            raise ValidationError({'status': 'Implementação exige mudança aprovada.'})
        blocking_actions = self.actions.filter(
            mandatory=True, required_before_implementation=True
        ).exclude(status=ChangeAction.Status.COMPLETED)
        if blocking_actions.exists():
            raise ValidationError(
                {'actions': 'Implementação exige ações obrigatórias prévias concluídas.'}
            )
        self.status = self.Status.IN_IMPLEMENTATION
        self.implementation_started_by = user
        self.implementation_started_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=[
                'status',
                'implementation_started_by',
                'implementation_started_at',
                'updated_at',
            ]
        )

    def close(self, summary, user=None):
        if not summary:
            raise ValidationError({'closure_summary': 'Informe o resumo de encerramento.'})
        if self.status != self.Status.IN_IMPLEMENTATION:
            raise ValidationError({'status': 'Encerramento exige mudança em implementação.'})
        mandatory_actions = self.actions.filter(mandatory=True)
        if (
            not mandatory_actions.exists()
            or mandatory_actions.exclude(status=ChangeAction.Status.COMPLETED).exists()
        ):
            raise ValidationError(
                {'actions': 'Encerramento exige todas as ações obrigatórias concluídas.'}
            )
        if self.requires_stock_assessment:
            required_stock = self.stock_assessments.filter(required=True)
            if (
                not required_stock.exists()
                or required_stock.exclude(status=ChangeStockAssessment.Status.COMPLETED).exists()
            ):
                raise ValidationError(
                    {'stock_assessments': 'Encerramento exige avaliação de estoque concluída.'}
                )
        has_pending_required_approval = (
            self.approvals.filter(required=True)
            .exclude(decision=ChangeApproval.Decision.APPROVED)
            .exists()
        )
        if has_pending_required_approval:
            raise ValidationError(
                {'approvals': 'Encerramento exige aprovações obrigatórias aprovadas.'}
            )
        self.status = self.Status.CLOSED
        self.closure_summary = summary
        self.closed_by = user
        self.closed_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=['status', 'closure_summary', 'closed_by', 'closed_at', 'updated_at']
        )

    def cancel(self, reason):
        if not reason:
            raise ValidationError({'cancel_reason': 'Informe o motivo do cancelamento.'})
        if self.status == self.Status.CLOSED:
            raise ValidationError({'status': 'Mudança encerrada não pode ser cancelada.'})
        self.status = self.Status.CANCELLED
        self.cancel_reason = reason
        self.save(update_fields=['status', 'cancel_reason', 'updated_at'])

    def clean(self):
        super().clean()
        errors = {}
        for field in (
            'owner',
            'requested_by',
            'submitted_by',
            'approved_by',
            'implementation_started_by',
            'closed_by',
        ):
            pass
        if self.closed_at and self.submitted_at and self.closed_at < self.submitted_at:
            errors['closed_at'] = 'A data de encerramento não pode ser anterior à submissão.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.change_number


class ChangeAffectedItem(SingleInstanceModel):
    class ItemType(models.TextChoices):
        PRODUCT = 'product', 'Produto'
        DOCUMENT = 'document', 'Documento'
        SUPPLIER = 'supplier', 'Fornecedor'
        SYSTEM = 'system', 'Sistema'
        PROCESS = 'process', 'Processo'
        TRAINING = 'training', 'Treinamento'
        VALIDATION = 'validation', 'Validação'
        OTHER = 'other', 'Outro'

    change = models.ForeignKey(
        ChangeControl,
        on_delete=models.CASCADE,
        related_name='affected_items',
        verbose_name='mudança',
    )
    item_type = models.CharField('tipo de item', max_length=24, choices=ItemType.choices)
    product = models.ForeignKey(
        'masters.Product',
        on_delete=models.PROTECT,
        related_name='change_impacts',
        null=True,
        blank=True,
        verbose_name='produto',
    )
    document = models.ForeignKey(
        'documents.ControlledDocument',
        on_delete=models.PROTECT,
        related_name='change_impacts',
        null=True,
        blank=True,
        verbose_name='documento',
    )
    supplier = models.ForeignKey(
        'masters.BusinessPartner',
        on_delete=models.PROTECT,
        related_name='change_impacts',
        null=True,
        blank=True,
        verbose_name='fornecedor',
    )
    reference_code = models.CharField('referência', max_length=120, blank=True)
    impact_description = models.TextField('descrição do impacto')

    class Meta:
        ordering = ['change__change_number', 'item_type']
        indexes = [
            models.Index(fields=['change', 'item_type']),
            models.Index(fields=['product']),
            models.Index(fields=['document']),
            models.Index(fields=['supplier']),
        ]
        verbose_name = 'item afetado pela mudança'
        verbose_name_plural = 'itens afetados pela mudança'

    def clean(self):
        super().clean()
        errors = {}
        for field in ('change', 'product', 'document', 'supplier'):
            pass
        if self.item_type == self.ItemType.PRODUCT and not self.product_id:
            errors['product'] = 'Item afetado do tipo produto exige produto.'
        if self.item_type == self.ItemType.DOCUMENT and not self.document_id:
            errors['document'] = 'Item afetado do tipo documento exige documento.'
        if self.item_type == self.ItemType.SUPPLIER and not self.supplier_id:
            errors['supplier'] = 'Item afetado do tipo fornecedor exige fornecedor.'
        if self.supplier and self.supplier.partner_type not in {
            BusinessPartner.PartnerType.SUPPLIER,
            BusinessPartner.PartnerType.MANUFACTURER,
            BusinessPartner.PartnerType.OUTSOURCED_LAB,
        }:
            errors['supplier'] = (
                'Fornecedor afetado deve ser fornecedor, fabricante ou laboratório terceirizado.'
            )
        if (
            self.item_type
            in {
                self.ItemType.SYSTEM,
                self.ItemType.PROCESS,
                self.ItemType.TRAINING,
                self.ItemType.VALIDATION,
                self.ItemType.OTHER,
            }
            and not self.reference_code
        ):
            errors['reference_code'] = 'Informe uma referência para o item afetado.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.change} - {self.get_item_type_display()}'


class ChangeAssessment(SingleInstanceModel):
    class Department(models.TextChoices):
        QA = 'qa', 'Garantia da Qualidade'
        QC = 'qc', 'Controle de Qualidade'
        PRODUCTION = 'production', 'Produção'
        ENGINEERING = 'engineering', 'Engenharia'
        REGULATORY = 'regulatory', 'Regulatório'
        FISCAL = 'fiscal', 'Fiscal'
        FINANCE = 'finance', 'Financeiro'
        WAREHOUSE = 'warehouse', 'Estoque'
        OTHER = 'other', 'Outra área'

    class ImpactLevel(models.TextChoices):
        NONE = 'none', 'Sem impacto'
        LOW = 'low', 'Baixo'
        MEDIUM = 'medium', 'Médio'
        HIGH = 'high', 'Alto'
        CRITICAL = 'critical', 'Crítico'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        COMPLETED = 'completed', 'Concluída'

    change = models.ForeignKey(
        ChangeControl, on_delete=models.CASCADE, related_name='assessments', verbose_name='mudança'
    )
    department = models.CharField('área', max_length=32, choices=Department.choices)
    department_ref = models.ForeignKey(
        'auxiliary.Department',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='departamento normalizado',
    )
    assessor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='change_assessments',
        verbose_name='avaliador',
    )
    impact_level = models.CharField(
        'nível de impacto', max_length=24, choices=ImpactLevel.choices, blank=True
    )
    impact_description = models.TextField('descrição do impacto', blank=True)
    required_actions = models.TextField('ações requeridas', blank=True)
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.PENDING
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='completed_change_assessments',
        null=True,
        blank=True,
        verbose_name='concluída por',
    )
    completed_at = models.DateTimeField('concluída em', null=True, blank=True)

    class Meta:
        ordering = ['change__change_number', 'department']
        constraints = [
            models.UniqueConstraint(
                fields=['change', 'department'],
                name='unique_change_assessment_department',
            ),
        ]
        indexes = [
            models.Index(fields=['change', 'status']),
            models.Index(fields=['department']),
            models.Index(fields=['assessor']),
        ]
        verbose_name = 'análise de mudança'
        verbose_name_plural = 'análises de mudança'

    def complete(self, impact_level, impact_description, required_actions, user=None):
        if not impact_level:
            raise ValidationError({'impact_level': 'Informe o nível de impacto.'})
        if not impact_description:
            raise ValidationError({'impact_description': 'Informe a descrição do impacto.'})
        self.impact_level = impact_level
        self.impact_description = impact_description
        self.required_actions = required_actions
        self.status = self.Status.COMPLETED
        self.completed_by = user or self.assessor
        self.completed_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=[
                'impact_level',
                'impact_description',
                'required_actions',
                'status',
                'completed_by',
                'completed_at',
                'updated_at',
            ]
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.status == self.Status.COMPLETED and (
            not self.impact_level
            or not self.impact_description
            or not self.completed_by_id
            or not self.completed_at
        ):
            errors['impact_description'] = 'Análise concluída exige impacto, responsável e data.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.change} - {self.get_department_display()}'


class ChangeAction(SingleInstanceModel):
    class ActionType(models.TextChoices):
        DOCUMENT_UPDATE = 'document_update', 'Atualização documental'
        TRAINING = 'training', 'Treinamento'
        VALIDATION = 'validation', 'Validação'
        REGULATORY_COMMUNICATION = 'regulatory_communication', 'Comunicação regulatória'
        STOCK_ASSESSMENT = 'stock_assessment', 'Avaliação de estoque'
        IMPLEMENTATION = 'implementation', 'Implementação'
        OTHER = 'other', 'Outra ação'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        IN_PROGRESS = 'in_progress', 'Em andamento'
        COMPLETED = 'completed', 'Concluída'
        CANCELLED = 'cancelled', 'Cancelada'

    change = models.ForeignKey(
        ChangeControl, on_delete=models.CASCADE, related_name='actions', verbose_name='mudança'
    )
    action_type = models.CharField('tipo', max_length=32, choices=ActionType.choices)
    title = models.CharField('título', max_length=180)
    description = models.TextField('descrição')
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='change_actions',
        verbose_name='responsável',
    )
    due_date = models.DateField('prazo')
    mandatory = models.BooleanField('obrigatória', default=True)
    required_before_implementation = models.BooleanField(
        'exige antes da implementação', default=False
    )
    evidence_required = models.BooleanField('exige evidência', default=True)
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.PENDING
    )
    completion_notes = models.TextField('observações de conclusão', blank=True)
    evidence_reference = models.CharField('evidência', max_length=255, blank=True)
    content_hash = models.CharField('hash do conteúdo', max_length=128, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='completed_change_actions',
        null=True,
        blank=True,
        verbose_name='concluída por',
    )
    completed_at = models.DateTimeField('concluída em', null=True, blank=True)

    class Meta:
        ordering = ['change__change_number', 'due_date']
        indexes = [
            models.Index(fields=['change', 'status']),
            models.Index(fields=['responsible', 'due_date']),
            models.Index(fields=['action_type']),
            models.Index(fields=['required_before_implementation']),
        ]
        verbose_name = 'ação de mudança'
        verbose_name_plural = 'ações de mudança'

    def start(self):
        if self.status != self.Status.PENDING:
            raise ValidationError({'status': 'Somente ações pendentes podem iniciar.'})
        self.status = self.Status.IN_PROGRESS
        self.save(update_fields=['status', 'updated_at'])

    def complete(self, user=None, completion_notes='', evidence_reference='', content_hash=''):
        if not completion_notes:
            raise ValidationError({'completion_notes': 'Informe as observações de conclusão.'})
        if self.evidence_required and (not evidence_reference or not content_hash):
            raise ValidationError(
                {'evidence_reference': 'Ação com evidência obrigatória exige referência e hash.'}
            )
        self.status = self.Status.COMPLETED
        self.completed_by = user
        self.completed_at = timezone.now()
        self.completion_notes = completion_notes
        self.evidence_reference = evidence_reference
        self.content_hash = content_hash
        self.full_clean()
        self.save(
            update_fields=[
                'status',
                'completed_by',
                'completed_at',
                'completion_notes',
                'evidence_reference',
                'content_hash',
                'updated_at',
            ]
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.status == self.Status.COMPLETED and (
            not self.completion_notes or not self.completed_by_id or not self.completed_at
        ):
            errors['completion_notes'] = 'Ação concluída exige responsável, data e observações.'
        if (
            self.status == self.Status.COMPLETED
            and self.evidence_required
            and (not self.evidence_reference or not self.content_hash)
        ):
            errors['evidence_reference'] = 'Ação com evidência obrigatória exige referência e hash.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


class ChangeApproval(SingleInstanceModel):
    class Role(models.TextChoices):
        QA = 'qa', 'Garantia da Qualidade'
        QC = 'qc', 'Controle de Qualidade'
        PRODUCTION = 'production', 'Produção'
        ENGINEERING = 'engineering', 'Engenharia'
        REGULATORY = 'regulatory', 'Regulatório'
        FISCAL = 'fiscal', 'Fiscal'
        FINANCE = 'finance', 'Financeiro'
        OWNER = 'owner', 'Responsável'

    class Decision(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        APPROVED = 'approved', 'Aprovado'
        REJECTED = 'rejected', 'Rejeitado'

    change = models.ForeignKey(
        ChangeControl, on_delete=models.CASCADE, related_name='approvals', verbose_name='mudança'
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='change_approvals',
        verbose_name='aprovador',
    )
    role = models.CharField('papel', max_length=32, choices=Role.choices)
    required = models.BooleanField('obrigatória', default=True)
    decision = models.CharField(
        'decisão', max_length=24, choices=Decision.choices, default=Decision.PENDING
    )
    comments = models.TextField('comentários', blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='decided_change_approvals',
        null=True,
        blank=True,
        verbose_name='decidido por',
    )
    decided_at = models.DateTimeField('decidido em', null=True, blank=True)

    class Meta:
        ordering = ['change__change_number', 'role']
        constraints = [
            models.UniqueConstraint(
                fields=['change', 'role', 'approver'],
                name='unique_change_approval_role_user',
            ),
        ]
        indexes = [
            models.Index(fields=['change', 'decision']),
            models.Index(fields=['approver']),
        ]
        verbose_name = 'aprovação de mudança'
        verbose_name_plural = 'aprovações de mudança'

    def _validate_decision(self, user):
        if self.decision != self.Decision.PENDING:
            raise ValidationError({'decision': 'Somente aprovações pendentes podem ser decididas.'})
        if self.change.status in {
            ChangeControl.Status.APPROVED,
            ChangeControl.Status.CLOSED,
            ChangeControl.Status.CANCELLED,
        }:
            raise ValidationError(
                {'change': 'A mudança não aceita mais decisões de aprovação neste status.'}
            )
        actor = user or self.approver
        if self.approver_id and actor.pk != self.approver_id:
            raise ValidationError({'decided_by': 'Somente o aprovador designado pode decidir.'})
        if actor.pk in {self.change.submitted_by_id, self.change.requested_by_id}:
            raise ValidationError(
                {'decided_by': 'Segregação de funções: autor da mudança não pode aprová-la.'}
            )
        return actor

    def _decide(self, decision, actor, comments, action, message):
        self.decision = decision
        self.comments = comments
        self.decided_by = actor
        self.decided_at = timezone.now()
        self.full_clean()
        with transaction.atomic():
            self.save(
                update_fields=['decision', 'comments', 'decided_by', 'decided_at', 'updated_at']
            )
            _record_change_audit(
                action, message, self, actor, change_id=self.change_id, decision=decision
            )

    def approve(self, user=None, comments=''):
        actor = self._validate_decision(user)
        self._decide(
            self.Decision.APPROVED,
            actor,
            comments or self.comments,
            'changes.approval.approved',
            'Aprovação de mudança registrada.',
        )

    def reject(self, user=None, comments=''):
        if not comments:
            raise ValidationError({'comments': 'Informe o motivo da rejeição.'})
        actor = self._validate_decision(user)
        self._decide(
            self.Decision.REJECTED,
            actor,
            comments,
            'changes.approval.rejected',
            'Rejeição de mudança registrada.',
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.decision != self.Decision.PENDING and not self.decided_at:
            errors['decided_at'] = 'Decisão exige data/hora.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.change} - {self.get_role_display()}'


class ChangeStockAssessment(SingleInstanceModel):
    class Decision(models.TextChoices):
        NOT_APPLICABLE = 'not_applicable', 'Não aplicável'
        USE_AS_IS = 'use_as_is', 'Usar como está'
        QUARANTINE = 'quarantine', 'Quarentenar'
        RELABEL = 'relabel', 'Reetiquetar'
        REPROCESS = 'reprocess', 'Reprocessar'
        DISCARD = 'discard', 'Descartar'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        COMPLETED = 'completed', 'Concluída'

    change = models.ForeignKey(
        ChangeControl,
        on_delete=models.CASCADE,
        related_name='stock_assessments',
        verbose_name='mudança',
    )
    product = models.ForeignKey(
        'masters.Product',
        on_delete=models.PROTECT,
        related_name='change_stock_assessments',
        verbose_name='produto',
    )
    stock_lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.PROTECT,
        related_name='change_stock_assessments',
        null=True,
        blank=True,
        verbose_name='lote',
    )
    quantity_affected = models.DecimalField(
        'quantidade afetada', max_digits=14, decimal_places=4, default=ZERO_QUANTITY
    )
    required = models.BooleanField('obrigatória', default=True)
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.PENDING
    )
    decision = models.CharField('decisão', max_length=32, choices=Decision.choices, blank=True)
    assessment_summary = models.TextField('resumo da avaliação', blank=True)
    assessed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='completed_change_stock_assessments',
        null=True,
        blank=True,
        verbose_name='avaliado por',
    )
    assessed_at = models.DateTimeField('avaliado em', null=True, blank=True)

    class Meta:
        ordering = ['change__change_number', 'product__code']
        indexes = [
            models.Index(fields=['change', 'status']),
            models.Index(fields=['product']),
            models.Index(fields=['stock_lot']),
        ]
        verbose_name = 'avaliação de estoque da mudança'
        verbose_name_plural = 'avaliações de estoque da mudança'

    def complete(self, decision, assessment_summary, user=None):
        if not decision:
            raise ValidationError({'decision': 'Informe a decisão para o estoque.'})
        if not assessment_summary:
            raise ValidationError(
                {'assessment_summary': 'Informe o resumo da avaliação de estoque.'}
            )
        self.decision = decision
        self.assessment_summary = assessment_summary
        self.status = self.Status.COMPLETED
        self.assessed_by = user
        self.assessed_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=[
                'decision',
                'assessment_summary',
                'status',
                'assessed_by',
                'assessed_at',
                'updated_at',
            ]
        )

    def clean(self):
        super().clean()
        errors = {}
        for field in ('change', 'product', 'stock_lot'):
            pass
        if self.stock_lot and self.product and self.stock_lot.product_id != self.product_id:
            errors['stock_lot'] = 'O lote deve pertencer ao produto informado.'
        if self.quantity_affected < 0:
            errors['quantity_affected'] = 'A quantidade afetada não pode ser negativa.'
        if self.status == self.Status.COMPLETED and (
            not self.decision
            or not self.assessment_summary
            or not self.assessed_by_id
            or not self.assessed_at
        ):
            errors['assessment_summary'] = (
                'Avaliação concluída exige decisão, resumo, responsável e data.'
            )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.change} - {self.product}'
