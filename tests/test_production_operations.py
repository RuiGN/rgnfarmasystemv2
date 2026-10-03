from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from decimal import Decimal
from inspect import Parameter, signature
from threading import Barrier, Event
from unittest.mock import patch

import pytest
from django.contrib.auth.models import AnonymousUser, Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, close_old_connections, connection, transaction
from django.db.models import F
from django.db.models.signals import post_save
from django.urls import reverse
from django.test import RequestFactory
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from formulations.models import FormulaComponent, ManufacturingRoute, MasterFormula, RouteStep
from costing.models import MonthlyCostClosing, ProductionCostCapture, StandardCost
from inventory.models import StockBalance, StockLot, StockMovement, StockQualityStatus
from masters.models import Product, Site, StorageLocation, UnitOfMeasure, Warehouse
from production.models import (
    MaterialConsumption,
    ProductionLaborEntry,
    ProductionOperationExecution,
    ProductionOrder,
    ProductionOutput,
)


requires_postgresql = pytest.mark.skipif(
    connection.vendor != 'postgresql',
    reason='Requer locks ou constraints do PostgreSQL.',
)


@pytest.fixture
def production_order():
    today = timezone.localdate()
    unit = UnitOfMeasure.objects.create(code='KG-OP', name='Quilograma', symbol='kg')
    product = Product.objects.create(
        code='PA-OP',
        description='Comprimido operacional',
        item_type=Product.ItemType.FINISHED_PRODUCT,
        unit=unit,
        status=Product.Status.APPROVED,
    )
    material = Product.objects.create(
        code='MP-OP',
        description='Excipiente operacional',
        item_type=Product.ItemType.EXCIPIENT,
        unit=unit,
        status=Product.Status.APPROVED,
    )
    formula = MasterFormula.objects.create(
        product=product,
        code='F-PA-OP',
        version=1,
        status=MasterFormula.Status.APPROVED,
        batch_size=Decimal('100.0000'),
        batch_unit=unit,
        effective_from=today,
    )
    FormulaComponent.objects.create(
        formula=formula,
        line_number=10,
        material=material,
        quantity=Decimal('10.0000'),
        unit=unit,
    )
    route = ManufacturingRoute.objects.create(
        product=product,
        formula=formula,
        code='R-PA-OP',
        version=1,
        status=ManufacturingRoute.Status.APPROVED,
        effective_from=today,
    )
    RouteStep.objects.create(
        route=route,
        sequence=10,
        operation='Pesagem',
        work_center='Sala de pesagem',
        standard_time_minutes=Decimal('30.00'),
    )
    return ProductionOrder.objects.create(
        order_number='OP-OPERACIONAL',
        product=product,
        formula=formula,
        route=route,
        planned_quantity=Decimal('100.0000'),
        unit=unit,
    )


@pytest.fixture
def stock_lot(production_order):
    material = production_order.formula.components.get().material
    return StockLot.objects.create(product=material, lot_number='LOT-MP-OP')


@pytest.fixture
def stock_address():
    site = Site.objects.create(code='PLANTA-OP', name='Planta operacional')
    warehouse = Warehouse.objects.create(
        site=site,
        code='ALMOX-OP',
        name='Almoxarifado operacional',
        warehouse_type=Warehouse.WarehouseType.GENERAL,
    )
    location = StorageLocation.objects.create(
        warehouse=warehouse,
        code='LOC-OP',
        name='Localização operacional',
    )
    return warehouse, location


@pytest.fixture
def allocated_consumption(production_order, stock_lot, stock_address):
    warehouse, location = stock_address
    return MaterialConsumption.objects.create(
        order=production_order,
        component=production_order.formula.components.get(),
        material=stock_lot.product,
        planned_quantity=Decimal('10.0000'),
        reserved_quantity=Decimal('1.0000'),
        issued_quantity=Decimal('1.0000'),
        loss_quantity=Decimal('1.0000'),
        returned_quantity=Decimal('1.0000'),
        unit=production_order.unit,
        stock_lot=stock_lot,
        warehouse=warehouse,
        location=location,
        lot_number=stock_lot.lot_number,
        quality_status=MaterialConsumption.QualityStatus.APPROVED,
    )


@pytest.fixture
def material_allocation(allocated_consumption):
    allocated_consumption.actual_quantity = Decimal('10.0000')
    allocated_consumption.loss_quantity = Decimal('0.0000')
    allocated_consumption.returned_quantity = Decimal('0.0000')
    allocated_consumption.reserved_quantity = Decimal('10.0000')
    allocated_consumption.issued_quantity = Decimal('0.0000')
    allocated_consumption.save(
        update_fields=[
            'actual_quantity',
            'loss_quantity',
            'returned_quantity',
            'reserved_quantity',
            'issued_quantity',
            'updated_at',
        ]
    )
    StockBalance.objects.create(
        product=allocated_consumption.material,
        lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        quality_status=StockQualityStatus.APPROVED,
        quantity=Decimal('100.0000'),
        reserved_quantity=Decimal('10.0000'),
        unit=allocated_consumption.unit,
    )
    return allocated_consumption


@pytest.fixture
def reconciled_material_allocation(allocated_consumption):
    allocated_consumption.actual_quantity = Decimal('0.0000')
    allocated_consumption.loss_quantity = Decimal('2.0000')
    allocated_consumption.returned_quantity = Decimal('8.0000')
    allocated_consumption.reserved_quantity = Decimal('20.0000')
    allocated_consumption.issued_quantity = Decimal('0.0000')
    allocated_consumption.save(
        update_fields=[
            'actual_quantity',
            'loss_quantity',
            'returned_quantity',
            'reserved_quantity',
            'issued_quantity',
            'updated_at',
        ]
    )
    StockBalance.objects.create(
        product=allocated_consumption.material,
        lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        quality_status=StockQualityStatus.APPROVED,
        quantity=Decimal('100.0000'),
        reserved_quantity=Decimal('20.0000'),
        unit=allocated_consumption.unit,
    )
    return allocated_consumption


@pytest.fixture
def production_output(production_order, stock_address):
    warehouse, location = stock_address
    return ProductionOutput.objects.create(
        order=production_order,
        product=production_order.product,
        lot_number=production_order.batch_number,
        sublot_number='SUB-RECEBIMENTO',
        planned_quantity=production_order.planned_quantity,
        produced_quantity=Decimal('98.0000'),
        unit=production_order.unit,
        warehouse=warehouse,
        location=location,
        manufacturing_date=timezone.localdate(),
        expiry_date=timezone.localdate() + timedelta(days=365),
    )


def create_consumption_movement(
    consumption,
    movement_type,
    *,
    incoming=False,
    quantity=Decimal('1.0000'),
):
    address = (
        {
            'to_warehouse': consumption.warehouse,
            'to_location': consumption.location,
        }
        if incoming
        else {
            'from_warehouse': consumption.warehouse,
            'from_location': consumption.location,
        }
    )
    return StockMovement.objects.create(
        movement_type=movement_type,
        product=consumption.material,
        lot=consumption.stock_lot,
        quantity=quantity,
        unit=consumption.unit,
        quality_status=StockQualityStatus.APPROVED,
        source_production_order=consumption.order,
        source_material_consumption=consumption,
        **address,
    )


@pytest.fixture
def received_output(production_order, stock_address, django_user_model):
    warehouse, location = stock_address
    stock_lot = StockLot.objects.create(
        product=production_order.product,
        lot_number=production_order.batch_number,
        sublot_number='SUB-01',
        source_production_order=production_order,
    )
    stock_movement = StockMovement.objects.create(
        movement_type=StockMovement.MovementType.PRODUCTION_RECEIPT,
        product=production_order.product,
        lot=stock_lot,
        quantity=Decimal('98.0000'),
        unit=production_order.unit,
        quality_status=StockQualityStatus.QUARANTINE,
        to_warehouse=warehouse,
        to_location=location,
        source_production_order=production_order,
    )
    user = django_user_model.objects.create_user(
        username='recebedor',
        email='recebedor@example.com',
    )
    return ProductionOutput(
        order=production_order,
        product=production_order.product,
        lot_number=stock_lot.lot_number,
        sublot_number=stock_lot.sublot_number,
        planned_quantity=production_order.planned_quantity,
        produced_quantity=stock_movement.quantity,
        unit=production_order.unit,
        warehouse=warehouse,
        location=location,
        status=ProductionOutput.Status.RECEIVED,
        stock_lot=stock_lot,
        stock_movement=stock_movement,
        received_by=user,
        received_at=timezone.now(),
    )


@pytest.mark.django_db
def test_production_output_defaults_to_pending_quarantine_receipt(production_order):
    output = ProductionOutput(
        order=production_order,
        product=production_order.product,
        lot_number=production_order.batch_number,
        planned_quantity=production_order.planned_quantity,
        produced_quantity=Decimal('98.0000'),
        unit=production_order.unit,
        manufacturing_date=timezone.localdate(),
        expiry_date=timezone.localdate() + timedelta(days=365),
    )

    output.full_clean()

    assert output.status == ProductionOutput.Status.PENDING
    assert output.stock_lot_id is None
    assert output.stock_movement_id is None


@pytest.mark.django_db
def test_operation_and_labor_reject_inverted_times(production_order, django_user_model):
    operation = ProductionOperationExecution(
        order=production_order,
        sequence=10,
        operation='Pesagem',
        planned_minutes=Decimal('30.00'),
        started_at=timezone.now(),
        ended_at=timezone.now() - timedelta(minutes=1),
    )
    with pytest.raises(ValidationError) as operation_error:
        operation.full_clean()
    assert 'ended_at' in operation_error.value.message_dict

    user = django_user_model.objects.create_user(username='operador', email='operador@example.com')
    labor = ProductionLaborEntry(
        order=production_order,
        user=user,
        role='Operador',
        started_at=timezone.now(),
        ended_at=timezone.now() - timedelta(minutes=1),
        hourly_cost=Decimal('25.0000'),
    )
    with pytest.raises(ValidationError) as labor_error:
        labor.full_clean()
    assert 'ended_at' in labor_error.value.message_dict


@pytest.mark.django_db
def test_material_allocation_requires_matching_stock_lot(production_order, stock_lot):
    consumption = MaterialConsumption(
        order=production_order,
        material=production_order.product,
        planned_quantity=Decimal('1.0000'),
        unit=production_order.unit,
        stock_lot=stock_lot,
    )

    with pytest.raises(ValidationError) as error:
        consumption.full_clean()

    assert 'stock_lot' in error.value.message_dict


@pytest.mark.django_db
def test_production_output_rejects_negative_planned_quantity(production_order):
    output = ProductionOutput(
        order=production_order,
        product=production_order.product,
        lot_number=production_order.batch_number,
        planned_quantity=Decimal('-0.0001'),
        unit=production_order.unit,
    )

    with pytest.raises(ValidationError) as error:
        output.full_clean()

    assert 'planned_quantity' in error.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('model_name', 'field_name'),
    [
        ('consumption', 'planned_quantity'),
        ('consumption', 'actual_quantity'),
        ('consumption', 'loss_quantity'),
        ('consumption', 'returned_quantity'),
        ('consumption', 'reserved_quantity'),
        ('consumption', 'issued_quantity'),
        ('output', 'planned_quantity'),
        ('output', 'produced_quantity'),
        ('operation', 'planned_minutes'),
        ('operation', 'actual_minutes'),
        ('operation', 'machine_hourly_cost'),
        ('labor', 'duration_minutes'),
        ('labor', 'hourly_cost'),
    ],
)
def test_database_rejects_negative_operational_values(
    production_order,
    django_user_model,
    model_name,
    field_name,
):
    now = timezone.now()
    user = django_user_model.objects.create_user(
        username=f'operador-{model_name}-{field_name}',
        email=f'{model_name}-{field_name}@example.com',
    )
    instances = {
        'consumption': MaterialConsumption(
            order=production_order,
            material=production_order.product,
            planned_quantity=Decimal('1.0000'),
            unit=production_order.unit,
        ),
        'output': ProductionOutput(
            order=production_order,
            product=production_order.product,
            lot_number=production_order.batch_number,
            planned_quantity=Decimal('1.0000'),
            unit=production_order.unit,
        ),
        'operation': ProductionOperationExecution(
            order=production_order,
            sequence=10,
            operation='Pesagem',
        ),
        'labor': ProductionLaborEntry(
            order=production_order,
            user=user,
            role='Operador',
            started_at=now,
            ended_at=now,
        ),
    }
    instance = instances[model_name]
    setattr(instance, field_name, Decimal('-0.01'))

    with pytest.raises(IntegrityError), transaction.atomic():
        instance.save()


@pytest.mark.django_db
@pytest.mark.parametrize('model_name', ['operation', 'labor'])
def test_database_rejects_inverted_execution_times(
    production_order,
    django_user_model,
    model_name,
):
    started_at = timezone.now()
    ended_at = started_at - timedelta(minutes=1)
    user = django_user_model.objects.create_user(
        username=f'operador-tempo-{model_name}',
        email=f'operador-tempo-{model_name}@example.com',
    )
    instances = {
        'operation': ProductionOperationExecution(
            order=production_order,
            sequence=10,
            operation='Pesagem',
            started_at=started_at,
            ended_at=ended_at,
        ),
        'labor': ProductionLaborEntry(
            order=production_order,
            user=user,
            role='Operador',
            started_at=started_at,
            ended_at=ended_at,
        ),
    }

    with pytest.raises(IntegrityError), transaction.atomic():
        instances[model_name].save()


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('model_name', 'field_name'),
    [
        ('consumption', 'planned_quantity'),
        ('consumption', 'actual_quantity'),
        ('consumption', 'loss_quantity'),
        ('consumption', 'returned_quantity'),
        ('consumption', 'reserved_quantity'),
        ('consumption', 'issued_quantity'),
        ('output', 'planned_quantity'),
        ('output', 'produced_quantity'),
        ('operation', 'planned_minutes'),
        ('operation', 'actual_minutes'),
        ('operation', 'machine_hourly_cost'),
        ('labor', 'duration_minutes'),
        ('labor', 'hourly_cost'),
    ],
)
def test_incomplete_operational_values_raise_field_validation_errors(
    production_order,
    django_user_model,
    model_name,
    field_name,
):
    now = timezone.now()
    user = django_user_model.objects.create_user(
        username=f'incompleto-{model_name}-{field_name}',
        email=f'incompleto-{model_name}-{field_name}@example.com',
    )
    instances = {
        'consumption': MaterialConsumption(
            order=production_order,
            material=production_order.product,
            planned_quantity=Decimal('1.0000'),
            unit=production_order.unit,
        ),
        'output': ProductionOutput(
            order=production_order,
            product=production_order.product,
            lot_number=production_order.batch_number,
            planned_quantity=Decimal('1.0000'),
            unit=production_order.unit,
        ),
        'operation': ProductionOperationExecution(
            order=production_order,
            sequence=10,
            operation='Pesagem',
        ),
        'labor': ProductionLaborEntry(
            order=production_order,
            user=user,
            role='Operador',
            started_at=now,
            ended_at=now,
        ),
    }
    instance = instances[model_name]
    setattr(instance, field_name, None)

    with pytest.raises(ValidationError) as error:
        instance.full_clean()

    assert field_name in error.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('field_name', 'invalid_value'),
    [
        ('sequence', 20),
        ('operation', 'Mistura'),
    ],
)
def test_route_step_requires_matching_execution_identity(
    production_order,
    field_name,
    invalid_value,
):
    route_step = production_order.route.steps.get()
    operation = ProductionOperationExecution(
        order=production_order,
        route_step=route_step,
        sequence=route_step.sequence,
        operation=route_step.operation,
    )
    setattr(operation, field_name, invalid_value)

    with pytest.raises(ValidationError) as error:
        operation.full_clean()

    assert field_name in error.value.message_dict


@pytest.mark.django_db
def test_route_step_allows_execution_work_center_snapshots(production_order):
    route_step = production_order.route.steps.get()
    operation = ProductionOperationExecution(
        order=production_order,
        route_step=route_step,
        sequence=route_step.sequence,
        operation=route_step.operation,
        work_center='Centro efetivamente utilizado',
    )

    operation.full_clean()


@pytest.mark.django_db
def test_material_consumption_accepts_coherent_stock_movements(allocated_consumption):
    allocated_consumption.reservation_movement = create_consumption_movement(
        allocated_consumption,
        StockMovement.MovementType.RESERVATION,
    )
    allocated_consumption.issue_movement = create_consumption_movement(
        allocated_consumption,
        StockMovement.MovementType.ISSUE,
    )
    allocated_consumption.loss_movement = create_consumption_movement(
        allocated_consumption,
        StockMovement.MovementType.LOSS,
    )
    allocated_consumption.return_movement = create_consumption_movement(
        allocated_consumption,
        StockMovement.MovementType.RELEASE_RESERVATION,
    )

    allocated_consumption.full_clean()


@pytest.mark.django_db
def test_material_consumption_allows_transient_counters_without_movements(
    allocated_consumption,
):
    allocated_consumption.full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize(
    'field_name',
    [
        'reservation_movement',
        'issue_movement',
        'loss_movement',
        'return_movement',
    ],
)
def test_material_consumption_rejects_wrong_stock_movement_type(
    allocated_consumption,
    field_name,
):
    movement = create_consumption_movement(
        allocated_consumption,
        StockMovement.MovementType.ADJUSTMENT,
    )
    setattr(allocated_consumption, field_name, movement)

    with pytest.raises(ValidationError) as error:
        allocated_consumption.full_clean()

    assert field_name in error.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('field_name', 'movement_type', 'quantity_field'),
    [
        (
            'reservation_movement',
            StockMovement.MovementType.RESERVATION,
            'reserved_quantity',
        ),
        ('issue_movement', StockMovement.MovementType.ISSUE, 'issued_quantity'),
        ('loss_movement', StockMovement.MovementType.LOSS, 'loss_quantity'),
        (
            'return_movement',
            StockMovement.MovementType.RELEASE_RESERVATION,
            'returned_quantity',
        ),
    ],
)
def test_material_consumption_rejects_movement_with_mismatched_quantity(
    allocated_consumption,
    field_name,
    movement_type,
    quantity_field,
):
    movement = create_consumption_movement(
        allocated_consumption,
        movement_type,
        quantity=getattr(allocated_consumption, quantity_field) + Decimal('0.0001'),
    )
    setattr(allocated_consumption, field_name, movement)

    with pytest.raises(ValidationError) as error:
        allocated_consumption.full_clean()

    assert field_name in error.value.message_dict
    assert 'quantidade' in error.value.message_dict[field_name][0]


@pytest.mark.django_db
@pytest.mark.parametrize(
    'movement_attribute',
    [
        'product_id',
        'unit_id',
        'lot_id',
        'from_warehouse_id',
        'from_location_id',
        'source_production_order_id',
        'source_material_consumption_id',
    ],
)
def test_material_consumption_rejects_movement_with_mismatched_identity(
    allocated_consumption,
    movement_attribute,
):
    movement = create_consumption_movement(
        allocated_consumption,
        StockMovement.MovementType.ISSUE,
    )
    alternate_unit = UnitOfMeasure.objects.create(
        code=f'UN-{movement_attribute[:8]}',
        name='Unidade alternativa',
        symbol='un',
    )
    alternate_lot = StockLot.objects.create(
        product=allocated_consumption.material,
        lot_number=f'ALT-{movement_attribute}',
    )
    alternate_site = Site.objects.create(
        code=f'S-{movement_attribute[:8]}',
        name='Planta alternativa',
    )
    alternate_warehouse = Warehouse.objects.create(
        site=alternate_site,
        code=f'W-{movement_attribute[:8]}',
        name='Almoxarifado alternativo',
        warehouse_type=Warehouse.WarehouseType.GENERAL,
    )
    alternate_location = StorageLocation.objects.create(
        warehouse=alternate_warehouse,
        code=f'L-{movement_attribute[:8]}',
        name='Localização alternativa',
    )
    mismatched_values = {
        'product_id': allocated_consumption.order.product_id,
        'unit_id': alternate_unit.id,
        'lot_id': alternate_lot.id,
        'from_warehouse_id': alternate_warehouse.id,
        'from_location_id': alternate_location.id,
        'source_production_order_id': None,
        'source_material_consumption_id': None,
    }
    StockMovement.objects.filter(pk=movement.pk).update(
        **{movement_attribute: mismatched_values[movement_attribute]}
    )
    movement.refresh_from_db()
    allocated_consumption.issue_movement = movement

    with pytest.raises(ValidationError) as error:
        allocated_consumption.full_clean()

    assert 'issue_movement' in error.value.message_dict


@pytest.mark.django_db
def test_material_reservation_release_requires_origin_address(allocated_consumption):
    movement = create_consumption_movement(
        allocated_consumption,
        StockMovement.MovementType.RELEASE_RESERVATION,
        incoming=True,
    )
    allocated_consumption.return_movement = movement

    with pytest.raises(ValidationError) as error:
        allocated_consumption.full_clean()

    assert 'return_movement' in error.value.message_dict


@pytest.mark.django_db
def test_received_output_accepts_coherent_receipt_evidence(received_output):
    received_output.full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize('evidence_field', ['stock_lot', 'stock_movement'])
def test_received_output_rejects_approved_quality_evidence(
    received_output,
    evidence_field,
):
    evidence = getattr(received_output, evidence_field)
    evidence.quality_status = StockQualityStatus.APPROVED

    with pytest.raises(ValidationError) as error:
        received_output.full_clean()

    assert evidence_field in error.value.message_dict


@pytest.mark.django_db
def test_received_output_rejects_movement_quantity_different_from_produced(
    received_output,
):
    received_output.stock_movement.quantity += Decimal('0.0001')

    with pytest.raises(ValidationError) as error:
        received_output.full_clean()

    assert 'stock_movement' in error.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize(
    'missing_field',
    ['stock_lot', 'stock_movement', 'received_by', 'received_at'],
)
def test_received_output_requires_complete_receipt_evidence(received_output, missing_field):
    setattr(received_output, missing_field, None)

    with pytest.raises(ValidationError) as error:
        received_output.full_clean()

    assert missing_field in error.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize(
    'evidence_field',
    ['stock_lot', 'stock_movement', 'received_by', 'received_at'],
)
def test_pending_output_rejects_partial_receipt_evidence(received_output, evidence_field):
    evidence = getattr(received_output, evidence_field)
    received_output.status = ProductionOutput.Status.PENDING
    received_output.stock_lot = None
    received_output.stock_movement = None
    received_output.received_by = None
    received_output.received_at = None
    setattr(received_output, evidence_field, evidence)

    with pytest.raises(ValidationError) as error:
        received_output.full_clean()

    assert evidence_field in error.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('stock_lot_attribute', 'invalid_value'),
    [
        ('product_id', None),
        ('lot_number', 'LOTE-DIVERGENTE'),
        ('sublot_number', 'SUB-DIVERGENTE'),
        ('source_production_order_id', None),
    ],
)
def test_production_output_rejects_mismatched_stock_lot(
    received_output,
    stock_lot_attribute,
    invalid_value,
):
    if stock_lot_attribute == 'product_id':
        invalid_value = Product.objects.create(
            code='PA-LOTE-DIVERGENTE',
            description='Produto divergente',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=received_output.unit,
            status=Product.Status.APPROVED,
        ).id
    StockLot.objects.filter(pk=received_output.stock_lot_id).update(
        **{stock_lot_attribute: invalid_value}
    )
    received_output.stock_lot.refresh_from_db()

    with pytest.raises(ValidationError) as error:
        received_output.full_clean()

    assert 'stock_lot' in error.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize(
    'movement_attribute',
    [
        'movement_type',
        'product_id',
        'unit_id',
        'lot_id',
        'to_warehouse_id',
        'to_location_id',
        'source_production_order_id',
    ],
)
def test_production_output_rejects_mismatched_stock_movement(
    received_output,
    movement_attribute,
):
    alternate_unit = UnitOfMeasure.objects.create(
        code=f'OUT-{movement_attribute[:7]}',
        name='Unidade alternativa de saída',
        symbol='un',
    )
    alternate_product = Product.objects.create(
        code=f'OUT-P-{movement_attribute[:7]}',
        description='Produto alternativo de saída',
        item_type=Product.ItemType.FINISHED_PRODUCT,
        unit=received_output.unit,
        status=Product.Status.APPROVED,
    )
    alternate_lot = StockLot.objects.create(
        product=received_output.product,
        lot_number=f'OUT-L-{movement_attribute}',
        source_production_order=received_output.order,
    )
    mismatched_values = {
        'movement_type': StockMovement.MovementType.ISSUE,
        'product_id': alternate_product.id,
        'unit_id': alternate_unit.id,
        'lot_id': alternate_lot.id,
        'to_warehouse_id': None,
        'to_location_id': None,
        'source_production_order_id': None,
    }
    StockMovement.objects.filter(pk=received_output.stock_movement_id).update(
        **{movement_attribute: mismatched_values[movement_attribute]}
    )
    received_output.stock_movement.refresh_from_db()

    with pytest.raises(ValidationError) as error:
        received_output.full_clean()

    assert 'stock_movement' in error.value.message_dict


@pytest.mark.django_db
def test_database_rejects_unknown_production_output_status(production_order):
    output = ProductionOutput(
        order=production_order,
        product=production_order.product,
        lot_number=production_order.batch_number,
        planned_quantity=production_order.planned_quantity,
        produced_quantity=Decimal('0.0000'),
        unit=production_order.unit,
        status='unknown',
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        output.save()


@pytest.mark.django_db
def test_reserve_stock_movement_has_only_source_address(material_allocation):
    movement = StockMovement.reserve_stock(
        product=material_allocation.material,
        lot=material_allocation.stock_lot,
        warehouse=material_allocation.warehouse,
        location=material_allocation.location,
        quantity=Decimal('1.0000'),
        unit=material_allocation.unit,
        reason='Reserva para produção',
    )

    assert movement.movement_type == StockMovement.MovementType.RESERVATION
    assert movement.from_warehouse == material_allocation.warehouse
    assert movement.from_location == material_allocation.location
    assert movement.to_warehouse is None
    assert movement.to_location is None


@pytest.mark.django_db
def test_issue_reserved_stock_reduces_balance_and_reservation(material_allocation):
    movement = StockMovement.issue_reserved_stock(
        consumption=material_allocation,
        user=material_allocation.order.responsible,
    )

    balance = StockBalance.objects.get(
        product=material_allocation.material,
        lot=material_allocation.stock_lot,
        warehouse=material_allocation.warehouse,
        location=material_allocation.location,
    )
    assert movement.source_material_consumption == material_allocation
    assert movement.movement_type == StockMovement.MovementType.ISSUE
    assert movement.from_warehouse == material_allocation.warehouse
    assert movement.from_location == material_allocation.location
    assert movement.to_warehouse is None
    assert movement.to_location is None
    assert balance.quantity == Decimal('90.0000')
    assert balance.reserved_quantity == Decimal('0.0000')


@pytest.mark.django_db
def test_loss_consumes_reserved_stock_and_release_only_reduces_reservation(
    reconciled_material_allocation,
):
    loss = StockMovement.record_reserved_loss(
        consumption=reconciled_material_allocation,
        user=reconciled_material_allocation.order.responsible,
    )
    released = StockMovement.release_reserved_stock(
        consumption=reconciled_material_allocation,
        user=reconciled_material_allocation.order.responsible,
    )

    balance = StockBalance.objects.get(
        product=reconciled_material_allocation.material,
        lot=reconciled_material_allocation.stock_lot,
        warehouse=reconciled_material_allocation.warehouse,
        location=reconciled_material_allocation.location,
    )
    assert loss.movement_type == StockMovement.MovementType.LOSS
    assert released.movement_type == StockMovement.MovementType.RELEASE_RESERVATION
    assert loss.from_location == reconciled_material_allocation.location
    assert released.from_location == reconciled_material_allocation.location
    assert loss.to_warehouse is None
    assert loss.to_location is None
    assert released.to_warehouse is None
    assert released.to_location is None
    assert balance.quantity == Decimal('98.0000')
    assert balance.reserved_quantity == Decimal('10.0000')


@pytest.mark.django_db
def test_receive_production_output_creates_quarantine_destination(production_output):
    movement = StockMovement.receive_production_output(
        output=production_output,
        user=production_output.order.responsible,
    )

    balance = StockBalance.objects.get(lot=movement.lot, location=production_output.location)
    assert movement.movement_type == StockMovement.MovementType.PRODUCTION_RECEIPT
    assert movement.source_production_order == production_output.order
    assert movement.quality_status == StockQualityStatus.QUARANTINE
    assert movement.from_warehouse is None
    assert movement.from_location is None
    assert movement.to_warehouse == production_output.warehouse
    assert movement.to_location == production_output.location
    assert movement.lot.quality_status == StockQualityStatus.QUARANTINE
    assert balance.quality_status == StockQualityStatus.QUARANTINE
    assert balance.quantity == production_output.produced_quantity


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('link_field', 'movement_type', 'method_name', 'quantity_field'),
    [
        (
            'issue_movement',
            StockMovement.MovementType.ISSUE,
            'issue_reserved_stock',
            'actual_quantity',
        ),
        (
            'loss_movement',
            StockMovement.MovementType.LOSS,
            'record_reserved_loss',
            'loss_quantity',
        ),
        (
            'return_movement',
            StockMovement.MovementType.RELEASE_RESERVATION,
            'release_reserved_stock',
            'returned_quantity',
        ),
    ],
)
def test_reserved_stock_primitives_return_existing_link_without_mutating_balance(
    material_allocation,
    link_field,
    movement_type,
    method_name,
    quantity_field,
):
    quantity = getattr(material_allocation, quantity_field)
    if quantity == Decimal('0.0000'):
        quantity = Decimal('1.0000')
        setattr(material_allocation, quantity_field, quantity)
    if link_field == 'issue_movement':
        material_allocation.issued_quantity = quantity
    movement = create_consumption_movement(
        material_allocation,
        movement_type,
        quantity=quantity,
    )
    setattr(material_allocation, link_field, movement)
    material_allocation.save()
    balance = StockBalance.objects.get(
        product=material_allocation.material,
        lot=material_allocation.stock_lot,
        warehouse=material_allocation.warehouse,
        location=material_allocation.location,
    )
    initial_quantity = balance.quantity
    initial_reserved = balance.reserved_quantity

    returned = getattr(StockMovement, method_name)(
        consumption=material_allocation,
        user=material_allocation.order.responsible,
    )

    balance.refresh_from_db()
    assert returned == movement
    assert balance.quantity == initial_quantity
    assert balance.reserved_quantity == initial_reserved
    assert (
        StockMovement.objects.filter(
            source_material_consumption=material_allocation,
            movement_type=movement_type,
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_receive_production_output_returns_existing_link_without_new_receipt(received_output):
    returned = StockMovement.receive_production_output(
        output=received_output,
        user=received_output.received_by,
    )

    assert returned == received_output.stock_movement
    assert (
        StockMovement.objects.filter(
            source_production_order=received_output.order,
            movement_type=StockMovement.MovementType.PRODUCTION_RECEIPT,
        ).count()
        == 1
    )
    assert not StockBalance.objects.filter(lot=received_output.stock_lot).exists()


@pytest.mark.django_db
def test_issue_reserved_stock_rejects_missing_balance(allocated_consumption):
    allocated_consumption.actual_quantity = Decimal('1.0000')

    with pytest.raises(ValidationError) as error:
        StockMovement.issue_reserved_stock(consumption=allocated_consumption)

    assert 'quantity' in error.value.message_dict
    assert not StockMovement.objects.filter(
        source_material_consumption=allocated_consumption,
        movement_type=StockMovement.MovementType.ISSUE,
    ).exists()


@pytest.mark.django_db
def test_issue_reserved_stock_rejects_reservation_smaller_than_consumption(
    material_allocation,
):
    balance = StockBalance.objects.get(
        product=material_allocation.material,
        lot=material_allocation.stock_lot,
        warehouse=material_allocation.warehouse,
        location=material_allocation.location,
    )
    balance.reserved_quantity = Decimal('9.9999')
    balance.save(update_fields=['reserved_quantity', 'updated_at'])

    with pytest.raises(ValidationError) as error:
        StockMovement.issue_reserved_stock(consumption=material_allocation)

    assert 'reserved_quantity' in error.value.message_dict
    balance.refresh_from_db()
    assert balance.quantity == Decimal('100.0000')
    assert balance.reserved_quantity == Decimal('9.9999')


@pytest.mark.django_db
def test_receive_production_output_rejects_unit_different_from_order(production_output):
    production_output.unit = UnitOfMeasure.objects.create(
        code='G-OUTPUT',
        name='Grama',
        symbol='g',
    )

    with pytest.raises(ValidationError) as error:
        StockMovement.receive_production_output(output=production_output)

    assert 'unit' in error.value.message_dict
    assert not StockLot.objects.filter(
        product=production_output.product,
        lot_number=production_output.lot_number,
        sublot_number=production_output.sublot_number,
    ).exists()
    assert not StockMovement.objects.filter(
        source_production_order=production_output.order,
        movement_type=StockMovement.MovementType.PRODUCTION_RECEIPT,
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    'quality_status',
    [StockQualityStatus.APPROVED, StockQualityStatus.REJECTED],
)
def test_receive_production_output_rejects_reused_non_quarantine_lot(
    production_output,
    quality_status,
):
    lot = StockLot.objects.create(
        product=production_output.product,
        lot_number=production_output.lot_number,
        sublot_number=production_output.sublot_number,
        quality_status=quality_status,
        source_production_order=production_output.order,
        manufacturing_date=production_output.manufacturing_date,
        expiry_date=production_output.expiry_date,
    )

    with pytest.raises(ValidationError) as error:
        StockMovement.receive_production_output(output=production_output)

    assert 'stock_lot' in error.value.message_dict
    assert not StockBalance.objects.filter(lot=lot).exists()


@pytest.mark.django_db
@pytest.mark.parametrize('incompatibility', ['order', 'manufacturing_date', 'expiry_date'])
def test_receive_production_output_rejects_reused_lot_with_incoherent_origin_or_dates(
    production_output,
    incompatibility,
):
    source_order = production_output.order
    manufacturing_date = production_output.manufacturing_date
    expiry_date = production_output.expiry_date
    if incompatibility == 'order':
        source_order = ProductionOrder.objects.create(
            order_number='OP-OUTRA-ORIGEM',
            product=production_output.order.product,
            formula=production_output.order.formula,
            route=production_output.order.route,
            planned_quantity=production_output.order.planned_quantity,
            unit=production_output.order.unit,
        )
    elif incompatibility == 'manufacturing_date':
        manufacturing_date -= timedelta(days=1)
    else:
        expiry_date += timedelta(days=1)
    lot = StockLot.objects.create(
        product=production_output.product,
        lot_number=production_output.lot_number,
        sublot_number=production_output.sublot_number,
        quality_status=StockQualityStatus.QUARANTINE,
        source_production_order=source_order,
        manufacturing_date=manufacturing_date,
        expiry_date=expiry_date,
    )

    with pytest.raises(ValidationError) as error:
        StockMovement.receive_production_output(output=production_output)

    assert 'stock_lot' in error.value.message_dict
    assert not StockBalance.objects.filter(lot=lot).exists()


@pytest.mark.django_db
def test_issue_reserved_stock_rolls_back_balance_when_movement_creation_fails(
    material_allocation,
    monkeypatch,
):
    def fail_movement_creation(**_kwargs):
        raise RuntimeError('falha simulada ao criar movimento')

    monkeypatch.setattr(StockMovement.objects, 'create', fail_movement_creation)

    with pytest.raises(RuntimeError, match='falha simulada'):
        StockMovement.issue_reserved_stock(consumption=material_allocation)

    balance = StockBalance.objects.get(
        product=material_allocation.material,
        lot=material_allocation.stock_lot,
        warehouse=material_allocation.warehouse,
        location=material_allocation.location,
    )
    assert balance.quantity == Decimal('100.0000')
    assert balance.reserved_quantity == Decimal('10.0000')


@pytest.mark.django_db
def test_receive_production_output_rolls_back_lot_and_balance_when_movement_fails(
    production_output,
    monkeypatch,
):
    def fail_movement_creation(**_kwargs):
        raise RuntimeError('falha simulada ao criar movimento')

    monkeypatch.setattr(StockMovement.objects, 'create', fail_movement_creation)

    with pytest.raises(RuntimeError, match='falha simulada'):
        StockMovement.receive_production_output(output=production_output)

    assert not StockLot.objects.filter(
        product=production_output.product,
        lot_number=production_output.lot_number,
        sublot_number=production_output.sublot_number,
    ).exists()
    assert not StockBalance.objects.filter(
        product=production_output.product,
        warehouse=production_output.warehouse,
        location=production_output.location,
    ).exists()


@pytest.mark.django_db
def test_receive_production_output_rounds_quantity_to_inventory_scale(production_output):
    production_output.produced_quantity = Decimal('1.23456')

    movement = StockMovement.receive_production_output(output=production_output)

    balance = StockBalance.objects.get(lot=movement.lot, location=production_output.location)
    assert movement.quantity == Decimal('1.2346')
    assert balance.quantity == Decimal('1.2346')


def test_labor_entries_define_order_started_at_index():
    assert any(
        index.fields == ['order', 'started_at'] for index in ProductionLaborEntry._meta.indexes
    )


@pytest.fixture
def operations_user(django_user_model):
    return django_user_model.objects.create_user(
        username='operacoes-producao',
        email='operacoes-producao@example.com',
    )


@pytest.fixture
def reservable_order(production_order, allocated_consumption):
    production_order.status = ProductionOrder.Status.APPROVED
    production_order.save(update_fields=['status', 'updated_at'])
    allocated_consumption.reserved_quantity = Decimal('0.0000')
    allocated_consumption.issued_quantity = Decimal('0.0000')
    allocated_consumption.actual_quantity = Decimal('0.0000')
    allocated_consumption.loss_quantity = Decimal('0.0000')
    allocated_consumption.returned_quantity = Decimal('0.0000')
    allocated_consumption.save(
        update_fields=[
            'reserved_quantity',
            'issued_quantity',
            'actual_quantity',
            'loss_quantity',
            'returned_quantity',
            'updated_at',
        ]
    )
    StockBalance.objects.create(
        product=allocated_consumption.material,
        lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        quality_status=StockQualityStatus.APPROVED,
        quantity=Decimal('100.0000'),
        reserved_quantity=Decimal('0.0000'),
        unit=allocated_consumption.unit,
    )
    return production_order


@pytest.mark.django_db(transaction=True)
def test_reserve_materials_is_atomic_and_idempotent(reservable_order, operations_user):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    operations = ProductionOrderOperations(reservable_order, operations_user)

    first = operations.reserve_materials()
    second = operations.reserve_materials()

    assert [movement.pk for movement in first] == [movement.pk for movement in second]
    consumption = reservable_order.material_consumptions.get()
    balance = StockBalance.objects.get(
        product=consumption.material,
        lot=consumption.stock_lot,
        warehouse=consumption.warehouse,
        location=consumption.location,
        quality_status=StockQualityStatus.APPROVED,
    )
    assert consumption.reserved_quantity == Decimal('10.0000')
    assert consumption.reservation_movement_id == first[0].pk
    assert balance.reserved_quantity == Decimal('10.0000')
    assert (
        StockMovement.objects.filter(
            source_material_consumption=consumption,
            movement_type=StockMovement.MovementType.RESERVATION,
        ).count()
        == 1
    )
    assert (
        GovernanceAuditLog.objects.filter(
            action='production.materials.reserved',
            target_record_id=str(reservable_order.pk),
        ).count()
        == 1
    )


@pytest.mark.django_db(transaction=True)
def test_receive_outputs_creates_genealogy_and_keeps_output_in_quarantine(
    production_output,
    allocated_consumption,
    operations_user,
):
    from inventory.models import StockLotGenealogy
    from production.services import ProductionOrderOperations

    order = production_output.order
    allocated_consumption.actual_quantity = Decimal('4.0000')
    allocated_consumption.issued_quantity = Decimal('4.0000')
    allocated_consumption.save(update_fields=['actual_quantity', 'issued_quantity', 'updated_at'])
    allocated_consumption.issue_movement = create_consumption_movement(
        allocated_consumption,
        StockMovement.MovementType.ISSUE,
        quantity=Decimal('4.0000'),
    )
    allocated_consumption.save(update_fields=['issue_movement', 'updated_at'])

    # Prepare all material evidence before making the order terminal.
    order.status = ProductionOrder.Status.COMPLETED
    order.save(update_fields=['status', 'updated_at'])
    outputs = ProductionOrderOperations(order, operations_user).receive_outputs()

    output = outputs[0]
    output.refresh_from_db()
    output.full_clean()
    assert output.status == ProductionOutput.Status.RECEIVED
    assert output.stock_lot.quality_status == StockQualityStatus.QUARANTINE
    assert output.stock_movement.quality_status == StockQualityStatus.QUARANTINE
    genealogy = StockLotGenealogy.objects.get(
        input_lot=allocated_consumption.stock_lot,
        output_lot=output.stock_lot,
        production_order=order,
        relation_type=StockLotGenealogy.RelationType.CONSUMED_IN_PRODUCTION,
    )
    assert genealogy.quantity == Decimal('4.0000')
    assert genealogy.unit == allocated_consumption.unit


@pytest.mark.django_db
def test_reserve_materials_rejects_invalid_status_without_mutation(
    production_order,
    allocated_consumption,
    operations_user,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(production_order, operations_user).reserve_materials()

    assert 'status' in error.value.message_dict
    allocated_consumption.refresh_from_db()
    assert allocated_consumption.reservation_movement_id is None
    assert not StockMovement.objects.filter(
        source_material_consumption=allocated_consumption,
        movement_type=StockMovement.MovementType.RESERVATION,
    ).exists()
    assert not GovernanceAuditLog.objects.filter(
        action='production.materials.reserved',
        target_record_id=str(production_order.pk),
    ).exists()


@pytest.mark.django_db
def test_reserve_materials_prevalidates_allocation_before_mutating_previous_items(
    reservable_order,
    allocated_consumption,
    operations_user,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    MaterialConsumption.objects.create(
        order=reservable_order,
        material=allocated_consumption.material,
        planned_quantity=Decimal('1.0000'),
        unit=allocated_consumption.unit,
        quality_status=MaterialConsumption.QualityStatus.APPROVED,
    )

    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(reservable_order, operations_user).reserve_materials()

    assert 'materials' in error.value.message_dict
    allocated_consumption.refresh_from_db()
    balance = StockBalance.objects.get(
        product=allocated_consumption.material,
        lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        quality_status=StockQualityStatus.APPROVED,
    )
    assert allocated_consumption.reservation_movement_id is None
    assert balance.reserved_quantity == Decimal('0.0000')
    assert not StockMovement.objects.filter(
        movement_type=StockMovement.MovementType.RESERVATION,
        source_production_order=reservable_order,
    ).exists()
    assert not GovernanceAuditLog.objects.filter(
        action='production.materials.reserved',
        target_record_id=str(reservable_order.pk),
    ).exists()


@pytest.mark.django_db
def test_reserve_materials_rejects_insufficient_available_balance_without_mutation(
    reservable_order,
    allocated_consumption,
    operations_user,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    balance = StockBalance.objects.get(
        product=allocated_consumption.material,
        lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        quality_status=StockQualityStatus.APPROVED,
    )
    balance.quantity = Decimal('9.9999')
    balance.save(update_fields=['quantity', 'updated_at'])

    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(reservable_order, operations_user).reserve_materials()

    assert 'quantity' in error.value.message_dict
    balance.refresh_from_db()
    allocated_consumption.refresh_from_db()
    assert balance.reserved_quantity == Decimal('0.0000')
    assert allocated_consumption.reservation_movement_id is None
    assert not GovernanceAuditLog.objects.filter(
        action='production.materials.reserved',
        target_record_id=str(reservable_order.pk),
    ).exists()


@pytest.mark.django_db
def test_reserve_materials_rolls_back_first_item_and_audit_when_later_reservation_fails(
    reservable_order,
    allocated_consumption,
    operations_user,
    monkeypatch,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    second = MaterialConsumption.objects.create(
        order=reservable_order,
        material=allocated_consumption.material,
        planned_quantity=Decimal('10.0000'),
        unit=allocated_consumption.unit,
        stock_lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        lot_number=allocated_consumption.lot_number,
        quality_status=MaterialConsumption.QualityStatus.APPROVED,
    )
    balance = StockBalance.objects.get(
        product=allocated_consumption.material,
        lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        quality_status=StockQualityStatus.APPROVED,
    )
    original = StockMovement.reserve_stock
    calls = 0

    def fail_second_reservation(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('falha simulada na segunda reserva')
        return original(*args, **kwargs)

    monkeypatch.setattr(StockMovement, 'reserve_stock', fail_second_reservation)

    with pytest.raises(RuntimeError, match='segunda reserva'):
        ProductionOrderOperations(reservable_order, operations_user).reserve_materials()

    balance.refresh_from_db()
    allocated_consumption.refresh_from_db()
    second.refresh_from_db()
    assert balance.reserved_quantity == Decimal('0.0000')
    assert allocated_consumption.reservation_movement_id is None
    assert second.reservation_movement_id is None
    assert not StockMovement.objects.filter(
        movement_type=StockMovement.MovementType.RESERVATION,
        source_production_order=reservable_order,
    ).exists()
    assert not GovernanceAuditLog.objects.filter(
        action='production.materials.reserved',
        target_record_id=str(reservable_order.pk),
    ).exists()


@pytest.mark.django_db
def test_reserve_materials_rolls_back_when_audit_fails(
    reservable_order,
    allocated_consumption,
    operations_user,
    monkeypatch,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    def fail_audit(**_kwargs):
        raise RuntimeError('falha simulada na auditoria')

    monkeypatch.setattr(GovernanceAuditLog, 'record', fail_audit)

    with pytest.raises(RuntimeError, match='auditoria'):
        ProductionOrderOperations(reservable_order, operations_user).reserve_materials()

    allocated_consumption.refresh_from_db()
    balance = StockBalance.objects.get(
        product=allocated_consumption.material,
        lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        quality_status=StockQualityStatus.APPROVED,
    )
    assert allocated_consumption.reservation_movement_id is None
    assert balance.reserved_quantity == Decimal('0.0000')
    assert not StockMovement.objects.filter(
        movement_type=StockMovement.MovementType.RESERVATION,
        source_production_order=reservable_order,
    ).exists()


@pytest.mark.django_db
def test_issue_materials_reconciles_reservation_and_is_idempotent(
    reservable_order,
    operations_user,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    operations = ProductionOrderOperations(reservable_order, operations_user)
    operations.reserve_materials()
    reservable_order.status = ProductionOrder.Status.IN_PROGRESS
    reservable_order.save(update_fields=['status', 'updated_at'])
    consumption = reservable_order.material_consumptions.get()
    consumption.actual_quantity = Decimal('6.0000')
    consumption.loss_quantity = Decimal('1.0000')
    consumption.returned_quantity = Decimal('3.0000')
    consumption.quality_status = MaterialConsumption.QualityStatus.APPROVED
    consumption.save(
        update_fields=[
            'actual_quantity',
            'loss_quantity',
            'returned_quantity',
            'quality_status',
            'updated_at',
        ]
    )

    first = operations.issue_materials()
    second = operations.issue_materials()

    assert [movement.pk for movement in first] == [movement.pk for movement in second]
    assert [movement.movement_type for movement in first] == [
        StockMovement.MovementType.ISSUE,
        StockMovement.MovementType.LOSS,
        StockMovement.MovementType.RELEASE_RESERVATION,
    ]
    consumption.refresh_from_db()
    consumption.full_clean()
    balance = StockBalance.objects.get(
        product=consumption.material,
        lot=consumption.stock_lot,
        warehouse=consumption.warehouse,
        location=consumption.location,
        quality_status=StockQualityStatus.APPROVED,
    )
    assert consumption.issued_quantity == Decimal('6.0000')
    assert balance.quantity == Decimal('93.0000')
    assert balance.reserved_quantity == Decimal('0.0000')
    assert (
        GovernanceAuditLog.objects.filter(
            action='production.materials.issued',
            target_record_id=str(reservable_order.pk),
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_issue_materials_rejects_unreconciled_quantities_without_mutation(
    reservable_order,
    operations_user,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    operations = ProductionOrderOperations(reservable_order, operations_user)
    operations.reserve_materials()
    reservable_order.status = ProductionOrder.Status.IN_PROGRESS
    reservable_order.save(update_fields=['status', 'updated_at'])
    consumption = reservable_order.material_consumptions.get()
    consumption.actual_quantity = Decimal('9.0000')
    consumption.quality_status = MaterialConsumption.QualityStatus.APPROVED
    consumption.save(update_fields=['actual_quantity', 'quality_status', 'updated_at'])

    with pytest.raises(ValidationError) as error:
        operations.issue_materials()

    assert 'materials' in error.value.message_dict
    balance = StockBalance.objects.get(
        product=consumption.material,
        lot=consumption.stock_lot,
        warehouse=consumption.warehouse,
        location=consumption.location,
        quality_status=StockQualityStatus.APPROVED,
    )
    consumption.refresh_from_db()
    assert consumption.issue_movement_id is None
    assert consumption.issued_quantity == Decimal('0.0000')
    assert balance.quantity == Decimal('100.0000')
    assert balance.reserved_quantity == Decimal('10.0000')
    assert not GovernanceAuditLog.objects.filter(
        action='production.materials.issued',
        target_record_id=str(reservable_order.pk),
    ).exists()


@pytest.mark.django_db
def test_issue_materials_rolls_back_movements_balances_links_and_audit_on_later_failure(
    reservable_order,
    allocated_consumption,
    operations_user,
    monkeypatch,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    second = MaterialConsumption.objects.create(
        order=reservable_order,
        material=allocated_consumption.material,
        planned_quantity=Decimal('10.0000'),
        unit=allocated_consumption.unit,
        stock_lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        lot_number=allocated_consumption.lot_number,
        quality_status=MaterialConsumption.QualityStatus.APPROVED,
    )
    operations = ProductionOrderOperations(reservable_order, operations_user)
    operations.reserve_materials()
    reservable_order.status = ProductionOrder.Status.IN_PROGRESS
    reservable_order.save(update_fields=['status', 'updated_at'])
    for consumption in reservable_order.material_consumptions.all():
        consumption.actual_quantity = Decimal('10.0000')
        consumption.quality_status = MaterialConsumption.QualityStatus.APPROVED
        consumption.save(update_fields=['actual_quantity', 'quality_status', 'updated_at'])
    original = StockMovement.issue_reserved_stock
    calls = 0

    def fail_second_issue(cls, *, consumption, user=None):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('falha simulada na segunda baixa')
        return original(consumption=consumption, user=user)

    monkeypatch.setattr(
        StockMovement,
        'issue_reserved_stock',
        classmethod(fail_second_issue),
    )

    with pytest.raises(RuntimeError, match='segunda baixa'):
        operations.issue_materials()

    balance = StockBalance.objects.get(
        product=allocated_consumption.material,
        lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        quality_status=StockQualityStatus.APPROVED,
    )
    allocated_consumption.refresh_from_db()
    second.refresh_from_db()
    assert balance.quantity == Decimal('100.0000')
    assert balance.reserved_quantity == Decimal('20.0000')
    assert allocated_consumption.issue_movement_id is None
    assert second.issue_movement_id is None
    assert not StockMovement.objects.filter(
        movement_type=StockMovement.MovementType.ISSUE,
        source_production_order=reservable_order,
    ).exists()
    assert not GovernanceAuditLog.objects.filter(
        action='production.materials.issued',
        target_record_id=str(reservable_order.pk),
    ).exists()


@pytest.mark.django_db
def test_receive_outputs_aggregates_same_input_lot_and_is_idempotent(
    production_output,
    allocated_consumption,
    operations_user,
):
    from governance.models import GovernanceAuditLog
    from inventory.models import StockLotGenealogy
    from production.services import ProductionOrderOperations

    order = production_output.order
    allocated_consumption.actual_quantity = Decimal('4.0000')
    allocated_consumption.issued_quantity = Decimal('4.0000')
    allocated_consumption.save(update_fields=['actual_quantity', 'issued_quantity', 'updated_at'])
    allocated_consumption.issue_movement = create_consumption_movement(
        allocated_consumption,
        StockMovement.MovementType.ISSUE,
        quantity=Decimal('4.0000'),
    )
    allocated_consumption.save(update_fields=['issue_movement', 'updated_at'])
    second = MaterialConsumption.objects.create(
        order=order,
        component=allocated_consumption.component,
        material=allocated_consumption.material,
        planned_quantity=Decimal('3.0000'),
        actual_quantity=Decimal('3.0000'),
        issued_quantity=Decimal('3.0000'),
        unit=allocated_consumption.unit,
        stock_lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        lot_number=allocated_consumption.lot_number,
        quality_status=MaterialConsumption.QualityStatus.APPROVED,
    )
    second.issue_movement = create_consumption_movement(
        second,
        StockMovement.MovementType.ISSUE,
        quantity=Decimal('3.0000'),
    )
    second.save(update_fields=['issue_movement', 'updated_at'])
    # Prepare all material evidence before making the order terminal.
    order.status = ProductionOrder.Status.COMPLETED
    order.save(update_fields=['status', 'updated_at'])
    operations = ProductionOrderOperations(order, operations_user)

    first = operations.receive_outputs()
    second_call = operations.receive_outputs()

    assert [output.pk for output in first] == [output.pk for output in second_call]
    output = first[0]
    output.refresh_from_db()
    output.full_clean()
    genealogy = StockLotGenealogy.objects.get(
        input_lot=allocated_consumption.stock_lot,
        output_lot=output.stock_lot,
        production_order=order,
        relation_type=StockLotGenealogy.RelationType.CONSUMED_IN_PRODUCTION,
    )
    assert genealogy.quantity == Decimal('7.0000')
    assert (
        StockLotGenealogy.objects.filter(
            input_lot=allocated_consumption.stock_lot,
            output_lot=output.stock_lot,
            production_order=order,
            relation_type=StockLotGenealogy.RelationType.CONSUMED_IN_PRODUCTION,
        ).count()
        == 1
    )
    assert (
        StockMovement.objects.filter(
            movement_type=StockMovement.MovementType.PRODUCTION_RECEIPT,
            source_production_order=order,
        ).count()
        == 1
    )
    assert (
        GovernanceAuditLog.objects.filter(
            action='production.outputs.received',
            target_record_id=str(order.pk),
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_receive_outputs_rejects_mixed_units_for_same_input_lot_before_mutation(
    production_output,
    allocated_consumption,
    operations_user,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    order = production_output.order
    allocated_consumption.actual_quantity = Decimal('4.0000')
    allocated_consumption.issued_quantity = Decimal('4.0000')
    allocated_consumption.save(update_fields=['actual_quantity', 'issued_quantity', 'updated_at'])
    allocated_consumption.issue_movement = create_consumption_movement(
        allocated_consumption,
        StockMovement.MovementType.ISSUE,
        quantity=Decimal('4.0000'),
    )
    allocated_consumption.save(update_fields=['issue_movement', 'updated_at'])
    alternate_unit = UnitOfMeasure.objects.create(
        code='G-OPERACOES',
        name='Grama',
        symbol='g',
    )
    second = MaterialConsumption.objects.create(
        order=order,
        component=allocated_consumption.component,
        material=allocated_consumption.material,
        planned_quantity=Decimal('3000.0000'),
        actual_quantity=Decimal('3000.0000'),
        issued_quantity=Decimal('3000.0000'),
        unit=alternate_unit,
        stock_lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        lot_number=allocated_consumption.lot_number,
        quality_status=MaterialConsumption.QualityStatus.APPROVED,
    )
    second.issue_movement = create_consumption_movement(
        second,
        StockMovement.MovementType.ISSUE,
        quantity=Decimal('3000.0000'),
    )
    second.save(update_fields=['issue_movement', 'updated_at'])

    # Prepare all material evidence before making the order terminal.
    order.status = ProductionOrder.Status.COMPLETED
    order.save(update_fields=['status', 'updated_at'])
    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(order, operations_user).receive_outputs()

    assert 'genealogy' in error.value.message_dict
    production_output.refresh_from_db()
    assert production_output.status == ProductionOutput.Status.PENDING
    assert production_output.stock_lot_id is None
    assert production_output.stock_movement_id is None
    assert not StockBalance.objects.filter(product=production_output.product).exists()
    assert not GovernanceAuditLog.objects.filter(
        action='production.outputs.received',
        target_record_id=str(order.pk),
    ).exists()


@pytest.mark.django_db
def test_receive_outputs_propagates_reused_lot_validation_without_partial_state(
    production_output,
    operations_user,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    order = production_output.order
    conflicting_order = ProductionOrder.objects.create(
        order_number='OP-LOTE-CONFLITANTE',
        product=order.product,
        formula=order.formula,
        route=order.route,
        planned_quantity=order.planned_quantity,
        unit=order.unit,
    )
    lot = StockLot.objects.create(
        product=production_output.product,
        lot_number=production_output.lot_number,
        sublot_number=production_output.sublot_number,
        quality_status=StockQualityStatus.QUARANTINE,
        source_production_order=conflicting_order,
        manufacturing_date=production_output.manufacturing_date,
        expiry_date=production_output.expiry_date,
    )
    _issued_formula_consumption(order=order, output=production_output)

    # Prepare all material evidence before making the order terminal.
    order.status = ProductionOrder.Status.COMPLETED
    order.save(update_fields=['status', 'updated_at'])
    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(order, operations_user).receive_outputs()

    assert 'stock_lot' in error.value.message_dict
    production_output.refresh_from_db()
    assert production_output.status == ProductionOutput.Status.PENDING
    assert production_output.stock_lot_id is None
    assert production_output.stock_movement_id is None
    assert not StockBalance.objects.filter(lot=lot).exists()
    assert not StockMovement.objects.filter(
        movement_type=StockMovement.MovementType.PRODUCTION_RECEIPT,
        source_production_order=order,
    ).exists()
    assert not GovernanceAuditLog.objects.filter(
        action='production.outputs.received',
        target_record_id=str(order.pk),
    ).exists()


@pytest.mark.django_db
def test_receive_outputs_rejects_output_unit_different_from_order_without_mutation(
    production_output,
    operations_user,
):
    from production.services import ProductionOrderOperations

    order = production_output.order
    order.status = ProductionOrder.Status.COMPLETED
    order.save(update_fields=['status', 'updated_at'])
    production_output.unit = UnitOfMeasure.objects.create(
        code='CX-OUTPUT',
        name='Caixa',
        symbol='cx',
    )
    production_output.save(update_fields=['unit', 'updated_at'])

    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(order, operations_user).receive_outputs()

    assert 'unit' in error.value.message_dict
    production_output.refresh_from_db()
    assert production_output.status == ProductionOutput.Status.PENDING
    assert not StockMovement.objects.filter(
        movement_type=StockMovement.MovementType.PRODUCTION_RECEIPT,
        source_production_order=order,
    ).exists()


@pytest.mark.django_db
def test_receive_outputs_rolls_back_earlier_output_when_later_output_fails(
    production_output,
    operations_user,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    order = production_output.order
    second = ProductionOutput.objects.create(
        order=order,
        product=order.product,
        lot_number=order.batch_number,
        sublot_number='SUB-INVALIDO',
        planned_quantity=order.planned_quantity,
        produced_quantity=Decimal('2.0000'),
        unit=order.unit,
        warehouse=production_output.warehouse,
        location=production_output.location,
        manufacturing_date=production_output.manufacturing_date,
        expiry_date=production_output.expiry_date,
    )
    conflicting_order = ProductionOrder.objects.create(
        order_number='OP-SEGUNDO-OUTPUT',
        product=order.product,
        formula=order.formula,
        route=order.route,
        planned_quantity=order.planned_quantity,
        unit=order.unit,
    )
    StockLot.objects.create(
        product=second.product,
        lot_number=second.lot_number,
        sublot_number=second.sublot_number,
        quality_status=StockQualityStatus.QUARANTINE,
        source_production_order=conflicting_order,
        manufacturing_date=second.manufacturing_date,
        expiry_date=second.expiry_date,
    )
    _issued_formula_consumption(order=order, output=production_output)

    # Prepare all material evidence before making the order terminal.
    order.status = ProductionOrder.Status.COMPLETED
    order.save(update_fields=['status', 'updated_at'])
    with pytest.raises(ValidationError):
        ProductionOrderOperations(order, operations_user).receive_outputs()

    production_output.refresh_from_db()
    second.refresh_from_db()
    assert production_output.status == ProductionOutput.Status.PENDING
    assert production_output.stock_lot_id is None
    assert production_output.stock_movement_id is None
    assert second.status == ProductionOutput.Status.PENDING
    assert not StockMovement.objects.filter(
        movement_type=StockMovement.MovementType.PRODUCTION_RECEIPT,
        source_production_order=order,
    ).exists()
    assert not StockBalance.objects.filter(product=order.product).exists()
    assert not GovernanceAuditLog.objects.filter(
        action='production.outputs.received',
        target_record_id=str(order.pk),
    ).exists()


@requires_postgresql
@pytest.mark.django_db
def test_stock_lot_genealogy_constraint_prevents_duplicate_production_link(
    production_order,
    stock_lot,
):
    from inventory.models import StockLotGenealogy

    output_lot = StockLot.objects.create(
        product=production_order.product,
        lot_number='LOT-SAIDA-GENEALOGIA',
        source_production_order=production_order,
    )
    relation = {
        'input_lot': stock_lot,
        'output_lot': output_lot,
        'production_order': production_order,
        'relation_type': StockLotGenealogy.RelationType.CONSUMED_IN_PRODUCTION,
        'quantity': Decimal('1.0000'),
        'unit': production_order.unit,
    }
    StockLotGenealogy.objects.create(**relation)

    with pytest.raises(IntegrityError), transaction.atomic():
        StockLotGenealogy.objects.create(**relation)


@pytest.mark.django_db
def test_calculate_cost_uses_effective_approved_standard_labor_and_machine_once(
    production_order,
    allocated_consumption,
    operations_user,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    period_start = timezone.localdate().replace(day=1)
    period_end = timezone.localdate()
    standard = StandardCost.objects.create(
        product=allocated_consumption.material,
        version='OPERACOES-1',
        effective_from=period_start,
        standard_quantity=Decimal('100.0000'),
        unit=allocated_consumption.unit,
        material_cost=Decimal('200.0000'),
    )
    standard.approve(user=operations_user)
    allocated_consumption.actual_quantity = Decimal('6.0000')
    allocated_consumption.loss_quantity = Decimal('1.0000')
    allocated_consumption.save(update_fields=['actual_quantity', 'loss_quantity', 'updated_at'])
    # Prepare all material evidence before making the order terminal.
    production_order.status = ProductionOrder.Status.COMPLETED
    production_order.save(update_fields=['status', 'updated_at'])
    ProductionLaborEntry.objects.create(
        order=production_order,
        user=operations_user,
        role='Operador',
        started_at=timezone.now() - timedelta(hours=2),
        ended_at=timezone.now(),
        duration_minutes=Decimal('120.00'),
        hourly_cost=Decimal('30.0000'),
    )
    operation_end = timezone.now()
    ProductionOperationExecution.objects.create(
        order=production_order,
        sequence=20,
        operation='Compressão',
        status=ProductionOperationExecution.Status.COMPLETED,
        started_at=operation_end - timedelta(minutes=30),
        ended_at=operation_end,
        actual_minutes=Decimal('30.00'),
        machine_hourly_cost=Decimal('40.0000'),
        recorded_by=operations_user,
    )
    operations = ProductionOrderOperations(production_order, operations_user)

    first = operations.calculate_cost(
        period_start=period_start,
        period_end=period_end,
    )
    second = operations.calculate_cost(
        period_start=period_start,
        period_end=period_end,
    )

    assert first.pk == second.pk
    capture = ProductionCostCapture.objects.get(pk=first.pk)
    assert capture.planned_cost == Decimal('20.0000')
    assert capture.actual_material_cost == Decimal('12.0000')
    assert capture.actual_loss_cost == Decimal('2.0000')
    assert capture.actual_labor_cost == Decimal('60.0000')
    assert capture.actual_machine_cost == Decimal('20.0000')
    assert capture.total_actual_cost == Decimal('94.0000')
    assert capture.variance_amount == Decimal('74.0000')
    assert (
        GovernanceAuditLog.objects.filter(
            action='production.cost.calculated',
            target_record_id=str(production_order.pk),
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_calculate_cost_rejects_missing_effective_standard_without_partial_state(
    production_order,
    allocated_consumption,
    operations_user,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    period_start = timezone.localdate().replace(day=1)
    period_end = timezone.localdate()
    obsolete = StandardCost.objects.create(
        product=allocated_consumption.material,
        version='EXPIRADO-1',
        effective_from=period_start - timedelta(days=60),
        effective_to=period_start - timedelta(days=1),
        standard_quantity=Decimal('100.0000'),
        unit=allocated_consumption.unit,
        material_cost=Decimal('200.0000'),
    )
    obsolete.approve(user=operations_user)
    production_order.status = ProductionOrder.Status.COMPLETED
    production_order.save(update_fields=['status', 'updated_at'])

    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(production_order, operations_user).calculate_cost(
            period_start=period_start,
            period_end=period_end,
        )

    assert 'standard_cost' in error.value.message_dict
    assert not ProductionCostCapture.objects.filter(
        production_order=production_order,
        period_start=period_start,
        period_end=period_end,
    ).exists()
    assert not GovernanceAuditLog.objects.filter(
        action='production.cost.calculated',
        target_record_id=str(production_order.pk),
    ).exists()


@pytest.mark.django_db
def test_calculate_cost_rejects_unfinished_order_without_mutation(
    production_order,
    operations_user,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(production_order, operations_user).calculate_cost(
            period_start=timezone.localdate().replace(day=1),
            period_end=timezone.localdate(),
        )

    assert 'status' in error.value.message_dict
    assert not ProductionCostCapture.objects.filter(
        production_order=production_order,
    ).exists()
    assert not GovernanceAuditLog.objects.filter(
        action='production.cost.calculated',
        target_record_id=str(production_order.pk),
    ).exists()


@pytest.mark.django_db
def test_reserve_materials_rejects_bidirectional_linked_movement(
    reservable_order,
    allocated_consumption,
    operations_user,
):
    from production.services import ProductionOrderOperations

    movement = StockMovement.objects.create(
        movement_type=StockMovement.MovementType.RESERVATION,
        product=allocated_consumption.material,
        lot=allocated_consumption.stock_lot,
        quantity=allocated_consumption.planned_quantity,
        unit=allocated_consumption.unit,
        quality_status=StockQualityStatus.APPROVED,
        from_warehouse=allocated_consumption.warehouse,
        from_location=allocated_consumption.location,
        to_warehouse=allocated_consumption.warehouse,
        to_location=allocated_consumption.location,
        source_production_order=reservable_order,
        source_material_consumption=allocated_consumption,
    )
    allocated_consumption.reserved_quantity = allocated_consumption.planned_quantity
    allocated_consumption.reservation_movement = movement
    allocated_consumption.save(
        update_fields=['reserved_quantity', 'reservation_movement', 'updated_at']
    )
    balance = StockBalance.objects.get(
        product=allocated_consumption.material,
        lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        quality_status=StockQualityStatus.APPROVED,
    )
    balance.reserved_quantity = allocated_consumption.planned_quantity
    balance.save(update_fields=['reserved_quantity', 'updated_at'])

    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(reservable_order, operations_user).reserve_materials()

    assert 'movement' in error.value.message_dict


@pytest.mark.django_db
def test_receive_outputs_rejects_bidirectional_receipt_evidence(
    received_output,
    operations_user,
):
    from production.services import ProductionOrderOperations

    received_output.order.status = ProductionOrder.Status.COMPLETED
    received_output.order.save(update_fields=['status', 'updated_at'])
    received_output.stock_movement.from_warehouse = received_output.warehouse
    received_output.stock_movement.from_location = received_output.location
    received_output.stock_movement.save(
        update_fields=['from_warehouse', 'from_location', 'updated_at']
    )
    received_output.save()

    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(
            received_output.order,
            operations_user,
        ).receive_outputs()

    assert 'movement' in error.value.message_dict


def _create_approved_standard(
    *,
    consumption,
    user,
    effective_from,
    version,
    approved_at=None,
):

    standard = StandardCost.objects.create(
        product=consumption.material,
        version=version,
        effective_from=effective_from,
        standard_quantity=Decimal('100.0000'),
        unit=consumption.unit,
        material_cost=Decimal('200.0000'),
    )
    if approved_at is None:
        standard.approve(user=user)
    else:
        with patch('costing.models.timezone.now', return_value=approved_at):
            standard.approve(user=user)
    return standard


def _issued_formula_consumption(*, order, output, component=None, quantity=Decimal('1.0000')):
    component = component or order.formula.components.get()
    lot = StockLot.objects.create(
        product=component.material,
        lot_number=f'LOT-{order.order_number}',
    )
    consumption = MaterialConsumption.objects.create(
        order=order,
        component=component,
        material=component.material,
        planned_quantity=quantity,
        actual_quantity=quantity,
        issued_quantity=quantity,
        unit=component.unit,
        stock_lot=lot,
        warehouse=output.warehouse,
        location=output.location,
        lot_number=lot.lot_number,
        quality_status=MaterialConsumption.QualityStatus.APPROVED,
    )
    consumption.issue_movement = create_consumption_movement(
        consumption,
        StockMovement.MovementType.ISSUE,
        quantity=quantity,
    )
    consumption.save(update_fields=['issue_movement', 'updated_at'])
    return consumption


@pytest.mark.django_db
def test_receive_outputs_rejects_zero_genealogy_before_any_mutation(
    production_output,
    operations_user,
):
    from governance.models import GovernanceAuditLog
    from inventory.models import StockLotGenealogy
    from production.services import ProductionOrderOperations

    order = production_output.order
    order.status = ProductionOrder.Status.COMPLETED
    order.save(update_fields=['status', 'updated_at'])

    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(order, operations_user).receive_outputs()

    assert 'materials' in error.value.message_dict
    production_output.refresh_from_db()
    assert production_output.status == ProductionOutput.Status.PENDING
    assert production_output.stock_lot_id is None
    assert production_output.stock_movement_id is None
    assert not StockMovement.objects.filter(
        movement_type=StockMovement.MovementType.PRODUCTION_RECEIPT,
        source_production_order=order,
    ).exists()
    assert not StockBalance.objects.filter(product=production_output.product).exists()
    assert not StockLotGenealogy.objects.filter(production_order=order).exists()
    assert not GovernanceAuditLog.objects.filter(
        action='production.outputs.received',
        target_record_id=str(order.pk),
    ).exists()


@pytest.mark.django_db
def test_receive_outputs_rejects_expected_component_without_issue(
    production_output,
    operations_user,
):
    from production.services import ProductionOrderOperations

    order = production_output.order
    component = order.formula.components.get()
    lot = StockLot.objects.create(product=component.material, lot_number='LOT-NAO-BAIXADO')
    MaterialConsumption.objects.create(
        order=order,
        component=component,
        material=component.material,
        planned_quantity=Decimal('1.0000'),
        actual_quantity=Decimal('1.0000'),
        unit=component.unit,
        stock_lot=lot,
        warehouse=production_output.warehouse,
        location=production_output.location,
        lot_number=lot.lot_number,
        quality_status=MaterialConsumption.QualityStatus.APPROVED,
    )
    order.status = ProductionOrder.Status.COMPLETED
    order.save(update_fields=['status', 'updated_at'])

    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(order, operations_user).receive_outputs()

    assert 'materials' in error.value.message_dict
    production_output.refresh_from_db()
    assert production_output.status == ProductionOutput.Status.PENDING
    assert production_output.stock_lot_id is None
    assert production_output.stock_movement_id is None


@pytest.mark.django_db
def test_receive_outputs_rejects_issued_consumption_without_expected_component(
    production_output,
    operations_user,
):
    from production.services import ProductionOrderOperations

    order = production_output.order
    component = order.formula.components.get()
    lot = StockLot.objects.create(product=component.material, lot_number='LOT-SEM-COMPONENTE')
    consumption = MaterialConsumption.objects.create(
        order=order,
        material=component.material,
        planned_quantity=Decimal('1.0000'),
        actual_quantity=Decimal('1.0000'),
        issued_quantity=Decimal('1.0000'),
        unit=component.unit,
        stock_lot=lot,
        warehouse=production_output.warehouse,
        location=production_output.location,
        lot_number=lot.lot_number,
        quality_status=MaterialConsumption.QualityStatus.APPROVED,
    )
    consumption.issue_movement = create_consumption_movement(
        consumption,
        StockMovement.MovementType.ISSUE,
    )
    consumption.save(update_fields=['issue_movement', 'updated_at'])
    order.status = ProductionOrder.Status.COMPLETED
    order.save(update_fields=['status', 'updated_at'])

    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(order, operations_user).receive_outputs()

    assert 'materials' in error.value.message_dict
    production_output.refresh_from_db()
    assert production_output.status == ProductionOutput.Status.PENDING
    assert production_output.stock_lot_id is None
    assert production_output.stock_movement_id is None


@pytest.mark.django_db
def test_issue_materials_retry_does_not_save_consumption_or_change_evidence(
    reservable_order,
    operations_user,
):
    from governance.models import GovernanceAuditLog
    from production.services import ProductionOrderOperations

    operations = ProductionOrderOperations(reservable_order, operations_user)
    operations.reserve_materials()
    reservable_order.status = ProductionOrder.Status.IN_PROGRESS
    reservable_order.save(update_fields=['status', 'updated_at'])
    consumption = reservable_order.material_consumptions.get()
    consumption.actual_quantity = Decimal('10.0000')
    consumption.quality_status = MaterialConsumption.QualityStatus.APPROVED
    consumption.save(update_fields=['actual_quantity', 'quality_status', 'updated_at'])
    first = operations.issue_materials()
    consumption.refresh_from_db()
    balance = StockBalance.objects.get(
        product=consumption.material,
        lot=consumption.stock_lot,
        warehouse=consumption.warehouse,
        location=consumption.location,
        quality_status=StockQualityStatus.APPROVED,
    )
    evidence = {
        'updated_at': consumption.updated_at,
        'movement_ids': tuple(movement.pk for movement in first),
        'quantity': balance.quantity,
        'reserved_quantity': balance.reserved_quantity,
        'movement_count': StockMovement.objects.filter(
            source_production_order=reservable_order
        ).count(),
        'audit_count': GovernanceAuditLog.objects.filter(
            target_record_id=str(reservable_order.pk)
        ).count(),
    }
    saved_consumptions = []

    def record_consumption_save(sender, instance, **_kwargs):
        if instance.pk == consumption.pk:
            saved_consumptions.append(instance.pk)

    post_save.connect(
        record_consumption_save,
        sender=MaterialConsumption,
        dispatch_uid='test-issue-materials-noop-retry',
    )
    try:
        second = operations.issue_materials()
    finally:
        post_save.disconnect(
            sender=MaterialConsumption,
            dispatch_uid='test-issue-materials-noop-retry',
        )

    consumption.refresh_from_db()
    balance.refresh_from_db()
    assert saved_consumptions == []
    assert consumption.updated_at == evidence['updated_at']
    assert tuple(movement.pk for movement in second) == evidence['movement_ids']
    assert balance.quantity == evidence['quantity']
    assert balance.reserved_quantity == evidence['reserved_quantity']
    assert (
        StockMovement.objects.filter(source_production_order=reservable_order).count()
        == evidence['movement_count']
    )
    assert (
        GovernanceAuditLog.objects.filter(target_record_id=str(reservable_order.pk)).count()
        == evidence['audit_count']
    )


def test_balance_lock_keys_are_globally_sorted_and_deduplicated():
    from production.services import _ordered_balance_keys

    keys = [
        (2, 5, 3, 8, StockQualityStatus.APPROVED),
        (1, 9, 3, 8, StockQualityStatus.APPROVED),
        (2, 5, 3, 8, StockQualityStatus.APPROVED),
        (1, 4, 7, 2, StockQualityStatus.APPROVED),
    ]

    assert _ordered_balance_keys(keys) == [
        (1, 4, 7, 2, StockQualityStatus.APPROVED),
        (1, 9, 3, 8, StockQualityStatus.APPROVED),
        (2, 5, 3, 8, StockQualityStatus.APPROVED),
    ]


@requires_postgresql
@pytest.mark.django_db(transaction=True)
def test_reserve_and_issue_materials_opposite_allocations_do_not_deadlock(
    reservable_order,
    allocated_consumption,
    operations_user,
):
    from production.services import ProductionOrderOperations

    second_material = Product.objects.create(
        code='MP-LOCK-B',
        description='Material B para lock',
        item_type=Product.ItemType.RAW_MATERIAL,
        unit=allocated_consumption.unit,
        status=Product.Status.APPROVED,
    )
    second_lot = StockLot.objects.create(
        product=second_material,
        lot_number='LOT-LOCK-B',
    )
    second_balance = StockBalance.objects.create(
        product=second_material,
        lot=second_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        quality_status=StockQualityStatus.APPROVED,
        quantity=Decimal('100.0000'),
        reserved_quantity=Decimal('0.0000'),
        unit=allocated_consumption.unit,
    )
    first_balance = StockBalance.objects.get(
        product=allocated_consumption.material,
        lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        quality_status=StockQualityStatus.APPROVED,
    )
    MaterialConsumption.objects.create(
        order=reservable_order,
        material=second_material,
        planned_quantity=Decimal('1.0000'),
        unit=allocated_consumption.unit,
        stock_lot=second_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        lot_number=second_lot.lot_number,
        quality_status=MaterialConsumption.QualityStatus.APPROVED,
    )
    opposite_order = ProductionOrder.objects.create(
        order_number='OP-LOCK-REVERSA',
        product=reservable_order.product,
        formula=reservable_order.formula,
        route=reservable_order.route,
        planned_quantity=reservable_order.planned_quantity,
        unit=reservable_order.unit,
        status=ProductionOrder.Status.APPROVED,
    )
    MaterialConsumption.objects.create(
        order=opposite_order,
        material=second_material,
        planned_quantity=Decimal('1.0000'),
        unit=allocated_consumption.unit,
        stock_lot=second_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        lot_number=second_lot.lot_number,
        quality_status=MaterialConsumption.QualityStatus.APPROVED,
    )
    MaterialConsumption.objects.create(
        order=opposite_order,
        material=allocated_consumption.material,
        planned_quantity=Decimal('1.0000'),
        unit=allocated_consumption.unit,
        stock_lot=allocated_consumption.stock_lot,
        warehouse=allocated_consumption.warehouse,
        location=allocated_consumption.location,
        lot_number=allocated_consumption.stock_lot.lot_number,
        quality_status=MaterialConsumption.QualityStatus.APPROVED,
    )
    start = Barrier(2)

    def reserve(order_id):
        close_old_connections()
        try:
            order = ProductionOrder.objects.get(pk=order_id)
            user = type(operations_user).objects.get(pk=operations_user.pk)
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '5s'")
                start.wait(timeout=5)
                return [
                    movement.pk
                    for movement in ProductionOrderOperations(order, user).reserve_materials()
                ]
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(reserve, reservable_order.pk),
            executor.submit(reserve, opposite_order.pk),
        ]
        results = [future.result(timeout=10) for future in futures]

    assert [len(result) for result in results] == [2, 2]
    first_balance.refresh_from_db()
    second_balance.refresh_from_db()
    assert first_balance.reserved_quantity == Decimal('11.0000')
    assert second_balance.reserved_quantity == Decimal('2.0000')

    ProductionOrder.objects.filter(pk__in=[reservable_order.pk, opposite_order.pk]).update(
        status=ProductionOrder.Status.IN_PROGRESS
    )
    MaterialConsumption.objects.filter(
        order_id__in=[reservable_order.pk, opposite_order.pk]
    ).update(
        actual_quantity=F('planned_quantity'),
        quality_status=MaterialConsumption.QualityStatus.APPROVED,
    )
    issue_start = Barrier(2)

    def issue(order_id):
        close_old_connections()
        try:
            order = ProductionOrder.objects.get(pk=order_id)
            user = type(operations_user).objects.get(pk=operations_user.pk)
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL lock_timeout = '5s'")
                issue_start.wait(timeout=5)
                return [
                    movement.pk
                    for movement in ProductionOrderOperations(order, user).issue_materials()
                ]
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(issue, reservable_order.pk),
            executor.submit(issue, opposite_order.pk),
        ]
        issue_results = [future.result(timeout=10) for future in futures]

    assert [len(result) for result in issue_results] == [2, 2]
    first_balance.refresh_from_db()
    second_balance.refresh_from_db()
    assert first_balance.quantity == Decimal('89.0000')
    assert first_balance.reserved_quantity == Decimal('0.0000')
    assert second_balance.quantity == Decimal('98.0000')
    assert second_balance.reserved_quantity == Decimal('0.0000')


@pytest.mark.django_db
def test_calculate_cost_rejects_period_crossing_month_boundary(
    production_order,
    allocated_consumption,
    operations_user,
):
    from production.services import ProductionOrderOperations

    period_start = date(2026, 7, 31)
    period_end = date(2026, 8, 1)
    _create_approved_standard(
        consumption=allocated_consumption,
        user=operations_user,
        effective_from=period_start,
        version='CRUZADO-1',
    )
    production_order.status = ProductionOrder.Status.COMPLETED
    production_order.save(update_fields=['status', 'updated_at'])

    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(production_order, operations_user).calculate_cost(
            period_start=period_start,
            period_end=period_end,
        )

    assert 'period_end' in error.value.message_dict
    assert not ProductionCostCapture.objects.filter(
        production_order=production_order,
    ).exists()


@pytest.mark.django_db
def test_calculate_cost_rejects_cross_month_when_final_month_is_closed(
    production_order,
    allocated_consumption,
    operations_user,
):
    from production.services import ProductionOrderOperations

    period_start = date(2026, 7, 31)
    period_end = date(2026, 8, 1)
    _create_approved_standard(
        consumption=allocated_consumption,
        user=operations_user,
        effective_from=period_start,
        version='FINAL-FECHADO-1',
    )
    MonthlyCostClosing.objects.create(
        period_year=period_end.year,
        period_month=period_end.month,
        status=MonthlyCostClosing.Status.CLOSED,
        closed_by=operations_user,
        closed_at=timezone.now(),
    )
    production_order.status = ProductionOrder.Status.COMPLETED
    production_order.save(update_fields=['status', 'updated_at'])

    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(production_order, operations_user).calculate_cost(
            period_start=period_start,
            period_end=period_end,
        )

    assert 'period_end' in error.value.message_dict
    assert not ProductionCostCapture.objects.filter(
        production_order=production_order,
    ).exists()


@requires_postgresql
@pytest.mark.django_db
def test_calculate_cost_locks_monthly_closing_before_rejecting_closed_period(
    production_order,
    allocated_consumption,
    operations_user,
):
    from production.services import ProductionOrderOperations

    period_start = date(2026, 7, 1)
    period_end = date(2026, 7, 31)
    MonthlyCostClosing.objects.create(
        period_year=period_start.year,
        period_month=period_start.month,
        status=MonthlyCostClosing.Status.CLOSED,
        closed_by=operations_user,
        closed_at=timezone.now(),
    )
    production_order.status = ProductionOrder.Status.COMPLETED
    production_order.save(update_fields=['status', 'updated_at'])

    with CaptureQueriesContext(connection) as queries:
        with pytest.raises(ValidationError) as error:
            ProductionOrderOperations(production_order, operations_user).calculate_cost(
                period_start=period_start,
                period_end=period_end,
            )

    assert 'period_start' in error.value.message_dict
    closing_queries = [
        query['sql']
        for query in queries.captured_queries
        if 'costing_monthlycostclosing' in query['sql'].lower()
    ]
    assert any('FOR UPDATE' in sql.upper() for sql in closing_queries)


@requires_postgresql
@pytest.mark.django_db
def test_monthly_cost_closing_close_acquires_compatible_row_lock(operations_user):

    closing = MonthlyCostClosing.objects.create(
        period_year=2026,
        period_month=7,
        status=MonthlyCostClosing.Status.VALIDATED,
    )

    with CaptureQueriesContext(connection) as queries:
        closing.close(user=operations_user)

    closing_queries = [
        query['sql']
        for query in queries.captured_queries
        if 'costing_monthlycostclosing' in query['sql'].lower()
    ]
    assert any('FOR UPDATE' in sql.upper() for sql in closing_queries)


@requires_postgresql
@pytest.mark.django_db(transaction=True)
def test_calculate_cost_and_monthly_close_serialize_consistently(
    production_order,
    allocated_consumption,
    operations_user,
):
    from costing.models import (
        MonthlyCostClosing,
        ProductionCostCapture,
    )
    from production.services import ProductionOrderOperations

    period_start = date(2026, 7, 1)
    period_end = date(2026, 7, 31)
    _create_approved_standard(
        consumption=allocated_consumption,
        user=operations_user,
        effective_from=period_start,
        version='CORRIDA-1',
    )
    closing = MonthlyCostClosing.objects.create(
        period_year=period_start.year,
        period_month=period_start.month,
        status=MonthlyCostClosing.Status.VALIDATED,
    )
    production_order.status = ProductionOrder.Status.COMPLETED
    production_order.save(update_fields=['status', 'updated_at'])
    start = Barrier(2)

    def calculate():
        close_old_connections()
        try:
            order = ProductionOrder.objects.get(pk=production_order.pk)
            user = type(operations_user).objects.get(pk=operations_user.pk)
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            start.wait(timeout=5)
            try:
                capture = ProductionOrderOperations(order, user).calculate_cost(
                    period_start=period_start,
                    period_end=period_end,
                )
            except ValidationError as exc:
                return 'closed', exc.message_dict
            return 'captured', capture.pk
        finally:
            close_old_connections()

    def close_period():
        close_old_connections()
        try:
            user = type(operations_user).objects.get(pk=operations_user.pk)
            period = MonthlyCostClosing.objects.get(pk=closing.pk)
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            start.wait(timeout=5)
            period.close(user=user)
            return period.status
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as executor:
        calculate_future = executor.submit(calculate)
        close_future = executor.submit(close_period)
        calculation_result = calculate_future.result(timeout=10)
        closing_result = close_future.result(timeout=10)

    closing.refresh_from_db()
    assert closing_result == MonthlyCostClosing.Status.CLOSED
    assert closing.status == MonthlyCostClosing.Status.CLOSED
    if calculation_result[0] == 'captured':
        assert ProductionCostCapture.objects.filter(pk=calculation_result[1]).exists()
    else:
        assert 'period_start' in calculation_result[1]
        assert not ProductionCostCapture.objects.filter(
            production_order=production_order,
        ).exists()


@pytest.mark.django_db
def test_calculate_cost_queries_standard_cost_candidates_once(
    production_order,
    allocated_consumption,
    operations_user,
):
    from production.services import ProductionOrderOperations

    period_start = date(2026, 7, 1)
    period_end = date(2026, 7, 31)
    _create_approved_standard(
        consumption=allocated_consumption,
        user=operations_user,
        effective_from=period_start,
        version='LOTE-A-1',
    )
    second_material = Product.objects.create(
        code='MP-CUSTO-LOTE-B',
        description='Material B custo em lote',
        item_type=Product.ItemType.RAW_MATERIAL,
        unit=allocated_consumption.unit,
        status=Product.Status.APPROVED,
    )
    second_consumption = MaterialConsumption.objects.create(
        order=production_order,
        material=second_material,
        planned_quantity=Decimal('5.0000'),
        actual_quantity=Decimal('4.0000'),
        loss_quantity=Decimal('1.0000'),
        unit=allocated_consumption.unit,
        quality_status=MaterialConsumption.QualityStatus.APPROVED,
    )
    _create_approved_standard(
        consumption=second_consumption,
        user=operations_user,
        effective_from=period_start,
        version='LOTE-B-1',
    )
    production_order.status = ProductionOrder.Status.COMPLETED
    production_order.save(update_fields=['status', 'updated_at'])

    with CaptureQueriesContext(connection) as queries:
        ProductionOrderOperations(production_order, operations_user).calculate_cost(
            period_start=period_start,
            period_end=period_end,
        )

    standard_queries = [
        query['sql']
        for query in queries.captured_queries
        if 'costing_standardcost' in query['sql'].lower()
    ]
    assert len(standard_queries) == 1


@pytest.mark.django_db
def test_calculate_cost_selects_latest_approved_revision_not_lexical_version(
    production_order,
    allocated_consumption,
    operations_user,
):
    from production.services import ProductionOrderOperations

    period_start = date(2026, 7, 1)
    period_end = date(2026, 7, 31)
    other_unit = UnitOfMeasure.objects.create(
        code='G-REV-CRONO',
        name='Grama revisão cronológica',
        symbol='g',
    )
    allocated_consumption.actual_quantity = Decimal('10.0000')
    allocated_consumption.loss_quantity = Decimal('0.0000')
    allocated_consumption.save(update_fields=['actual_quantity', 'loss_quantity', 'updated_at'])

    old_revision = _create_approved_standard(
        consumption=allocated_consumption,
        user=operations_user,
        effective_from=period_start,
        version='9',
        approved_at=timezone.make_aware(datetime(2026, 7, 10, 9, 0)),
    )
    old_revision.material_cost = Decimal('900.0000')
    old_revision.recalculate()
    newest_revision = _create_approved_standard(
        consumption=allocated_consumption,
        user=operations_user,
        effective_from=period_start,
        version='10',
        approved_at=timezone.make_aware(datetime(2026, 7, 11, 9, 0)),
    )
    newest_revision.material_cost = Decimal('1000.0000')
    newest_revision.recalculate()
    created_later_revision = _create_approved_standard(
        consumption=allocated_consumption,
        user=operations_user,
        effective_from=period_start,
        version='CRIADA-DEPOIS-APROVADA-ANTES',
        approved_at=timezone.make_aware(datetime(2026, 7, 9, 9, 0)),
    )
    created_later_revision.material_cost = Decimal('9900.0000')
    created_later_revision.recalculate()
    StandardCost.objects.filter(pk=old_revision.pk).update(
        created_at=timezone.make_aware(datetime(2026, 7, 1, 9, 0)),
    )
    StandardCost.objects.filter(pk=newest_revision.pk).update(
        created_at=timezone.make_aware(datetime(2026, 7, 2, 9, 0)),
    )
    StandardCost.objects.filter(pk=created_later_revision.pk).update(
        created_at=timezone.make_aware(datetime(2026, 7, 12, 9, 0)),
    )

    other_center_revision = _create_approved_standard(
        consumption=allocated_consumption,
        user=operations_user,
        effective_from=period_start,
        version='OUTRO-CENTRO',
    )
    other_center_revision.obsolete()
    other_unit_revision = _create_approved_standard(
        consumption=allocated_consumption,
        user=operations_user,
        effective_from=period_start,
        version='OUTRA-UNIDADE',
    )
    StandardCost.objects.filter(pk=other_unit_revision.pk).update(unit=other_unit)
    StandardCost.objects.create(
        product=allocated_consumption.material,
        version='RASCUNHO',
        effective_from=period_start,
        standard_quantity=Decimal('100.0000'),
        unit=allocated_consumption.unit,
        material_cost=Decimal('9900.0000'),
    )
    obsolete = _create_approved_standard(
        consumption=allocated_consumption,
        user=operations_user,
        effective_from=period_start,
        version='OBSOLETO',
    )
    obsolete.obsolete()
    _create_approved_standard(
        consumption=allocated_consumption,
        user=operations_user,
        effective_from=period_end + timedelta(days=1),
        version='FUTURO',
    )
    expired = _create_approved_standard(
        consumption=allocated_consumption,
        user=operations_user,
        effective_from=period_start - timedelta(days=30),
        version='EXPIRADO',
    )
    expired.effective_to = period_end - timedelta(days=1)
    expired.save(update_fields=['effective_to', 'updated_at'])
    production_order.status = ProductionOrder.Status.COMPLETED
    production_order.save(update_fields=['status', 'updated_at'])

    capture = ProductionOrderOperations(production_order, operations_user).calculate_cost(
        period_start=period_start,
        period_end=period_end,
    )

    assert capture.actual_material_cost == Decimal('100.0000')


@requires_postgresql
@pytest.mark.django_db(transaction=True)
def test_calculate_cost_rejects_approved_candidate_without_real_approval_time(
    production_order,
    allocated_consumption,
    operations_user,
):
    from production.services import ProductionOrderOperations

    period_start = date(2026, 7, 1)
    period_end = date(2026, 7, 31)
    allocated_consumption.actual_quantity = Decimal('10.0000')
    allocated_consumption.loss_quantity = Decimal('0.0000')
    allocated_consumption.save(update_fields=['actual_quantity', 'loss_quantity', 'updated_at'])
    invalid_candidate = _create_approved_standard(
        consumption=allocated_consumption,
        user=operations_user,
        effective_from=period_start,
        version='SEM-APROVACAO-REAL',
    )
    invalid_candidate.material_cost = Decimal('1000.0000')
    invalid_candidate.recalculate()
    production_order.status = ProductionOrder.Status.COMPLETED
    production_order.save(update_fields=['status', 'updated_at'])

    constraint_name = 'standard_cost_approved_at_required'
    trigger_name = 'costing_standardcost_state_transition_trigger'
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conrelid = %s::regclass
                  AND conname = %s
            )
            """,
            [StandardCost._meta.db_table, constraint_name],
        )
        constraint_was_present = cursor.fetchone()[0]
        cursor.execute(
            """
            SELECT EXISTS (
                SELECT 1
                FROM pg_trigger
                WHERE tgrelid = %s::regclass
                  AND tgname = %s
                  AND NOT tgisinternal
            )
            """,
            [StandardCost._meta.db_table, trigger_name],
        )
        trigger_was_present = cursor.fetchone()[0]
        if trigger_was_present:
            cursor.execute(
                """
                ALTER TABLE "costing_standardcost"
                DISABLE TRIGGER "costing_standardcost_state_transition_trigger"
                """
            )
        if constraint_was_present:
            cursor.execute(
                """
                ALTER TABLE "costing_standardcost"
                DROP CONSTRAINT "standard_cost_approved_at_required"
                """
            )

    try:
        StandardCost.objects.filter(pk=invalid_candidate.pk).update(approved_at=None)

        with pytest.raises(ValidationError) as error:
            ProductionOrderOperations(production_order, operations_user).calculate_cost(
                period_start=period_start,
                period_end=period_end,
            )

        assert 'standard_cost' in error.value.message_dict
        assert not ProductionCostCapture.objects.filter(
            production_order=production_order,
            period_start=period_start,
            period_end=period_end,
        ).exists()
    finally:
        StandardCost.objects.filter(pk=invalid_candidate.pk).update(
            status=StandardCost.Status.DRAFT
        )
        if constraint_was_present:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    ALTER TABLE "costing_standardcost"
                    ADD CONSTRAINT "standard_cost_approved_at_required"
                    CHECK (status <> 'approved' OR approved_at IS NOT NULL)
                    """
                )
        if trigger_was_present:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    ALTER TABLE "costing_standardcost"
                    ENABLE TRIGGER "costing_standardcost_state_transition_trigger"
                    """
                )


@pytest.mark.django_db
def test_receive_outputs_ignores_inactive_component_but_requires_each_active_component(
    production_output,
    operations_user,
):
    from inventory.models import StockLotGenealogy
    from production.services import ProductionOrderOperations

    order = production_output.order
    active_component = order.formula.components.get()
    inactive_material = Product.objects.create(
        code='MP-COMPONENTE-INATIVO',
        description='Componente inativo',
        item_type=Product.ItemType.EXCIPIENT,
        unit=active_component.unit,
        status=Product.Status.APPROVED,
    )
    inactive_component = FormulaComponent.objects.create(
        formula=order.formula,
        line_number=20,
        material=inactive_material,
        quantity=Decimal('1.0000'),
        unit=active_component.unit,
        is_active=False,
    )
    _issued_formula_consumption(
        order=order,
        output=production_output,
        component=inactive_component,
    )
    order.status = ProductionOrder.Status.COMPLETED
    order.save(update_fields=['status', 'updated_at'])

    with pytest.raises(ValidationError) as error:
        ProductionOrderOperations(order, operations_user).receive_outputs()

    assert 'materials' in error.value.message_dict
    # Prepare the second snapshot while operational; terminal edits remain forbidden.
    order.status = ProductionOrder.Status.IN_PROGRESS
    order.save(update_fields=['status', 'updated_at'])
    _issued_formula_consumption(
        order=order,
        output=production_output,
        component=active_component,
    )

    order.status = ProductionOrder.Status.COMPLETED
    order.save(update_fields=['status', 'updated_at'])

    outputs = ProductionOrderOperations(order, operations_user).receive_outputs()

    assert outputs[0].status == ProductionOutput.Status.RECEIVED
    assert StockLotGenealogy.objects.filter(production_order=order).count() == 2


def _grant_permissions(user, *permission_names):
    app_labels_and_codenames = [
        permission_name.split('.', maxsplit=1) for permission_name in permission_names
    ]
    permissions = [
        Permission.objects.get(content_type__app_label=app_label, codename=codename)
        for app_label, codename in app_labels_and_codenames
    ]
    user.user_permissions.add(*permissions)
    for cache_name in ('_perm_cache', '_user_perm_cache', '_group_perm_cache'):
        if hasattr(user, cache_name):
            delattr(user, cache_name)


PRODUCTION_ACTION_PERMISSIONS = {
    'reserve_materials': (
        'production.change_productionorder',
        'production.change_materialconsumption',
        'inventory.add_stockmovement',
    ),
    'issue_materials': (
        'production.change_productionorder',
        'production.change_materialconsumption',
        'inventory.add_stockmovement',
    ),
    'receive_outputs': (
        'production.receive_productionoutput',
        'inventory.add_stockmovement',
    ),
    'calculate_cost': (
        'production.change_productionorder',
        'costing.add_productioncostcapture',
    ),
}


@pytest.mark.django_db
@pytest.mark.permission_strict
@pytest.mark.parametrize('action', tuple(PRODUCTION_ACTION_PERMISSIONS))
def test_production_operational_actions_return_401_for_anonymous_users(action, production_order):
    response = APIClient().post(
        reverse(f'production:order-{action.replace("_", "-")}', args=[production_order.pk])
    )

    assert response.status_code == 401
    assert response['WWW-Authenticate'].startswith('Basic')


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_production_operational_action_keeps_session_authentication_precedence(
    production_order, django_user_model
):
    user = django_user_model.objects.create_user(
        username='operador-sessao-api', email='operador-sessao-api@example.com'
    )
    _grant_permissions(user, *PRODUCTION_ACTION_PERMISSIONS['reserve_materials'])
    client = APIClient()
    client.force_login(user)
    client.credentials(HTTP_AUTHORIZATION='Basic invalid-credentials')

    response = client.post(
        reverse('production:order-reserve-materials', args=[production_order.pk])
    )

    assert response.status_code == 400
    assert 'status' in response.data


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_production_operational_action_rejects_invalid_basic_credentials(production_order):
    client = APIClient()
    client.credentials(HTTP_AUTHORIZATION='Basic invalid-credentials')

    response = client.post(
        reverse('production:order-reserve-materials', args=[production_order.pk])
    )

    assert response.status_code == 401


@pytest.mark.django_db
@pytest.mark.permission_strict
@pytest.mark.parametrize(
    ('action', 'missing_permission'),
    [
        (action, permission)
        for action, permissions in PRODUCTION_ACTION_PERMISSIONS.items()
        for permission in permissions
    ],
)
def test_production_operational_actions_require_all_specific_permissions(
    action, missing_permission, production_order, django_user_model
):
    user = django_user_model.objects.create_user(
        username=f'{action}-{missing_permission.split(".")[1]}',
        email=f'{action}-{missing_permission.split(".")[1]}@example.com',
    )
    client = APIClient()
    client.force_authenticate(user)
    granted_permissions = set(PRODUCTION_ACTION_PERMISSIONS[action]) - {missing_permission}
    _grant_permissions(user, *granted_permissions)

    response = client.post(
        reverse(f'production:order-{action.replace("_", "-")}', args=[production_order.pk])
    )

    assert response.status_code == 403


@pytest.mark.django_db(transaction=True)
@pytest.mark.permission_strict
def test_reserve_materials_api_is_idempotent_and_returns_stable_movement_ids(
    reservable_order, django_user_model
):
    user = django_user_model.objects.create_user(
        username='operador-reserva-api', email='operador-reserva-api@example.com'
    )
    _grant_permissions(user, *PRODUCTION_ACTION_PERMISSIONS['reserve_materials'])
    client = APIClient()
    client.force_authenticate(user)
    url = reverse('production:order-reserve-materials', args=[reservable_order.pk])

    first = client.post(url)
    second = client.post(url)

    assert first.status_code == 200
    assert first.data['movement_ids']
    assert second.status_code == 200
    assert second.data['movement_ids'] == first.data['movement_ids']


@pytest.mark.django_db(transaction=True)
@pytest.mark.permission_strict
def test_issue_materials_api_is_idempotent_and_returns_stable_movement_ids(
    reservable_order, django_user_model
):
    user = django_user_model.objects.create_user(
        username='operador-baixa-api', email='operador-baixa-api@example.com'
    )
    _grant_permissions(
        user,
        *PRODUCTION_ACTION_PERMISSIONS['reserve_materials'],
        *PRODUCTION_ACTION_PERMISSIONS['issue_materials'],
    )
    client = APIClient()
    client.force_authenticate(user)
    reserve_url = reverse('production:order-reserve-materials', args=[reservable_order.pk])
    issue_url = reverse('production:order-issue-materials', args=[reservable_order.pk])

    assert client.post(reserve_url).status_code == 200
    consumption = reservable_order.material_consumptions.get()
    consumption.actual_quantity = consumption.planned_quantity
    consumption.save(update_fields=['actual_quantity', 'updated_at'])
    reservable_order.status = ProductionOrder.Status.IN_PROGRESS
    reservable_order.save(update_fields=['status', 'updated_at'])

    first = client.post(issue_url)
    second = client.post(issue_url)

    assert first.status_code == 200
    assert first.data['movement_ids']
    assert second.status_code == 200
    assert second.data['movement_ids'] == first.data['movement_ids']


@pytest.mark.django_db(transaction=True)
@pytest.mark.permission_strict
def test_receive_outputs_api_is_idempotent_and_returns_stable_output_ids(
    production_output, allocated_consumption, django_user_model
):
    user = django_user_model.objects.create_user(
        username='operador-recebimento-api', email='operador-recebimento-api@example.com'
    )
    _grant_permissions(user, *PRODUCTION_ACTION_PERMISSIONS['receive_outputs'])
    client = APIClient()
    client.force_authenticate(user)
    order = production_output.order
    allocated_consumption.actual_quantity = Decimal('4.0000')
    allocated_consumption.issued_quantity = Decimal('4.0000')
    allocated_consumption.save(update_fields=['actual_quantity', 'issued_quantity', 'updated_at'])
    allocated_consumption.issue_movement = create_consumption_movement(
        allocated_consumption,
        StockMovement.MovementType.ISSUE,
        quantity=Decimal('4.0000'),
    )
    allocated_consumption.save(update_fields=['issue_movement', 'updated_at'])
    # Prepare all material evidence before making the order terminal.
    order.status = ProductionOrder.Status.COMPLETED
    order.save(update_fields=['status', 'updated_at'])
    url = reverse('production:order-receive-outputs', args=[order.pk])

    first = client.post(url)
    second = client.post(url)

    assert first.status_code == 200
    assert first.data['output_ids'] == [production_output.pk]
    assert second.status_code == 200
    assert second.data['output_ids'] == first.data['output_ids']


@pytest.mark.django_db(transaction=True)
@pytest.mark.permission_strict
def test_calculate_cost_api_is_idempotent_and_returns_stable_capture_id(
    production_order, allocated_consumption, django_user_model
):

    user = django_user_model.objects.create_user(
        username='operador-custo-idempotente-api',
        email='operador-custo-idempotente-api@example.com',
    )
    _grant_permissions(user, *PRODUCTION_ACTION_PERMISSIONS['calculate_cost'])
    client = APIClient()
    client.force_authenticate(user)
    period_start = timezone.localdate().replace(day=1)
    period_end = timezone.localdate()
    standard = StandardCost.objects.create(
        product=allocated_consumption.material,
        version='API-1',
        effective_from=period_start,
        standard_quantity=Decimal('100.0000'),
        unit=allocated_consumption.unit,
        material_cost=Decimal('200.0000'),
    )
    standard.approve(user=user)
    production_order.status = ProductionOrder.Status.COMPLETED
    production_order.save(update_fields=['status', 'updated_at'])
    url = reverse('production:order-calculate-cost', args=[production_order.pk])
    payload = {
        'period_start': period_start.isoformat(),
        'period_end': period_end.isoformat(),
    }

    first = client.post(url, payload)
    second = client.post(url, payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.data['cost_capture_id'] == first.data['cost_capture_id']


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_reserve_materials_api_returns_structured_domain_validation_error(
    production_order, django_user_model
):
    user = django_user_model.objects.create_user(
        username='operador-erro-dominio-api', email='operador-erro-dominio-api@example.com'
    )
    _grant_permissions(user, *PRODUCTION_ACTION_PERMISSIONS['reserve_materials'])
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        reverse('production:order-reserve-materials', args=[production_order.pk])
    )

    assert response.status_code == 400
    assert 'status' in response.data


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_calculate_cost_api_rejects_invalid_period(production_order, django_user_model):

    user = django_user_model.objects.create_user(
        username='operador-custo-api', email='operador-custo-api@example.com'
    )
    _grant_permissions(user, *PRODUCTION_ACTION_PERMISSIONS['calculate_cost'])
    client = APIClient()
    client.force_authenticate(user)
    url = reverse('production:order-calculate-cost', args=[production_order.pk])

    invalid_range = client.post(
        url,
        {
            'period_start': '2026-07-31',
            'period_end': '2026-07-01',
        },
    )
    cross_month = client.post(
        url,
        {
            'period_start': '2026-07-31',
            'period_end': '2026-08-01',
        },
    )
    assert invalid_range.status_code == 400
    assert 'period_end' in invalid_range.data
    assert cross_month.status_code == 400
    assert 'period_end' in cross_month.data


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_production_operational_resource_routes_support_crud(
    production_order, stock_address, django_user_model
):
    user = django_user_model.objects.create_user(
        username='operador-recursos-api', email='operador-recursos-api@example.com'
    )
    _grant_permissions(
        user,
        'production.add_productionoutput',
        'production.change_productionoutput',
        'production.delete_productionoutput',
        'production.view_productionoutput',
        'production.add_productionoperationexecution',
        'production.change_productionoperationexecution',
        'production.delete_productionoperationexecution',
        'production.view_productionoperationexecution',
        'production.add_productionlaborentry',
        'production.change_productionlaborentry',
        'production.delete_productionlaborentry',
        'production.view_productionlaborentry',
    )
    client = APIClient()
    client.force_authenticate(user)
    warehouse, location = stock_address
    production_order.status = ProductionOrder.Status.IN_PROGRESS
    production_order.save(update_fields=['status', 'updated_at'])

    resources = (
        (
            'output',
            'outputs',
            {
                'order': production_order.pk,
                'product': production_order.product_id,
                'lot_number': production_order.batch_number,
                'sublot_number': 'API',
                'planned_quantity': '100.0000',
                'produced_quantity': '90.0000',
                'unit': production_order.unit_id,
                'warehouse': warehouse.pk,
                'location': location.pk,
            },
            {'notes': 'atualizado'},
        ),
        (
            'operation',
            'operations',
            {
                'order': production_order.pk,
                'sequence': 99,
                'operation': 'Conferência API',
            },
            {'notes': 'atualizado'},
        ),
        (
            'labor-entry',
            'labor-entries',
            {
                'order': production_order.pk,
                'user': user.pk,
                'role': 'Operador API',
                'started_at': '2026-07-01T08:00:00-03:00',
                'ended_at': '2026-07-01T09:00:00-03:00',
            },
            {'notes': 'atualizado'},
        ),
    )

    for basename, route, payload, update_payload in resources:
        list_url = reverse(f'production:{basename}-list')
        assert list_url == f'/api/production/{route}/'
        assert client.get(list_url).status_code == 200

        created = client.post(list_url, payload)
        assert created.status_code == 201
        if basename != 'labor-entry':
            assert client.post(list_url, payload).status_code == 400

        detail_url = reverse(f'production:{basename}-detail', args=[created.data['id']])
        updated = client.patch(detail_url, update_payload)
        assert updated.status_code == 200, updated.data
        assert client.delete(detail_url).status_code == 403
        model = {
            'output': ProductionOutput,
            'operation': ProductionOperationExecution,
            'labor-entry': ProductionLaborEntry,
        }[basename]
        assert model.objects.filter(pk=created.data['id']).exists()


def _production_resource_client(user, model_name):
    _grant_permissions(
        user,
        f'production.add_{model_name}',
        f'production.change_{model_name}',
        f'production.view_{model_name}',
    )
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_operation_api_persists_derived_duration_and_retrospective_actor(
    production_order, django_user_model
):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_user(
        username='ator-operacao-retroativa',
        email='ator-operacao-retroativa@example.com',
    )
    spoofed_actor = django_user_model.objects.create_user(
        username='ator-operacao-forjado',
        email='ator-operacao-forjado@example.com',
    )
    client = _production_resource_client(actor, 'productionoperationexecution')
    started_at = timezone.now() - timedelta(minutes=95)
    ended_at = timezone.now()

    response = client.post(
        reverse('production:operation-list'),
        {
            'order': production_order.pk,
            'sequence': 90,
            'operation': 'Apontamento retrospectivo',
            'status': ProductionOperationExecution.Status.COMPLETED,
            'started_at': started_at.isoformat(),
            'ended_at': ended_at.isoformat(),
            'actual_minutes': '999.00',
            'recorded_by': spoofed_actor.pk,
        },
    )

    assert response.status_code == 201, response.data
    operation = ProductionOperationExecution.objects.get(pk=response.data['id'])
    expected_minutes = (
        Decimal(str((ended_at - started_at).total_seconds())) / Decimal('60')
    ).quantize(Decimal('0.01'))
    assert operation.actual_minutes == expected_minutes
    assert Decimal(response.data['actual_minutes']) == expected_minutes
    assert operation.recorded_by == actor
    audit = GovernanceAuditLog.objects.get(
        action='api.production_operation_execution.created',
        target_record_id=str(operation.pk),
    )
    assert audit.user == actor
    assert audit.safe_context['before'] == {'record_exists': False}
    assert audit.safe_context['after']['status'] == ProductionOperationExecution.Status.COMPLETED
    assert audit.safe_context['after']['actual_minutes'] == str(expected_minutes)


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_operation_api_enforces_forward_transitions_and_terminal_immutability(
    production_order, django_user_model
):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_user(
        username='ator-transicao-operacao',
        email='ator-transicao-operacao@example.com',
    )
    client = _production_resource_client(actor, 'productionoperationexecution')
    list_url = reverse('production:operation-list')
    created = client.post(
        list_url,
        {
            'order': production_order.pk,
            'sequence': 91,
            'operation': 'Transição controlada',
        },
    )
    assert created.status_code == 201, created.data
    detail_url = reverse('production:operation-detail', args=[created.data['id']])
    started_at = timezone.now() - timedelta(minutes=45)
    ended_at = timezone.now()

    started = client.patch(
        detail_url,
        {
            'status': ProductionOperationExecution.Status.IN_PROGRESS,
            'started_at': started_at.isoformat(),
        },
    )
    assert started.status_code == 200, started.data
    completed = client.patch(
        detail_url,
        {
            'status': ProductionOperationExecution.Status.COMPLETED,
            'ended_at': ended_at.isoformat(),
        },
    )
    assert completed.status_code == 200, completed.data
    audit_count = GovernanceAuditLog.objects.filter(
        target_model='ProductionOperationExecution',
        target_record_id=str(created.data['id']),
    ).count()

    rejected = client.patch(detail_url, {'status': ProductionOperationExecution.Status.PENDING})

    assert rejected.status_code == 400
    operation = ProductionOperationExecution.objects.get(pk=created.data['id'])
    assert operation.status == ProductionOperationExecution.Status.COMPLETED
    assert (
        GovernanceAuditLog.objects.filter(
            target_model='ProductionOperationExecution',
            target_record_id=str(operation.pk),
        ).count()
        == audit_count
    )


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_operation_api_rejects_incoherent_state_without_audit(production_order, django_user_model):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_user(
        username='ator-operacao-incoerente',
        email='ator-operacao-incoerente@example.com',
    )
    client = _production_resource_client(actor, 'productionoperationexecution')

    response = client.post(
        reverse('production:operation-list'),
        {
            'order': production_order.pk,
            'sequence': 92,
            'operation': 'Operação incoerente',
            'status': ProductionOperationExecution.Status.IN_PROGRESS,
        },
    )

    assert response.status_code == 400
    assert 'started_at' in response.data
    assert not ProductionOperationExecution.objects.filter(
        order=production_order, sequence=92
    ).exists()
    assert not GovernanceAuditLog.objects.filter(
        action='api.production_operation_execution.created'
    ).exists()


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_operation_api_rejects_creating_skipped_without_audit(production_order, django_user_model):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_user(
        username='ator-operacao-skipped-criacao',
        email='ator-operacao-skipped-criacao@example.com',
    )
    client = _production_resource_client(actor, 'productionoperationexecution')

    response = client.post(
        reverse('production:operation-list'),
        {
            'order': production_order.pk,
            'sequence': 97,
            'operation': 'Operação dispensada sem histórico',
            'status': ProductionOperationExecution.Status.SKIPPED,
            'notes': 'A etapa não se aplicava ao lote.',
        },
    )

    assert response.status_code == 400
    assert response.data['status'] == [
        'Crie a operação pendente antes de registrar que ela não foi executada.'
    ]
    assert not ProductionOperationExecution.objects.filter(
        order=production_order, sequence=97
    ).exists()
    assert not GovernanceAuditLog.objects.filter(
        action='api.production_operation_execution.created'
    ).exists()


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_labor_api_persists_recalculated_duration_on_post_and_patch(
    production_order, django_user_model
):
    from governance.models import GovernanceAuditLog

    production_order.status = ProductionOrder.Status.IN_PROGRESS
    production_order.save(update_fields=['status', 'updated_at'])
    actor = django_user_model.objects.create_user(
        username='ator-mao-obra',
        email='ator-mao-obra@example.com',
    )
    client = _production_resource_client(actor, 'productionlaborentry')
    started_at = timezone.now() - timedelta(minutes=75)
    first_end = started_at + timedelta(minutes=30)
    second_end = started_at + timedelta(minutes=75)

    created = client.post(
        reverse('production:labor-entry-list'),
        {
            'order': production_order.pk,
            'user': actor.pk,
            'role': 'Operador',
            'started_at': started_at.isoformat(),
            'ended_at': first_end.isoformat(),
            'duration_minutes': '999.00',
        },
    )

    assert created.status_code == 201, created.data
    entry = ProductionLaborEntry.objects.get(pk=created.data['id'])
    assert entry.duration_minutes == Decimal('30.00')
    assert Decimal(created.data['duration_minutes']) == Decimal('30.00')

    updated = client.patch(
        reverse('production:labor-entry-detail', args=[entry.pk]),
        {'ended_at': second_end.isoformat()},
    )

    assert updated.status_code == 200, updated.data
    entry.refresh_from_db()
    assert entry.duration_minutes == Decimal('75.00')
    assert Decimal(updated.data['duration_minutes']) == Decimal('75.00')
    assert (
        GovernanceAuditLog.objects.filter(
            target_model='ProductionLaborEntry',
            target_record_id=str(entry.pk),
        ).count()
        == 2
    )


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_received_output_is_immutable_via_crud_and_failed_update_is_not_audited(
    received_output, django_user_model
):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_user(
        username='ator-output-recebido',
        email='ator-output-recebido@example.com',
    )
    received_output.full_clean()
    received_output.save()
    client = _production_resource_client(actor, 'productionoutput')
    original_notes = received_output.notes
    audit_count = GovernanceAuditLog.objects.count()

    response = client.patch(
        reverse('production:output-detail', args=[received_output.pk]),
        {'notes': 'tentativa de alteração'},
    )

    assert response.status_code == 400
    received_output.refresh_from_db()
    assert received_output.notes == original_notes
    assert GovernanceAuditLog.objects.count() == audit_count


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_labor_entry_is_immutable_after_order_terminal_state(production_order, django_user_model):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_user(
        username='ator-mao-obra-terminal',
        email='ator-mao-obra-terminal@example.com',
    )
    production_order.status = ProductionOrder.Status.RELEASED
    production_order.save(update_fields=['status', 'updated_at'])
    started_at = timezone.now() - timedelta(minutes=30)
    entry = ProductionLaborEntry(
        order=production_order,
        user=actor,
        role='Operador',
        started_at=started_at,
        ended_at=timezone.now(),
    )
    entry.full_clean()
    entry.save()
    production_order.status = ProductionOrder.Status.COMPLETED
    production_order.save(update_fields=['status', 'updated_at'])
    client = _production_resource_client(actor, 'productionlaborentry')
    audit_count = GovernanceAuditLog.objects.count()

    response = client.patch(
        reverse('production:labor-entry-detail', args=[entry.pk]),
        {'role': 'Supervisor'},
    )

    assert response.status_code == 400
    entry.refresh_from_db()
    assert entry.role == 'Operador'
    assert GovernanceAuditLog.objects.count() == audit_count


@pytest.mark.django_db
@pytest.mark.permission_strict
@pytest.mark.parametrize(
    ('basename', 'model_name'),
    [
        ('output', 'productionoutput'),
        ('labor-entry', 'productionlaborentry'),
    ],
)
def test_terminal_order_rejects_new_output_planning_and_labor_without_audit(
    production_order,
    stock_address,
    django_user_model,
    basename,
    model_name,
):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_user(
        username=f'ator-criacao-terminal-{basename}',
        email=f'ator-criacao-terminal-{basename}@example.com',
    )
    production_order.status = ProductionOrder.Status.COMPLETED
    production_order.save(update_fields=['status', 'updated_at'])
    warehouse, location = stock_address
    payloads = {
        'output': {
            'order': production_order.pk,
            'product': production_order.product_id,
            'lot_number': production_order.batch_number,
            'sublot_number': 'TERMINAL',
            'planned_quantity': '100.0000',
            'unit': production_order.unit_id,
            'warehouse': warehouse.pk,
            'location': location.pk,
        },
        'labor-entry': {
            'order': production_order.pk,
            'user': actor.pk,
            'role': 'Operador',
            'started_at': (timezone.now() - timedelta(minutes=30)).isoformat(),
            'ended_at': timezone.now().isoformat(),
        },
    }
    client = _production_resource_client(actor, model_name)
    audit_count = GovernanceAuditLog.objects.count()

    response = client.post(reverse(f'production:{basename}-list'), payloads[basename])

    assert response.status_code == 400
    assert 'order' in response.data
    assert GovernanceAuditLog.objects.count() == audit_count


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('status_value', 'started_offset', 'ended_offset', 'notes', 'invalid_field'),
    [
        (ProductionOperationExecution.Status.PENDING, 0, None, '', 'started_at'),
        (ProductionOperationExecution.Status.IN_PROGRESS, None, None, '', 'started_at'),
        (ProductionOperationExecution.Status.IN_PROGRESS, 0, 1, '', 'ended_at'),
        (ProductionOperationExecution.Status.COMPLETED, 0, None, '', 'ended_at'),
        (ProductionOperationExecution.Status.SKIPPED, None, None, '', 'notes'),
    ],
)
def test_operation_model_rejects_incoherent_status_evidence(
    production_order,
    operations_user,
    status_value,
    started_offset,
    ended_offset,
    notes,
    invalid_field,
):
    now = timezone.now()
    operation = ProductionOperationExecution(
        order=production_order,
        sequence=93,
        operation='Coerência de estado',
        status=status_value,
        started_at=now + timedelta(minutes=started_offset) if started_offset is not None else None,
        ended_at=now + timedelta(minutes=ended_offset) if ended_offset is not None else None,
        recorded_by=operations_user,
        notes=notes,
    )

    with pytest.raises(ValidationError) as error:
        operation.full_clean()

    assert invalid_field in error.value.message_dict


@pytest.mark.django_db
def test_database_rejects_operation_status_without_coherent_evidence(production_order):
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductionOperationExecution.objects.create(
            order=production_order,
            sequence=94,
            operation='Estado incoerente no banco',
            status=ProductionOperationExecution.Status.PENDING,
            started_at=timezone.now(),
        )


@pytest.mark.django_db
def test_database_rejects_skipped_operation_with_whitespace_reason(
    production_order,
    operations_user,
):
    with pytest.raises(IntegrityError), transaction.atomic():
        ProductionOperationExecution.objects.create(
            order=production_order,
            sequence=95,
            operation='Justificativa em branco',
            status=ProductionOperationExecution.Status.SKIPPED,
            recorded_by=operations_user,
            notes='   ',
        )


@pytest.mark.django_db
def test_received_output_model_rejects_changes_after_receipt(received_output):
    received_output.full_clean()
    received_output.save()
    received_output.order.status = ProductionOrder.Status.CLOSED
    received_output.order.save(update_fields=['status', 'updated_at'])
    received_output.full_clean()
    received_output.notes = 'tentativa por caminho interno'

    with pytest.raises(ValidationError) as error:
        received_output.full_clean()

    assert 'status' in error.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize(
    'terminal_status',
    [
        ProductionOperationExecution.Status.COMPLETED,
        ProductionOperationExecution.Status.SKIPPED,
    ],
)
def test_terminal_operation_model_rejects_changes(
    production_order,
    operations_user,
    terminal_status,
):
    now = timezone.now()
    values = {
        'order': production_order,
        'sequence': 96,
        'operation': 'Operação terminal',
        'status': ProductionOperationExecution.Status.PENDING,
    }
    if terminal_status == ProductionOperationExecution.Status.COMPLETED:
        values.update(
            status=terminal_status,
            recorded_by=operations_user,
            started_at=now - timedelta(minutes=20),
            ended_at=now,
        )
    operation = ProductionOperationExecution(**values)
    operation.full_clean()
    operation.save()
    if terminal_status == ProductionOperationExecution.Status.SKIPPED:
        operation.status = terminal_status
        operation.recorded_by = operations_user
        operation.notes = 'Motivo de não execução'
        operation.full_clean()
        operation.save()
    operation.notes = 'tentativa por caminho interno'

    with pytest.raises(ValidationError) as error:
        operation.full_clean()

    assert 'status' in error.value.message_dict


@pytest.mark.django_db
def test_operation_model_rejects_creating_skipped_without_a_prior_pending_transition(
    production_order,
    operations_user,
):
    operation = ProductionOperationExecution(
        order=production_order,
        sequence=97,
        operation='Operação dispensada sem histórico',
        status=ProductionOperationExecution.Status.SKIPPED,
        recorded_by=operations_user,
        notes='A etapa não se aplicava ao lote.',
    )

    with pytest.raises(ValidationError) as error:
        operation.full_clean()

    assert error.value.message_dict['status'] == [
        'Crie a operação pendente antes de registrar que ela não foi executada.'
    ]


@pytest.mark.django_db
def test_labor_model_rejects_creation_and_change_after_order_is_terminal(
    production_order,
    operations_user,
):
    started_at = timezone.now() - timedelta(minutes=30)
    production_order.status = ProductionOrder.Status.RELEASED
    production_order.save(update_fields=['status', 'updated_at'])
    existing = ProductionLaborEntry(
        order=production_order,
        user=operations_user,
        role='Operador',
        started_at=started_at,
        ended_at=timezone.now(),
    )
    existing.full_clean()
    existing.save()
    production_order.status = ProductionOrder.Status.COMPLETED
    production_order.save(update_fields=['status', 'updated_at'])

    new_entry = ProductionLaborEntry(
        order=production_order,
        user=operations_user,
        role='Operador',
        started_at=started_at,
        ended_at=timezone.now(),
    )
    with pytest.raises(ValidationError) as create_error:
        new_entry.full_clean()
    assert 'order' in create_error.value.message_dict

    existing.full_clean()
    existing.role = 'Supervisor'
    with pytest.raises(ValidationError) as update_error:
        existing.full_clean()
    assert 'order' in update_error.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize(
    'terminal_status',
    [
        ProductionOrder.Status.COMPLETED,
        ProductionOrder.Status.CANCELLED,
        ProductionOrder.Status.CLOSED,
    ],
)
def test_pending_output_model_rejects_creation_and_change_for_terminal_order(
    production_output,
    terminal_status,
    operations_user,
):
    order = production_output.order
    if terminal_status == ProductionOrder.Status.CANCELLED:
        order.cancel('Fixture terminal', operations_user)
    else:
        order.status = terminal_status
        order.save(update_fields=['status', 'updated_at'])

    production_output.full_clean()

    new_output = ProductionOutput(
        order=order,
        product=order.product,
        lot_number=order.batch_number,
        sublot_number=f'NOVO-{terminal_status}',
        planned_quantity=order.planned_quantity,
        produced_quantity=Decimal('1.0000'),
        unit=order.unit,
    )
    with pytest.raises(ValidationError) as create_error:
        new_output.full_clean()
    assert 'order' in create_error.value.message_dict

    production_output.notes = 'tentativa por caminho interno'
    with pytest.raises(ValidationError) as update_error:
        production_output.full_clean()
    assert 'order' in update_error.value.message_dict


@pytest.mark.django_db
@pytest.mark.parametrize(
    'invalid_status',
    [
        ProductionOrder.Status.DRAFT,
        ProductionOrder.Status.APPROVED,
        ProductionOrder.Status.COMPLETED,
        ProductionOrder.Status.CANCELLED,
        ProductionOrder.Status.CLOSED,
    ],
)
def test_labor_model_rejects_creation_outside_operational_order_statuses(
    production_order,
    operations_user,
    invalid_status,
):
    if invalid_status == ProductionOrder.Status.CANCELLED:
        production_order.cancel('Fixture terminal', operations_user)
    else:
        production_order.status = invalid_status
        production_order.save(update_fields=['status', 'updated_at'])

    labor = ProductionLaborEntry(
        order=production_order,
        user=operations_user,
        role='Operador',
        started_at=timezone.now() - timedelta(minutes=30),
        ended_at=timezone.now(),
    )

    with pytest.raises(ValidationError) as error:
        labor.full_clean()

    assert 'order' in error.value.message_dict


@pytest.mark.django_db
@pytest.mark.permission_strict
@pytest.mark.parametrize(
    ('basename', 'model_name', 'model_class'),
    [
        ('output', 'productionoutput', ProductionOutput),
        (
            'operation',
            'productionoperationexecution',
            ProductionOperationExecution,
        ),
        ('labor-entry', 'productionlaborentry', ProductionLaborEntry),
    ],
)
def test_operational_resource_api_calls_full_clean_once_per_post_and_patch(
    production_order,
    stock_address,
    django_user_model,
    basename,
    model_name,
    model_class,
):
    actor = django_user_model.objects.create_user(
        username=f'ator-full-clean-{basename}',
        email=f'ator-full-clean-{basename}@example.com',
    )
    production_order.status = ProductionOrder.Status.IN_PROGRESS
    production_order.save(update_fields=['status', 'updated_at'])
    warehouse, location = stock_address
    started_at = timezone.now() - timedelta(minutes=30)
    payloads = {
        'output': {
            'order': production_order.pk,
            'product': production_order.product_id,
            'lot_number': production_order.batch_number,
            'sublot_number': 'FULL-CLEAN',
            'planned_quantity': '100.0000',
            'unit': production_order.unit_id,
            'warehouse': warehouse.pk,
            'location': location.pk,
        },
        'operation': {
            'order': production_order.pk,
            'sequence': 97,
            'operation': 'Full clean único',
        },
        'labor-entry': {
            'order': production_order.pk,
            'user': actor.pk,
            'role': 'Operador',
            'started_at': started_at.isoformat(),
            'ended_at': timezone.now().isoformat(),
        },
    }
    client = _production_resource_client(actor, model_name)

    with patch.object(
        model_class,
        'full_clean',
        autospec=True,
        side_effect=model_class.full_clean,
    ) as full_clean:
        created = client.post(reverse(f'production:{basename}-list'), payloads[basename])
        assert created.status_code == 201, created.data
        assert full_clean.call_count == 1

        updated = client.patch(
            reverse(f'production:{basename}-detail', args=[created.data['id']]),
            {'notes': 'correção antes do estado terminal'},
        )
        assert updated.status_code == 200, updated.data
        assert full_clean.call_count == 2


@requires_postgresql
@pytest.mark.django_db(transaction=True)
@pytest.mark.permission_strict
def test_output_patch_revalidates_after_concurrent_receipt(
    production_output,
    allocated_consumption,
    operations_user,
):
    from production.services import ProductionOrderOperations
    from production.views import NonDestructiveProductionViewSet

    order = production_output.order
    allocated_consumption.actual_quantity = Decimal('4.0000')
    allocated_consumption.issued_quantity = Decimal('4.0000')
    allocated_consumption.save(update_fields=['actual_quantity', 'issued_quantity', 'updated_at'])
    allocated_consumption.issue_movement = create_consumption_movement(
        allocated_consumption,
        StockMovement.MovementType.ISSUE,
        quantity=Decimal('4.0000'),
    )
    allocated_consumption.save(update_fields=['issue_movement', 'updated_at'])
    # Prepare all material evidence before making the order terminal.
    order.status = ProductionOrder.Status.COMPLETED
    order.save(update_fields=['status', 'updated_at'])
    _production_resource_client(operations_user, 'productionoutput')
    receive_locked = Event()
    update_attempted_order_lock = Event()
    original_service_lock = ProductionOrderOperations._locked_order
    original_api_lock = NonDestructiveProductionViewSet._lock_order

    def locked_order_for_receipt(service):
        locked_order = original_service_lock(service)
        receive_locked.set()
        assert update_attempted_order_lock.wait(timeout=5)
        return locked_order

    def notify_api_order_lock(order_id):
        update_attempted_order_lock.set()
        return original_api_lock(order_id)

    def receive():
        close_old_connections()
        try:
            thread_order = ProductionOrder.objects.get(pk=order.pk)
            thread_user = type(operations_user).objects.get(pk=operations_user.pk)
            return ProductionOrderOperations(thread_order, thread_user).receive_outputs()[0].pk
        finally:
            connection.close()

    def update():
        close_old_connections()
        try:
            thread_user = type(operations_user).objects.get(pk=operations_user.pk)
            thread_client = APIClient()
            thread_client.force_authenticate(thread_user)
            return thread_client.patch(
                reverse('production:output-detail', args=[production_output.pk]),
                {'notes': 'não pode sobrescrever o recebimento'},
            )
        finally:
            connection.close()

    with (
        patch.object(ProductionOrderOperations, '_locked_order', locked_order_for_receipt),
        patch.object(
            NonDestructiveProductionViewSet,
            '_lock_order',
            side_effect=notify_api_order_lock,
        ),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        receive_future = executor.submit(receive)
        assert receive_locked.wait(timeout=5)
        update_future = executor.submit(update)
        received_id = receive_future.result(timeout=10)
        response = update_future.result(timeout=10)

    assert received_id == production_output.pk
    assert response.status_code == 400
    production_output.refresh_from_db()
    assert production_output.status == ProductionOutput.Status.RECEIVED
    assert production_output.stock_lot_id is not None
    assert production_output.stock_movement_id is not None
    assert production_output.received_by_id == operations_user.pk
    assert production_output.received_at is not None
    assert production_output.notes == ''


@requires_postgresql
@pytest.mark.django_db(transaction=True)
@pytest.mark.permission_strict
def test_operation_patch_revalidates_after_concurrent_completion(
    production_order,
    operations_user,
):
    from production.views import NonDestructiveProductionViewSet

    operation = ProductionOperationExecution.objects.create(
        order=production_order,
        sequence=98,
        operation='Conclusão concorrente',
    )
    _production_resource_client(operations_user, 'productionoperationexecution')
    completion_locked = Event()
    update_attempted_order_lock = Event()
    original_api_lock = NonDestructiveProductionViewSet._lock_order

    def notify_api_order_lock(order_id):
        update_attempted_order_lock.set()
        return original_api_lock(order_id)

    def complete():
        close_old_connections()
        try:
            with transaction.atomic():
                locked_order = ProductionOrder.objects.select_for_update().get(
                    pk=production_order.pk
                )
                locked_operation = (
                    ProductionOperationExecution.objects.select_for_update()
                    .select_related('order')
                    .get(pk=operation.pk)
                )
                locked_operation.order = locked_order
                completion_locked.set()
                assert update_attempted_order_lock.wait(timeout=5)
                locked_operation.status = ProductionOperationExecution.Status.COMPLETED
                locked_operation.started_at = timezone.now() - timedelta(minutes=20)
                locked_operation.ended_at = timezone.now()
                locked_operation.recorded_by_id = operations_user.pk
                locked_operation.full_clean()
                locked_operation.save()
        finally:
            connection.close()

    def update():
        close_old_connections()
        try:
            thread_user = type(operations_user).objects.get(pk=operations_user.pk)
            thread_client = APIClient()
            thread_client.force_authenticate(thread_user)
            return thread_client.patch(
                reverse('production:operation-detail', args=[operation.pk]),
                {'notes': 'não pode sobrescrever a conclusão'},
            )
        finally:
            connection.close()

    with (
        patch.object(
            NonDestructiveProductionViewSet,
            '_lock_order',
            side_effect=notify_api_order_lock,
        ),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        completion_future = executor.submit(complete)
        assert completion_locked.wait(timeout=5)
        update_future = executor.submit(update)
        completion_future.result(timeout=10)
        response = update_future.result(timeout=10)

    assert response.status_code == 400
    operation.refresh_from_db()
    assert operation.status == ProductionOperationExecution.Status.COMPLETED
    assert operation.started_at is not None
    assert operation.ended_at is not None
    assert operation.actual_minutes == Decimal('20.00')
    assert operation.recorded_by_id == operations_user.pk
    assert operation.notes == ''


@requires_postgresql
@pytest.mark.django_db(transaction=True)
@pytest.mark.permission_strict
@pytest.mark.parametrize('mutation', ['create', 'update'])
def test_labor_write_revalidates_after_order_becomes_terminal(
    production_order,
    operations_user,
    mutation,
):
    from production.views import NonDestructiveProductionViewSet

    production_order.status = ProductionOrder.Status.IN_PROGRESS
    production_order.save(update_fields=['status', 'updated_at'])
    started_at = timezone.now() - timedelta(minutes=30)
    entry = ProductionLaborEntry(
        order=production_order,
        user=operations_user,
        role='Operador',
        started_at=started_at,
        ended_at=timezone.now(),
    )
    entry.full_clean()
    entry.save()
    _production_resource_client(operations_user, 'productionlaborentry')
    terminal_locked = Event()
    mutation_attempted_order_lock = Event()
    original_api_lock = NonDestructiveProductionViewSet._lock_order

    def notify_api_order_lock(order_id):
        mutation_attempted_order_lock.set()
        return original_api_lock(order_id)

    def terminate_order():
        close_old_connections()
        try:
            with transaction.atomic():
                locked_order = ProductionOrder.objects.select_for_update().get(
                    pk=production_order.pk
                )
                terminal_locked.set()
                assert mutation_attempted_order_lock.wait(timeout=5)
                locked_order.status = ProductionOrder.Status.COMPLETED
                locked_order.save(update_fields=['status', 'updated_at'])
        finally:
            connection.close()

    def mutate_labor():
        close_old_connections()
        try:
            thread_user = type(operations_user).objects.get(pk=operations_user.pk)
            thread_client = APIClient()
            thread_client.force_authenticate(thread_user)
            if mutation == 'create':
                return thread_client.post(
                    reverse('production:labor-entry-list'),
                    {
                        'order': production_order.pk,
                        'user': operations_user.pk,
                        'role': 'Novo operador concorrente',
                        'started_at': started_at.isoformat(),
                        'ended_at': timezone.now().isoformat(),
                    },
                )
            return thread_client.patch(
                reverse('production:labor-entry-detail', args=[entry.pk]),
                {'role': 'Supervisor concorrente'},
            )
        finally:
            connection.close()

    with (
        patch.object(
            NonDestructiveProductionViewSet,
            '_lock_order',
            side_effect=notify_api_order_lock,
        ),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        terminal_future = executor.submit(terminate_order)
        assert terminal_locked.wait(timeout=5)
        mutation_future = executor.submit(mutate_labor)
        terminal_future.result(timeout=10)
        response = mutation_future.result(timeout=10)

    assert response.status_code == 400
    entry.refresh_from_db()
    assert entry.role == 'Operador'
    assert not ProductionLaborEntry.objects.filter(role='Novo operador concorrente').exists()


@pytest.mark.django_db
def test_production_execution_workspace_renders_accessible_operational_tabs(
    client, production_order, django_user_model
):
    user = django_user_model.objects.create_superuser(
        username='workspace-operator',
        email='workspace-operator@example.com',
        password='S3curePass!123',
    )
    client.force_login(user)

    response = client.get(
        reverse('app:resource_execute', args=['production', 'orders', production_order.pk])
    )

    assert response.status_code == 200
    content = response.content.decode()
    assert 'role="tablist"' in content
    assert 'aria-label="Domínios operacionais da ordem"' in content
    for key, label in (
        ('material-consumptions', 'Matérias-primas'),
        ('outputs', 'Produtos acabados'),
        ('operations', 'Processos'),
        ('labor-entries', 'Colaboradores'),
    ):
        assert f'id="production-tab-{key}"' in content
        assert f'id="production-panel-{key}"' in content
        assert f'{key}-TOTAL_FORMS' in content
        assert label in content
    assert 'production-tab-material-consumptions"' in content
    assert 'aria-selected="true"' in content
    assert 'actual_minutes' not in content
    assert 'duration_minutes' not in content
    assert '-DELETE' not in content


@pytest.mark.django_db
def test_standard_production_order_creation_does_not_take_execution_locks(
    client, production_order, django_user_model
):
    user = django_user_model.objects.create_superuser(
        username='production-order-creator',
        email='production-order-creator@example.com',
        password='S3curePass!123',
    )
    client.force_login(user)

    response = client.post(
        reverse('app:resource_create', args=['production', 'orders']),
        {
            'product': production_order.product_id,
            'formula': production_order.formula_id,
            'route': production_order.route_id,
            'planned_quantity': '25.0000',
            'unit': production_order.unit_id,
            'priority': ProductionOrder.Priority.NORMAL,
            'material-consumptions-TOTAL_FORMS': '0',
            'material-consumptions-INITIAL_FORMS': '0',
            'material-consumptions-MIN_NUM_FORMS': '0',
            'material-consumptions-MAX_NUM_FORMS': '1000',
            'outputs-TOTAL_FORMS': '0',
            'outputs-INITIAL_FORMS': '0',
            'outputs-MIN_NUM_FORMS': '0',
            'outputs-MAX_NUM_FORMS': '1000',
            'operations-TOTAL_FORMS': '0',
            'operations-INITIAL_FORMS': '0',
            'operations-MIN_NUM_FORMS': '0',
            'operations-MAX_NUM_FORMS': '1000',
            'labor-entries-TOTAL_FORMS': '0',
            'labor-entries-INITIAL_FORMS': '0',
            'labor-entries-MIN_NUM_FORMS': '0',
            'labor-entries-MAX_NUM_FORMS': '1000',
        },
    )

    assert response.status_code == 302
    created_order = ProductionOrder.objects.exclude(pk=production_order.pk).latest('created_at')
    assert created_order.order_number.startswith(f'OP-{timezone.localdate():%Y%m%d}-')


def _production_order_ui_payload(order):
    """Return the persisted order fields required by the generic UI form."""
    payload = {
        'product': order.product_id,
        'formula': order.formula_id,
        'route': order.route_id,
        'planned_quantity': str(order.planned_quantity),
        'unit': order.unit_id,
        'priority': order.priority,
        'status': order.status,
        'material-consumptions-TOTAL_FORMS': '0',
        'material-consumptions-INITIAL_FORMS': '0',
        'material-consumptions-MIN_NUM_FORMS': '0',
        'material-consumptions-MAX_NUM_FORMS': '1000',
        'outputs-TOTAL_FORMS': '0',
        'outputs-INITIAL_FORMS': '0',
        'outputs-MIN_NUM_FORMS': '0',
        'outputs-MAX_NUM_FORMS': '1000',
        'operations-TOTAL_FORMS': '0',
        'operations-INITIAL_FORMS': '0',
        'operations-MIN_NUM_FORMS': '0',
        'operations-MAX_NUM_FORMS': '1000',
        'labor-entries-TOTAL_FORMS': '0',
        'labor-entries-INITIAL_FORMS': '0',
        'labor-entries-MIN_NUM_FORMS': '0',
        'labor-entries-MAX_NUM_FORMS': '1000',
    }
    return payload


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_execution_board_exposes_unavailable_panel_without_querying_or_rendering_child_forms(
    client, production_order, django_user_model
):
    """A parent editor cannot discover child records without the child view permission."""
    user = django_user_model.objects.create_user(
        username='sem-visao-operacional', email='sem-visao-operacional@example.com'
    )
    _grant_permissions(
        user,
        'production.view_productionorder',
        'production.change_productionorder',
    )
    ProductionLaborEntry.objects.create(
        order=production_order,
        user=user,
        role='Segredo de custo',
        started_at=timezone.now() - timedelta(minutes=30),
        ended_at=timezone.now(),
        hourly_cost=Decimal('999.0000'),
    )
    client.force_login(user)

    response = client.get(
        reverse('app:resource_execute', args=['production', 'orders', production_order.pk])
    )

    assert response.status_code == 200
    unavailable = {inline['key']: inline for inline in response.context['inline_formsets']}
    assert set(unavailable) == {
        'material-consumptions',
        'outputs',
        'operations',
        'labor-entries',
    }
    assert all(
        not inline['available'] and inline['formset'] is None for inline in unavailable.values()
    )
    content = response.content.decode()
    assert 'Colaboradores' in content
    assert 'Você não possui permissão para visualizar estes registros.' in content
    for key in unavailable:
        assert f'{key}-TOTAL_FORMS' not in content
    assert 'Segredo de custo' not in content
    assert '999.0000' not in content


@pytest.mark.django_db
def test_operation_inline_assigns_actor_before_model_form_validation(
    production_order, django_user_model
):
    """A server-controlled actor satisfies completed-operation validation without a client field."""
    from base.ui.registry import get_resource
    from base.ui.views import _build_inline_form_class

    actor = django_user_model.objects.create_user(
        username='ator-formset-ui', email='ator-formset-ui@example.com'
    )
    production_order.status = ProductionOrder.Status.IN_PROGRESS
    production_order.save(update_fields=['status', 'updated_at'])
    operation_inline = next(
        inline
        for inline in get_resource('production', 'orders').inlines
        if inline.key == 'operations'
    )
    request = RequestFactory().post('/')
    request.user = actor
    started_at = timezone.now() - timedelta(minutes=20)
    ended_at = timezone.now()

    form = _build_inline_form_class(operation_inline)(
        data={
            'sequence': '91',
            'operation': 'Apontamento assinado na UI',
            'planned_minutes': '0.00',
            'machine_hourly_cost': '0.0000',
            'status': ProductionOperationExecution.Status.COMPLETED,
            'started_at': started_at.isoformat(),
            'ended_at': ended_at.isoformat(),
        },
        request=request,
    )
    form.instance.order = production_order

    assert form.is_valid(), form.errors
    assert form.instance.recorded_by == actor
    assert form.instance.actual_minutes == Decimal('20.00')


@pytest.mark.django_db
def test_execution_post_keeps_unchanged_terminal_operation_actor(
    production_order, client, django_user_model
):
    """Opening another field must not rewrite an immutable operation's actor."""
    original_actor = django_user_model.objects.create_user(
        username='ator-terminal-original', email='ator-terminal-original@example.com'
    )
    editor = django_user_model.objects.create_superuser(
        username='editor-terminal-ui',
        email='editor-terminal-ui@example.com',
        password='S3curePass!123',
    )
    production_order.status = ProductionOrder.Status.IN_PROGRESS
    production_order.save(update_fields=['status', 'updated_at'])
    ended_at = timezone.now()
    operation = ProductionOperationExecution(
        order=production_order,
        sequence=90,
        operation='Etapa terminal preservada',
        status=ProductionOperationExecution.Status.COMPLETED,
        recorded_by=original_actor,
        started_at=ended_at - timedelta(minutes=15),
        ended_at=ended_at,
    )
    operation.full_clean()
    operation.save()
    client.force_login(editor)
    payload = _production_order_ui_payload(production_order)
    payload.update(
        {
            'operations-TOTAL_FORMS': '1',
            'operations-INITIAL_FORMS': '1',
            'operations-0-id': operation.pk,
            'operations-0-sequence': operation.sequence,
            'operations-0-operation': operation.operation,
            'operations-0-planned_minutes': operation.planned_minutes,
            'operations-0-machine_hourly_cost': operation.machine_hourly_cost,
            'operations-0-status': operation.status,
            'operations-0-started_at': operation.started_at.isoformat(),
            'operations-0-ended_at': operation.ended_at.isoformat(),
        }
    )

    response = client.post(
        reverse('app:resource_execute', args=['production', 'orders', production_order.pk]),
        payload,
    )

    assert response.status_code == 302
    operation.refresh_from_db()
    assert operation.recorded_by == original_actor


def _operation_inline_payload(order, *, status, sequence=91, started_at=None, ended_at=None):
    payload = _production_order_ui_payload(order)
    payload.update(
        {
            'operations-TOTAL_FORMS': '1',
            'operations-INITIAL_FORMS': '0',
            'operations-0-sequence': str(sequence),
            'operations-0-operation': f'Operação UI {status}',
            'operations-0-planned_minutes': '0.00',
            'operations-0-machine_hourly_cost': '0.0000',
            'operations-0-status': status,
        }
    )
    if started_at is not None:
        payload['operations-0-started_at'] = started_at.isoformat()
    if ended_at is not None:
        payload['operations-0-ended_at'] = ended_at.isoformat()
    if status == ProductionOperationExecution.Status.SKIPPED:
        payload['operations-0-notes'] = 'Etapa dispensada com justificativa.'
    return payload


@pytest.mark.django_db
@pytest.mark.parametrize(
    ('status', 'needs_start', 'needs_end', 'expected_minutes'),
    (
        (ProductionOperationExecution.Status.PENDING, False, False, Decimal('0.00')),
        (ProductionOperationExecution.Status.IN_PROGRESS, True, False, Decimal('0.00')),
        (ProductionOperationExecution.Status.COMPLETED, True, True, Decimal('20.00')),
    ),
)
def test_execution_post_creates_operation_with_server_actor_duration_and_single_audit(
    client, production_order, django_user_model, status, needs_start, needs_end, expected_minutes
):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_superuser(
        username=f'actor-execute-{status}',
        email=f'actor-execute-{status}@example.com',
        password='S3curePass!123',
    )
    production_order.status = ProductionOrder.Status.IN_PROGRESS
    production_order.save(update_fields=['status', 'updated_at'])
    client.force_login(actor)
    ended_at = timezone.now()
    started_at = ended_at - timedelta(minutes=20)
    payload = _operation_inline_payload(
        production_order,
        status=status,
        sequence=100 + len(status),
        started_at=started_at if needs_start else None,
        ended_at=ended_at if needs_end else None,
    )

    response = client.post(
        reverse('app:resource_execute', args=['production', 'orders', production_order.pk]),
        payload,
    )

    assert response.status_code == 302, getattr(response, 'context', None)
    operation = ProductionOperationExecution.objects.get(
        order=production_order, sequence=100 + len(status)
    )
    assert operation.recorded_by == actor
    assert operation.actual_minutes == expected_minutes
    assert (
        GovernanceAuditLog.objects.filter(
            action='ui.resource.updated',
            target_model='ProductionOrder',
            target_record_id=str(production_order.pk),
        ).count()
        == 1
    )


@pytest.mark.django_db
def test_execution_post_rejects_creating_skipped_operation_without_persisting_or_audit(
    client, production_order, django_user_model
):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_superuser(
        username='actor-execute-skipped-create',
        email='actor-execute-skipped-create@example.com',
        password='S3curePass!123',
    )
    production_order.status = ProductionOrder.Status.IN_PROGRESS
    production_order.save(update_fields=['status', 'updated_at'])
    client.force_login(actor)
    payload = _operation_inline_payload(
        production_order,
        status=ProductionOperationExecution.Status.SKIPPED,
        sequence=117,
    )
    audit_count = GovernanceAuditLog.objects.count()

    response = client.post(
        reverse('app:resource_execute', args=['production', 'orders', production_order.pk]),
        payload,
    )

    assert response.status_code == 200
    assert (
        'Crie a operação pendente antes de registrar que ela não foi executada.'
        in response.content.decode()
    )
    assert not ProductionOperationExecution.objects.filter(
        order=production_order, sequence=117
    ).exists()
    assert GovernanceAuditLog.objects.count() == audit_count


@pytest.mark.django_db
def test_execution_post_transitions_pending_operation_to_skipped_with_actor_notes_and_audit(
    client, production_order, django_user_model
):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_superuser(
        username='actor-execute-skipped-transition',
        email='actor-execute-skipped-transition@example.com',
        password='S3curePass!123',
    )
    production_order.status = ProductionOrder.Status.IN_PROGRESS
    production_order.save(update_fields=['status', 'updated_at'])
    pending = ProductionOperationExecution(
        order=production_order,
        sequence=118,
        operation='Operação dispensada com trilha',
        status=ProductionOperationExecution.Status.PENDING,
    )
    pending.full_clean()
    pending.save()
    client.force_login(actor)
    payload = _production_order_ui_payload(production_order)
    payload.update(
        {
            'operations-TOTAL_FORMS': '1',
            'operations-INITIAL_FORMS': '1',
            'operations-0-id': pending.pk,
            'operations-0-sequence': pending.sequence,
            'operations-0-operation': pending.operation,
            'operations-0-planned_minutes': pending.planned_minutes,
            'operations-0-machine_hourly_cost': pending.machine_hourly_cost,
            'operations-0-status': ProductionOperationExecution.Status.SKIPPED,
            'operations-0-notes': 'Etapa dispensada conforme desvio aprovado.',
        }
    )
    audit_count = GovernanceAuditLog.objects.filter(
        action='ui.resource.updated',
        target_model='ProductionOrder',
        target_record_id=str(production_order.pk),
    ).count()

    response = client.post(
        reverse('app:resource_execute', args=['production', 'orders', production_order.pk]),
        payload,
    )

    assert response.status_code == 302
    pending.refresh_from_db()
    assert pending.status == ProductionOperationExecution.Status.SKIPPED
    assert pending.recorded_by == actor
    assert pending.notes == 'Etapa dispensada conforme desvio aprovado.'
    assert (
        GovernanceAuditLog.objects.filter(
            action='ui.resource.updated',
            target_model='ProductionOrder',
            target_record_id=str(production_order.pk),
        ).count()
        == audit_count + 1
    )


@pytest.mark.django_db
def test_execution_rolls_back_inline_write_when_functional_audit_fails(
    client, production_order, django_user_model
):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_superuser(
        username='actor-audit-rollback-ui',
        email='actor-audit-rollback-ui@example.com',
        password='S3curePass!123',
    )
    client.force_login(actor)
    payload = _operation_inline_payload(
        production_order,
        status=ProductionOperationExecution.Status.PENDING,
        sequence=199,
    )

    with patch.object(GovernanceAuditLog, 'record', side_effect=RuntimeError('audit failure')):
        with pytest.raises(RuntimeError, match='audit failure'):
            client.post(
                reverse('app:resource_execute', args=['production', 'orders', production_order.pk]),
                payload,
            )

    assert not ProductionOperationExecution.objects.filter(
        order=production_order, sequence=199
    ).exists()


@pytest.mark.django_db
@pytest.mark.permission_strict
@pytest.mark.parametrize(
    'inline_key', ('material-consumptions', 'outputs', 'operations', 'labor-entries')
)
def test_execution_rejects_posted_management_form_for_inline_without_view_permission(
    client, production_order, django_user_model, inline_key
):
    user = django_user_model.objects.create_user(
        username=f'sem-visao-{inline_key}', email=f'sem-visao-{inline_key}@example.com'
    )
    _grant_permissions(
        user,
        'production.view_productionorder',
        'production.change_productionorder',
    )
    client.force_login(user)
    payload = _production_order_ui_payload(production_order)
    payload[f'{inline_key}-TOTAL_FORMS'] = '0'

    response = client.post(
        reverse('app:resource_execute', args=['production', 'orders', production_order.pk]),
        payload,
    )

    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_production_order_new_rejects_forged_operational_inline_rows(
    client, production_order, django_user_model
):
    user = django_user_model.objects.create_superuser(
        username='forged-new-operator',
        email='forged-new-operator@example.com',
        password='S3curePass!123',
    )
    client.force_login(user)
    payload = _production_order_ui_payload(production_order)
    payload.update(
        {
            'order_number': 'OP-UI-FORGED-NEW',
            'outputs-TOTAL_FORMS': '1',
            'outputs-0-product': production_order.product_id,
            'outputs-0-lot_number': 'LOTE-FORJADO',
            'outputs-0-planned_quantity': '1.0000',
            'outputs-0-produced_quantity': '1.0000',
            'outputs-0-unit': production_order.unit_id,
        }
    )

    response = client.post(reverse('app:resource_create', args=['production', 'orders']), payload)

    assert response.status_code in {200, 403}
    assert not ProductionOrder.objects.filter(order_number='OP-UI-FORGED-NEW').exists()
    assert not ProductionOutput.objects.filter(lot_number='LOTE-FORJADO').exists()


@pytest.mark.django_db
def test_execution_save_converts_locked_inline_revalidation_error_into_form_error(
    client, production_order, django_user_model
):
    """A race detected after the lock is a recoverable form response, not a 500."""
    user = django_user_model.objects.create_superuser(
        username='revalidation-ui-operator',
        email='revalidation-ui-operator@example.com',
        password='S3curePass!123',
    )
    client.force_login(user)
    payload = _production_order_ui_payload(production_order)
    payload.update(
        {
            'outputs-TOTAL_FORMS': '1',
            'outputs-0-product': production_order.product_id,
            'outputs-0-lot_number': 'LOTE-REVALIDACAO',
            'outputs-0-planned_quantity': '1.0000',
            'outputs-0-produced_quantity': '1.0000',
            'outputs-0-unit': production_order.unit_id,
        }
    )
    original_full_clean = ProductionOutput.full_clean
    calls = 0

    def fail_only_after_formset_validation(instance, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise ValidationError({'status': 'O estado mudou durante o apontamento.'})
        return original_full_clean(instance, *args, **kwargs)

    with patch.object(ProductionOutput, 'full_clean', fail_only_after_formset_validation):
        response = client.post(
            reverse('app:resource_execute', args=['production', 'orders', production_order.pk]),
            payload,
        )

    assert response.status_code == 200, response.context['inline_formsets'][1]['formset'].errors
    content = response.content.decode()
    assert 'O estado mudou durante o apontamento.' in content
    assert '<tr class="resource-inline-formset__error">' in content
    assert 'colspan="11"' in content
    assert not ProductionOutput.objects.filter(lot_number='LOTE-REVALIDACAO').exists()


@pytest.mark.django_db
def test_execution_save_converts_locked_order_revalidation_error_into_main_form_error(
    client, production_order, django_user_model
):
    """A stale parent order returns a controlled response and rolls back every write."""
    from governance.models import GovernanceAuditLog

    user = django_user_model.objects.create_superuser(
        username='locked-order-revalidation-ui',
        email='locked-order-revalidation-ui@example.com',
        password='S3curePass!123',
    )
    client.force_login(user)
    payload = _production_order_ui_payload(production_order)
    payload['notes'] = 'Não deve persistir após revalidação bloqueada.'
    original_full_clean = ProductionOrder.full_clean
    calls = 0
    audit_count = GovernanceAuditLog.objects.filter(
        target_model='ProductionOrder', target_record_id=str(production_order.pk)
    ).count()

    def fail_after_initial_form_validation(instance, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls >= 2:
            raise ValidationError({'notes': 'A ordem mudou durante o apontamento.'})
        return original_full_clean(instance, *args, **kwargs)

    with patch.object(ProductionOrder, 'full_clean', fail_after_initial_form_validation):
        response = client.post(
            reverse('app:resource_execute', args=['production', 'orders', production_order.pk]),
            payload,
        )

    assert response.status_code == 200
    assert 'A ordem mudou durante o apontamento.' in response.content.decode()
    production_order.refresh_from_db()
    assert production_order.notes != 'Não deve persistir após revalidação bloqueada.'
    assert (
        GovernanceAuditLog.objects.filter(
            target_model='ProductionOrder', target_record_id=str(production_order.pk)
        ).count()
        == audit_count
    )


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_execution_defaults_to_first_available_tab_when_no_tab_has_errors(
    client, production_order, django_user_model
):
    user = django_user_model.objects.create_user(
        username='first-available-execution-tab',
        email='first-available-execution-tab@example.com',
    )
    _grant_permissions(
        user,
        'production.view_productionorder',
        'production.change_productionorder',
        'production.view_productionoperationexecution',
    )
    client.force_login(user)

    response = client.get(
        reverse('app:resource_execute', args=['production', 'orders', production_order.pk])
    )

    assert response.status_code == 200
    assert response.context['active_inline_key'] == 'operations'


@pytest.mark.django_db
def test_production_order_lifecycle_records_each_transition_once_with_real_actor(
    production_order, django_user_model
):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_user(
        username='production-lifecycle-actor',
        email='production-lifecycle-actor@example.com',
    )

    production_order.approve(user=actor)
    production_order.release(user=actor)
    production_order.start(user=actor)
    production_order.pause(user=actor)
    production_order.resume(user=actor)
    production_order.complete(Decimal('98.0000'), user=actor)
    production_order.refresh_from_db()

    events = list(
        GovernanceAuditLog.objects.filter(
            module='production',
            target_model='ProductionOrder',
            target_record_id=str(production_order.pk),
        ).order_by('occurred_at', 'pk')
    )
    assert [event.action for event in events] == [
        'production.order.approved',
        'production.order.released',
        'production.order.started',
        'production.order.paused',
        'production.order.resumed',
        'production.order.completed',
    ]
    assert all(event.user == actor for event in events)
    assert production_order.approved_by == actor
    assert production_order.released_by == actor
    assert production_order.started_by == actor
    assert production_order.completed_by == actor
    assert [
        (event.safe_context['from_status'], event.safe_context['to_status']) for event in events
    ] == [
        (ProductionOrder.Status.DRAFT, ProductionOrder.Status.APPROVED),
        (ProductionOrder.Status.APPROVED, ProductionOrder.Status.RELEASED),
        (ProductionOrder.Status.RELEASED, ProductionOrder.Status.IN_PROGRESS),
        (ProductionOrder.Status.IN_PROGRESS, ProductionOrder.Status.PAUSED),
        (ProductionOrder.Status.PAUSED, ProductionOrder.Status.IN_PROGRESS),
        (ProductionOrder.Status.IN_PROGRESS, ProductionOrder.Status.COMPLETED),
    ]


LIFECYCLE_TRANSITION_CASES = (
    ('approve', ProductionOrder.Status.DRAFT, ()),
    ('release', ProductionOrder.Status.APPROVED, ()),
    ('start', ProductionOrder.Status.RELEASED, ()),
    ('pause', ProductionOrder.Status.IN_PROGRESS, ()),
    ('resume', ProductionOrder.Status.PAUSED, ()),
    ('complete', ProductionOrder.Status.IN_PROGRESS, (Decimal('98.0000'),)),
    ('cancel', ProductionOrder.Status.DRAFT, ('Desvio confirmado.',)),
)


@pytest.mark.django_db
@pytest.mark.parametrize(('method_name', 'origin_status', 'args'), LIFECYCLE_TRANSITION_CASES)
def test_production_order_lifecycle_requires_explicit_actor_argument_without_mutation(
    production_order,
    method_name,
    origin_status,
    args,
):
    from governance.models import GovernanceAuditLog

    ProductionOrder.objects.filter(pk=production_order.pk).update(status=origin_status)
    production_order.refresh_from_db()
    method = getattr(production_order, method_name)

    assert signature(method).parameters['user'].default is Parameter.empty
    with pytest.raises(TypeError):
        method(*args)

    production_order.refresh_from_db()
    assert production_order.status == origin_status
    assert not GovernanceAuditLog.objects.filter(
        module='production',
        target_model='ProductionOrder',
        target_record_id=str(production_order.pk),
    ).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(('method_name', 'origin_status', 'args'), LIFECYCLE_TRANSITION_CASES)
@pytest.mark.parametrize('invalid_actor_kind', ('none', 'anonymous', 'unsaved'))
def test_production_order_lifecycle_rejects_invalid_actor_before_mutation_or_audit(
    production_order,
    django_user_model,
    method_name,
    origin_status,
    args,
    invalid_actor_kind,
):
    from governance.models import GovernanceAuditLog

    invalid_actor = {
        'none': None,
        'anonymous': AnonymousUser(),
        'unsaved': django_user_model(username='unsaved-production-actor'),
    }[invalid_actor_kind]
    ProductionOrder.objects.filter(pk=production_order.pk).update(status=origin_status)
    production_order.refresh_from_db()

    with pytest.raises(ValidationError, match='ator'):
        getattr(production_order, method_name)(*args, user=invalid_actor)

    production_order.refresh_from_db()
    assert production_order.status == origin_status
    assert not GovernanceAuditLog.objects.filter(
        module='production',
        target_model='ProductionOrder',
        target_record_id=str(production_order.pk),
    ).exists()


@pytest.mark.django_db
def test_invalid_production_order_transition_does_not_create_an_audit_event(
    production_order, django_user_model
):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_user(
        username='invalid-production-transition',
        email='invalid-production-transition@example.com',
    )
    production_order.approve(user=actor)
    audit_count = GovernanceAuditLog.objects.filter(
        module='production',
        target_model='ProductionOrder',
        target_record_id=str(production_order.pk),
    ).count()

    with pytest.raises(ValidationError):
        production_order.approve(user=actor)

    assert (
        GovernanceAuditLog.objects.filter(
            module='production',
            target_model='ProductionOrder',
            target_record_id=str(production_order.pk),
        ).count()
        == audit_count
    )


@pytest.mark.django_db
def test_production_order_transition_rolls_back_when_lifecycle_audit_fails(
    production_order, django_user_model
):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_user(
        username='production-lifecycle-audit-failure',
        email='production-lifecycle-audit-failure@example.com',
    )

    with patch.object(
        GovernanceAuditLog,
        'record',
        side_effect=RuntimeError('lifecycle audit failure'),
    ):
        with pytest.raises(RuntimeError, match='lifecycle audit failure'):
            production_order.approve(user=actor)

    production_order.refresh_from_db()
    assert production_order.status == ProductionOrder.Status.DRAFT
    assert not GovernanceAuditLog.objects.filter(
        module='production',
        target_model='ProductionOrder',
        target_record_id=str(production_order.pk),
    ).exists()


@pytest.mark.django_db
def test_production_lifecycle_api_propagates_actor_without_duplicate_events(
    production_order, django_user_model
):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_superuser(
        username='production-lifecycle-api-actor',
        email='production-lifecycle-api-actor@example.com',
        password='S3curePass!123',
    )
    client = APIClient()
    client.force_authenticate(user=actor)
    action_payloads = (
        ('approve', {}),
        ('release', {}),
        ('start', {}),
        ('pause', {}),
        ('resume', {}),
        ('complete', {'actual_yield_quantity': '97.5000'}),
    )

    for action_name, payload in action_payloads:
        response = client.post(
            reverse(f'v1_production:order-{action_name}', args=[production_order.pk]),
            payload,
            format='json',
        )
        assert response.status_code == 200, response.data

    events = GovernanceAuditLog.objects.filter(
        module='production',
        target_model='ProductionOrder',
        target_record_id=str(production_order.pk),
    )
    assert events.count() == len(action_payloads)
    assert all(event.user == actor for event in events)


@pytest.mark.django_db
def test_production_order_cancel_audit_keeps_reason_out_of_safe_context(
    production_order, django_user_model
):
    from governance.models import GovernanceAuditLog

    actor = django_user_model.objects.create_user(
        username='production-cancel-actor',
        email='production-cancel-actor@example.com',
    )
    confidential_reason = 'Desvio interno com referência restrita DEV-2026-0042.'

    production_order.cancel(confidential_reason, user=actor)

    event = GovernanceAuditLog.objects.get(
        module='production',
        action='production.order.cancelled',
        target_model='ProductionOrder',
        target_record_id=str(production_order.pk),
    )
    assert event.user == actor
    assert event.safe_context == {
        'from_status': ProductionOrder.Status.DRAFT,
        'to_status': ProductionOrder.Status.CANCELLED,
        'reason_recorded': True,
    }
    assert confidential_reason not in event.message
    assert confidential_reason not in str(event.safe_context)


@pytest.mark.django_db
def test_repeated_production_order_cancel_preserves_original_evidence_and_audit(
    production_order, django_user_model
):
    from governance.models import GovernanceAuditLog

    first_actor = django_user_model.objects.create_user(
        username='production-cancel-first-actor',
        email='production-cancel-first-actor@example.com',
    )
    second_actor = django_user_model.objects.create_user(
        username='production-cancel-second-actor',
        email='production-cancel-second-actor@example.com',
    )
    production_order.cancel('Justificativa original.', user=first_actor)
    production_order.refresh_from_db()
    original_evidence = (
        production_order.status,
        production_order.cancel_reason,
        production_order.cancelled_at,
        production_order.cancelled_by_id,
    )
    audit_count = GovernanceAuditLog.objects.filter(
        module='production',
        action='production.order.cancelled',
        target_model='ProductionOrder',
        target_record_id=str(production_order.pk),
    ).count()

    with pytest.raises(ValidationError):
        production_order.cancel('Tentativa de sobrescrita.', user=second_actor)

    production_order.refresh_from_db()
    assert (
        production_order.status,
        production_order.cancel_reason,
        production_order.cancelled_at,
        production_order.cancelled_by_id,
    ) == original_evidence
    assert (
        GovernanceAuditLog.objects.filter(
            module='production',
            action='production.order.cancelled',
            target_model='ProductionOrder',
            target_record_id=str(production_order.pk),
        ).count()
        == audit_count
    )


@pytest.mark.django_db
@pytest.mark.parametrize('origin_status', ProductionOrder.CANCELLABLE_STATUSES)
def test_production_order_cancel_accepts_only_the_shared_domain_origins(
    production_order,
    django_user_model,
    origin_status,
):
    actor = django_user_model.objects.create_user(
        username=f'production-cancel-{origin_status}',
        email=f'production-cancel-{origin_status}@example.com',
    )
    ProductionOrder.objects.filter(pk=production_order.pk).update(status=origin_status)
    production_order.refresh_from_db()

    production_order.cancel('Justificativa validada.', user=actor)

    production_order.refresh_from_db()
    assert production_order.status == ProductionOrder.Status.CANCELLED
    assert production_order.cancelled_by == actor


PRODUCTION_MAP_PERMISSION = 'production.view_production_maps'


MAP_VIEW_PERMISSIONS = (
    'production.view_productionorder',
    PRODUCTION_MAP_PERMISSION,
    'production.view_materialconsumption',
    'production.view_productionoutput',
    'production.view_productionoperationexecution',
    'production.view_productionlaborentry',
    'inventory.view_stockmovement',
    'inventory.view_stocklotgenealogy',
    'costing.view_productioncostcapture',
    'governance.view_governanceauditlog',
)


@pytest.fixture
def mapped_production_order(
    production_order, allocated_consumption, stock_address, operations_user
):
    """A traceable, completed batch record for the printable maps."""
    from inventory.models import StockLotGenealogy

    warehouse, location = stock_address
    now = timezone.now()
    production_order.priority = ProductionOrder.Priority.HIGH
    production_order.scheduled_start = timezone.localdate() - timedelta(days=1)
    production_order.scheduled_end = timezone.localdate()
    production_order.production_line = 'Linha de sólidos 1'
    production_order.responsible = operations_user
    production_order.notes = 'Acompanhar umidade crítica do lote.'
    production_order.save(
        update_fields=[
            'priority',
            'scheduled_start',
            'scheduled_end',
            'production_line',
            'responsible',
            'notes',
            'updated_at',
        ]
    )
    production_order.approve(user=operations_user)
    production_order.release(user=operations_user)
    production_order.start(user=operations_user)
    production_order.pause(user=operations_user)
    production_order.resume(user=operations_user)

    production_order.real_loss_quantity = Decimal('1.0000')
    production_order.rework_quantity = Decimal('2.0000')
    production_order.save(
        update_fields=[
            'real_loss_quantity',
            'rework_quantity',
            'updated_at',
        ]
    )
    allocated_consumption.actual_quantity = Decimal('12.0000')
    allocated_consumption.loss_quantity = Decimal('1.0000')
    allocated_consumption.returned_quantity = Decimal('1.5000')
    allocated_consumption.notes = 'Devolução segregada após pesagem.'
    allocated_consumption.save(
        update_fields=[
            'actual_quantity',
            'loss_quantity',
            'returned_quantity',
            'notes',
            'updated_at',
        ]
    )

    operation = ProductionOperationExecution(
        order=production_order,
        sequence=20,
        operation='Mistura',
        work_center='Sala de mistura',
        planned_minutes=Decimal('35.00'),
        status=ProductionOperationExecution.Status.COMPLETED,
        started_at=now - timedelta(minutes=45),
        ended_at=now - timedelta(minutes=15),
        recorded_by=operations_user,
        notes='Parâmetros dentro da faixa aprovada.',
    )
    operation.full_clean()
    operation.save()
    labor = ProductionLaborEntry(
        order=production_order,
        operation_execution=operation,
        user=operations_user,
        role='Operador de mistura',
        started_at=now - timedelta(minutes=30),
        ended_at=now,
        hourly_cost=Decimal('20.0000'),
        notes='Dupla checagem concluída.',
    )
    labor.full_clean()
    labor.save()
    production_order.complete(Decimal('98.0000'), user=operations_user)

    output_lot = StockLot.objects.create(
        product=production_order.product,
        lot_number='MAP-SAIDA',
        source_production_order=production_order,
        manufacturing_date=timezone.localdate(),
        expiry_date=timezone.localdate() + timedelta(days=365),
        notes='Lote mantido em quarentena para análise.',
    )
    output_movement = StockMovement.objects.create(
        movement_type=StockMovement.MovementType.PRODUCTION_RECEIPT,
        product=production_order.product,
        lot=output_lot,
        quantity=Decimal('98.0000'),
        unit=production_order.unit,
        quality_status=StockQualityStatus.QUARANTINE,
        to_warehouse=warehouse,
        to_location=location,
        source_production_order=production_order,
    )
    output = ProductionOutput(
        order=production_order,
        product=production_order.product,
        lot_number=output_lot.lot_number,
        planned_quantity=production_order.planned_quantity,
        produced_quantity=Decimal('98.0000'),
        unit=production_order.unit,
        warehouse=warehouse,
        location=location,
        stock_lot=output_lot,
        stock_movement=output_movement,
        status=ProductionOutput.Status.RECEIVED,
        received_by=operations_user,
        received_at=now,
        manufacturing_date=output_lot.manufacturing_date,
        expiry_date=output_lot.expiry_date,
        notes='Amostra de CQ coletada no recebimento.',
    )
    output.full_clean()
    output.save()
    StockMovement.objects.create(
        movement_type=StockMovement.MovementType.ISSUE,
        product=allocated_consumption.material,
        lot=allocated_consumption.stock_lot,
        quantity=Decimal('12.0000'),
        unit=allocated_consumption.unit,
        quality_status=StockQualityStatus.APPROVED,
        from_warehouse=allocated_consumption.warehouse,
        from_location=allocated_consumption.location,
        source_production_order=production_order,
        source_material_consumption=allocated_consumption,
    )
    StockLotGenealogy.objects.create(
        input_lot=allocated_consumption.stock_lot,
        output_lot=output_lot,
        production_order=production_order,
        relation_type=StockLotGenealogy.RelationType.CONSUMED_IN_PRODUCTION,
        quantity=Decimal('12.0000'),
        unit=production_order.unit,
        notes='Rastreabilidade integral do lote consumido.',
    )
    cost_capture = ProductionCostCapture.objects.create(
        production_order=production_order,
        period_start=timezone.localdate().replace(day=1),
        period_end=timezone.localdate(),
        planned_cost=Decimal('100.0000'),
        actual_material_cost=Decimal('110.0000'),
        actual_loss_cost=Decimal('15.0000'),
    )
    cost_capture.calculate_actuals()
    return production_order


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_control_map_materializes_traceable_inputs_processes_people_and_costs(
    client, django_user_model, mapped_production_order
):
    user = django_user_model.objects.create_user(
        username='controle-mapa', email='controle-mapa@example.com'
    )
    _grant_permissions(user, *MAP_VIEW_PERMISSIONS)
    client.force_login(user)

    response = client.get(reverse('app:production_control_map', args=[mapped_production_order.pk]))

    assert response.status_code == 200
    assert response.context['map_kind'] == 'control'
    assert len(response.context['materials']) == 1
    assert len(response.context['outputs']) == 1
    assert len(response.context['operations']) == 1
    assert len(response.context['labor_entries']) == 1
    assert len(response.context['movements']) == 2
    assert len(response.context['genealogy']) == 1
    assert len(response.context['cost_captures']) == 1
    assert len(response.context['events']) == 6
    assert {event.action for event in response.context['events']} == {
        'production.order.approved',
        'production.order.released',
        'production.order.started',
        'production.order.paused',
        'production.order.resumed',
        'production.order.completed',
    }
    content = response.content.decode()
    for expected in (
        'F-PA-OP',
        'R-PA-OP',
        'Alta',
        'Linha de sólidos 1',
        'Acompanhar umidade crítica do lote.',
        'Devolução segregada após pesagem.',
        'Sala de mistura',
        'Parâmetros dentro da faixa aprovada.',
        'Dupla checagem concluída.',
        'MAP-SAIDA',
        'Quarentena',
        'Amostra de CQ coletada no recebimento.',
        'Ordem de produção aprovada.',
        'Execução da ordem de produção pausada.',
        'Execução da ordem de produção retomada.',
    ):
        assert expected in content
    assert content.count('<main') == 1


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_results_map_uses_decimal_yield_variances_losses_rework_and_cost_totals(
    client, django_user_model, mapped_production_order
):
    user = django_user_model.objects.create_user(
        username='resultado-mapa', email='resultado-mapa@example.com'
    )
    _grant_permissions(user, *MAP_VIEW_PERMISSIONS)
    client.force_login(user)

    response = client.get(reverse('app:production_results_map', args=[mapped_production_order.pk]))

    assert response.status_code == 200
    assert response.context['map_kind'] == 'results'
    assert response.context['summary'] == {
        'yield_percent': Decimal('98.0000'),
        'loss_quantity': Decimal('1.0000'),
        'rework_quantity': Decimal('2.0000'),
        'process_minutes': Decimal('30.00'),
        'labor_minutes': Decimal('30.00'),
        'planned_cost': Decimal('100.0000'),
        'actual_cost': Decimal('125.0000'),
        'cost_variance': Decimal('25.0000'),
    }
    variance = response.context['material_variances'][0]
    assert variance['planned_quantity'] == Decimal('10.0000')
    assert variance['actual_quantity'] == Decimal('12.0000')
    assert variance['variance_quantity'] == Decimal('2.0000')
    assert variance['returned_quantity'] == Decimal('1.5000')
    assert 'Real − planejado' in response.content.decode()


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_results_map_yield_is_zero_decimal_when_planned_quantity_is_zero(
    client, django_user_model, production_order
):
    user = django_user_model.objects.create_user(
        username='resultado-zero', email='resultado-zero@example.com'
    )
    _grant_permissions(user, 'production.view_productionorder', PRODUCTION_MAP_PERMISSION)
    ProductionOrder.objects.filter(pk=production_order.pk).update(
        planned_quantity=Decimal('0.0000')
    )
    client.force_login(user)

    response = client.get(reverse('app:production_results_map', args=[production_order.pk]))

    assert response.status_code == 200
    assert response.context['summary']['yield_percent'] == Decimal('0.0000')


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_maps_return_404_for_an_unknown_order(client, django_user_model):
    user = django_user_model.objects.create_user(
        username='mapa-ordem-ausente', email='mapa-ordem-ausente@example.com'
    )
    _grant_permissions(user, 'production.view_productionorder', PRODUCTION_MAP_PERMISSION)
    client.force_login(user)

    response = client.get(reverse('app:production_control_map', args=[999999]))

    assert response.status_code == 404


@pytest.mark.django_db
@pytest.mark.permission_strict
@pytest.mark.parametrize(
    'map_url_name',
    ('app:production_control_map', 'app:production_results_map'),
)
def test_maps_require_parent_permission_and_do_not_query_or_leak_child_data(
    client, django_user_model, mapped_production_order, map_url_name
):
    map_url = reverse(map_url_name, args=[mapped_production_order.pk])
    anonymous = client.get(map_url)
    assert anonymous.status_code == 302

    user = django_user_model.objects.create_user(
        username='somente-ordem-mapa', email='somente-ordem-mapa@example.com'
    )
    client.force_login(user)
    forbidden = client.get(map_url)
    assert forbidden.status_code == 403

    _grant_permissions(user, 'production.view_productionorder')
    with CaptureQueriesContext(connection) as captured:
        response = client.get(map_url)

    assert response.status_code == 403
    child_tables = (
        'production_materialconsumption',
        'production_productionoutput',
        'production_productionoperationexecution',
        'production_productionlaborentry',
        'inventory_stockmovement',
        'inventory_stocklotgenealogy',
        'costing_productioncostcapture',
        'governance_governanceauditlog',
    )
    query_sql = ' '.join(query['sql'].lower() for query in captured.captured_queries)
    assert not any(table in query_sql for table in child_tables)

    _grant_permissions(user, PRODUCTION_MAP_PERMISSION)
    with CaptureQueriesContext(connection) as captured:
        response = client.get(map_url)

    assert response.status_code == 200
    assert all(
        response.context[key] is None
        for key in (
            'materials',
            'outputs',
            'operations',
            'labor_entries',
            'movements',
            'genealogy',
            'cost_captures',
            'events',
        )
    )
    query_sql = ' '.join(query['sql'].lower() for query in captured.captured_queries)
    assert not any(table in query_sql for table in child_tables)
    content = response.content.decode()
    assert 'MAP-SAIDA' not in content
    assert 'Operador de mistura' not in content
    assert '125.0000' not in content


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_maps_have_bounded_queries_empty_state_detail_links_and_are_read_only(
    client, django_user_model, mapped_production_order
):
    from governance.models import GovernanceAuditLog

    user = django_user_model.objects.create_user(
        username='mapa-consulta', email='mapa-consulta@example.com'
    )
    _grant_permissions(user, *MAP_VIEW_PERMISSIONS)
    client.force_login(user)
    audit_count = GovernanceAuditLog.objects.count()

    with CaptureQueriesContext(connection) as captured:
        response = client.get(
            reverse('app:production_results_map', args=[mapped_production_order.pk])
        )

    assert response.status_code == 200
    assert len(captured) <= 25
    assert GovernanceAuditLog.objects.count() == audit_count
    content = response.content.decode()
    assert 'data-production-map-print' in content
    assert 'onclick="window.print()"' not in content
    assert 'js/production-order-map.js' in content
    assert '<style media="print">' not in content

    detail = client.get(
        reverse('app:resource_detail', args=['production', 'orders', mapped_production_order.pk])
    )
    assert detail.status_code == 200
    detail_content = detail.content.decode()
    assert (
        reverse('app:production_control_map', args=[mapped_production_order.pk]) in detail_content
    )
    assert (
        reverse('app:production_results_map', args=[mapped_production_order.pk]) in detail_content
    )

    empty_order = ProductionOrder.objects.create(
        order_number='OP-MAPA-VAZIO',
        product=mapped_production_order.product,
        formula=mapped_production_order.formula,
        route=mapped_production_order.route,
        planned_quantity=Decimal('1.0000'),
        unit=mapped_production_order.unit,
    )
    response = client.get(reverse('app:production_control_map', args=[empty_order.pk]))
    assert 'data-ui="empty-state"' in response.content.decode()


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_production_map_links_require_parent_and_dedicated_permission(
    client, django_user_model, mapped_production_order
):
    user = django_user_model.objects.create_user(
        username='mapa-links-dedicados',
        email='mapa-links-dedicados@example.com',
    )
    _grant_permissions(user, 'production.view_productionorder')
    client.force_login(user)
    detail_url = reverse(
        'app:resource_detail',
        args=['production', 'orders', mapped_production_order.pk],
    )

    response = client.get(detail_url)

    assert response.status_code == 200
    content = response.content.decode()
    assert reverse('app:production_control_map', args=[mapped_production_order.pk]) not in content
    assert reverse('app:production_results_map', args=[mapped_production_order.pk]) not in content

    _grant_permissions(user, PRODUCTION_MAP_PERMISSION)
    response = client.get(detail_url)

    assert response.status_code == 200
    content = response.content.decode()
    assert reverse('app:production_control_map', args=[mapped_production_order.pk]) in content
    assert reverse('app:production_results_map', args=[mapped_production_order.pk]) in content


def test_production_order_declares_dedicated_map_permission():
    expected_permission = (
        'view_production_maps',
        'Pode consultar mapas da ordem de produção',
    )
    assert expected_permission in ProductionOrder._meta.permissions


MAP_SECTION_CASES = (
    (
        'production.view_materialconsumption',
        'materials',
        'production_materialconsumption',
        'Devolução segregada após pesagem.',
    ),
    (
        'production.view_productionoutput',
        'outputs',
        'production_productionoutput',
        'Amostra de CQ coletada no recebimento.',
    ),
    (
        'production.view_productionoperationexecution',
        'operations',
        'production_productionoperationexecution',
        'Sala de mistura',
    ),
    (
        'production.view_productionlaborentry',
        'labor_entries',
        'production_productionlaborentry',
        'Dupla checagem concluída.',
    ),
    (
        'inventory.view_stockmovement',
        'movements',
        'inventory_stockmovement',
        'Entrada de produção',
    ),
    (
        'inventory.view_stocklotgenealogy',
        'genealogy',
        'inventory_stocklotgenealogy',
        'Rastreabilidade integral do lote consumido.',
    ),
    (
        'costing.view_productioncostcapture',
        'cost_captures',
        'costing_productioncostcapture',
        'Custos planejados e reais da ordem',
    ),
    (
        'governance.view_governanceauditlog',
        'events',
        'governance_governanceauditlog',
        'Ordem de produção aprovada.',
    ),
)

MAP_CHILD_TABLES = tuple(case[2] for case in MAP_SECTION_CASES)


@pytest.mark.django_db
@pytest.mark.permission_strict
@pytest.mark.parametrize(
    ('permission_name', 'visible_section', 'visible_table', 'visible_marker'),
    MAP_SECTION_CASES,
)
def test_maps_enforce_least_privilege_for_each_individual_section(
    client,
    django_user_model,
    mapped_production_order,
    permission_name,
    visible_section,
    visible_table,
    visible_marker,
):
    user = django_user_model.objects.create_user(
        username=f'mapa-secao-{visible_section}',
        email=f'mapa-secao-{visible_section}@example.com',
    )
    _grant_permissions(
        user,
        'production.view_productionorder',
        PRODUCTION_MAP_PERMISSION,
        permission_name,
    )
    client.force_login(user)

    with CaptureQueriesContext(connection) as captured:
        response = client.get(
            reverse('app:production_control_map', args=[mapped_production_order.pk])
        )

    assert response.status_code == 200
    assert response.context[visible_section]
    for _permission, section, _table, _marker in MAP_SECTION_CASES:
        if section != visible_section:
            assert response.context[section] is None
    query_sql = ' '.join(query['sql'].lower() for query in captured.captured_queries)
    assert visible_table in query_sql
    assert not any(table in query_sql for table in MAP_CHILD_TABLES if table != visible_table)
    assert visible_marker in response.content.decode()


@pytest.mark.django_db
@pytest.mark.permission_strict
@pytest.mark.parametrize(
    ('permission_name', 'available_key', 'available_value', 'unavailable_keys'),
    (
        (
            'production.view_materialconsumption',
            'material_variances',
            'not_none',
            ('planned_cost', 'process_minutes', 'labor_minutes'),
        ),
        (
            'costing.view_productioncostcapture',
            'planned_cost',
            Decimal('100.0000'),
            ('material_variances', 'process_minutes', 'labor_minutes'),
        ),
        (
            'production.view_productionoperationexecution',
            'process_minutes',
            Decimal('30.00'),
            ('material_variances', 'planned_cost', 'labor_minutes'),
        ),
        (
            'production.view_productionlaborentry',
            'labor_minutes',
            Decimal('30.00'),
            ('material_variances', 'planned_cost', 'process_minutes'),
        ),
    ),
)
def test_results_map_totals_follow_independent_section_permissions(
    client,
    django_user_model,
    mapped_production_order,
    permission_name,
    available_key,
    available_value,
    unavailable_keys,
):
    user = django_user_model.objects.create_user(
        username=f'resultado-parcial-{available_key}',
        email=f'resultado-parcial-{available_key}@example.com',
    )
    _grant_permissions(
        user,
        'production.view_productionorder',
        PRODUCTION_MAP_PERMISSION,
        permission_name,
    )
    client.force_login(user)

    response = client.get(reverse('app:production_results_map', args=[mapped_production_order.pk]))

    assert response.status_code == 200
    if available_key == 'material_variances':
        assert response.context[available_key] is not None
    else:
        assert response.context['summary'][available_key] == available_value
    for unavailable_key in unavailable_keys:
        if unavailable_key == 'material_variances':
            assert response.context[unavailable_key] is None
        else:
            assert response.context['summary'][unavailable_key] is None


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_map_events_use_strict_order_target_filter(
    client, django_user_model, mapped_production_order
):
    from governance.models import GovernanceAuditLog

    common = {
        'log_type': GovernanceAuditLog.LogType.FUNCTIONAL,
        'severity': GovernanceAuditLog.Severity.INFO,
        'target_record_id': str(mapped_production_order.pk),
        'user': None,
    }
    GovernanceAuditLog.record(
        **common,
        module='finance',
        action='finance.unrelated',
        target_model='ProductionOrder',
        message='Evento financeiro não relacionado.',
    )
    GovernanceAuditLog.record(
        **common,
        module='production',
        action='production.other-model',
        target_model='OtherModel',
        message='Evento de outro modelo.',
    )
    user = django_user_model.objects.create_user(
        username='mapa-eventos-estritos',
        email='mapa-eventos-estritos@example.com',
    )
    _grant_permissions(
        user,
        'production.view_productionorder',
        PRODUCTION_MAP_PERMISSION,
        'governance.view_governanceauditlog',
    )
    client.force_login(user)

    response = client.get(reverse('app:production_control_map', args=[mapped_production_order.pk]))

    assert response.status_code == 200
    assert len(response.context['events']) == 6
    content = response.content.decode()
    assert 'Evento financeiro não relacionado.' not in content
    assert 'Evento de outro modelo.' not in content


@pytest.mark.django_db
@pytest.mark.permission_strict
def test_map_query_count_is_constant_as_materials_and_movements_grow(
    client,
    django_user_model,
    mapped_production_order,
):
    # This scale fixture creates allocations, so use an operational parent state.
    mapped_production_order.status = ProductionOrder.Status.IN_PROGRESS
    mapped_production_order.save(update_fields=['status', 'updated_at'])
    existing = mapped_production_order.material_consumptions.select_related(
        'component', 'material', 'stock_lot', 'warehouse', 'location', 'unit'
    ).get()
    user = django_user_model.objects.create_user(
        username='mapa-consultas-constantes',
        email='mapa-consultas-constantes@example.com',
    )
    _grant_permissions(
        user,
        'production.view_productionorder',
        PRODUCTION_MAP_PERMISSION,
        'production.view_materialconsumption',
        'inventory.view_stockmovement',
    )
    client.force_login(user)

    with CaptureQueriesContext(connection) as baseline_queries:
        baseline_response = client.get(
            reverse('app:production_control_map', args=[mapped_production_order.pk])
        )
    assert baseline_response.status_code == 200

    for index in range(5):
        extra_lot = StockLot.objects.create(
            product=existing.material,
            lot_number=f'MAP-ESCALA-{index}',
        )
        MaterialConsumption.objects.create(
            order=mapped_production_order,
            component=existing.component,
            material=existing.material,
            planned_quantity=Decimal('1.0000'),
            actual_quantity=Decimal('1.0000'),
            unit=existing.unit,
            stock_lot=extra_lot,
            warehouse=existing.warehouse,
            location=existing.location,
            lot_number=extra_lot.lot_number,
            quality_status=MaterialConsumption.QualityStatus.APPROVED,
        )
        StockMovement.objects.create(
            movement_type=StockMovement.MovementType.ISSUE,
            product=existing.material,
            lot=extra_lot,
            quantity=Decimal('1.0000'),
            unit=existing.unit,
            quality_status=StockQualityStatus.APPROVED,
            from_warehouse=existing.warehouse,
            from_location=existing.location,
            source_production_order=mapped_production_order,
        )

    with CaptureQueriesContext(connection) as scaled_queries:
        scaled_response = client.get(
            reverse('app:production_control_map', args=[mapped_production_order.pk])
        )

    assert scaled_response.status_code == 200
    assert len(scaled_queries) == len(baseline_queries)
