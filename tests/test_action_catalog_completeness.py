from base.ui.actions.discovery import discover_post_actions
from base.ui.actions.inventory import FIELD_SPECS, KIND_MAP
from base.ui.actions.registry import action_registry
from base.ui.actions.types import FieldKind
from costing.models import StandardCost


def test_html_catalog_exactly_matches_post_actions():
    discovered = {item.key: item for item in discover_post_actions()}
    registered = {
        (config.model._meta.label_lower, config.action_name, config.detail): config
        for config in action_registry.all()
    }

    assert registered.keys() == discovered.keys()
    for key, config in registered.items():
        endpoint = discovered[key]
        assert config.route_name == endpoint.route_name
        assert config.permissions == endpoint.permissions


def test_catalog_has_approved_cardinality():
    configs = action_registry.all()

    assert len(configs) == 234
    assert sum(config.detail for config in configs) == 227
    assert sum(not config.detail for config in configs) == 7


def test_integrated_nfe_import_keeps_its_collection_contract():
    config = action_registry.get('procurement', 'receipts', 'import_xml')

    assert config.detail is False
    assert config.route_name == 'v1_procurement:receipt-import-xml'
    assert config.permissions == ('procurement.add_purchasereceipt',)
    assert config.submission_format.value == 'multipart'
    assert tuple(field.name for field in config.fields) == ('order_id', 'xml')


def test_standard_cost_obsolete_action_has_complete_html_contract():
    config = action_registry.get('costing', 'standard-costs', 'obsolete')

    assert config.model is StandardCost
    assert config.route_name == 'v1_costing:standard-cost-obsolete'
    assert config.permissions == ('costing.change_standardcost',)
    assert tuple(config.allowed_states) == (StandardCost.Status.APPROVED,)
    assert config.fields == ()
    assert config.confirmation is not None
    assert config.confirmation.acknowledge_label


def test_catalog_payloads_match_frozen_inventory():
    configs = {config.key: config for config in action_registry.all()}

    for key, specification in FIELD_SPECS.items():
        expected = tuple(
            (name, KIND_MAP[code])
            for name, code in (item.split(':', 1) for item in specification.split(','))
        )
        actual = tuple((field.name, field.kind) for field in configs[key].fields)
        assert actual == expected

    assert all(
        field.choices
        for config in configs.values()
        for field in config.fields
        if field.kind == FieldKind.CHOICE
    )
    assert all(
        field.queryset_factory is not None
        for config in configs.values()
        for field in config.fields
        if field.kind == FieldKind.RELATION
    )
