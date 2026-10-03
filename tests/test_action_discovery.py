from dataclasses import FrozenInstanceError, replace
from typing import cast
from types import SimpleNamespace

import pytest

from base.ui.actions.discovery import discover_post_actions
from base.ui.actions.types import ActionConfig
from inventory.models import StockLot
from production.models import ProductionOrder


def test_discovers_each_post_action_once_without_format_suffix_duplicates():
    actions = discover_post_actions()

    assert len(actions) == 234
    assert len({action.key for action in actions}) == 234
    assert sum(action.detail for action in actions) == 227
    assert sum(not action.detail for action in actions) == 7
    assert all(
        not (action.model is StockLot and action.action_name == 'print_label') for action in actions
    )

    production = next(
        item
        for item in actions
        if item.app_label == 'production' and item.action_name == 'complete'
    )
    assert production.route_name == 'v1_production:order-complete'
    assert production.model._meta.label == 'production.ProductionOrder'
    assert production.permissions == ('production.change_productionorder',)


def test_discovery_preserves_custom_multi_permission_contracts():
    actions = discover_post_actions()

    run = next(
        item for item in actions if item.app_label == 'ai_agents' and item.action_name == 'run'
    )

    assert run.permissions == (
        'ai_agents.change_aiagentprofile',
        'ai_agents.add_aiagentrun',
    )


def test_action_config_is_immutable_reverses_route_and_checks_availability():
    config = ActionConfig(
        module_slug='production',
        resource_slug='orders',
        app_label='production',
        model=ProductionOrder,
        action_name='complete',
        route_name='v1_production:order-complete',
        detail=True,
        label='Concluir',
        description='Concluir a ordem de produção.',
        success_message='Ordem de produção concluída.',
        permissions=('production.change_productionorder',),
        allowed_states=(cast(str, ProductionOrder.Status.IN_PROGRESS),),
    )
    allowed_user = SimpleNamespace(has_perms=lambda permissions: permissions == config.permissions)
    denied_user = SimpleNamespace(has_perms=lambda permissions: False)

    assert config.api_url(pk=42) == '/api/v1/production/orders/42/complete/'
    assert config.is_available(
        allowed_user,
        SimpleNamespace(status=ProductionOrder.Status.IN_PROGRESS),
    )
    assert not config.is_available(
        allowed_user,
        SimpleNamespace(status=ProductionOrder.Status.COMPLETED),
    )
    assert not config.is_available(
        denied_user,
        SimpleNamespace(status=ProductionOrder.Status.IN_PROGRESS),
    )
    with pytest.raises(FrozenInstanceError):
        config.label = 'Alterado'  # type: ignore[misc]
    collection_config = replace(
        config,
        detail=False,
        route_name='v1_risks:alert-generate',
    )
    assert collection_config.api_url() == '/api/v1/risks/alerts/generate/'
