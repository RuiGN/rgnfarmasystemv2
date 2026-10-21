"""Frozen 59-key follow-up set from the independent model-clean review."""

import pytest
from django.apps import apps

from tests.test_proven_related_dependencies import resource_form

EXPECTED_CANDIDATES = (
    ('audits.auditfinding', 'checklist_item', 'audit', 'audit'),
    ('capa.capanotification', 'action', 'capa', 'capa'),
    ('capa.capanotification', 'approval', 'capa', 'capa'),
    ('capa.capanotification', 'effectiveness_check', 'capa', 'capa'),
    ('changes.changestockassessment', 'stock_lot', 'product', 'product'),
    ('crm.customercomplaint', 'contact', 'customer', 'customer'),
    ('crm.customercomplaint', 'fiscal_document', 'customer', 'partner'),
    ('crm.customercomplaint', 'sales_order', 'customer', 'customer'),
    ('crm.customercomplaint', 'stock_lot', 'product', 'product'),
    ('crm.customerinteraction', 'contact', 'customer', 'customer'),
    ('crm.customerinteraction', 'opportunity', 'customer', 'customer'),
    ('crm.opportunity', 'contact', 'customer', 'customer'),
    ('crm.salescontract', 'opportunity', 'customer', 'customer'),
    ('crm.salescontract', 'proposal', 'customer', 'customer'),
    ('crm.salesorder', 'contract', 'customer', 'customer'),
    ('crm.salesorder', 'proposal', 'customer', 'customer'),
    ('crm.salesproposal', 'opportunity', 'customer', 'customer'),
    ('deviations.qualityevent', 'stock_lot', 'product', 'product'),
    ('fiscal.fiscaldocument', 'purchase_receipt', 'purchase_order', 'order'),
    ('fiscal.fiscaltax', 'item', 'document', 'document'),
    ('inventory.stockbalance', 'lot', 'product', 'product'),
    ('procurement.purchaseorderitem', 'requisition_item', 'product', 'product'),
    ('procurement.purchasereceiptitem', 'order_item', 'product', 'product'),
    ('procurement.purchaserequisitionitem', 'mrp_suggestion', 'product', 'product'),
    ('production.materialconsumption', 'component', 'material', 'material'),
    ('production.materialconsumption', 'stock_lot', 'material', 'product'),
    ('qa.lotrelease', 'production_order', 'product', 'product'),
    ('qa.lotrelease', 'qa_review', 'production_order', 'production_order'),
    ('qa.lotrelease', 'qa_review', 'quality_document', 'quality_document'),
    ('qa.lotrelease', 'qa_review', 'stock_lot', 'stock_lot'),
    ('qa.lotrelease', 'quality_document', 'product', 'product'),
    ('qa.lotrelease', 'quality_document', 'stock_lot', 'stock_lot'),
    ('qa.lotrelease', 'stock_lot', 'product', 'product'),
    ('qa.lotrelease', 'stock_lot', 'production_order', 'source_production_order'),
    ('qa.qareview', 'quality_document', 'stock_lot', 'stock_lot'),
    ('qa.qualityblock', 'stock_lot', 'product', 'product'),
    ('quality.analyticalspecification', 'stock_lot', 'product', 'product'),
    ('quality.laboratoryinvestigation', 'analysis', 'sample', 'sample'),
    ('quality.laboratoryinvestigation', 'result', 'analysis', 'analysis'),
    ('quality.qualitydocument', 'sample', 'product', 'product'),
    ('quality.qualitydocument', 'stock_lot', 'product', 'product'),
    ('quality.qualitysample', 'specification', 'product', 'product'),
    ('quality.qualitysample', 'stock_lot', 'product', 'product'),
    ('recalls.marketcomplaint', 'customer_complaint', 'customer', 'customer'),
    ('recalls.marketcomplaint', 'fiscal_document', 'customer', 'partner'),
    ('recalls.marketcomplaint', 'quality_sample', 'product', 'product'),
    ('recalls.marketcomplaint', 'sales_order', 'customer', 'customer'),
    ('recalls.marketcomplaint', 'stock_lot', 'product', 'product'),
    ('recalls.productreturn', 'complaint', 'customer', 'customer'),
    ('recalls.productreturn', 'fiscal_document', 'customer', 'partner'),
    ('recalls.productreturn', 'sales_order', 'customer', 'customer'),
    ('recalls.productreturn', 'stock_lot', 'product', 'product'),
    ('recalls.recallcampaign', 'complaint', 'product', 'product'),
    ('recalls.recallcampaign', 'stock_lot', 'product', 'product'),
    ('recalls.recallimpactedcustomer', 'fiscal_document', 'customer', 'partner'),
    ('recalls.recallimpactedcustomer', 'sales_order', 'customer', 'customer'),
    ('training.trainingenrollment', 'session', 'requirement', 'requirement'),
    ('training.trainingmatrixrequirement', 'function', 'job_position', 'job_position'),
    ('training.trainingrequirement', 'function', 'job_position', 'job_position'),
)

# UX direction deliberately reverses these equalities (no mutually clearing cycles).
INVERSE = {
    ('procurement.purchasereceiptitem', 'order_item'): ('product', 'order_item', 'pk'),
    ('procurement.purchaseorderitem', 'requisition_item'): ('product', 'requisition_item', 'pk'),
    ('procurement.purchaserequisitionitem', 'mrp_suggestion'): ('product', 'mrp_suggestion', 'pk'),
    ('production.materialconsumption', 'component'): ('material', 'component', 'pk'),
    ('qa.lotrelease', 'stock_lot', 'production_order'): ('production_order', 'stock_lot', 'pk'),
}


def test_review_candidate_set_is_deduplicated_and_complete():
    assert len(EXPECTED_CANDIDATES) == 59
    assert len(set(EXPECTED_CANDIDATES)) == 59


@pytest.mark.parametrize(('owner', 'dependent', 'controller', 'path'), EXPECTED_CANDIDATES)
def test_every_review_candidate_has_an_explicit_rule_without_database(
    owner, dependent, controller, path
):
    model = apps.get_model(owner)
    names = (dependent, controller)
    form = resource_form(model, names)
    expected = INVERSE.get(
        (owner, dependent, controller),
        INVERSE.get((owner, dependent), (dependent, controller, path)),
    )
    name, source, relation = expected
    rules = form._related_field_rules.get(name, [])
    assert any(rule['field'] == source and rule['path'] == relation for rule in rules), (
        owner,
        expected,
        rules,
    )


def test_frozen_candidates_are_covered_on_every_editable_registry_surface_without_database():
    from django.contrib.auth import get_user_model
    from django.test import RequestFactory
    from base.ui.forms import build_resource_form
    from base.ui.registry import get_modules
    from base.ui.views import _build_inline_formset

    request = RequestFactory().get('/')
    request.user = get_user_model()(is_staff=True, is_superuser=True, is_active=True)
    seen = set()
    surfaces = []

    def check(form, model, context):
        for owner, dependent, controller, path in EXPECTED_CANDIDATES:
            if model._meta.label_lower != owner:
                continue
            expected = INVERSE.get(
                (owner, dependent, controller),
                INVERSE.get((owner, dependent), (dependent, controller, path)),
            )
            name, source, relation = expected
            field, other = form.fields.get(name), form.fields.get(source)
            if field is None or other is None or field.disabled or field.widget.is_hidden:
                continue
            rules = form._related_field_rules.get(name, [])
            if other.widget.is_hidden:
                assert any(
                    rule['field'] == source and 'controller_form' in rule for rule in rules
                ), (context, owner, expected, 'hidden parent requires authoritative binding')
            assert any(rule['field'] == source and rule['path'] == relation for rule in rules), (
                context,
                owner,
                expected,
            )
            seen.add((owner, dependent, controller, path))
            surfaces.append((context, owner, dependent, controller, path))

    for module in get_modules():
        for resource in module.resources:
            for update in (False, True):
                form = build_resource_form(resource, update=update)(request=request)
                check(
                    form,
                    resource.model,
                    (module.slug, resource.slug, 'update' if update else 'create'),
                )
            for inline in resource.inlines:
                parent = build_resource_form(resource)(request=request)
                formset = _build_inline_formset(
                    request, resource, inline, instance=parent.instance, parent_form=parent
                )
                check(
                    formset.empty_form, inline.child_model, (module.slug, resource.slug, inline.key)
                )
    assert seen == set(EXPECTED_CANDIDATES)
    assert len(surfaces) == len(set(surfaces))


def test_registered_actions_have_no_unbound_model_specific_pairs():
    from base.ui.actions.registry import action_registry
    from base.ui.related_fields import MODEL_DEPENDENCIES

    # Action forms do not carry a ModelForm owner. Do not apply owner-scoped
    # rules to arbitrary same-named action fields. Make a new applicable action
    # fail explicitly until its owner/context is passed by the action builder.
    unbound = []
    for config in action_registry.all():
        names = {field.name for field in config.fields}
        for dependent, controller, _path, _generic in MODEL_DEPENDENCIES.get(
            config.model._meta.label_lower, ()
        ):
            if dependent in names and controller.partition('__')[0] in names:
                unbound.append(
                    (config.model._meta.label_lower, config.action_name, dependent, controller)
                )
    assert unbound == []
