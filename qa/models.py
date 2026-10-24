from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from base.modules import OperationalModule
from base.models import SingleInstanceModel
from base.sequences import AutoCodeMixin, IdentifierSpec, sequence_code
from inventory.models import StockBalance, StockLot, StockQualityStatus
from masters.models import BusinessPartner, Product


def _sequence_code(model, *args):
    if len(args) == 3:
        _legacy_scope, field_name, prefix = args
    else:
        field_name, prefix = args
    return sequence_code(model, field_name, prefix)


class QAReview(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('review_number', 'RQA'),)

    class ReviewType(models.TextChoices):
        LOT_RELEASE = 'lot_release', 'Liberação de lote'
        PRODUCTION_ORDER = 'production_order', 'Ordem de produção'
        PACKAGING_RECORD = 'packaging_record', 'Registro de embalagem'
        QUALITY_DOCUMENT = 'quality_document', 'Laudo/documento de qualidade'
        DEVIATION = 'deviation', 'Desvio'
        CAPA = 'capa', 'CAPA'
        CHANGE = 'change', 'Mudança'
        CONTROLLED_DOCUMENT = 'controlled_document', 'Documento controlado'

    class Status(models.TextChoices):
        DRAFT = 'draft', 'Rascunho'
        IN_REVIEW = 'in_review', 'Em revisão'
        APPROVED = 'approved', 'Aprovada'
        REJECTED = 'rejected', 'Rejeitada'
        CANCELLED = 'cancelled', 'Cancelada'

    review_number = models.CharField('revisão', max_length=80, blank=True)
    review_type = models.CharField('tipo', max_length=32, choices=ReviewType.choices)
    title = models.CharField('título', max_length=180)
    stock_lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.PROTECT,
        related_name='qa_reviews',
        null=True,
        blank=True,
        verbose_name='lote',
    )
    production_order = models.ForeignKey(
        'production.ProductionOrder',
        on_delete=models.PROTECT,
        related_name='qa_reviews',
        null=True,
        blank=True,
        verbose_name='ordem de produção',
    )
    quality_document = models.ForeignKey(
        'quality.QualityDocument',
        on_delete=models.PROTECT,
        related_name='qa_reviews',
        null=True,
        blank=True,
        verbose_name='documento de qualidade',
    )
    packaging_record_reference = models.CharField(
        'registro de embalagem', max_length=120, blank=True
    )
    deviation_reference = models.CharField('desvio', max_length=120, blank=True)
    capa_reference = models.CharField('CAPA', max_length=120, blank=True)
    change_reference = models.CharField('mudança', max_length=120, blank=True)
    controlled_document_reference = models.CharField(
        'documento controlado', max_length=120, blank=True
    )
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.DRAFT)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='submitted_qa_reviews',
        null=True,
        blank=True,
        verbose_name='submetida por',
    )
    submitted_at = models.DateTimeField('submetida em', null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='approved_qa_reviews',
        null=True,
        blank=True,
        verbose_name='aprovada por',
    )
    approved_at = models.DateTimeField('aprovada em', null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='rejected_qa_reviews',
        null=True,
        blank=True,
        verbose_name='rejeitada por',
    )
    rejected_at = models.DateTimeField('rejeitada em', null=True, blank=True)
    rejection_reason = models.TextField('motivo da rejeição', blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['review_number'], name='unique_qa_review_number'),
        ]
        indexes = [
            models.Index(fields=['review_type', 'status']),
            models.Index(fields=['stock_lot']),
            models.Index(fields=['production_order']),
            models.Index(fields=['quality_document']),
            models.Index(fields=['review_number']),
        ]
        verbose_name = 'revisão QA'
        verbose_name_plural = 'revisões QA'

    def save(self, *args, **kwargs):
        if not self.review_number:
            self.review_number = _sequence_code(QAReview, 'review_number', 'RQA')
        super().save(*args, **kwargs)

    def submit(self, user=None):
        if self.status != self.Status.DRAFT:
            raise ValidationError({'status': 'Somente revisões em rascunho podem ser submetidas.'})
        self.status = self.Status.IN_REVIEW
        self.submitted_by = user
        self.submitted_at = timezone.now()
        self.full_clean()
        self.save(update_fields=['status', 'submitted_by', 'submitted_at', 'updated_at'])

    def approve(self, user=None):
        if self.status not in {self.Status.DRAFT, self.Status.IN_REVIEW}:
            raise ValidationError(
                {'status': 'Somente revisões em rascunho ou em revisão podem ser aprovadas.'}
            )
        if user is not None and self.submitted_by_id and self.submitted_by_id == user.pk:
            raise ValidationError(
                {'approved_by': 'Segregação de funções: o autor da submissão não pode aprovar.'}
            )
        if self.checklist_items.exclude(status=BatchRecordChecklistItem.Status.COMPLETED).exists():
            raise ValidationError({'checklist': 'A aprovação exige checklist sem pendências.'})
        self.status = self.Status.APPROVED
        self.approved_by = user
        self.approved_at = timezone.now()
        self.rejection_reason = ''
        self.full_clean()
        self.save(
            update_fields=['status', 'approved_by', 'approved_at', 'rejection_reason', 'updated_at']
        )

    def reject(self, reason, user=None):
        if not reason:
            raise ValidationError({'rejection_reason': 'Informe o motivo da rejeição.'})
        if self.status == self.Status.APPROVED:
            raise ValidationError({'status': 'Revisões aprovadas não podem ser rejeitadas.'})
        self.status = self.Status.REJECTED
        self.rejected_by = user
        self.rejected_at = timezone.now()
        self.rejection_reason = reason
        self.full_clean()
        self.save(
            update_fields=['status', 'rejected_by', 'rejected_at', 'rejection_reason', 'updated_at']
        )

    def clean(self):
        super().clean()
        errors = {}
        for field in ('stock_lot', 'production_order', 'quality_document'):
            pass
        for field in ('submitted_by', 'approved_by', 'rejected_by'):
            pass
        has_reference = any(
            (
                self.stock_lot_id,
                self.production_order_id,
                self.quality_document_id,
                self.packaging_record_reference,
                self.deviation_reference,
                self.capa_reference,
                self.change_reference,
                self.controlled_document_reference,
            )
        )
        if not has_reference:
            errors['review_type'] = 'Informe ao menos um objeto ou referência para revisão.'
        if (
            self.quality_document
            and self.stock_lot
            and self.quality_document.stock_lot_id != self.stock_lot_id
        ):
            errors['quality_document'] = (
                'O documento de qualidade deve pertencer ao lote informado.'
            )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.review_number


class BatchRecordChecklistItem(SingleInstanceModel):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        COMPLETED = 'completed', 'Concluído'
        BLOCKED = 'blocked', 'Bloqueado'
        NOT_APPLICABLE = 'not_applicable', 'Não aplicável'

    review = models.ForeignKey(
        QAReview,
        on_delete=models.CASCADE,
        related_name='checklist_items',
        verbose_name='revisão QA',
    )
    title = models.CharField('item de checklist', max_length=180)
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.PENDING
    )
    responsible = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='qa_checklist_items',
        null=True,
        blank=True,
        verbose_name='responsável',
    )
    due_date = models.DateField('prazo', null=True, blank=True)
    comments = models.TextField('comentários', blank=True)
    evidence_reference = models.CharField('evidência', max_length=255, blank=True)
    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='completed_qa_checklist_items',
        null=True,
        blank=True,
        verbose_name='concluído por',
    )
    completed_at = models.DateTimeField('concluído em', null=True, blank=True)

    class Meta:
        ordering = ['review__review_number', 'created_at']
        indexes = [
            models.Index(fields=['review', 'status']),
            models.Index(fields=['responsible', 'due_date']),
        ]
        verbose_name = 'item de checklist de batch record'
        verbose_name_plural = 'itens de checklist de batch record'

    def complete(self, user=None, evidence_reference='', comments=''):
        if not evidence_reference:
            raise ValidationError({'evidence_reference': 'Informe a evidência da conclusão.'})
        self.status = self.Status.COMPLETED
        self.completed_by = user
        self.completed_at = timezone.now()
        self.evidence_reference = evidence_reference
        if comments:
            self.comments = comments
        self.full_clean()
        self.save(
            update_fields=[
                'status',
                'completed_by',
                'completed_at',
                'evidence_reference',
                'comments',
                'updated_at',
            ]
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.status == self.Status.COMPLETED and not self.evidence_reference:
            errors['evidence_reference'] = 'Checklist concluído exige evidência.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


class LotRelease(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('release_number', 'LIB'),)
    TARGET_FIELDS = (
        'product',
        'stock_lot',
        'qa_review',
        'quality_document',
        'production_order',
    )
    DISPOSITION_FIELDS = (
        'decision',
        'released_by',
        'released_at',
        'rejection_reason',
        'rejected_by',
        'rejected_at',
        'block_reason',
        'blocked_by',
        'blocked_at',
        'unblock_reason',
        'unblocked_by',
        'unblocked_at',
    )

    class ReleaseStatus(models.TextChoices):
        UNDER_REVIEW = 'under_review', 'Em revisão'
        RELEASED = 'released', 'Liberado'
        REJECTED = 'rejected', 'Rejeitado'
        BLOCKED = 'blocked', 'Bloqueado'

    release_number = models.CharField('liberação', max_length=80, blank=True)
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='qa_lot_releases', verbose_name='produto'
    )
    stock_lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.PROTECT,
        related_name='qa_lot_releases',
        verbose_name='lote',
    )
    qa_review = models.ForeignKey(
        QAReview,
        on_delete=models.PROTECT,
        related_name='lot_releases',
        null=True,
        blank=True,
        verbose_name='revisão QA',
    )
    quality_document = models.ForeignKey(
        'quality.QualityDocument',
        on_delete=models.PROTECT,
        related_name='qa_lot_releases',
        null=True,
        blank=True,
        verbose_name='documento de qualidade',
    )
    production_order = models.ForeignKey(
        'production.ProductionOrder',
        on_delete=models.PROTECT,
        related_name='qa_lot_releases',
        null=True,
        blank=True,
        verbose_name='ordem de produção',
    )
    release_status = models.CharField(
        'status de liberação',
        max_length=24,
        choices=ReleaseStatus.choices,
        default=ReleaseStatus.UNDER_REVIEW,
    )
    decision = models.TextField('decisão', blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='released_qa_lots',
        null=True,
        blank=True,
        verbose_name='liberado por',
    )
    released_at = models.DateTimeField('liberado em', null=True, blank=True)
    rejected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='rejected_qa_lots',
        null=True,
        blank=True,
        verbose_name='rejeitado por',
    )
    rejected_at = models.DateTimeField('rejeitado em', null=True, blank=True)
    rejection_reason = models.TextField('motivo da rejeição', blank=True)
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='blocked_qa_lots',
        null=True,
        blank=True,
        verbose_name='bloqueado por',
    )
    blocked_at = models.DateTimeField('bloqueado em', null=True, blank=True)
    block_reason = models.TextField('motivo do bloqueio', blank=True)
    unblocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='unblocked_qa_lots',
        null=True,
        blank=True,
        verbose_name='desbloqueado por',
    )
    unblocked_at = models.DateTimeField('desbloqueado em', null=True, blank=True)
    unblock_reason = models.TextField('motivo do desbloqueio', blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['release_number'], name='unique_lot_release_number'),
            models.UniqueConstraint(fields=['stock_lot'], name='unique_lot_release_lot'),
        ]
        indexes = [
            models.Index(fields=['release_status']),
            models.Index(fields=['product']),
            models.Index(fields=['stock_lot']),
            models.Index(fields=['release_number']),
        ]
        verbose_name = 'liberação de lote'
        verbose_name_plural = 'liberações de lote'

    def save(self, *args, **kwargs):
        if not self.release_number:
            self.release_number = _sequence_code(LotRelease, 'release_number', 'LIB')
        target_errors = self._immutable_target_errors()
        if target_errors:
            raise ValidationError(target_errors)
        disposition_errors = self._controlled_disposition_errors()
        if disposition_errors:
            raise ValidationError(disposition_errors)
        super().save(*args, **kwargs)

    def _immutable_target_errors(self):
        if self.pk is None:
            return {}
        persisted = (
            type(self)
            .objects.filter(pk=self.pk)
            .values(*(f'{field_name}_id' for field_name in self.TARGET_FIELDS))
            .first()
        )
        if persisted is None:
            return {}
        return {
            field_name: 'O vínculo-alvo da liberação não pode ser alterado após a criação.'
            for field_name in self.TARGET_FIELDS
            if persisted[f'{field_name}_id'] != getattr(self, f'{field_name}_id')
        }

    def _controlled_disposition_errors(self):
        if self.pk is None or getattr(self, '_domain_transition', False):
            return {}
        persisted_fields = tuple(
            f'{field_name}_id' if field_name.endswith('_by') else field_name
            for field_name in self.DISPOSITION_FIELDS
        )
        persisted = (
            type(self)
            .objects.filter(pk=self.pk)
            .values('release_status', *persisted_fields)
            .first()
        )
        if persisted is None:
            return {}
        errors = {}
        if persisted['release_status'] != self.release_status:
            errors['release_status'] = 'O status só pode ser alterado pelas ações de disposição.'
        if persisted['release_status'] in {
            self.ReleaseStatus.RELEASED,
            self.ReleaseStatus.REJECTED,
        }:
            for field_name in self.DISPOSITION_FIELDS:
                if field_name.endswith('_by'):
                    current_value = getattr(self, f'{field_name}_id')
                    persisted_value = persisted[f'{field_name}_id']
                else:
                    current_value = getattr(self, field_name)
                    persisted_value = persisted[field_name]
                if current_value != persisted_value:
                    errors[field_name] = 'A evidência de uma disposição terminal é imutável.'
        return errors

    @staticmethod
    def _prevalidate_disposition_actor(user):
        if (
            user is None
            or not getattr(user, 'is_authenticated', False)
            or getattr(user, 'pk', None) is None
        ):
            raise ValidationError(
                {'user': 'Informe um ator QA autenticado, ativo e persistido para a disposição.'}
            )
        return user

    def _locked_for_disposition(self):
        if self.pk is None:
            raise ValidationError(
                {'release_status': 'A liberação deve estar persistida antes da disposição.'}
            )
        return type(self).objects.select_for_update(of=('self',)).get(pk=self.pk)

    @staticmethod
    def _locked_actor(user):
        User = get_user_model()
        try:
            actor = User.objects.select_for_update().get(pk=user.pk, is_active=True)
        except User.DoesNotExist as exc:
            raise ValidationError(
                {'user': 'O ator QA informado não está ativo ou persistido.'}
            ) from exc
        return actor

    @staticmethod
    def _transition_error(allowed_origins):
        labels = ', '.join(str(status) for status in allowed_origins)
        return ValidationError(
            {'release_status': f'Transição inválida. Status de origem esperado: {labels}.'}
        )

    def _validate_locked_evidence(self, release, stock_lot, qa_review, quality_document, order):
        errors = {}
        if stock_lot.product_id != release.product_id:
            errors['stock_lot'] = 'O lote deve pertencer ao produto da liberação.'
        if qa_review:
            if qa_review.stock_lot_id != stock_lot.pk:
                errors['qa_review'] = 'A revisão QA deve pertencer ao lote da liberação.'
            elif (
                qa_review.quality_document_id
                and qa_review.quality_document_id != release.quality_document_id
            ):
                errors['qa_review'] = 'A revisão QA deve referenciar o documento da liberação.'
            elif (
                qa_review.production_order_id
                and qa_review.production_order_id != release.production_order_id
            ):
                errors['qa_review'] = 'A revisão QA deve referenciar a ordem da liberação.'
        if quality_document:
            if quality_document.product_id != release.product_id:
                errors['quality_document'] = (
                    'O documento de qualidade deve pertencer ao produto da liberação.'
                )
            elif quality_document.stock_lot_id != stock_lot.pk:
                errors['quality_document'] = (
                    'O documento de qualidade deve pertencer ao lote informado.'
                )
        if order:
            if order.product_id != release.product_id:
                errors['production_order'] = (
                    'A ordem de produção deve pertencer ao produto da liberação.'
                )
            if stock_lot.source_production_order_id != order.pk:
                errors['production_order'] = (
                    'A ordem de produção deve ser a origem do lote informado.'
                )
        if errors:
            raise ValidationError(errors)

    @transaction.atomic
    def _transition(
        self,
        *,
        user,
        allowed_origins,
        target_release_status,
        target_stock_status,
        action,
        message,
        evidence_field,
        evidence_value,
        actor_field,
        actor_at_field,
        require_approved_evidence=False,
    ):
        from governance.models import GovernanceAuditLog

        self._prevalidate_disposition_actor(user)
        release = self._locked_for_disposition()
        if release.release_status not in allowed_origins:
            raise self._transition_error(allowed_origins)

        # GMP lock order: release -> lot -> balances(pk) -> evidence -> actor.
        stock_lot = StockLot.objects.select_for_update().get(pk=release.stock_lot_id)
        balances = list(
            StockBalance.objects.select_for_update().filter(lot_id=stock_lot.pk).order_by('pk')
        )
        qa_review = (
            QAReview.objects.select_for_update().get(pk=release.qa_review_id)
            if release.qa_review_id
            else None
        )
        if release.quality_document_id:
            from quality.models import QualityDocument

            quality_document = QualityDocument.objects.select_for_update().get(
                pk=release.quality_document_id
            )
        else:
            quality_document = None
        if release.production_order_id:
            from production.models import ProductionOrder

            order = ProductionOrder.objects.select_for_update().get(pk=release.production_order_id)
        else:
            order = None
        actor = self._locked_actor(user)
        self._validate_locked_evidence(release, stock_lot, qa_review, quality_document, order)

        expected_stock_status = (
            StockQualityStatus.BLOCKED
            if release.release_status == self.ReleaseStatus.BLOCKED
            else StockQualityStatus.QUARANTINE
        )
        if stock_lot.quality_status != expected_stock_status:
            raise ValidationError(
                {'stock_lot': 'A disposição do lote diverge do estado da liberação.'}
            )
        if any(balance.quality_status != expected_stock_status for balance in balances):
            raise ValidationError(
                {'stock_balances': 'Os saldos divergem da disposição atual do lote.'}
            )
        if require_approved_evidence:
            from quality.models import LaboratoryInvestigation, QualityDocument

            if qa_review is None or qa_review.status != QAReview.Status.APPROVED:
                raise ValidationError({'qa_review': 'A liberação exige revisão QA aprovada.'})
            if quality_document is None or quality_document.status != QualityDocument.Status.ISSUED:
                raise ValidationError(
                    {'quality_document': 'A liberação exige documento de qualidade emitido.'}
                )
            open_investigations = LaboratoryInvestigation.objects.filter(
                sample__stock_lot_id=stock_lot.pk,
                status__in=(
                    LaboratoryInvestigation.Status.OPEN,
                    LaboratoryInvestigation.Status.IN_PROGRESS,
                ),
            )
            if open_investigations.exists():
                raise ValidationError(
                    {
                        'release_status': (
                            'A liberação exige investigações laboratoriais do lote concluídas.'
                        )
                    }
                )

        disposition_at = timezone.now()
        previous_status = release.release_status
        release.release_status = target_release_status
        setattr(release, evidence_field, evidence_value)
        setattr(release, actor_field, actor)
        setattr(release, actor_at_field, disposition_at)
        release.full_clean()
        release._domain_transition = True
        try:
            release.save(
                update_fields=[
                    'release_status',
                    evidence_field,
                    actor_field,
                    actor_at_field,
                    'updated_at',
                ]
            )
        finally:
            del release._domain_transition
        stock_lot.quality_status = target_stock_status
        stock_lot.updated_at = disposition_at
        stock_lot.save(update_fields=['quality_status', 'updated_at'])
        balance_ids = [balance.pk for balance in balances]
        if balance_ids:
            StockBalance.objects.filter(pk__in=balance_ids).update(
                quality_status=target_stock_status,
                updated_at=disposition_at,
            )
        GovernanceAuditLog.record(
            log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
            severity=GovernanceAuditLog.Severity.INFO,
            module=OperationalModule.QA,
            action=action,
            target_model='LotRelease',
            target_record_id=str(release.pk),
            user=actor,
            message=message,
            safe_context={
                'from_status': previous_status,
                'to_status': release.release_status,
                'stock_lot_id': stock_lot.pk,
                'affected_balances': len(balance_ids),
            },
        )
        self.__dict__.update(release.__dict__)
        self.stock_lot = stock_lot
        return self

    def approve(self, user=None, decision=''):
        return self._transition(
            user=user,
            allowed_origins=(self.ReleaseStatus.UNDER_REVIEW,),
            target_release_status=self.ReleaseStatus.RELEASED,
            target_stock_status=StockQualityStatus.APPROVED,
            action='qa.lot_release.approved',
            message='Lote e saldos liberados pela Garantia da Qualidade.',
            evidence_field='decision',
            evidence_value=decision or self.decision,
            actor_field='released_by',
            actor_at_field='released_at',
            require_approved_evidence=True,
        )

    def reject(self, reason, user=None):
        if not reason:
            raise ValidationError({'rejection_reason': 'Informe o motivo da rejeição.'})
        return self._transition(
            user=user,
            allowed_origins=(self.ReleaseStatus.UNDER_REVIEW, self.ReleaseStatus.BLOCKED),
            target_release_status=self.ReleaseStatus.REJECTED,
            target_stock_status=StockQualityStatus.REJECTED,
            action='qa.lot_release.rejected',
            message='Lote e saldos rejeitados pela Garantia da Qualidade.',
            evidence_field='rejection_reason',
            evidence_value=reason,
            actor_field='rejected_by',
            actor_at_field='rejected_at',
        )

    def block(self, reason, user=None):
        if not reason:
            raise ValidationError({'block_reason': 'Informe o motivo do bloqueio.'})
        return self._transition(
            user=user,
            allowed_origins=(self.ReleaseStatus.UNDER_REVIEW,),
            target_release_status=self.ReleaseStatus.BLOCKED,
            target_stock_status=StockQualityStatus.BLOCKED,
            action='qa.lot_release.blocked',
            message='Lote e saldos bloqueados pela Garantia da Qualidade.',
            evidence_field='block_reason',
            evidence_value=reason,
            actor_field='blocked_by',
            actor_at_field='blocked_at',
        )

    def unblock(self, reason, user=None):
        if not reason:
            raise ValidationError({'unblock_reason': 'Informe o motivo do desbloqueio.'})
        return self._transition(
            user=user,
            allowed_origins=(self.ReleaseStatus.BLOCKED,),
            target_release_status=self.ReleaseStatus.UNDER_REVIEW,
            target_stock_status=StockQualityStatus.QUARANTINE,
            action='qa.lot_release.unblocked',
            message='Lote e saldos retornados à quarentena pela Garantia da Qualidade.',
            evidence_field='unblock_reason',
            evidence_value=reason,
            actor_field='unblocked_by',
            actor_at_field='unblocked_at',
        )

    def clean(self):
        super().clean()
        errors = self._immutable_target_errors()
        for field in ('released_by', 'rejected_by', 'blocked_by', 'unblocked_by'):
            pass
        if self.stock_lot and self.product and self.stock_lot.product_id != self.product_id:
            errors['stock_lot'] = 'O lote deve pertencer ao produto da liberação.'
        if self.qa_review and self.stock_lot:
            if self.qa_review.stock_lot_id != self.stock_lot_id:
                errors['qa_review'] = 'A revisão QA deve pertencer ao lote da liberação.'
            elif (
                self.qa_review.quality_document_id
                and self.qa_review.quality_document_id != self.quality_document_id
            ):
                errors['qa_review'] = 'A revisão QA deve referenciar o documento da liberação.'
            elif (
                self.qa_review.production_order_id
                and self.qa_review.production_order_id != self.production_order_id
            ):
                errors['qa_review'] = 'A revisão QA deve referenciar a ordem da liberação.'
        if (
            self.quality_document
            and self.stock_lot
            and self.quality_document.stock_lot_id != self.stock_lot_id
        ):
            errors['quality_document'] = (
                'O documento de qualidade deve pertencer ao lote informado.'
            )
        elif (
            self.quality_document
            and self.product
            and self.quality_document.product_id != self.product_id
        ):
            errors['quality_document'] = (
                'O documento de qualidade deve pertencer ao produto informado.'
            )
        if self.production_order:
            if self.product and self.production_order.product_id != self.product_id:
                errors['production_order'] = (
                    'A ordem de produção deve pertencer ao produto da liberação.'
                )
            if (
                self.stock_lot
                and self.stock_lot.source_production_order_id != self.production_order_id
            ):
                errors['production_order'] = (
                    'A ordem de produção deve ser a origem do lote informado.'
                )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.release_number


class QualityBlock(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('block_number', 'BLQ'),)

    class TargetType(models.TextChoices):
        LOT = 'lot', 'Lote'
        PRODUCT = 'product', 'Item/produto'
        SUPPLIER = 'supplier', 'Fornecedor'
        DOCUMENT = 'document', 'Documento'
        PROCESS = 'process', 'Processo'

    class Status(models.TextChoices):
        ACTIVE = 'active', 'Ativo'
        UNBLOCKED = 'unblocked', 'Desbloqueado'
        CANCELLED = 'cancelled', 'Cancelado'

    block_number = models.CharField('bloqueio', max_length=80, blank=True)
    target_type = models.CharField('tipo de alvo', max_length=24, choices=TargetType.choices)
    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name='qa_blocks',
        null=True,
        blank=True,
        verbose_name='item/produto',
    )
    stock_lot = models.ForeignKey(
        'inventory.StockLot',
        on_delete=models.PROTECT,
        related_name='qa_blocks',
        null=True,
        blank=True,
        verbose_name='lote',
    )
    supplier = models.ForeignKey(
        BusinessPartner,
        on_delete=models.PROTECT,
        related_name='qa_blocks',
        null=True,
        blank=True,
        verbose_name='fornecedor',
    )
    quality_document = models.ForeignKey(
        'quality.QualityDocument',
        on_delete=models.PROTECT,
        related_name='qa_blocks',
        null=True,
        blank=True,
        verbose_name='documento de qualidade',
    )
    process_reference = models.CharField('processo', max_length=120, blank=True)
    document_reference = models.CharField('documento', max_length=120, blank=True)
    reason = models.TextField('motivo')
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.ACTIVE
    )
    blocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_qa_blocks',
        null=True,
        blank=True,
        verbose_name='bloqueado por',
    )
    blocked_at = models.DateTimeField('bloqueado em', default=timezone.now)
    unblock_reason = models.TextField('motivo do desbloqueio', blank=True)
    unblocked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='released_qa_blocks',
        null=True,
        blank=True,
        verbose_name='desbloqueado por',
    )
    unblocked_at = models.DateTimeField('desbloqueado em', null=True, blank=True)

    class Meta:
        ordering = ['-blocked_at']
        constraints = [
            models.UniqueConstraint(fields=['block_number'], name='unique_quality_block_number'),
        ]
        indexes = [
            models.Index(fields=['target_type', 'status']),
            models.Index(fields=['product']),
            models.Index(fields=['stock_lot']),
            models.Index(fields=['supplier']),
            models.Index(fields=['block_number']),
        ]
        verbose_name = 'bloqueio QA'
        verbose_name_plural = 'bloqueios QA'

    def save(self, *args, **kwargs):
        if not self.block_number:
            self.block_number = _sequence_code(QualityBlock, 'block_number', 'BLQ')
        super().save(*args, **kwargs)

    def apply(self):
        self.status = self.Status.ACTIVE
        self.full_clean()
        self.save(update_fields=['status', 'updated_at'])
        if self.stock_lot_id:
            self.stock_lot.quality_status = StockQualityStatus.BLOCKED
            self.stock_lot.save(update_fields=['quality_status', 'updated_at'])
        if self.product_id:
            self.product.status = Product.Status.BLOCKED
            self.product.save(update_fields=['status', 'updated_at'])
        if self.supplier_id:
            self.supplier.is_blocked = True
            self.supplier.save(update_fields=['is_blocked', 'updated_at'])

    @transaction.atomic
    def unblock(self, reason, user=None):
        from governance.models import GovernanceAuditLog

        if not reason:
            raise ValidationError({'unblock_reason': 'Informe o motivo do desbloqueio.'})
        if user is None or not getattr(user, 'pk', None):
            raise ValidationError({'unblocked_by': 'Desbloqueio exige usuário identificado.'})
        locked = type(self).objects.select_for_update().get(pk=self.pk)
        if locked.status != self.Status.ACTIVE:
            raise ValidationError({'status': 'Somente bloqueios ativos podem ser desbloqueados.'})
        if locked.blocked_by_id and locked.blocked_by_id == user.pk:
            raise ValidationError(
                {'unblocked_by': 'Segregação de funções: quem bloqueou não pode desbloquear.'}
            )
        self.status = self.Status.UNBLOCKED
        self.unblock_reason = reason
        self.unblocked_by = user
        self.unblocked_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=['status', 'unblock_reason', 'unblocked_by', 'unblocked_at', 'updated_at']
        )
        others = type(self).objects.filter(status=self.Status.ACTIVE).exclude(pk=self.pk)
        restored = []
        if self.stock_lot_id:
            lot = StockLot.objects.select_for_update().get(pk=self.stock_lot_id)
            if (
                lot.quality_status != StockQualityStatus.REJECTED
                and not others.filter(stock_lot_id=lot.pk).exists()
            ):
                lot.quality_status = StockQualityStatus.QUARANTINE
                lot.save(update_fields=['quality_status', 'updated_at'])
                restored.append('stock_lot')
        if self.product_id:
            # Trava o produto antes de avaliar os demais bloqueios ativos (ordem: lote, produto, fornecedor).
            product = Product.objects.select_for_update().get(pk=self.product_id)
            if not others.filter(product_id=product.pk).exists():
                product.status = Product.Status.APPROVED
                product.save(update_fields=['status', 'updated_at'])
                restored.append('product')
        if self.supplier_id:
            supplier = type(self.supplier).objects.select_for_update().get(pk=self.supplier_id)
            if not others.filter(supplier_id=supplier.pk).exists():
                supplier.is_blocked = False
                supplier.save(update_fields=['is_blocked', 'updated_at'])
                restored.append('supplier')
        GovernanceAuditLog.record(
            log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
            severity=GovernanceAuditLog.Severity.INFO,
            module=OperationalModule.QA,
            action='qa.quality_block.unblocked',
            message='Bloqueio de qualidade desbloqueado pela Garantia da Qualidade.',
            target_model='QualityBlock',
            target_record_id=str(self.pk),
            user=user,
            safe_context={'restored_targets': restored},
        )

    def clean(self):
        super().clean()
        errors = {}
        for field in ('product', 'stock_lot', 'supplier', 'quality_document'):
            pass
        has_target = any(
            (
                self.product_id,
                self.stock_lot_id,
                self.supplier_id,
                self.quality_document_id,
                self.process_reference,
                self.document_reference,
            )
        )
        if not has_target:
            errors['target_type'] = 'Informe o alvo do bloqueio.'
        if self.stock_lot and self.product and self.stock_lot.product_id != self.product_id:
            errors['stock_lot'] = 'O lote deve pertencer ao produto informado.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.block_number


class TrainingRequirement(AutoCodeMixin, SingleInstanceModel):
    CODE_PREFIX = 'TRQ'
    code = models.CharField('código', max_length=40, blank=True)
    title = models.CharField('treinamento', max_length=180)
    document_reference = models.CharField('documento relacionado', max_length=120, blank=True)
    required_role = models.CharField('função obrigatória', max_length=120, blank=True)
    role_ref = models.ForeignKey(
        'auxiliary.OrganizationalRole',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='função normalizada',
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
    process = models.CharField('processo', max_length=120, blank=True)
    process_ref = models.ForeignKey(
        'auxiliary.BusinessProcess',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='processo normalizado',
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='targeted_training_requirements',
        null=True,
        blank=True,
        verbose_name='usuário alvo',
    )
    validity_days = models.PositiveIntegerField('validade em dias', default=365)
    is_mandatory = models.BooleanField('obrigatório', default=True)
    is_active = models.BooleanField('ativo', default=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_training_requirement_code'),
        ]
        indexes = [
            models.Index(fields=['is_active', 'is_mandatory']),
            models.Index(fields=['area', 'process']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'requisito de treinamento'
        verbose_name_plural = 'requisitos de treinamento'

    def user_has_valid_training(self, user):
        return (
            self.training_records.filter(user=user)
            .filter(status=TrainingRecord.Status.COMPLETED)
            .filter(
                models.Q(valid_until__isnull=True) | models.Q(valid_until__gte=timezone.localdate())
            )
            .exists()
        )

    def clean(self):
        super().clean()
        errors = {}
        if self.validity_days <= 0:
            errors['validity_days'] = 'A validade deve ser maior que zero.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.code} - {self.title}'


class TrainingRecord(SingleInstanceModel):
    class Status(models.TextChoices):
        PLANNED = 'planned', 'Planejado'
        COMPLETED = 'completed', 'Concluído'
        EXPIRED = 'expired', 'Expirado'
        REVOKED = 'revoked', 'Revogado'

    requirement = models.ForeignKey(
        TrainingRequirement,
        on_delete=models.PROTECT,
        related_name='training_records',
        verbose_name='requisito',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='training_records',
        verbose_name='usuário',
    )
    trainer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='delivered_training_records',
        null=True,
        blank=True,
        verbose_name='instrutor',
    )
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.PLANNED
    )
    completed_at = models.DateTimeField('concluído em', null=True, blank=True)
    valid_until = models.DateField('válido até', null=True, blank=True)
    evidence_reference = models.CharField('evidência', max_length=255, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['-completed_at', '-created_at']
        indexes = [
            models.Index(fields=['requirement', 'status']),
            models.Index(fields=['user', 'valid_until']),
        ]
        verbose_name = 'registro de treinamento'
        verbose_name_plural = 'registros de treinamento'

    @property
    def is_valid(self):
        if self.status != self.Status.COMPLETED:
            return False
        if self.valid_until and self.valid_until < timezone.localdate():
            return False
        return True

    def complete(self, completed_at=None, user=None, evidence_reference=''):
        completed_at = completed_at or timezone.now()
        self.status = self.Status.COMPLETED
        self.completed_at = completed_at
        self.trainer = user or self.trainer
        completed_date = timezone.localdate(value=completed_at)
        self.valid_until = completed_date + timedelta(days=self.requirement.validity_days)
        if evidence_reference:
            self.evidence_reference = evidence_reference
        self.full_clean()
        self.save(
            update_fields=[
                'status',
                'completed_at',
                'trainer',
                'valid_until',
                'evidence_reference',
                'updated_at',
            ]
        )

    def revoke(self, reason):
        if not reason:
            raise ValidationError({'notes': 'Informe a justificativa da revogação.'})
        self.status = self.Status.REVOKED
        self.notes = reason
        self.save(update_fields=['status', 'notes', 'updated_at'])

    def clean(self):
        super().clean()
        errors = {}
        if (
            self.valid_until
            and self.completed_at
            and self.valid_until < timezone.localdate(value=self.completed_at)
        ):
            errors['valid_until'] = 'A validade não pode ser anterior à conclusão.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.requirement} - {self.user}'


class CriticalActivityRule(SingleInstanceModel):
    activity_code = models.CharField('atividade', max_length=80)
    name = models.CharField('nome', max_length=180)
    training_requirement = models.ForeignKey(
        TrainingRequirement,
        on_delete=models.PROTECT,
        related_name='critical_activity_rules',
        verbose_name='treinamento obrigatório',
    )
    required_role = models.CharField('função', max_length=120, blank=True)
    role_ref = models.ForeignKey(
        'auxiliary.OrganizationalRole',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='função normalizada',
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
    process = models.CharField('processo', max_length=120, blank=True)
    process_ref = models.ForeignKey(
        'auxiliary.BusinessProcess',
        on_delete=models.PROTECT,
        related_name='+',
        null=True,
        blank=True,
        verbose_name='processo normalizado',
    )
    enforce_training = models.BooleanField('bloquear sem treinamento', default=True)
    is_active = models.BooleanField('ativo', default=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['activity_code']
        constraints = [
            models.UniqueConstraint(fields=['activity_code'], name='unique_critical_activity_code'),
        ]
        indexes = [
            models.Index(fields=['is_active', 'enforce_training']),
            models.Index(fields=['activity_code']),
        ]
        verbose_name = 'regra de atividade crítica'
        verbose_name_plural = 'regras de atividades críticas'

    def validate_user_training(self, user):
        if not self.is_active or not self.enforce_training:
            return True
        errors = {}
        if errors:
            raise ValidationError(errors)
        if not self.training_requirement.user_has_valid_training(user):
            raise ValidationError(
                {'training': 'Usuário sem treinamento válido para atividade crítica.'}
            )
        return True

    def clean(self):
        super().clean()
        errors = {}
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.activity_code} - {self.name}'
