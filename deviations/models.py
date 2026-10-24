from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from base.models import SingleInstanceModel
from base.modules import OperationalModule
from base.sequences import IdentifierSpec, sequence_code
from masters.models import BusinessPartner, Product


def _sequence_code(model, *args):
    if len(args) == 3:
        _legacy_scope, field_name, prefix = args
    else:
        field_name, prefix = args
    return sequence_code(model, field_name, prefix)


def _record_deviation_audit(*, instance, action, message, user=None, **context):
    """Registra transição de estado de desvio na trilha de auditoria de governança."""
    from governance.models import GovernanceAuditLog

    event = getattr(instance, 'event', instance)
    GovernanceAuditLog.record(
        log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
        severity=GovernanceAuditLog.Severity.INFO,
        module=OperationalModule.DEVIATIONS,
        action=action,
        message=message,
        target_model=type(instance).__name__,
        target_record_id=str(instance.pk),
        user=user,
        safe_context={'event_id': event.pk, 'event_number': event.event_number, **context},
    )


def _require_actor_not_author(event, user, field='approver'):
    """Segregação de funções: quem abriu o desvio não decide aprovação."""
    if user is None:
        raise ValidationError({field: 'Informe o usuário que está decidindo.'})
    if user.pk == event.opened_by_id:
        raise ValidationError(
            {field: 'O autor do desvio não pode aprovar ou rejeitar o próprio desvio.'}
        )


class QualityEvent(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('event_number', 'DEV'),)

    class EventType(models.TextChoices):
        DEVIATION = 'deviation', 'Desvio'
        NONCONFORMITY = 'nonconformity', 'Não conformidade'

    class Origin(models.TextChoices):
        MANUAL = 'manual', 'Manual'
        AUTOMATIC = 'automatic', 'Automática'
        PRODUCTION = 'production', 'Produção'
        QUALITY_CONTROL = 'quality_control', 'Controle de qualidade'
        CUSTOMER_COMPLAINT = 'customer_complaint', 'Reclamação de cliente'
        SUPPLIER = 'supplier', 'Fornecedor'
        AUDIT = 'audit', 'Auditoria'
        INVENTORY = 'inventory', 'Estoque'
        DOCUMENT = 'document', 'Documento'

    class Severity(models.TextChoices):
        LOW = 'low', 'Baixa'
        MEDIUM = 'medium', 'Média'
        HIGH = 'high', 'Alta'
        CRITICAL = 'critical', 'Crítica'

    class Criticality(models.TextChoices):
        MINOR = 'minor', 'Menor'
        MAJOR = 'major', 'Maior'
        CRITICAL = 'critical', 'Crítica'

    class Status(models.TextChoices):
        OPEN = 'open', 'Aberto'
        UNDER_INVESTIGATION = 'under_investigation', 'Em investigação'
        PENDING_APPROVAL = 'pending_approval', 'Pendente de aprovação'
        CLOSED = 'closed', 'Encerrado'
        CANCELLED = 'cancelled', 'Cancelado'

    event_number = models.CharField('evento', max_length=80, blank=True)
    event_type = models.CharField('tipo', max_length=24, choices=EventType.choices)
    origin = models.CharField('origem', max_length=32, choices=Origin.choices)
    area = models.CharField('área', max_length=120)
    area_ref = models.ForeignKey(
        'auxiliary.BusinessArea',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='área normalizada',
    )
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='quality_events',
        null=True,
        blank=True,
        verbose_name='produto',
    )
    stock_lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.PROTECT,
        related_name='quality_events',
        null=True,
        blank=True,
        verbose_name='lote',
    )
    controlled_document = models.ForeignKey(
        'documents.ControlledDocument',
        on_delete=models.PROTECT,
        related_name='quality_events',
        null=True,
        blank=True,
        verbose_name='documento controlado',
    )
    supplier = models.ForeignKey(
        BusinessPartner,
        on_delete=models.PROTECT,
        related_name='supplier_quality_events',
        null=True,
        blank=True,
        verbose_name='fornecedor',
    )
    customer = models.ForeignKey(
        BusinessPartner,
        on_delete=models.PROTECT,
        related_name='customer_quality_events',
        null=True,
        blank=True,
        verbose_name='cliente',
    )
    severity = models.CharField('severidade', max_length=24, choices=Severity.choices)
    criticality = models.CharField('criticidade', max_length=24, choices=Criticality.choices)
    severity_ref = models.ForeignKey(
        'auxiliary.ImpactLevel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='severidade normalizada',
    )
    criticality_ref = models.ForeignKey(
        'auxiliary.ImpactLevel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='criticidade normalizada',
    )
    status = models.CharField('status', max_length=32, choices=Status.choices, default=Status.OPEN)
    description = models.TextField('descrição')
    detected_at = models.DateTimeField('detectado em')
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='responsible_quality_events',
        null=True,
        blank=True,
        verbose_name='responsável',
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='opened_quality_events',
        null=True,
        blank=True,
        verbose_name='aberto por',
    )
    opened_at = models.DateTimeField('aberto em', default=timezone.now)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='closed_quality_events',
        null=True,
        blank=True,
        verbose_name='encerrado por',
    )
    closed_at = models.DateTimeField('encerrado em', null=True, blank=True)
    closure_summary = models.TextField('resumo de encerramento', blank=True)
    cancel_reason = models.TextField('motivo do cancelamento', blank=True)

    class Meta:
        ordering = ['-opened_at']
        constraints = [
            models.UniqueConstraint(fields=['event_number'], name='unique_quality_event_number'),
        ]
        indexes = [
            models.Index(fields=['event_type', 'status']),
            models.Index(fields=['origin']),
            models.Index(fields=['severity', 'criticality']),
            models.Index(fields=['product']),
            models.Index(fields=['stock_lot']),
            models.Index(fields=['event_number']),
        ]
        verbose_name = 'desvio/não conformidade'
        verbose_name_plural = 'desvios/não conformidades'

    def save(self, *args, **kwargs):
        if not self.event_number:
            self.event_number = _sequence_code(QualityEvent, 'event_number', 'DEV')
        super().save(*args, **kwargs)

    def start_investigation(self, user=None):
        if self.status not in {self.Status.OPEN, self.Status.PENDING_APPROVAL}:
            raise ValidationError(
                {'status': 'Somente eventos abertos ou pendentes podem entrar em investigação.'}
            )
        previous_status = self.status
        self.status = self.Status.UNDER_INVESTIGATION
        self.responsible = self.responsible or user
        self.full_clean()
        self.save(update_fields=['status', 'responsible', 'updated_at'])
        _record_deviation_audit(
            instance=self,
            action='deviations.event.investigation_started',
            message='Investigação do desvio iniciada.',
            user=user,
            from_status=previous_status,
            to_status=self.status,
        )

    def close(self, summary, user=None):
        if self.status in {self.Status.CLOSED, self.Status.CANCELLED}:
            raise ValidationError(
                {'status': 'Evento encerrado ou cancelado não pode ser encerrado.'}
            )
        if not summary:
            raise ValidationError({'closure_summary': 'Informe o resumo de encerramento.'})
        if not self.investigations.filter(status=DeviationInvestigation.Status.CONCLUDED).exists():
            raise ValidationError({'investigation': 'Encerramento exige investigação concluída.'})
        impact = getattr(self, 'impact_assessment', None)
        if impact is None or not impact.is_completed:
            raise ValidationError(
                {'impact_assessment': 'Encerramento exige avaliação de impacto concluída.'}
            )
        has_required_approval = self.approvals.filter(required=True).exists()
        has_pending_required_approval = (
            self.approvals.filter(required=True)
            .exclude(decision=DeviationApproval.Decision.APPROVED)
            .exists()
        )
        if not has_required_approval or has_pending_required_approval:
            raise ValidationError(
                {'approvals': 'Encerramento exige aprovações obrigatórias aprovadas.'}
            )
        previous_status = self.status
        self.status = self.Status.CLOSED
        self.closure_summary = summary
        self.closed_by = user
        self.closed_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=['status', 'closure_summary', 'closed_by', 'closed_at', 'updated_at']
        )
        _record_deviation_audit(
            instance=self,
            action='deviations.event.closed',
            message='Desvio encerrado.',
            user=user,
            from_status=previous_status,
            to_status=self.status,
        )

    def cancel(self, reason):
        if not reason:
            raise ValidationError({'cancel_reason': 'Informe o motivo do cancelamento.'})
        if self.status in {self.Status.CLOSED, self.Status.CANCELLED}:
            raise ValidationError(
                {'status': 'Evento encerrado ou cancelado não pode ser cancelado.'}
            )
        previous_status = self.status
        self.status = self.Status.CANCELLED
        self.cancel_reason = reason
        self.save(update_fields=['status', 'cancel_reason', 'updated_at'])
        _record_deviation_audit(
            instance=self,
            action='deviations.event.cancelled',
            message='Desvio cancelado.',
            from_status=previous_status,
            to_status=self.status,
        )

    def clean(self):
        super().clean()
        errors = {}
        for field in ('product', 'stock_lot', 'controlled_document', 'supplier', 'customer'):
            pass
        for field in ('responsible', 'opened_by', 'closed_by'):
            pass
        if self.stock_lot and self.product and self.stock_lot.product_id != self.product_id:
            errors['stock_lot'] = 'O lote deve pertencer ao produto informado.'
        if self.supplier and self.supplier.partner_type != BusinessPartner.PartnerType.SUPPLIER:
            errors['supplier'] = 'O parceiro deve ser fornecedor.'
        if self.customer and self.customer.partner_type != BusinessPartner.PartnerType.CUSTOMER:
            errors['customer'] = 'O parceiro deve ser cliente.'
        if self.status == self.Status.CLOSED and (
            not self.closure_summary or not self.closed_by_id or not self.closed_at
        ):
            errors['closure_summary'] = 'Eventos encerrados exigem resumo, responsável e data.'
        if errors:
            raise ValidationError(errors)

    @property
    def title(self):
        return self.event_number

    def __str__(self):
        return self.event_number


class DeviationEvidence(SingleInstanceModel):
    event = models.ForeignKey(
        QualityEvent, on_delete=models.CASCADE, related_name='evidences', verbose_name='evento'
    )
    title = models.CharField('título', max_length=160)
    file_reference = models.CharField('arquivo', max_length=255)
    content_hash = models.CharField('hash do conteúdo', max_length=128)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='uploaded_deviation_evidences',
        null=True,
        blank=True,
        verbose_name='enviado por',
    )
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['event__event_number', 'title']
        indexes = [
            models.Index(fields=['event']),
            models.Index(fields=['content_hash']),
        ]
        verbose_name = 'evidência de desvio'
        verbose_name_plural = 'evidências de desvios'

    def clean(self):
        super().clean()
        errors = {}
        if not self.content_hash:
            errors['content_hash'] = 'Evidência exige hash para integridade dos dados.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


class DeviationInvestigation(SingleInstanceModel):
    class Status(models.TextChoices):
        OPEN = 'open', 'Aberta'
        IN_PROGRESS = 'in_progress', 'Em andamento'
        CONCLUDED = 'concluded', 'Concluída'
        CANCELLED = 'cancelled', 'Cancelada'

    event = models.ForeignKey(
        QualityEvent, on_delete=models.CASCADE, related_name='investigations', verbose_name='evento'
    )
    investigator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='deviation_investigations',
        null=True,
        blank=True,
        verbose_name='investigador',
    )
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.OPEN)
    immediate_actions = models.TextField('ações imediatas')
    containment_actions = models.TextField('ações de contenção')
    root_cause = models.TextField('causa raiz', blank=True)
    impact_conclusion = models.TextField('conclusão de impacto', blank=True)
    conclusion = models.TextField('conclusão', blank=True)
    concluded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='concluded_deviation_investigations',
        null=True,
        blank=True,
        verbose_name='concluído por',
    )
    concluded_at = models.DateTimeField('concluído em', null=True, blank=True)

    class Meta:
        ordering = ['event__event_number', '-created_at']
        indexes = [
            models.Index(fields=['event', 'status']),
            models.Index(fields=['investigator']),
        ]
        verbose_name = 'investigação de desvio'
        verbose_name_plural = 'investigações de desvios'

    def conclude(self, root_cause, impact_conclusion, conclusion, user=None):
        if self.status not in {self.Status.OPEN, self.Status.IN_PROGRESS}:
            raise ValidationError(
                {'status': 'Somente investigações abertas ou em andamento podem ser concluídas.'}
            )
        if not root_cause:
            raise ValidationError({'root_cause': 'Informe a causa raiz.'})
        if not impact_conclusion:
            raise ValidationError({'impact_conclusion': 'Informe a conclusão de impacto.'})
        if not conclusion:
            raise ValidationError({'conclusion': 'Informe a conclusão da investigação.'})
        previous_status = self.status
        self.status = self.Status.CONCLUDED
        self.root_cause = root_cause
        self.impact_conclusion = impact_conclusion
        self.conclusion = conclusion
        self.concluded_by = user
        self.concluded_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=[
                'status',
                'root_cause',
                'impact_conclusion',
                'conclusion',
                'concluded_by',
                'concluded_at',
                'updated_at',
            ]
        )
        if self.event.status == QualityEvent.Status.UNDER_INVESTIGATION:
            self.event.status = QualityEvent.Status.PENDING_APPROVAL
            self.event.save(update_fields=['status', 'updated_at'])
        _record_deviation_audit(
            instance=self,
            action='deviations.investigation.concluded',
            message='Investigação do desvio concluída.',
            user=user,
            from_status=previous_status,
            to_status=self.status,
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.status == self.Status.CONCLUDED and (
            not self.root_cause or not self.impact_conclusion or not self.conclusion
        ):
            errors['conclusion'] = 'Investigação concluída exige causa raiz, impacto e conclusão.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.event} - {self.get_status_display()}'


class DeviationImpactAssessment(SingleInstanceModel):
    event = models.OneToOneField(
        QualityEvent,
        on_delete=models.CASCADE,
        related_name='impact_assessment',
        verbose_name='evento',
    )
    impacts_quality = models.BooleanField('impacta qualidade', default=False)
    impacts_safety = models.BooleanField('impacta segurança', default=False)
    impacts_efficacy = models.BooleanField('impacta eficácia', default=False)
    impacts_regulatory = models.BooleanField('impacta regulatório', default=False)
    impacts_patient = models.BooleanField('impacta paciente', default=False)
    impacts_inventory = models.BooleanField('impacta estoque', default=False)
    impacts_cost = models.BooleanField('impacta custo', default=False)
    impacts_deadline = models.BooleanField('impacta prazo', default=False)
    summary = models.TextField('sumário de impacto')
    is_completed = models.BooleanField('concluída', default=False)
    assessed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='assessed_deviation_impacts',
        null=True,
        blank=True,
        verbose_name='avaliado por',
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='completed_deviation_impacts',
        null=True,
        blank=True,
        verbose_name='concluído por',
    )
    completed_at = models.DateTimeField('concluído em', null=True, blank=True)

    class Meta:
        ordering = ['event__event_number']
        indexes = [
            models.Index(fields=['event']),
            models.Index(fields=['is_completed']),
        ]
        verbose_name = 'avaliação de impacto de desvio'
        verbose_name_plural = 'avaliações de impacto de desvios'

    def complete(self, user=None):
        self.is_completed = True
        self.completed_by = user or self.assessed_by
        self.completed_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['is_completed', 'completed_by', 'completed_at', 'updated_at'])

    def clean(self):
        super().clean()
        errors = {}
        if not self.summary:
            errors['summary'] = 'Informe o sumário da avaliação de impacto.'
        if self.is_completed and not any(
            (
                self.impacts_quality,
                self.impacts_safety,
                self.impacts_efficacy,
                self.impacts_regulatory,
                self.impacts_patient,
                self.impacts_inventory,
                self.impacts_cost,
                self.impacts_deadline,
            )
        ):
            errors['summary'] = 'Avaliação concluída deve classificar ao menos um impacto.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.event} - impacto'


class DeviationApproval(SingleInstanceModel):
    class Role(models.TextChoices):
        QA = 'qa', 'Garantia da Qualidade'
        QC = 'qc', 'Controle de Qualidade'
        PRODUCTION = 'production', 'Produção'
        REGULATORY = 'regulatory', 'Regulatório'
        RESPONSIBLE_AREA = 'responsible_area', 'Área responsável'

    class Decision(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        APPROVED = 'approved', 'Aprovado'
        REJECTED = 'rejected', 'Rejeitado'

    event = models.ForeignKey(
        QualityEvent, on_delete=models.CASCADE, related_name='approvals', verbose_name='evento'
    )
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='deviation_approvals',
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
        related_name='decided_deviation_approvals',
        null=True,
        blank=True,
        verbose_name='decidido por',
    )
    decided_at = models.DateTimeField('decidido em', null=True, blank=True)

    class Meta:
        ordering = ['event__event_number', 'role']
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'role', 'approver'],
                name='unique_deviation_approval_role_user',
            ),
        ]
        indexes = [
            models.Index(fields=['event', 'decision']),
            models.Index(fields=['approver']),
        ]
        verbose_name = 'aprovação de desvio'
        verbose_name_plural = 'aprovações de desvios'

    def _decide(self, decision, user, comments, action, message):
        if self.decision != self.Decision.PENDING:
            raise ValidationError({'decision': 'Somente aprovações pendentes podem ser decididas.'})
        _require_actor_not_author(self.event, user)
        self.decision = decision
        self.comments = comments or self.comments
        self.decided_by = user
        self.decided_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['decision', 'comments', 'decided_by', 'decided_at', 'updated_at'])
        _record_deviation_audit(
            instance=self,
            action=action,
            message=message,
            user=user,
            from_status=self.Decision.PENDING,
            to_status=decision,
            role=self.role,
        )

    def approve(self, user=None, comments=''):
        self._decide(
            self.Decision.APPROVED,
            user,
            comments,
            'deviations.approval.approved',
            'Desvio aprovado.',
        )

    def reject(self, user=None, comments=''):
        if not comments:
            raise ValidationError({'comments': 'Informe o motivo da rejeição.'})
        self._decide(
            self.Decision.REJECTED,
            user,
            comments,
            'deviations.approval.rejected',
            'Desvio rejeitado.',
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.decision != self.Decision.PENDING and not self.decided_at:
            errors['decided_at'] = 'Decisão exige data/hora.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.event} - {self.get_role_display()}'


class DeviationLink(SingleInstanceModel):
    class LinkType(models.TextChoices):
        CAPA = 'capa', 'CAPA'
        CHANGE = 'change', 'Mudança'
        AUDIT = 'audit', 'Auditoria'
        COMPLAINT = 'complaint', 'Reclamação'
        OOS_OOT = 'oos_oot', 'OOS/OOT'
        LOT = 'lot', 'Lote'
        DOCUMENT = 'document', 'Documento'
        RISK = 'risk', 'Risco'

    event = models.ForeignKey(
        QualityEvent, on_delete=models.CASCADE, related_name='links', verbose_name='evento'
    )
    link_type = models.CharField('tipo de vínculo', max_length=24, choices=LinkType.choices)
    customer_complaint = models.ForeignKey(
        'crm.CustomerComplaint',
        on_delete=models.PROTECT,
        related_name='deviation_links',
        null=True,
        blank=True,
        verbose_name='reclamação',
    )
    quality_result = models.ForeignKey(
        'quality.QualityResult',
        on_delete=models.PROTECT,
        related_name='deviation_links',
        null=True,
        blank=True,
        verbose_name='resultado OOS/OOT',
    )
    stock_lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.PROTECT,
        related_name='deviation_links',
        null=True,
        blank=True,
        verbose_name='lote',
    )
    controlled_document = models.ForeignKey(
        'documents.ControlledDocument',
        on_delete=models.PROTECT,
        related_name='deviation_links',
        null=True,
        blank=True,
        verbose_name='documento',
    )
    reference_code = models.CharField('referência', max_length=120, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['event__event_number', 'link_type']
        indexes = [
            models.Index(fields=['event', 'link_type']),
            models.Index(fields=['customer_complaint']),
            models.Index(fields=['quality_result']),
            models.Index(fields=['stock_lot']),
            models.Index(fields=['controlled_document']),
            models.Index(fields=['reference_code']),
        ]
        verbose_name = 'vínculo de desvio'
        verbose_name_plural = 'vínculos de desvios'

    def clean(self):
        super().clean()
        errors = {}
        for field in (
            'event',
            'customer_complaint',
            'quality_result',
            'stock_lot',
            'controlled_document',
        ):
            pass
        has_target = any(
            (
                self.customer_complaint_id,
                self.quality_result_id,
                self.stock_lot_id,
                self.controlled_document_id,
                self.reference_code,
            )
        )
        if not has_target:
            errors['reference_code'] = 'Informe um registro relacionado ou referência.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.event} - {self.get_link_type_display()}'
