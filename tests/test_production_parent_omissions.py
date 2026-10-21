"""Parent formula edits must validate persisted consumption rows omitted by POST."""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from tests.test_proven_related_dependencies import production_pair as production_pair


@pytest.mark.permission_strict
def test_order_formula_change_cannot_omit_persisted_incompatible_consumption(
    client, production_pair
):
    from governance.models import GovernanceAuditLog
    from production.models import MaterialConsumption

    a, b = production_pair
    user = get_user_model().objects.create_superuser(
        'proven-parent', 'parent@example.invalid', None
    )
    client.force_login(user)
    consumption = MaterialConsumption.objects.create(
        order=a['order'],
        component=a['component'],
        material=a['material'],
        unit=a['unit'],
        stock_lot=a['lot'],
        planned_quantity=1,
    )
    address = reverse(
        'app:resource_edit',
        kwargs=dict(module_slug='production', resource_slug='orders', pk=a['order'].pk),
    )
    response = client.get(address)
    assert response.status_code == 200
    form = response.context['form']
    payload = {}
    for name, field in form.fields.items():
        value = form[name].value()
        if value is None or value is False:
            continue
        payload[name] = 'on' if value is True else str(getattr(value, 'pk', value))
    payload['formula'] = str(b['formula'].pk)
    for inline in response.context['inline_formsets']:
        prefix = inline['key']
        payload.update(
            {
                f'{prefix}-TOTAL_FORMS': '0',
                f'{prefix}-INITIAL_FORMS': '0',
                f'{prefix}-MIN_NUM_FORMS': '0',
                f'{prefix}-MAX_NUM_FORMS': '1000',
            }
        )
    before_audits = GovernanceAuditLog.objects.count()
    response = client.post(address, payload)
    a['order'].refresh_from_db()
    consumption.refresh_from_db()
    assert response.status_code == 200, (
        response.status_code,
        a['order'].formula_id,
        consumption.component.formula_id,
    )
    assert a['order'].formula_id == a['formula'].pk
    assert consumption.component_id == a['component'].pk
    assert GovernanceAuditLog.objects.count() == before_audits


@pytest.mark.permission_strict
@pytest.mark.parametrize('controller', ['route', 'product'])
def test_order_cannot_orphan_other_omitted_operational_rows(client, production_pair, controller):
    from formulations.models import ManufacturingRoute, MasterFormula, RouteStep
    from governance.models import GovernanceAuditLog
    from masters.models import Product
    from production.models import ProductionOperationExecution, ProductionOutput

    a, _ = production_pair
    order = a['order']
    user = get_user_model().objects.create_superuser(
        'parent-siblings', 'parent-siblings@example.invalid', None
    )
    client.force_login(user)
    original = getattr(order, f'{controller}_id')
    if controller == 'route':
        step = RouteStep.objects.create(
            route=order.route,
            sequence=1,
            operation='Mistura',
            work_center='Tanque',
            standard_time_minutes=1,
        )
        child = ProductionOperationExecution.objects.create(
            order=order,
            route_step=step,
            sequence=1,
            operation=step.operation,
        )
        replacement = ManufacturingRoute.objects.create(product=order.product, version=2)
        changes = {'route': str(replacement.pk)}
    else:
        child = ProductionOutput.objects.create(
            order=order,
            product=order.product,
            lot_number='OMITTED-OUTPUT',
            planned_quantity=1,
            unit=a['unit'],
        )
        product = Product.objects.create(
            description='Outro creme', unit=a['unit'], status='approved'
        )
        formula = MasterFormula.objects.create(
            product=product, version=1, batch_size=1, batch_unit=a['unit']
        )
        route = ManufacturingRoute.objects.create(product=product, version=1)
        changes = {'product': str(product.pk), 'formula': str(formula.pk), 'route': str(route.pk)}
    address = reverse(
        'app:resource_edit',
        kwargs={
            'module_slug': 'production',
            'resource_slug': 'orders',
            'pk': order.pk,
        },
    )
    page = client.get(address)
    assert page.status_code == 200
    form = page.context['form']
    payload = {
        name: 'on'
        if form[name].value() is True
        else str(getattr(form[name].value(), 'pk', form[name].value()))
        for name in form.fields
        if form[name].value() is not None and form[name].value() is not False
    }
    for inline in page.context['inline_formsets']:
        payload.update({f'{inline["key"]}-TOTAL_FORMS': '0', f'{inline["key"]}-INITIAL_FORMS': '0'})
    before = GovernanceAuditLog.objects.count()
    response = client.post(address, {**payload, **changes})
    assert response.status_code == 200
    order.refresh_from_db()
    child.refresh_from_db()
    assert getattr(order, f'{controller}_id') == original
    assert controller in response.context['form'].errors
    assert GovernanceAuditLog.objects.count() == before
