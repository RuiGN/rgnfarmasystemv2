from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from base.models import SingleInstanceModel
from base.modules import OperationalModule
from base.normalized_locations import validate_normalized_location
from base.sequences import IdentifierSpec, sequence_code
from masters.models import BusinessPartner


def _record_audit_audit(action, message, instance, user=None, **context):
    from governance.models import GovernanceAuditLog

    return GovernanceAuditLog.record(
        log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
        severity=GovernanceAuditLog.Severity.INFO,
        module=OperationalModule.AUDITS,
        action=action,
        message=message,
        target_model=type(instance).__name__,
        target_record_id=str(instance.pk),
        user=user,
        safe_context=context,
    )


def _sequence_code(model, *args):
    if len(args) == 3:
        _legacy_scope, field_name, prefix = args
    else:
        field_name, prefix = args
    return sequence_code(model, field_name, prefix)


class AuditTypeChoices(models.TextChoices):
    INTERNAL = 'internal', 'Interna'
    EXTERNAL = 'external', 'Externa'
    SUPPLIER = 'supplier', 'Fornecedor'
    CUSTOMER = 'customer', 'Cliente'
    REGULATORY = 'regulatory', 'Regulatória'


class AuditProgram(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('program_number', 'AUDPRG'),)
    AuditType = AuditTypeChoices

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        ACTIVE = 'active', 'Ativo'
        CLOSED = 'closed', 'Encerrado'
        CANCELLED = 'cancelled', 'Cancelado'

    program_number = models.CharField('programa', max_length=80, blank=True)
    audit_type = models.CharField('tipo', max_length=24, choices=AuditType.choices)
    title = models.CharField('título', max_length=180)
    year = models.PositiveIntegerField('ano')
    scope = models.TextField('escopo')
    criteria = models.TextField('critérios')
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='owned_audit_programs',
        verbose_name='responsável',
    )
    starts_on = models.DateField('início')
    ends_on = models.DateField('fim')
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)

    class Meta:
        ordering = ['-year', 'title']
        constraints = [
            models.UniqueConstraint(fields=['program_number'], name='unique_audit_program_number'),
        ]
        indexes = [
            models.Index(fields=['audit_type', 'status']),
            models.Index(fields=['year']),
            models.Index(fields=['owner']),
            models.Index(fields=['program_number']),
        ]
        verbose_name = 'programa de auditoria'
        verbose_name_plural = 'programas de auditoria'

    def save(self, *args, **kwargs):
        if not self.program_number:
            self.program_number = _sequence_code(AuditProgram, 'program_number', 'AUDPRG')
        super().save(*args, **kwargs)

    def activate(self):
        if self.status != self.Status.DRAFT:
            raise ValidationError({'status': 'Somente programas em rascunho podem ser ativados.'})
        self.status = self.Status.ACTIVE
        self.full_clean()
        self.save(update_fields=['status', 'updated_at'])

    def close(self):
        if self.status == self.Status.CANCELLED:
            raise ValidationError({'status': 'Programa cancelado não pode ser encerrado.'})
        self.status = self.Status.CLOSED
        self.full_clean()
        self.save(update_fields=['status', 'updated_at'])

    def clean(self):
        super().clean()
        errors = {}
        if self.ends_on and self.starts_on and self.ends_on < self.starts_on:
            errors['ends_on'] = 'A data final não pode ser anterior ao início.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.program_number


class AuditPlan(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('audit_number', 'AUD'),)
    AuditType = AuditTypeChoices

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        PLANNED = 'planned', 'Planejada'
        IN_PROGRESS = 'in_progress', 'Em execução'
        REPORTING = 'reporting', 'Em relatório'
        CLOSED = 'closed', 'Encerrada'
        CANCELLED = 'cancelled', 'Cancelada'

    audit_number = models.CharField('auditoria', max_length=80, blank=True)
    program = models.ForeignKey(
        AuditProgram, on_delete=models.PROTECT, related_name='audits', verbose_name='programa'
    )
    audit_type = models.CharField('tipo', max_length=24, choices=AuditType.choices)
    supplier = models.ForeignKey(
        'masters.BusinessPartner',
        on_delete=models.PROTECT,
        related_name='supplier_audits',
        null=True,
        blank=True,
        verbose_name='fornecedor/cliente auditado',
    )
    title = models.CharField('título', max_length=180)
    scope = models.TextField('escopo')
    criteria = models.TextField('critérios')
    agenda = models.TextField('agenda')
    lead_auditor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='led_audits',
        verbose_name='auditor líder',
    )
    auditee_name = models.CharField('auditado', max_length=180)
    area = models.CharField('área', max_length=120)
    area_ref = models.ForeignKey(
        'auxiliary.BusinessArea',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='área normalizada',
    )
    site = models.ForeignKey(
        'masters.Site',
        on_delete=models.PROTECT,
        related_name='audit_plans',
        null=True,
        blank=True,
        verbose_name='unidade/planta auditada',
    )
    venue_zipcode = models.CharField('CEP do local', max_length=20, blank=True)
    venue_street = models.CharField('logradouro do local', max_length=200, blank=True)
    venue_street_number = models.CharField('número', max_length=20, blank=True)
    venue_complement = models.CharField('complemento', max_length=100, blank=True)
    venue_neighborhood = models.CharField('bairro do local', max_length=120, blank=True)
    venue_country_ref = models.ForeignKey(
        'auxiliary.Country',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name='país',
    )
    venue_state_ref = models.ForeignKey(
        'auxiliary.StateProvince',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='UF',
    )
    venue_city_ref = models.ForeignKey(
        'auxiliary.City',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='Cidade',
    )
    scheduled_start = models.DateTimeField('início planejado')
    scheduled_end = models.DateTimeField('fim planejado')
    actual_start = models.DateTimeField('início real', null=True, blank=True)
    actual_end = models.DateTimeField('fim real', null=True, blank=True)
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='submitted_audits',
        null=True,
        blank=True,
        verbose_name='submetida por',
    )
    submitted_at = models.DateTimeField('submetida em', null=True, blank=True)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='started_audits',
        null=True,
        blank=True,
        verbose_name='iniciada por',
    )
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='completed_audits',
        null=True,
        blank=True,
        verbose_name='execução concluída por',
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='closed_audits',
        null=True,
        blank=True,
        verbose_name='encerrada por',
    )
    closed_at = models.DateTimeField('encerrada em', null=True, blank=True)
    closure_summary = models.TextField('resumo de encerramento', blank=True)
    cancel_reason = models.TextField('motivo do cancelamento', blank=True)

    class Meta:
        ordering = ['-scheduled_start']
        constraints = [
            models.UniqueConstraint(fields=['audit_number'], name='unique_audit_number'),
        ]
        indexes = [
            models.Index(fields=['audit_type', 'status']),
            models.Index(fields=['program']),
            models.Index(fields=['lead_auditor']),
            models.Index(fields=['supplier']),
            models.Index(fields=['scheduled_start']),
            models.Index(fields=['audit_number']),
        ]
        verbose_name = 'plano de auditoria'
        verbose_name_plural = 'planos de auditoria'

    def save(self, *args, **kwargs):
        if not self.audit_number:
            self.audit_number = _sequence_code(AuditPlan, 'audit_number', 'AUD')
        super().save(*args, **kwargs)

    def submit(self, user=None):
        if self.status != self.Status.DRAFT:
            raise ValidationError(
                {'status': 'Somente auditorias em rascunho podem ser submetidas.'}
            )
        self.status = self.Status.PLANNED
        self.submitted_by = user or self.submitted_by
        self.submitted_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'submitted_by', 'submitted_at', 'updated_at'])

    def start(self, user=None):
        if self.status != self.Status.PLANNED:
            raise ValidationError({'status': 'Somente auditorias planejadas podem iniciar.'})
        if not self.checklist_items.exists():
            raise ValidationError({'checklist': 'A execução exige checklist definido.'})
        self.status = self.Status.IN_PROGRESS
        self.actual_start = timezone.now()
        self.started_by = user
        self.full_clean()
        self.save(update_fields=['status', 'actual_start', 'started_by', 'updated_at'])

    def complete_execution(self, user=None):
        if self.status != self.Status.IN_PROGRESS:
            raise ValidationError(
                {'status': 'Somente auditorias em execução podem concluir execução.'}
            )
        unanswered_required = self.checklist_items.filter(
            required=True, status=AuditChecklistItem.Status.NOT_EVALUATED
        ).exists()
        if unanswered_required:
            raise ValidationError(
                {'checklist': 'Conclusão da execução exige checklist obrigatório respondido.'}
            )
        self.status = self.Status.REPORTING
        self.actual_end = timezone.now()
        self.completed_by = user
        self.full_clean()
        self.save(update_fields=['status', 'actual_end', 'completed_by', 'updated_at'])

    def close(self, summary, user=None):
        if not summary:
            raise ValidationError({'closure_summary': 'Informe o resumo de encerramento.'})
        if self.status != self.Status.REPORTING:
            raise ValidationError({'status': 'Encerramento exige auditoria em relatório.'})
        if not self.reports.exists():
            raise ValidationError({'report': 'Encerramento exige relatório de auditoria.'})
        if self.findings.exclude(evidences__isnull=False).exists():
            raise ValidationError(
                {'evidences': 'Encerramento exige evidência para todos os achados.'}
            )
        critical_findings = self.findings.filter(
            criticality__in=[AuditFinding.Criticality.MAJOR, AuditFinding.Criticality.CRITICAL]
        )
        if (
            critical_findings.filter(actions__mandatory=True)
            .exclude(actions__status=AuditFollowUpAction.Status.COMPLETED)
            .exists()
            or critical_findings.exclude(actions__mandatory=True).exists()
        ):
            raise ValidationError(
                {'actions': 'Achados maiores ou críticos exigem ações obrigatórias concluídas.'}
            )
        if not self.reports.filter(status=AuditReport.Status.ISSUED).exists():
            raise ValidationError({'report': 'Encerramento exige relatório emitido.'})
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
            raise ValidationError({'status': 'Auditoria encerrada não pode ser cancelada.'})
        self.status = self.Status.CANCELLED
        self.cancel_reason = reason
        self.save(update_fields=['status', 'cancel_reason', 'updated_at'])

    def clean(self):
        super().clean()
        validate_normalized_location(
            self,
            city_ref_field='venue_city_ref',
            state_ref_field='venue_state_ref',
        )
        errors = {}
        for field in ('lead_auditor', 'submitted_by', 'started_by', 'completed_by', 'closed_by'):
            pass
        if (
            self.scheduled_end
            and self.scheduled_start
            and self.scheduled_end <= self.scheduled_start
        ):
            errors['scheduled_end'] = 'O fim planejado deve ser posterior ao início.'
        if self.actual_end and self.actual_start and self.actual_end < self.actual_start:
            errors['actual_end'] = 'O fim real não pode ser anterior ao início.'
        if self.audit_type == self.AuditType.SUPPLIER and not self.supplier_id:
            errors['supplier'] = 'Auditoria de fornecedor exige fornecedor auditado.'
        if (
            self.audit_type == self.AuditType.CUSTOMER
            and self.supplier
            and self.supplier.partner_type != BusinessPartner.PartnerType.CUSTOMER
        ):
            errors['supplier'] = 'Auditoria de cliente exige parceiro do tipo cliente.'
        if (
            self.audit_type == self.AuditType.SUPPLIER
            and self.supplier
            and self.supplier.partner_type
            not in {
                BusinessPartner.PartnerType.SUPPLIER,
                BusinessPartner.PartnerType.MANUFACTURER,
                BusinessPartner.PartnerType.OUTSOURCED_LAB,
            }
        ):
            errors['supplier'] = (
                'Auditoria de fornecedor exige fornecedor, fabricante ou laboratório terceirizado.'
            )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.audit_number


class AuditChecklistItem(SingleInstanceModel):
    class Status(models.TextChoices):
        NOT_EVALUATED = 'not_evaluated', 'Não avaliado'
        CONFORM = 'conform', 'Conforme'
        NON_CONFORM = 'non_conform', 'Não conforme'
        NOT_APPLICABLE = 'not_applicable', 'Não aplicável'

    audit = models.ForeignKey(
        AuditPlan,
        on_delete=models.CASCADE,
        related_name='checklist_items',
        verbose_name='auditoria',
    )
    section = models.CharField('seção', max_length=120)
    question = models.TextField('pergunta')
    requirement_reference = models.CharField('referência do requisito', max_length=160)
    required = models.BooleanField('obrigatório', default=True)
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.NOT_EVALUATED
    )
    answer_text = models.TextField('resposta/evidência', blank=True, db_column='answer')
    answered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='answered_audit_checklists',
        null=True,
        blank=True,
        verbose_name='respondido por',
    )
    answered_at = models.DateTimeField('respondido em', null=True, blank=True)

    class Meta:
        ordering = ['audit__audit_number', 'section', 'id']
        indexes = [
            models.Index(fields=['audit', 'status']),
            models.Index(fields=['section']),
        ]
        verbose_name = 'item de checklist de auditoria'
        verbose_name_plural = 'itens de checklist de auditoria'

    def answer(self, status, answer, user=None):
        if not status:
            raise ValidationError({'status': 'Informe o resultado do checklist.'})
        if status != self.Status.NOT_APPLICABLE and not answer:
            raise ValidationError({'answer': 'Informe a resposta ou evidência do checklist.'})
        self.status = status
        self.answer_text = answer
        self.answered_by = user
        self.answered_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=['status', 'answer_text', 'answered_by', 'answered_at', 'updated_at']
        )

    def clean(self):
        super().clean()
        errors = {}
        if (
            self.status != self.Status.NOT_EVALUATED
            and self.status != self.Status.NOT_APPLICABLE
            and not self.answer_text
        ):
            errors['answer'] = 'Checklist avaliado exige resposta.'
        if self.status != self.Status.NOT_EVALUATED and (
            not self.answered_by_id or not self.answered_at
        ):
            errors['answered_by'] = 'Checklist avaliado exige responsável e data.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.audit} - {self.section}'


class AuditFinding(SingleInstanceModel):
    class Classification(models.TextChoices):
        NONCONFORMITY = 'nonconformity', 'Não conformidade'
        OBSERVATION = 'observation', 'Observação'
        OPPORTUNITY = 'opportunity', 'Oportunidade de melhoria'
        COMPLIANCE = 'compliance', 'Conformidade'

    class Criticality(models.TextChoices):
        MINOR = 'minor', 'Menor'
        MAJOR = 'major', 'Maior'
        CRITICAL = 'critical', 'Crítica'

    class Status(models.TextChoices):
        OPEN = 'open', 'Aberto'
        IN_ACTION = 'in_action', 'Em ação'
        CLOSED = 'closed', 'Encerrado'
        CANCELLED = 'cancelled', 'Cancelado'

    audit = models.ForeignKey(
        AuditPlan, on_delete=models.CASCADE, related_name='findings', verbose_name='auditoria'
    )
    checklist_item = models.ForeignKey(
        AuditChecklistItem,
        on_delete=models.PROTECT,
        related_name='findings',
        null=True,
        blank=True,
        verbose_name='item de checklist',
    )
    classification = models.CharField(
        'classificação', max_length=32, choices=Classification.choices
    )
    criticality = models.CharField('criticidade', max_length=24, choices=Criticality.choices)
    criticality_ref = models.ForeignKey(
        'auxiliary.ImpactLevel',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='criticidade normalizada',
    )
    title = models.CharField('título', max_length=180)
    description = models.TextField('descrição')
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='audit_findings',
        verbose_name='responsável',
    )
    due_date = models.DateField('prazo')
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.OPEN)

    class Meta:
        ordering = ['audit__audit_number', '-criticality', 'due_date']
        indexes = [
            models.Index(fields=['audit', 'classification']),
            models.Index(fields=['criticality', 'status']),
            models.Index(fields=['responsible', 'due_date']),
        ]
        verbose_name = 'achado de auditoria'
        verbose_name_plural = 'achados de auditoria'

    def close(self, user=None):
        if self.status not in {self.Status.OPEN, self.Status.IN_ACTION}:
            raise ValidationError(
                {'status': 'Somente achados abertos ou em ação podem ser encerrados.'}
            )
        if (
            self.actions.filter(mandatory=True)
            .exclude(status=AuditFollowUpAction.Status.COMPLETED)
            .exists()
        ):
            raise ValidationError(
                {'actions': 'Encerramento do achado exige ações obrigatórias concluídas.'}
            )
        previous_status = self.status
        with transaction.atomic():
            self.status = self.Status.CLOSED
            self.save(update_fields=['status', 'updated_at'])
            _record_audit_audit(
                'audits.finding.closed',
                'Achado de auditoria encerrado.',
                self,
                user,
                from_status=previous_status,
                to_status=self.status,
            )

    def clean(self):
        super().clean()
        errors = {}
        if self.checklist_item and self.audit and self.checklist_item.audit_id != self.audit_id:
            errors['checklist_item'] = 'O checklist deve pertencer à auditoria informada.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


class AuditEvidence(SingleInstanceModel):
    audit = models.ForeignKey(
        AuditPlan, on_delete=models.CASCADE, related_name='evidences', verbose_name='auditoria'
    )
    finding = models.ForeignKey(
        AuditFinding,
        on_delete=models.CASCADE,
        related_name='evidences',
        null=True,
        blank=True,
        verbose_name='achado',
    )
    title = models.CharField('título', max_length=160)
    file_reference = models.CharField('arquivo', max_length=255)
    content_hash = models.CharField('hash do conteúdo', max_length=128)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='uploaded_audit_evidences',
        null=True,
        blank=True,
        verbose_name='enviado por',
    )
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['audit__audit_number', 'title']
        indexes = [
            models.Index(fields=['audit']),
            models.Index(fields=['finding']),
            models.Index(fields=['content_hash']),
        ]
        verbose_name = 'evidência de auditoria'
        verbose_name_plural = 'evidências de auditoria'

    def clean(self):
        super().clean()
        errors = {}
        if self.finding and self.audit and self.finding.audit_id != self.audit_id:
            errors['finding'] = 'A evidência deve pertencer a achado da auditoria informada.'
        if not self.content_hash:
            errors['content_hash'] = 'Evidência exige hash para integridade dos dados.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


class AuditFollowUpAction(SingleInstanceModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        IN_PROGRESS = 'in_progress', 'Em andamento'
        COMPLETED = 'completed', 'Concluída'
        CANCELLED = 'cancelled', 'Cancelada'

    finding = models.ForeignKey(
        AuditFinding, on_delete=models.CASCADE, related_name='actions', verbose_name='achado'
    )
    title = models.CharField('título', max_length=180)
    description = models.TextField('descrição')
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='audit_follow_up_actions',
        verbose_name='responsável',
    )
    due_date = models.DateField('prazo')
    mandatory = models.BooleanField('obrigatória', default=True)
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
        related_name='completed_audit_actions',
        null=True,
        blank=True,
        verbose_name='concluída por',
    )
    completed_at = models.DateTimeField('concluída em', null=True, blank=True)

    class Meta:
        ordering = ['finding__audit__audit_number', 'due_date']
        indexes = [
            models.Index(fields=['finding', 'status']),
            models.Index(fields=['responsible', 'due_date']),
        ]
        verbose_name = 'ação de auditoria'
        verbose_name_plural = 'ações de auditoria'

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


class AuditFindingLink(SingleInstanceModel):
    class LinkType(models.TextChoices):
        CAPA = 'capa', 'CAPA'
        DEVIATION = 'deviation', 'Desvio'
        CHANGE = 'change', 'Mudança'
        RISK = 'risk', 'Risco'
        SUPPLIER = 'supplier', 'Fornecedor'
        DOCUMENT = 'document', 'Documento'
        TRAINING = 'training', 'Treinamento'

    finding = models.ForeignKey(
        AuditFinding, on_delete=models.CASCADE, related_name='links', verbose_name='achado'
    )
    link_type = models.CharField('tipo de vínculo', max_length=24, choices=LinkType.choices)
    capa = models.ForeignKey(
        'capa.CapaRecord',
        on_delete=models.PROTECT,
        related_name='audit_links',
        null=True,
        blank=True,
        verbose_name='CAPA',
    )
    deviation_event = models.ForeignKey(
        'deviations.QualityEvent',
        on_delete=models.PROTECT,
        related_name='audit_links',
        null=True,
        blank=True,
        verbose_name='desvio',
    )
    change_control = models.ForeignKey(
        'changes.ChangeControl',
        on_delete=models.PROTECT,
        related_name='audit_links',
        null=True,
        blank=True,
        verbose_name='mudança',
    )
    supplier = models.ForeignKey(
        'masters.BusinessPartner',
        on_delete=models.PROTECT,
        related_name='audit_finding_links',
        null=True,
        blank=True,
        verbose_name='fornecedor',
    )
    document = models.ForeignKey(
        'documents.ControlledDocument',
        on_delete=models.PROTECT,
        related_name='audit_finding_links',
        null=True,
        blank=True,
        verbose_name='documento',
    )
    reference_code = models.CharField('referência', max_length=120, blank=True)

    class Meta:
        ordering = ['finding__audit__audit_number', 'link_type']
        indexes = [
            models.Index(fields=['finding', 'link_type']),
            models.Index(fields=['capa']),
            models.Index(fields=['deviation_event']),
            models.Index(fields=['change_control']),
            models.Index(fields=['supplier']),
            models.Index(fields=['document']),
        ]
        verbose_name = 'vínculo de achado de auditoria'
        verbose_name_plural = 'vínculos de achados de auditoria'

    def clean(self):
        super().clean()
        errors = {}
        for field in (
            'finding',
            'capa',
            'deviation_event',
            'change_control',
            'supplier',
            'document',
        ):
            pass
        required_by_type = {
            self.LinkType.CAPA: ('capa', self.capa_id),
            self.LinkType.DEVIATION: ('deviation_event', self.deviation_event_id),
            self.LinkType.CHANGE: ('change_control', self.change_control_id),
            self.LinkType.SUPPLIER: ('supplier', self.supplier_id),
            self.LinkType.DOCUMENT: ('document', self.document_id),
        }
        if self.link_type in required_by_type:
            field, value = required_by_type[self.link_type]
            if not value:
                errors[field] = 'Informe o cadastro relacionado ao tipo de vínculo.'
        if (
            self.link_type in {self.LinkType.RISK, self.LinkType.TRAINING}
            and not self.reference_code
        ):
            errors['reference_code'] = 'Informe a referência do vínculo.'
        if self.supplier and self.supplier.partner_type not in {
            BusinessPartner.PartnerType.SUPPLIER,
            BusinessPartner.PartnerType.MANUFACTURER,
            BusinessPartner.PartnerType.OUTSOURCED_LAB,
        }:
            errors['supplier'] = (
                'Fornecedor vinculado deve ser fornecedor, fabricante ou laboratório terceirizado.'
            )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.finding} - {self.get_link_type_display()}'


class AuditReport(SingleInstanceModel):
    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        ISSUED = 'issued', 'Emitido'

    audit = models.ForeignKey(
        AuditPlan, on_delete=models.CASCADE, related_name='reports', verbose_name='auditoria'
    )
    executive_summary = models.TextField('sumário executivo')
    conclusion = models.TextField('conclusão')
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    total_findings = models.PositiveIntegerField('achados totais', default=0)
    critical_findings = models.PositiveIntegerField('achados críticos', default=0)
    major_findings = models.PositiveIntegerField('achados maiores', default=0)
    minor_findings = models.PositiveIntegerField('achados menores', default=0)
    opportunities = models.PositiveIntegerField('oportunidades', default=0)
    total_checklist_items = models.PositiveIntegerField('itens avaliados', default=0)
    conform_items = models.PositiveIntegerField('itens conformes', default=0)
    nonconform_items = models.PositiveIntegerField('itens não conformes', default=0)
    compliance_rate = models.PositiveIntegerField('índice de conformidade', default=0)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='issued_audit_reports',
        null=True,
        blank=True,
        verbose_name='emitido por',
    )
    issued_at = models.DateTimeField('emitido em', null=True, blank=True)

    class Meta:
        ordering = ['audit__audit_number', '-created_at']
        constraints = [
            models.UniqueConstraint(fields=['audit'], name='unique_audit_report'),
        ]
        indexes = [
            models.Index(fields=['audit', 'status']),
            models.Index(fields=['issued_at']),
        ]
        verbose_name = 'relatório de auditoria'
        verbose_name_plural = 'relatórios de auditoria'

    def issue(self, user=None):
        if self.status != self.Status.DRAFT:
            raise ValidationError({'status': 'Somente relatórios em rascunho podem ser emitidos.'})
        self.calculate_indicators()
        self.status = self.Status.ISSUED
        self.issued_by = user or self.issued_by
        self.issued_at = timezone.now()
        self.full_clean()
        with transaction.atomic():
            self._save_issued()
            _record_audit_audit(
                'audits.report.issued',
                'Relatório de auditoria emitido.',
                self,
                user,
                audit_id=self.audit_id,
                compliance_rate=self.compliance_rate,
            )

    def _save_issued(self):
        self.save(
            update_fields=[
                'status',
                'issued_by',
                'issued_at',
                'total_findings',
                'critical_findings',
                'major_findings',
                'minor_findings',
                'opportunities',
                'total_checklist_items',
                'conform_items',
                'nonconform_items',
                'compliance_rate',
                'updated_at',
            ]
        )

    def calculate_indicators(self):
        findings = self.audit.findings.all()
        self.total_findings = findings.count()
        self.critical_findings = findings.filter(
            criticality=AuditFinding.Criticality.CRITICAL
        ).count()
        self.major_findings = findings.filter(criticality=AuditFinding.Criticality.MAJOR).count()
        self.minor_findings = findings.filter(criticality=AuditFinding.Criticality.MINOR).count()
        self.opportunities = findings.filter(
            classification=AuditFinding.Classification.OPPORTUNITY
        ).count()
        checklist = self.audit.checklist_items.exclude(
            status=AuditChecklistItem.Status.NOT_EVALUATED
        )
        evaluated = checklist.exclude(status=AuditChecklistItem.Status.NOT_APPLICABLE)
        self.total_checklist_items = evaluated.count()
        self.conform_items = evaluated.filter(status=AuditChecklistItem.Status.CONFORM).count()
        self.nonconform_items = evaluated.filter(
            status=AuditChecklistItem.Status.NON_CONFORM
        ).count()
        self.compliance_rate = (
            int((self.conform_items / self.total_checklist_items) * 100)
            if self.total_checklist_items
            else 0
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.status == self.Status.ISSUED and (not self.issued_by_id or not self.issued_at):
            errors['issued_by'] = 'Relatório emitido exige responsável e data.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.audit} - {self.get_status_display()}'
