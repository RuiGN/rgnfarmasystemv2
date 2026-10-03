from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from base.models import SingleInstanceModel
from base.sequences import IdentifierSpec, sequence_code
from masters.models import BusinessPartner, Product, StorageLocation, UnitOfMeasure, Warehouse


QUANTITY_SCALE = Decimal('0.0001')
ZERO_QUANTITY = Decimal('0.0000')


class StockQualityStatus(models.TextChoices):
    QUARANTINE = 'quarantine', 'Quarentena'
    APPROVED = 'approved', 'Aprovado'
    REJECTED = 'rejected', 'Reprovado'
    BLOCKED = 'blocked', 'Bloqueado'
    RESERVED = 'reserved', 'Reservado'
    UNDER_ANALYSIS = 'under_analysis', 'Em análise'
    RETURNED = 'returned', 'Devolvido'
    SEGREGATED = 'segregated', 'Segregado'
    EXPIRED = 'expired', 'Vencido'


def _sequence_code(model, *args):
    if len(args) == 3:
        _legacy_scope, field_name, prefix = args
    else:
        field_name, prefix = args
    return sequence_code(model, field_name, prefix)


class StockLot(SingleInstanceModel):
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='stock_lots', verbose_name='produto'
    )
    lot_number = models.CharField('lote', max_length=80)
    sublot_number = models.CharField('sublote', max_length=80, blank=True)
    quality_status = models.CharField(
        'status de qualidade',
        max_length=24,
        choices=StockQualityStatus.choices,
        default=StockQualityStatus.QUARANTINE,
    )
    supplier = models.ForeignKey(
        BusinessPartner,
        on_delete=models.PROTECT,
        related_name='supplied_stock_lots',
        null=True,
        blank=True,
        verbose_name='fornecedor',
    )
    source_purchase_receipt_item = models.ForeignKey(
        'procurement.PurchaseReceiptItem',
        on_delete=models.PROTECT,
        related_name='stock_lots',
        null=True,
        blank=True,
        verbose_name='item de recebimento',
    )
    source_production_order = models.ForeignKey(
        'production.ProductionOrder',
        on_delete=models.PROTECT,
        related_name='stock_lots',
        null=True,
        blank=True,
        verbose_name='ordem de produção',
    )
    manufacturing_date = models.DateField('data de fabricação', null=True, blank=True)
    expiry_date = models.DateField('validade', null=True, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['product__code', 'lot_number', 'sublot_number']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'lot_number', 'sublot_number'],
                name='unique_product_lot_sublot',
            ),
        ]
        indexes = [
            models.Index(fields=['product']),
            models.Index(fields=['quality_status']),
            models.Index(fields=['lot_number']),
            models.Index(fields=['expiry_date']),
        ]
        verbose_name = 'lote de estoque'
        verbose_name_plural = 'lotes de estoque'

    @property
    def is_expired(self):
        return bool(self.expiry_date and self.expiry_date < timezone.localdate())

    def input_lots(self):
        return StockLot.objects.filter(output_genealogy_links__output_lot=self)

    def output_lots(self):
        return StockLot.objects.filter(input_genealogy_links__input_lot=self)

    def clean(self):
        super().clean()
        errors = {}
        if (
            self.expiry_date
            and self.manufacturing_date
            and self.expiry_date < self.manufacturing_date
        ):
            errors['expiry_date'] = 'A validade não pode ser anterior à fabricação.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.product.code} - {self.lot_number}'


class StockBalance(SingleInstanceModel):
    IDENTITY_FIELDS = ('product', 'lot', 'warehouse', 'location', 'unit')

    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='stock_balances', verbose_name='produto'
    )
    lot = models.ForeignKey(
        StockLot, on_delete=models.PROTECT, related_name='balances', verbose_name='lote'
    )
    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name='stock_balances',
        verbose_name='almoxarifado',
    )
    location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name='stock_balances',
        verbose_name='localização',
    )
    quality_status = models.CharField(
        'status de qualidade', max_length=24, choices=StockQualityStatus.choices
    )
    quantity = models.DecimalField(
        'quantidade', max_digits=14, decimal_places=4, default=ZERO_QUANTITY
    )
    reserved_quantity = models.DecimalField(
        'quantidade reservada', max_digits=14, decimal_places=4, default=ZERO_QUANTITY
    )
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='stock_balances',
        verbose_name='unidade',
    )

    class Meta:
        ordering = ['warehouse__name', 'location__code', 'product__code', 'lot__lot_number']
        constraints = [
            models.UniqueConstraint(
                fields=['product', 'lot', 'warehouse', 'location', 'quality_status'],
                name='unique_stock_balance_address_status',
            ),
        ]
        indexes = [
            models.Index(fields=['product', 'quality_status']),
            models.Index(fields=['warehouse', 'location']),
            models.Index(fields=['lot']),
        ]
        verbose_name = 'saldo de estoque'
        verbose_name_plural = 'saldos de estoque'

    @property
    def available_quantity(self):
        return max(self.quantity - self.reserved_quantity, ZERO_QUANTITY).quantize(QUANTITY_SCALE)

    @property
    def can_issue(self):
        if self.quality_status != StockQualityStatus.APPROVED:
            return False
        if self.lot.is_expired:
            return False
        return self.available_quantity > 0

    def _immutable_identity_errors(self):
        if self.pk is None:
            return {}
        persisted = (
            type(self)
            .objects.filter(pk=self.pk)
            .values(*(f'{field_name}_id' for field_name in self.IDENTITY_FIELDS))
            .first()
        )
        if persisted is None:
            return {}
        return {
            field_name: 'A dimensão de identidade do saldo não pode ser alterada após a criação.'
            for field_name in self.IDENTITY_FIELDS
            if persisted[f'{field_name}_id'] != getattr(self, f'{field_name}_id')
        }

    def save(self, *args, **kwargs):
        identity_errors = self._immutable_identity_errors()
        if identity_errors:
            raise ValidationError(identity_errors)
        return super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = self._immutable_identity_errors()
        if self.lot and self.product and self.lot.product_id != self.product_id:
            errors['lot'] = 'O lote deve pertencer ao mesmo produto do saldo.'
        if self.location and self.warehouse and self.location.warehouse_id != self.warehouse_id:
            errors['location'] = 'A localização deve pertencer ao almoxarifado informado.'
        if self.quantity < 0:
            errors['quantity'] = 'A quantidade não pode ser negativa.'
        if self.reserved_quantity < 0:
            errors['reserved_quantity'] = 'A quantidade reservada não pode ser negativa.'
        if self.reserved_quantity > self.quantity:
            errors['reserved_quantity'] = 'A quantidade reservada não pode superar o saldo.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.product} - {self.lot} - {self.quantity}'


class StockMovement(SingleInstanceModel):
    AUTOMATIC_IDENTIFIERS = (IdentifierSpec('movement_number', 'MOV'),)

    class MovementType(models.TextChoices):
        RECEIPT = 'receipt', 'Entrada'
        ISSUE = 'issue', 'Saída'
        TRANSFER = 'transfer', 'Transferência'
        ADJUSTMENT = 'adjustment', 'Ajuste'
        INVENTORY_COUNT = 'inventory_count', 'Inventário'
        RESERVATION = 'reservation', 'Reserva'
        RELEASE_RESERVATION = 'release_reservation', 'Liberação de reserva'
        RETURN = 'return', 'Devolução'
        LOSS = 'loss', 'Perda'
        SEGREGATION = 'segregation', 'Segregação'
        DISPOSAL = 'disposal', 'Descarte'
        PRODUCTION_RECEIPT = 'production_receipt', 'Entrada de produção'
        SHIPMENT = 'shipment', 'Expedição'

    movement_number = models.CharField('movimento', max_length=80, blank=True)
    movement_type = models.CharField('tipo', max_length=32, choices=MovementType.choices)
    product = models.ForeignKey(
        Product, on_delete=models.PROTECT, related_name='stock_movements', verbose_name='produto'
    )
    lot = models.ForeignKey(
        StockLot, on_delete=models.PROTECT, related_name='stock_movements', verbose_name='lote'
    )
    quantity = models.DecimalField('quantidade', max_digits=14, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='stock_movements',
        verbose_name='unidade',
    )
    quality_status = models.CharField(
        'status de qualidade', max_length=24, choices=StockQualityStatus.choices
    )
    from_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name='outgoing_stock_movements',
        null=True,
        blank=True,
        verbose_name='almoxarifado origem',
    )
    from_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name='outgoing_stock_movements',
        null=True,
        blank=True,
        verbose_name='localização origem',
    )
    to_warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.PROTECT,
        related_name='incoming_stock_movements',
        null=True,
        blank=True,
        verbose_name='almoxarifado destino',
    )
    to_location = models.ForeignKey(
        StorageLocation,
        on_delete=models.PROTECT,
        related_name='incoming_stock_movements',
        null=True,
        blank=True,
        verbose_name='localização destino',
    )
    movement_date = models.DateTimeField('data do movimento', default=timezone.now)
    source_purchase_receipt_item = models.ForeignKey(
        'procurement.PurchaseReceiptItem',
        on_delete=models.PROTECT,
        related_name='stock_movements',
        null=True,
        blank=True,
        verbose_name='item de recebimento',
    )
    source_production_order = models.ForeignKey(
        'production.ProductionOrder',
        on_delete=models.PROTECT,
        related_name='stock_movements',
        null=True,
        blank=True,
        verbose_name='ordem de produção',
    )
    source_material_consumption = models.ForeignKey(
        'production.MaterialConsumption',
        on_delete=models.PROTECT,
        related_name='stock_movements',
        null=True,
        blank=True,
        verbose_name='consumo de produção',
    )
    related_movement = models.ForeignKey(
        'self',
        on_delete=models.PROTECT,
        related_name='child_movements',
        null=True,
        blank=True,
        verbose_name='movimento relacionado',
    )
    document_reference = models.CharField('documento de referência', max_length=120, blank=True)
    reason = models.TextField('motivo', blank=True)
    adjustment_reason = models.TextField('justificativa do ajuste', blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='stock_movements',
        null=True,
        blank=True,
        verbose_name='criado por',
    )

    class Meta:
        ordering = ['-movement_date', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['movement_number'], name='unique_stock_movement_number'
            ),
        ]
        indexes = [
            models.Index(fields=['movement_type']),
            models.Index(fields=['product', 'movement_date']),
            models.Index(fields=['lot']),
            models.Index(fields=['movement_number']),
        ]
        verbose_name = 'movimento de estoque'
        verbose_name_plural = 'movimentos de estoque'

    def save(self, *args, **kwargs):
        if not self.movement_number:
            self.movement_number = _sequence_code(StockMovement, 'movement_number', 'MOV')
        super().save(*args, **kwargs)

    @classmethod
    def receive_purchase_receipt_item(
        cls,
        receipt_item,
        warehouse,
        location,
        quality_status=StockQualityStatus.QUARANTINE,
        user=None,
    ):
        with transaction.atomic():
            from procurement.models import PurchaseOrderItem, PurchaseReceipt, PurchaseReceiptItem

            receipt_id = PurchaseReceiptItem.objects.values_list('receipt_id', flat=True).get(
                pk=receipt_item.pk
            )
            receipt = PurchaseReceipt.objects.select_for_update().get(pk=receipt_id)
            receipt_item = PurchaseReceiptItem.objects.select_for_update().get(pk=receipt_item.pk)
            if receipt_item.receipt_id != receipt.pk:
                raise ValidationError(
                    {'receipt': 'O recebimento do item mudou; repita a operação.'}
                )
            order_item = PurchaseOrderItem.objects.select_for_update(no_key=True).get(
                pk=receipt_item.order_item_id
            )
            receipt_item.receipt = receipt
            receipt_item.order_item = order_item
            warehouse, location = cls._lock_purchase_address(warehouse, location)
            if receipt_item.accepted_quantity <= 0:
                raise ValidationError({'quantity': 'A quantidade aceita deve ser maior que zero.'})
            receipt._validate_stock_entry_status(quality_status)
            existing = list(
                cls.objects.filter(
                    source_purchase_receipt_item=receipt_item,
                    movement_type=cls.MovementType.RECEIPT,
                )
            )
            if existing:
                if len(existing) != 1:
                    raise ValidationError({'movement': 'Lançamento histórico duplicado.'})
                existing[0]._confirm_purchase_receipt_retry(
                    receipt_item, warehouse, location, quality_status
                )
                return existing[0]
            if (
                receipt.status == PurchaseReceipt.Status.STOCK_POSTED
                or receipt.stock_entry_status == PurchaseReceipt.StockEntryStatus.POSTED
            ):
                raise ValidationError({'movement': 'Lançamento histórico ausente.'})
            receipt._validate_first_stock_entry([receipt_item], quality_status)
            product = receipt_item.product
            unit = receipt_item.unit
            lot = cls._purchase_receipt_lot(receipt_item, quality_status)
            cls._increase_balance(
                product,
                lot,
                warehouse,
                location,
                quality_status,
                receipt_item.accepted_quantity,
                unit,
            )
            movement = cls.objects.create(
                movement_type=cls.MovementType.RECEIPT,
                product=product,
                lot=lot,
                quantity=receipt_item.accepted_quantity,
                unit=unit,
                quality_status=quality_status,
                to_warehouse=warehouse,
                to_location=location,
                source_purchase_receipt_item=receipt_item,
                created_by=user,
                document_reference=receipt_item.receipt.fiscal_document_number,
                reason='Recebimento de compra',
            )
            return movement

    def _confirm_purchase_receipt_retry(self, receipt_item, warehouse, location, quality_status):
        # The lot's current disposition/balance may have changed legitimately.
        # Check receipt economics and source metadata without recreating stock.
        # Older NF-e purchase entry omitted the lot's manufacturing date even
        # when the imported item supplied it. Existing NF-e/source links scope
        # this compatibility exception, but cannot prove when/why a date became
        # NULL (including later erasure). Missing metadata is not confirmed
        # equality; never backfill it during a retry. Known dates remain strict.
        missing_nfe_manufacturing_date = (
            self.lot.manufacturing_date is None
            and bool(receipt_item.receipt.nfe_access_key)
            and bool(receipt_item.receipt.nfe_xml_sha256)
            and receipt_item.receipt.nfe_xml_file_id is not None
            and self.lot.source_purchase_receipt_item_id == receipt_item.pk
            and self.lot.source_production_order_id is None
            and self.lot.sublot_number == ''
        )
        if (
            self.product_id != receipt_item.product_id
            or self.unit_id != receipt_item.unit_id
            or self.quantity != receipt_item.accepted_quantity
            or self.lot.product_id != receipt_item.product_id
            or self.lot.lot_number != receipt_item.lot_number
            or self.lot.supplier_id != receipt_item.receipt.order.supplier_id
            or self.lot.expiry_date != receipt_item.expiry_date
            or (
                self.lot.manufacturing_date != receipt_item.manufacturing_date
                and not missing_nfe_manufacturing_date
            )
            or self.document_reference != receipt_item.receipt.fiscal_document_number
            or self.to_warehouse_id != warehouse.pk
            or self.to_location_id != location.pk
            or self.quality_status != quality_status
            or receipt_item.order_item.order_id != receipt_item.receipt.order_id
            or receipt_item.order_item.product_id != receipt_item.product_id
            or receipt_item.order_item.unit_id != receipt_item.unit_id
            or receipt_item.product.unit_id != receipt_item.unit_id
            or receipt_item.rejected_quantity < ZERO_QUANTITY
            or receipt_item.accepted_quantity + receipt_item.rejected_quantity
            != receipt_item.received_quantity
        ):
            raise ValidationError(
                {'movement': 'O lançamento existente difere do recebimento ou destino.'}
            )

    @classmethod
    def _purchase_receipt_lot(cls, receipt_item, quality_status):
        product = receipt_item.product
        lot, _created = StockLot.objects.select_for_update(no_key=True).get_or_create(
            product=product,
            lot_number=receipt_item.lot_number,
            sublot_number='',
            defaults={
                'quality_status': quality_status,
                'supplier': receipt_item.receipt.order.supplier,
                'source_purchase_receipt_item': receipt_item,
                'manufacturing_date': receipt_item.manufacturing_date,
                'expiry_date': receipt_item.expiry_date,
            },
        )
        if lot.quality_status != quality_status:
            raise ValidationError(
                {
                    'quality_status': (
                        'O status do recebimento deve corresponder à disposição atual do lote.'
                    )
                }
            )
        if lot.source_production_order_id or (
            lot.supplier_id is not None
            and (
                lot.supplier_id != receipt_item.receipt.order.supplier_id
                or lot.expiry_date != receipt_item.expiry_date
                or lot.manufacturing_date != receipt_item.manufacturing_date
            )
        ):
            raise ValidationError(
                {'lot': 'Lote existente com fornecedor, origem ou validade incompatível.'}
            )
        if lot.supplier_id is None:
            lot.supplier = receipt_item.receipt.order.supplier
            lot.source_purchase_receipt_item = receipt_item
            lot.expiry_date = receipt_item.expiry_date
            lot.manufacturing_date = receipt_item.manufacturing_date
            lot.save(
                update_fields=[
                    'supplier',
                    'source_purchase_receipt_item',
                    'manufacturing_date',
                    'expiry_date',
                    'updated_at',
                ]
            )
        return lot

    @classmethod
    def issue_stock(
        cls,
        product,
        lot,
        warehouse,
        location,
        quantity,
        unit,
        reason,
        quality_status=StockQualityStatus.APPROVED,
        *,
        stock_balance_id=None,
    ):
        cls._validate_address(warehouse, location)
        with transaction.atomic():
            if stock_balance_id is None:
                balance = cls._get_balance_for_update(
                    product, lot, warehouse, location, quality_status
                )
            else:
                try:
                    balance = StockBalance.objects.select_for_update().get(pk=stock_balance_id)
                except StockBalance.DoesNotExist as error:
                    raise ValidationError(
                        {'stock_balance': 'Saldo selecionado não encontrado.'}
                    ) from error
                expected = (product.pk, lot.pk, warehouse.pk, location.pk, quality_status)
                actual = (
                    balance.product_id,
                    balance.lot_id,
                    balance.warehouse_id,
                    balance.location_id,
                    balance.quality_status,
                )
                if actual != expected:
                    raise ValidationError(
                        {
                            'stock_balance': 'O saldo selecionado deve manter as dimensões e estar aprovado.'
                        }
                    )
                cls._validate_address(balance.warehouse, balance.location)
            cls._validate_balance_unit(balance, unit)
            cls._validate_issue(balance, quantity)
            balance.quantity = (balance.quantity - quantity).quantize(QUANTITY_SCALE)
            balance.full_clean()
            balance.save(update_fields=['quantity', 'updated_at'])
            return cls.objects.create(
                movement_type=cls.MovementType.ISSUE,
                product=product,
                lot=lot,
                quantity=quantity,
                unit=unit,
                quality_status=quality_status,
                from_warehouse=warehouse,
                from_location=location,
                reason=reason,
            )

    @classmethod
    def transfer_stock(
        cls,
        product,
        lot,
        from_warehouse,
        from_location,
        to_warehouse,
        to_location,
        quantity,
        unit,
        quality_status,
        reason,
    ):
        cls._validate_address(from_warehouse, from_location)
        cls._validate_address(to_warehouse, to_location)
        with transaction.atomic():
            source_balance = cls._get_balance_for_update(
                product, lot, from_warehouse, from_location, quality_status
            )
            cls._validate_issue(source_balance, quantity)
            source_balance.quantity = (source_balance.quantity - quantity).quantize(QUANTITY_SCALE)
            source_balance.full_clean()
            source_balance.save(update_fields=['quantity', 'updated_at'])
            cls._increase_balance(
                product, lot, to_warehouse, to_location, quality_status, quantity, unit
            )
            return cls.objects.create(
                movement_type=cls.MovementType.TRANSFER,
                product=product,
                lot=lot,
                quantity=quantity,
                unit=unit,
                quality_status=quality_status,
                from_warehouse=from_warehouse,
                from_location=from_location,
                to_warehouse=to_warehouse,
                to_location=to_location,
                reason=reason,
            )

    @classmethod
    def adjust_stock(
        cls,
        product,
        lot,
        warehouse,
        location,
        quantity_delta,
        unit,
        reason,
        user,
        quality_status=StockQualityStatus.APPROVED,
    ):
        if not reason:
            raise ValidationError({'adjustment_reason': 'Ajustes de estoque exigem justificativa.'})
        if user is not None and not (user.is_staff or user.has_perm('inventory.add_stockmovement')):
            raise ValidationError(
                {'created_by': 'Usuário sem permissão específica para ajuste de estoque.'}
            )
        if quantity_delta == 0:
            raise ValidationError({'quantity': 'O ajuste deve alterar o saldo.'})
        cls._validate_address(warehouse, location)
        with transaction.atomic():
            if quantity_delta > 0:
                cls._increase_balance(
                    product, lot, warehouse, location, quality_status, quantity_delta, unit
                )
            else:
                balance = cls._get_balance_for_update(
                    product, lot, warehouse, location, quality_status
                )
                cls._validate_issue(balance, abs(quantity_delta), allow_reserved_consumption=True)
                balance.quantity = (balance.quantity + quantity_delta).quantize(QUANTITY_SCALE)
                balance.full_clean()
                balance.save(update_fields=['quantity', 'updated_at'])
            return cls.objects.create(
                movement_type=cls.MovementType.ADJUSTMENT,
                product=product,
                lot=lot,
                quantity=abs(quantity_delta),
                unit=unit,
                quality_status=quality_status,
                to_warehouse=warehouse if quantity_delta > 0 else None,
                to_location=location if quantity_delta > 0 else None,
                from_warehouse=warehouse if quantity_delta < 0 else None,
                from_location=location if quantity_delta < 0 else None,
                reason=reason,
                adjustment_reason=reason,
                created_by=user,
            )

    @classmethod
    def reserve_stock(
        cls,
        product,
        lot,
        warehouse,
        location,
        quantity,
        unit,
        reason,
        quality_status=StockQualityStatus.APPROVED,
    ):
        cls._validate_address(warehouse, location)
        with transaction.atomic():
            balance = cls._get_balance_for_update(product, lot, warehouse, location, quality_status)
            cls._validate_issue(balance, quantity)
            balance.reserved_quantity = (balance.reserved_quantity + quantity).quantize(
                QUANTITY_SCALE
            )
            balance.full_clean()
            balance.save(update_fields=['reserved_quantity', 'updated_at'])
            return cls.objects.create(
                movement_type=cls.MovementType.RESERVATION,
                product=product,
                lot=lot,
                quantity=quantity,
                unit=unit,
                quality_status=quality_status,
                from_warehouse=warehouse,
                from_location=location,
                reason=reason,
            )

    @classmethod
    def issue_reserved_stock(cls, *, consumption, user=None):
        quantity = consumption.actual_quantity.quantize(QUANTITY_SCALE)
        if quantity <= 0:
            raise ValidationError({'actual_quantity': 'Informe o consumo real.'})
        cls._validate_address(consumption.warehouse, consumption.location)
        with transaction.atomic():
            if consumption.issue_movement_id:
                return consumption.issue_movement
            balance = cls._get_balance_for_update(
                consumption.material,
                consumption.stock_lot,
                consumption.warehouse,
                consumption.location,
                StockQualityStatus.APPROVED,
            )
            cls._validate_balance_unit(balance, consumption.unit)
            if balance.reserved_quantity < quantity:
                raise ValidationError({'reserved_quantity': 'A reserva não cobre o consumo real.'})
            cls._validate_issue(balance, quantity, allow_reserved_consumption=True)
            balance.quantity = (balance.quantity - quantity).quantize(QUANTITY_SCALE)
            balance.reserved_quantity = (balance.reserved_quantity - quantity).quantize(
                QUANTITY_SCALE
            )
            balance.full_clean()
            balance.save(update_fields=['quantity', 'reserved_quantity', 'updated_at'])
            return cls.objects.create(
                movement_type=cls.MovementType.ISSUE,
                product=consumption.material,
                lot=consumption.stock_lot,
                quantity=quantity,
                unit=consumption.unit,
                quality_status=StockQualityStatus.APPROVED,
                from_warehouse=consumption.warehouse,
                from_location=consumption.location,
                source_production_order=consumption.order,
                source_material_consumption=consumption,
                document_reference=consumption.order.order_number,
                reason='Baixa de matéria-prima para produção',
                created_by=user,
            )

    @classmethod
    def record_reserved_loss(cls, *, consumption, user=None):
        quantity = consumption.loss_quantity.quantize(QUANTITY_SCALE)
        if quantity <= 0:
            raise ValidationError({'loss_quantity': 'Informe uma perda maior que zero.'})
        cls._validate_address(consumption.warehouse, consumption.location)
        with transaction.atomic():
            if consumption.loss_movement_id:
                return consumption.loss_movement
            balance = cls._get_balance_for_update(
                consumption.material,
                consumption.stock_lot,
                consumption.warehouse,
                consumption.location,
                StockQualityStatus.APPROVED,
            )
            cls._validate_balance_unit(balance, consumption.unit)
            if balance.reserved_quantity < quantity:
                raise ValidationError({'reserved_quantity': 'A reserva não cobre a perda.'})
            cls._validate_issue(balance, quantity, allow_reserved_consumption=True)
            balance.quantity = (balance.quantity - quantity).quantize(QUANTITY_SCALE)
            balance.reserved_quantity = (balance.reserved_quantity - quantity).quantize(
                QUANTITY_SCALE
            )
            balance.full_clean()
            balance.save(update_fields=['quantity', 'reserved_quantity', 'updated_at'])
            return cls.objects.create(
                movement_type=cls.MovementType.LOSS,
                product=consumption.material,
                lot=consumption.stock_lot,
                quantity=quantity,
                unit=consumption.unit,
                quality_status=StockQualityStatus.APPROVED,
                from_warehouse=consumption.warehouse,
                from_location=consumption.location,
                source_production_order=consumption.order,
                source_material_consumption=consumption,
                document_reference=consumption.order.order_number,
                reason='Perda de matéria-prima na produção',
                created_by=user,
            )

    @classmethod
    def release_reserved_stock(cls, *, consumption, user=None):
        quantity = consumption.returned_quantity.quantize(QUANTITY_SCALE)
        if quantity <= 0:
            raise ValidationError({'returned_quantity': 'Informe uma devolução maior que zero.'})
        cls._validate_address(consumption.warehouse, consumption.location)
        with transaction.atomic():
            if consumption.return_movement_id:
                return consumption.return_movement
            balance = cls._get_balance_for_update(
                consumption.material,
                consumption.stock_lot,
                consumption.warehouse,
                consumption.location,
                StockQualityStatus.APPROVED,
            )
            cls._validate_balance_unit(balance, consumption.unit)
            if balance.reserved_quantity < quantity:
                raise ValidationError({'reserved_quantity': 'A reserva não cobre a devolução.'})
            balance.reserved_quantity = (balance.reserved_quantity - quantity).quantize(
                QUANTITY_SCALE
            )
            balance.full_clean()
            balance.save(update_fields=['reserved_quantity', 'updated_at'])
            return cls.objects.create(
                movement_type=cls.MovementType.RELEASE_RESERVATION,
                product=consumption.material,
                lot=consumption.stock_lot,
                quantity=quantity,
                unit=consumption.unit,
                quality_status=StockQualityStatus.APPROVED,
                from_warehouse=consumption.warehouse,
                from_location=consumption.location,
                source_production_order=consumption.order,
                source_material_consumption=consumption,
                document_reference=consumption.order.order_number,
                reason='Devolução de reserva não consumida',
                created_by=user,
            )

    @classmethod
    def receive_production_output(cls, *, output, user=None):
        quantity = output.produced_quantity.quantize(QUANTITY_SCALE)
        if quantity <= 0:
            raise ValidationError({'produced_quantity': 'Informe a quantidade produzida.'})
        if output.product_id != output.order.product_id:
            raise ValidationError({'product': 'O produto deve corresponder à ordem de produção.'})
        if output.unit_id != output.order.unit_id:
            raise ValidationError(
                {'unit': 'A unidade do resultado deve corresponder à unidade da ordem.'}
            )
        cls._validate_address(output.warehouse, output.location)
        with transaction.atomic():
            if output.stock_movement_id:
                return output.stock_movement
            lot = cls._production_output_lot(output)
            cls._increase_balance(
                output.product,
                lot,
                output.warehouse,
                output.location,
                StockQualityStatus.QUARANTINE,
                quantity,
                output.unit,
            )
            return cls.objects.create(
                movement_type=cls.MovementType.PRODUCTION_RECEIPT,
                product=output.product,
                lot=lot,
                quantity=quantity,
                unit=output.unit,
                quality_status=StockQualityStatus.QUARANTINE,
                to_warehouse=output.warehouse,
                to_location=output.location,
                source_production_order=output.order,
                document_reference=output.order.order_number,
                reason='Recebimento de produto acabado em quarentena',
                created_by=user,
            )

    @classmethod
    def _production_output_lot(cls, output):
        lot, _created = StockLot.objects.select_for_update(no_key=True).get_or_create(
            product=output.product,
            lot_number=output.lot_number,
            sublot_number=output.sublot_number,
            defaults={
                'quality_status': StockQualityStatus.QUARANTINE,
                'source_production_order': output.order,
                'manufacturing_date': output.manufacturing_date,
                'expiry_date': output.expiry_date,
            },
        )
        cls._validate_production_output_lot(lot, output)
        lot.full_clean()
        return lot

    @classmethod
    def _lock_receiving_balances(cls, entries):
        """Prelock every batch balance before allocating any movement identifier."""
        from django.db.models import Q

        entries = list(entries)
        if not entries:
            return
        lookup = Q()
        for product, lot, warehouse, location, quality_status, unit in entries:
            lookup |= Q(
                product=product,
                lot=lot,
                warehouse=warehouse,
                location=location,
                quality_status=quality_status,
            )
        list(StockBalance.objects.select_for_update(of=('self',)).filter(lookup).order_by('pk'))
        for product, lot, warehouse, location, quality_status, unit in sorted(
            entries, key=lambda entry: tuple(getattr(value, 'pk', value) for value in entry)
        ):
            balance, _ = StockBalance.objects.select_for_update().get_or_create(
                product=product,
                lot=lot,
                warehouse=warehouse,
                location=location,
                quality_status=quality_status,
                defaults={'unit': unit},
            )
            cls._validate_balance_unit(balance, unit)

    @classmethod
    def _increase_balance(cls, product, lot, warehouse, location, quality_status, quantity, unit):
        balance, _created = StockBalance.objects.select_for_update().get_or_create(
            product=product,
            lot=lot,
            warehouse=warehouse,
            location=location,
            quality_status=quality_status,
            defaults={'quantity': ZERO_QUANTITY, 'reserved_quantity': ZERO_QUANTITY, 'unit': unit},
        )
        cls._validate_balance_unit(balance, unit)
        balance.quantity = (balance.quantity + quantity).quantize(QUANTITY_SCALE)
        balance.unit = unit
        balance.full_clean()
        balance.save(update_fields=['quantity', 'unit', 'updated_at'])
        return balance

    @classmethod
    def _get_balance_for_update(cls, product, lot, warehouse, location, quality_status):
        try:
            return StockBalance.objects.select_for_update().get(
                product=product,
                lot=lot,
                warehouse=warehouse,
                location=location,
                quality_status=quality_status,
            )
        except StockBalance.DoesNotExist as exc:
            raise ValidationError(
                {'quantity': 'Saldo de estoque não encontrado para o endereço, lote e status.'}
            ) from exc

    @classmethod
    def _validate_balance_unit(cls, balance, unit):
        if balance.unit_id != unit.id:
            raise ValidationError(
                {'unit': 'A unidade do movimento deve corresponder à unidade do saldo.'}
            )

    @classmethod
    def _validate_production_output_lot(cls, lot, output):
        if (
            lot.product_id != output.product_id
            or lot.lot_number != output.lot_number
            or lot.sublot_number != output.sublot_number
            or lot.source_production_order_id != output.order_id
            or lot.quality_status != StockQualityStatus.QUARANTINE
            or lot.manufacturing_date != output.manufacturing_date
            or lot.expiry_date != output.expiry_date
        ):
            raise ValidationError(
                {
                    'stock_lot': (
                        'O lote existente deve corresponder ao produto, lote, sublote, ordem, '
                        'datas e permanecer em quarentena.'
                    )
                }
            )

    @classmethod
    def _validate_issue(cls, balance, quantity, allow_reserved_consumption=False):
        if quantity <= 0:
            raise ValidationError({'quantity': 'A quantidade deve ser maior que zero.'})
        if balance.lot.is_expired:
            raise ValidationError({'lot': 'Lote vencido não pode ser movimentado para saída.'})
        if balance.quality_status != StockQualityStatus.APPROVED:
            raise ValidationError({'quality_status': 'Saída exige saldo aprovado.'})
        available = balance.quantity if allow_reserved_consumption else balance.available_quantity
        if available < quantity:
            raise ValidationError({'quantity': 'Quantidade indisponível para movimentação.'})

    @classmethod
    def _lock_purchase_address(cls, warehouse, location):
        """Purchase-only lock order: order items -> warehouse -> location -> site.

        Keep these locks until the outer transaction commits, before any lot,
        balance or sequence lock. Never trust objects cached by form/serializer.
        """
        from masters.models import Site

        if warehouse is None or location is None:
            raise ValidationError({'location': 'Informe almoxarifado e localização.'})
        try:
            warehouse = Warehouse.objects.select_for_update(no_key=True).get(pk=warehouse.pk)
            location = StorageLocation.objects.select_for_update(no_key=True).get(pk=location.pk)
            warehouse.site = Site.objects.select_for_update(no_key=True).get(pk=warehouse.site_id)
        except (Warehouse.DoesNotExist, StorageLocation.DoesNotExist, Site.DoesNotExist) as error:
            raise ValidationError({'location': 'Destino não encontrado.'}) from error
        cls._validate_address(warehouse, location)
        return warehouse, location

    @classmethod
    def _validate_address(cls, warehouse, location):
        if warehouse is None or location is None:
            raise ValidationError({'location': 'Informe almoxarifado e localização.'})
        if not warehouse.is_active or not location.is_active or not warehouse.site.is_active:
            raise ValidationError({'location': 'O destino deve estar ativo.'})
        if location.warehouse_id != warehouse.id:
            raise ValidationError(
                {'location': 'A localização deve pertencer ao almoxarifado informado.'}
            )

    def clean(self):
        super().clean()
        errors = {}
        for field_name in (
            'product',
            'lot',
            'unit',
            'from_warehouse',
            'from_location',
            'to_warehouse',
            'to_location',
            'source_purchase_receipt_item',
            'source_production_order',
            'source_material_consumption',
            'related_movement',
        ):
            pass
        if self.lot and self.product and self.lot.product_id != self.product_id:
            errors['lot'] = 'O lote deve pertencer ao mesmo produto do movimento.'
        if (
            self.from_location
            and self.from_warehouse
            and self.from_location.warehouse_id != self.from_warehouse_id
        ):
            errors['from_location'] = 'A localização origem deve pertencer ao almoxarifado origem.'
        if (
            self.to_location
            and self.to_warehouse
            and self.to_location.warehouse_id != self.to_warehouse_id
        ):
            errors['to_location'] = 'A localização destino deve pertencer ao almoxarifado destino.'
        if self.quantity <= 0:
            errors['quantity'] = 'A quantidade deve ser maior que zero.'
        if self.movement_type == self.MovementType.ADJUSTMENT and not self.adjustment_reason:
            errors['adjustment_reason'] = 'Ajustes de estoque exigem justificativa.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return self.movement_number


class StockLotGenealogy(SingleInstanceModel):
    class RelationType(models.TextChoices):
        CONSUMED_IN_PRODUCTION = 'consumed_in_production', 'Consumido na produção'
        GENERATED_FROM_PRODUCTION = 'generated_from_production', 'Gerado na produção'
        REWORK = 'rework', 'Retrabalho'
        RETURN = 'return', 'Devolução'

    input_lot = models.ForeignKey(
        StockLot,
        on_delete=models.PROTECT,
        related_name='output_genealogy_links',
        verbose_name='lote de entrada',
    )
    output_lot = models.ForeignKey(
        StockLot,
        on_delete=models.PROTECT,
        related_name='input_genealogy_links',
        verbose_name='lote de saída',
    )
    relation_type = models.CharField('tipo de relação', max_length=32, choices=RelationType.choices)
    quantity = models.DecimalField('quantidade', max_digits=14, decimal_places=4)
    unit = models.ForeignKey(
        UnitOfMeasure,
        on_delete=models.PROTECT,
        related_name='stock_genealogy_links',
        verbose_name='unidade',
    )
    production_order = models.ForeignKey(
        'production.ProductionOrder',
        on_delete=models.PROTECT,
        related_name='stock_genealogy_links',
        null=True,
        blank=True,
        verbose_name='ordem de produção',
    )
    document_reference = models.CharField('documento de referência', max_length=120, blank=True)
    notes = models.TextField('observações', blank=True)

    class Meta:
        ordering = ['output_lot__lot_number', 'input_lot__lot_number']
        constraints = [
            models.UniqueConstraint(
                fields=['input_lot', 'output_lot', 'production_order', 'relation_type'],
                name='unique_production_lot_genealogy',
                nulls_distinct=False,
            ),
        ]
        indexes = [
            models.Index(fields=['input_lot']),
            models.Index(fields=['output_lot']),
            models.Index(fields=['relation_type']),
        ]
        verbose_name = 'genealogia de lote'
        verbose_name_plural = 'genealogias de lote'

    def clean(self):
        super().clean()
        errors = {}
        for field_name in ('input_lot', 'output_lot', 'unit', 'production_order'):
            pass
        if self.input_lot_id == self.output_lot_id:
            errors['output_lot'] = 'O lote de saída deve ser diferente do lote de entrada.'
        if self.quantity <= 0:
            errors['quantity'] = 'A quantidade deve ser maior que zero.'
        if errors:
            raise ValidationError(errors)

        return None

    def __str__(self):
        return f'{self.input_lot} -> {self.output_lot}'
