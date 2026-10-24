from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from base.ui.forms import build_resource_form
from base.ui.registry import get_resource
from formulations.models import FormulaComponent, MasterFormula
from formulations.reuse import (
    build_master_formula_reuse_form,
    component_reuse_initial,
    is_formula_version_conflict,
    master_formula_reuse_initial,
)
from masters.models import Product, UnitOfMeasure


class FormulaInlineComponentsUiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            email='admin-formulas@example.com',
            password='S3curePass!123',
            username='Admin Formulas',
        )
        self.client.force_login(self.user)
        self.unit = UnitOfMeasure.objects.create(
            code='KG',
            name='Quilograma',
            symbol='kg',
        )
        self.product = Product.objects.create(
            code='PA-PAR500',
            description='Paracetamol 500mg comprimido',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=self.unit,
            status=Product.Status.APPROVED,
        )
        self.materials = [
            Product.objects.create(
                code=f'MAT-{index}',
                description=f'Material {index}',
                item_type=item_type,
                unit=self.unit,
                status=Product.Status.APPROVED,
            )
            for index, item_type in enumerate(
                [
                    Product.ItemType.RAW_MATERIAL,
                    Product.ItemType.EXCIPIENT,
                    Product.ItemType.PACKAGING,
                    Product.ItemType.PACKAGING,
                ],
                start=1,
            )
        ]

    def test_master_formula_reuse_builders_copy_only_approved_values(self):
        source, component = self._formula_with_component('FRM-REUSE-SOURCE', quantity='2.5000')
        source.status = MasterFormula.Status.APPROVED
        source.expected_yield_percent = Decimal('98.7500')
        source.notes = 'Origem validada.'
        source.save()
        MasterFormula.objects.create(
            product=self.product,
            code='FRM-REUSE-V3',
            version=3,
            batch_size=Decimal('100.0000'),
            batch_unit=self.unit,
        )

        parent_initial = master_formula_reuse_initial(source)
        children_initial = component_reuse_initial(source)

        assert parent_initial == {
            'product': self.product.pk,
            'version': 4,
            'status': MasterFormula.Status.DRAFT,
            'batch_size': source.batch_size,
            'batch_unit': self.unit.pk,
            'expected_yield_percent': Decimal('98.7500'),
            'effective_from': source.effective_from,
            'effective_to': source.effective_to,
            'notes': 'Origem validada.',
        }
        assert children_initial == [
            {
                'line_number': component.line_number,
                'material': component.material_id,
                'role': component.role,
                'quantity': component.quantity,
                'unit': component.unit_id,
                'expected_loss_percent': component.expected_loss_percent,
                'conversion_factor': component.conversion_factor,
                'is_active': component.is_active,
            }
        ]
        assert 'code' not in parent_initial
        assert 'copied_from' not in parent_initial

    def test_master_formula_reuse_form_hides_source_and_locks_status(self):
        form_class = build_master_formula_reuse_form(get_resource('formulations', 'formulas'))
        form = form_class(request=type('Request', (), {'user': self.user})())

        assert 'copied_from' not in form.fields
        assert form.fields['code'].disabled is True
        assert form.fields['status'].disabled is True
        assert form.fields['status'].initial == MasterFormula.Status.DRAFT

    def test_formula_version_conflict_classifier_is_constraint_specific(self):
        conflict = IntegrityError(
            'UNIQUE constraint failed: '
            'formulations_masterformula.product_id, formulations_masterformula.version'
        )
        unrelated = IntegrityError('UNIQUE constraint failed: formulations_masterformula.code')

        assert is_formula_version_conflict(conflict) is True
        assert is_formula_version_conflict(unrelated) is False

    def test_formula_list_offers_reuse_to_fully_authorized_user(self):
        source = self._formula_with_component('FRM-LIST-REUSE', quantity='1.0000')[0]

        response = self.client.get(
            reverse(
                'app:resource_list',
                kwargs={'module_slug': 'formulations', 'resource_slug': 'formulas'},
            )
        )

        assert response.status_code == 200
        assert 'Reaproveitar' in response.content.decode()
        assert (
            reverse('app:master_formula_reuse', kwargs={'pk': source.pk})
            in response.content.decode()
        )

    def test_formula_reuse_button_and_url_require_parent_and_component_permissions(self):
        source = self._formula_with_component('FRM-REUSE-PERMS', quantity='1.0000')[0]
        user = get_user_model().objects.create_user(
            email='reuse-permissions@example.com',
            password='S3curePass!123',
            username='Permissões de reaproveitamento',
        )
        permissions = Permission.objects.filter(
            content_type__app_label='formulations',
            codename__in=('view_masterformula', 'add_masterformula'),
        )
        user.user_permissions.set(permissions)
        self.client.force_login(user)

        list_response = self.client.get(
            reverse(
                'app:resource_list',
                kwargs={'module_slug': 'formulations', 'resource_slug': 'formulas'},
            )
        )
        direct_response = self.client.get(
            reverse('app:master_formula_reuse', kwargs={'pk': source.pk})
        )

        assert list_response.status_code == 200
        assert 'Reaproveitar' not in list_response.content.decode()
        assert direct_response.status_code == 403

    def test_formula_reuse_get_prefills_parent_and_all_components_without_persisting(self):
        from base.models import IdentifierSequence
        from governance.models import GovernanceAuditLog

        source, first = self._formula_with_component('FRM-REUSE-GET', quantity='2.0000')
        second = FormulaComponent.objects.create(
            formula=source,
            line_number=20,
            material=self.materials[1],
            role=FormulaComponent.Role.EXCIPIENT,
            quantity=Decimal('3.0000'),
            unit=self.unit,
        )
        MasterFormula.objects.create(
            product=self.product,
            code='FRM-REUSE-GET-V4',
            version=4,
            batch_size=Decimal('100.0000'),
            batch_unit=self.unit,
        )
        formula_count = MasterFormula.objects.count()
        component_count = FormulaComponent.objects.count()
        audit_count = GovernanceAuditLog.objects.count()
        sequence_count = IdentifierSequence.objects.count()

        response = self.client.get(reverse('app:master_formula_reuse', kwargs={'pk': source.pk}))

        assert response.status_code == 200
        form = response.context['form']
        formset = response.context['inline_formsets'][0]['formset']
        assert form.initial['product'] == self.product.pk
        assert form.initial['version'] == 5
        assert form.initial['status'] == MasterFormula.Status.DRAFT
        assert 'copied_from' not in form.fields
        copied_rows = [row.initial for row in formset.forms if row.initial.get('line_number')]
        assert [row['line_number'] for row in copied_rows] == [10, 20]
        assert [row['material'] for row in copied_rows] == [
            first.material_id,
            second.material_id,
        ]
        assert all(not row.instance.pk for row in formset.forms)
        assert MasterFormula.objects.count() == formula_count
        assert FormulaComponent.objects.count() == component_count
        assert GovernanceAuditLog.objects.count() == audit_count
        assert IdentifierSequence.objects.count() == sequence_count

    def test_formula_reuse_missing_source_returns_404(self):
        response = self.client.get(reverse('app:master_formula_reuse', kwargs={'pk': 999999}))

        assert response.status_code == 404

    def test_formula_reuse_post_generates_code_traceability_and_new_components(self):
        from governance.models import GovernanceAuditLog

        source, first = self._formula_with_component('FRM-REUSE-POST', quantity='2.0000')
        second = FormulaComponent.objects.create(
            formula=source,
            line_number=20,
            material=self.materials[1],
            role=FormulaComponent.Role.EXCIPIENT,
            quantity=Decimal('3.0000'),
            unit=self.unit,
        )
        payload = {
            **self._formula_payload('TAMPERED-CODE'),
            'version': '2',
            'status': MasterFormula.Status.APPROVED,
            'copied_from': '',
            'components-TOTAL_FORMS': '2',
            'components-INITIAL_FORMS': '0',
            'components-MIN_NUM_FORMS': '0',
            'components-MAX_NUM_FORMS': '1000',
            **self._component_payload(0, 10, first.material, first.role),
            **self._component_payload(1, 20, second.material, second.role),
        }

        response = self.client.post(
            reverse('app:master_formula_reuse', kwargs={'pk': source.pk}), payload
        )

        assert response.status_code == 302, self._response_form_errors(response)
        reused = MasterFormula.objects.exclude(pk=source.pk).get(version=2)
        assert reused.code.startswith('MF-')
        assert reused.code != 'TAMPERED-CODE'
        assert reused.status == MasterFormula.Status.DRAFT
        assert reused.copied_from == source
        assert reused.components.count() == 2
        assert not set(reused.components.values_list('pk', flat=True)) & {
            first.pk,
            second.pk,
        }
        audit = GovernanceAuditLog.objects.get(
            action='ui.resource.created',
            target_model='MasterFormula',
            target_record_id=str(reused.pk),
        )
        assert audit.safe_context['inline_resources']['components'] == 2
        source.refresh_from_db()
        assert source.code == 'FRM-REUSE-POST'
        assert source.components.count() == 2

    def test_formula_reuse_child_failure_rolls_back_parent(self):
        source = self._formula_with_component('FRM-REUSE-ROLLBACK', quantity='2.0000')[0]
        payload = {
            **self._formula_payload('IGNORED'),
            'version': '2',
            'components-TOTAL_FORMS': '1',
            'components-INITIAL_FORMS': '0',
            'components-MIN_NUM_FORMS': '0',
            'components-MAX_NUM_FORMS': '1000',
            **self._component_payload(
                0,
                10,
                self.materials[0],
                FormulaComponent.Role.ACTIVE,
            ),
        }

        with patch.object(FormulaComponent, 'save', side_effect=RuntimeError('storage failure')):
            with self.assertRaisesMessage(RuntimeError, 'storage failure'):
                self.client.post(
                    reverse('app:master_formula_reuse', kwargs={'pk': source.pk}),
                    payload,
                )

        assert MasterFormula.objects.count() == 1
        assert FormulaComponent.objects.count() == 1

    def test_formula_reuse_version_integrity_conflict_returns_form_error(self):
        source = self._formula_with_component('FRM-REUSE-CONFLICT', quantity='2.0000')[0]
        payload = {
            **self._formula_payload('IGNORED'),
            'version': '2',
            'components-TOTAL_FORMS': '0',
            'components-INITIAL_FORMS': '0',
            'components-MIN_NUM_FORMS': '0',
            'components-MAX_NUM_FORMS': '1000',
        }
        conflict = IntegrityError(
            'UNIQUE constraint failed: '
            'formulations_masterformula.product_id, formulations_masterformula.version'
        )

        with patch.object(MasterFormula, 'save', side_effect=conflict):
            response = self.client.post(
                reverse('app:master_formula_reuse', kwargs={'pk': source.pk}), payload
            )

        assert response.status_code == 200
        assert 'Esta versão já foi utilizada' in response.content.decode()
        assert MasterFormula.objects.count() == 1

    def test_formula_form_renders_inline_component_section(self):
        # A fórmula nasce do produto ou de uma cópia: o formulário em branco não existe.
        formula, _ = self._formula_with_component('FRM-RENDER', quantity='1.0000')
        response = self.client.get(self._formula_edit_url(formula))

        assert response.status_code == 200
        content = response.content.decode()
        assert 'data-inline-formset="components"' in content
        assert 'Componentes da fórmula' in content
        assert 'Adicionar componente' in content
        assert 'components-TOTAL_FORMS' in content

    def test_stacked_formula_delete_control_is_icon_action(self):
        formula, _ = self._formula_with_component('FRM-ICON', quantity='1.0000')
        response = self.client.get(self._formula_edit_url(formula))

        assert response.status_code == 200
        section = response.content.decode().split('data-inline-formset="components"', 1)[1]
        assert 'resource-inline-formset__form' in section
        assert '<table' not in section
        assert 'data-inline-formset-delete' in section
        assert 'aria-label="Excluir item"' in section
        assert 'feather-trash-2' in section
        assert '<span class="visually-hidden">' in section

    def test_qc_grid_template_uses_icon_delete_action(self):
        template = Path('templates/app/includes/inline_qc_grid.html').read_text()

        assert '>Ações</th>' in template
        assert '>Excluir</th>' not in template
        assert 'data-inline-formset-delete' in template
        assert 'aria-label="Excluir item"' in template
        assert 'feather-trash-2' in template
        assert '<span class="visually-hidden">' in template

    def test_inline_delete_action_marks_delete_field_and_hides_row(self):
        template = Path('templates/app/resource_form.html').read_text()

        assert "event.target.closest('[data-inline-formset-delete]')" in template
        assert 'deleteField.checked = true;' in template
        assert "row.classList.add('d-none');" in template

    def test_priority_parent_forms_render_registered_inline_sections(self):
        expectations = self._priority_inline_expectations()

        for module_slug, resource_slug, inline_key, title in expectations:
            resource = get_resource(module_slug, resource_slug)
            assert inline_key in {inline.key for inline in resource.inlines}
            if not resource.allow_create:
                # Coberto pelo formulário de edição em
                # test_formula_form_renders_inline_component_section.
                continue

            response = self.client.get(
                reverse(
                    'app:resource_create',
                    kwargs={'module_slug': module_slug, 'resource_slug': resource_slug},
                )
            )

            assert response.status_code == 200
            content = response.content.decode()
            assert f'data-inline-formset="{inline_key}"' in content
            assert title in content
            assert f'{inline_key}-TOTAL_FORMS' in content

    def test_priority_inline_registry_covers_prd_relationships(self):
        expected_relationships = {
            ('formulations', 'formulas'): {'components': ('FormulaComponent', 'formula')},
            ('production', 'orders'): {
                'material-consumptions': ('MaterialConsumption', 'order'),
                'outputs': ('ProductionOutput', 'order'),
                'operations': ('ProductionOperationExecution', 'order'),
                'labor-entries': ('ProductionLaborEntry', 'order'),
            },
            ('procurement', 'orders'): {'items': ('PurchaseOrderItem', 'order')},
            ('procurement', 'receipts'): {'items': ('PurchaseReceiptItem', 'receipt')},
            ('documents', 'controlled-documents'): {
                'attachments': ('DocumentAttachment', 'document'),
                'approvals': ('DocumentApproval', 'document'),
                'distributions': ('DocumentDistribution', 'document'),
            },
            ('deviations', 'events'): {
                'investigations': ('DeviationInvestigation', 'event'),
                'impact-assessments': ('DeviationImpactAssessment', 'event'),
                'approvals': ('DeviationApproval', 'event'),
                'evidences': ('DeviationEvidence', 'event'),
            },
            ('capa', 'records'): {
                'actions': ('CapaAction', 'capa'),
                'evidences': ('CapaEvidence', 'capa'),
                'approvals': ('CapaApproval', 'capa'),
                'effectiveness-checks': ('EffectivenessCheck', 'capa'),
            },
            ('audits', 'plans'): {
                'checklist-items': ('AuditChecklistItem', 'audit'),
                'findings': ('AuditFinding', 'audit'),
                'evidences': ('AuditEvidence', 'audit'),
            },
            ('audits', 'findings'): {
                'actions': ('AuditFollowUpAction', 'finding'),
            },
            ('risks', 'records'): {
                'assessments': ('RiskAssessment', 'risk'),
                'controls': ('RiskControl', 'risk'),
                'actions': ('RiskMitigationAction', 'risk'),
                'reviews': ('RiskReview', 'risk'),
                'alerts': ('RiskAlert', 'risk'),
            },
            ('recalls', 'campaigns'): {
                'impacted-customers': ('RecallImpactedCustomer', 'campaign'),
                'communications': ('RecallCommunication', 'campaign'),
                'reports': ('RecallEffectivenessReport', 'campaign'),
            },
        }

        actual_relationships = {}
        for parent, expected_inlines in expected_relationships.items():
            resource = get_resource(*parent)
            actual_relationships[parent] = {
                inline.key: (inline.child_model.__name__, inline.parent_field)
                for inline in resource.inlines
                if inline.key in expected_inlines
            }

        assert actual_relationships == expected_relationships

    def test_production_material_inline_includes_allocation_fields_for_operational_actions(self):
        resource = get_resource('production', 'orders')
        material_inline = next(
            inline for inline in resource.inlines if inline.key == 'material-consumptions'
        )

        assert {'stock_lot', 'warehouse', 'location'} <= set(material_inline.fields)
        assert 'lot_number' not in material_inline.fields
        assert {
            'reserved_quantity',
            'issued_quantity',
            'reservation_movement',
            'issue_movement',
        } & set(material_inline.fields) == set()

    def test_regulated_inline_forms_exclude_controlled_decision_fields(self):
        document = get_resource('documents', 'controlled-documents')
        document_fields = {inline.key: inline.fields for inline in document.inlines}
        assert document_fields['approvals'] == ('role', 'user')
        assert document_fields['distributions'] == ('recipient', 'due_date')

        deviation = get_resource('deviations', 'events')
        deviation_fields = {inline.key: inline.fields for inline in deviation.inlines}
        assert 'decision' not in deviation_fields['approvals']

        capa = get_resource('capa', 'records')
        capa_fields = {inline.key: inline.fields for inline in capa.inlines}
        assert 'decision' not in capa_fields['approvals']
        assert 'status' not in capa_fields['actions']
        assert 'result' not in capa_fields['effectiveness-checks']

    def test_regulated_document_outcomes_are_read_only_outside_parent_workflow(self):
        from documents.models import ControlledDocument, DocumentApproval

        approval_resource = get_resource('documents', 'approvals')
        distribution_resource = get_resource('documents', 'distributions')
        assert approval_resource.read_only is True
        assert distribution_resource.read_only is True

        document = ControlledDocument.objects.create(
            document_type=ControlledDocument.DocumentType.POLICY,
            code='POL-READ-ONLY-OUTCOMES',
            title='Resultados controlados',
            area='Qualidade',
            effective_from=timezone.localdate(),
            owner=self.user,
            content='Conteúdo controlado.',
            change_summary='Emissão inicial.',
        )
        approval = DocumentApproval.objects.create(
            document=document,
            role=DocumentApproval.Role.APPROVER,
            user=self.user,
        )

        create_response = self.client.get(
            reverse(
                'app:resource_create',
                kwargs={'module_slug': 'documents', 'resource_slug': 'approvals'},
            )
        )
        edit_response = self.client.get(
            reverse(
                'app:resource_edit',
                kwargs={
                    'module_slug': 'documents',
                    'resource_slug': 'approvals',
                    'pk': approval.pk,
                },
            )
        )

        assert create_response.status_code == 403
        assert edit_response.status_code == 403
        approval.refresh_from_db()
        assert approval.decision == DocumentApproval.Decision.PENDING

    def test_document_inline_actor_fields_are_attributed_to_request_user(self):
        from documents.models import ControlledDocument, DocumentAttachment, DocumentDistribution

        document = get_resource('documents', 'controlled-documents')
        inline_actor_fields = {inline.key: inline.actor_field for inline in document.inlines}
        assert inline_actor_fields['attachments'] == 'uploaded_by'
        assert inline_actor_fields['distributions'] == 'distributed_by'

        controlled_document = ControlledDocument.objects.create(
            document_type=ControlledDocument.DocumentType.POLICY,
            code='POL-INLINE-ACTOR',
            title='Atribuição de atores',
            area='Qualidade',
            version='1.0',
            status=ControlledDocument.Status.PUBLISHED,
            effective_from=timezone.localdate(),
            owner=self.user,
            content='Conteúdo controlado.',
            change_summary='Emissão inicial.',
        )
        response = self.client.post(
            reverse(
                'app:resource_edit',
                kwargs={
                    'module_slug': 'documents',
                    'resource_slug': 'controlled-documents',
                    'pk': controlled_document.pk,
                },
            ),
            {
                'document_type': controlled_document.document_type,
                'code': controlled_document.code,
                'title': controlled_document.title,
                'area': controlled_document.area,
                'area_ref': '',
                'version': controlled_document.version,
                'effective_from': controlled_document.effective_from.isoformat(),
                'valid_until': '',
                'owner': str(self.user.pk),
                'content': controlled_document.content,
                'change_summary': controlled_document.change_summary,
                'supersedes': '',
                'attachments-TOTAL_FORMS': '1',
                'attachments-INITIAL_FORMS': '0',
                'attachments-MIN_NUM_FORMS': '0',
                'attachments-MAX_NUM_FORMS': '1000',
                'attachments-0-file_name': 'procedimento.pdf',
                'attachments-0-file_reference': 'documents/procedimento.pdf',
                'attachments-0-content_hash': 'sha256:documento-controlado',
                'attachments-0-description': 'Anexo controlado.',
                'approvals-TOTAL_FORMS': '0',
                'approvals-INITIAL_FORMS': '0',
                'approvals-MIN_NUM_FORMS': '0',
                'approvals-MAX_NUM_FORMS': '1000',
                'distributions-TOTAL_FORMS': '1',
                'distributions-INITIAL_FORMS': '0',
                'distributions-MIN_NUM_FORMS': '0',
                'distributions-MAX_NUM_FORMS': '1000',
                'distributions-0-recipient': str(self.user.pk),
                'distributions-0-due_date': timezone.localdate().isoformat(),
            },
        )

        assert response.status_code == 302, self._response_form_errors(response)
        assert DocumentAttachment.objects.get(document=controlled_document).uploaded_by == self.user
        assert (
            DocumentDistribution.objects.get(document=controlled_document).distributed_by
            == self.user
        )

    def test_document_ui_creation_records_domain_audit_in_same_flow(self):
        from documents.models import ControlledDocument, DocumentAuditTrail

        response = self.client.post(
            reverse(
                'app:resource_create',
                kwargs={
                    'module_slug': 'documents',
                    'resource_slug': 'controlled-documents',
                },
            ),
            {
                'document_type': ControlledDocument.DocumentType.POLICY,
                'code': 'POL-CREATION-AUDIT',
                'title': 'Auditoria de criação',
                'area': 'Qualidade',
                'area_ref': '',
                'version': '1.0',
                'effective_from': timezone.localdate().isoformat(),
                'valid_until': '',
                'owner': str(self.user.pk),
                'content': 'Conteúdo controlado.',
                'change_summary': 'Emissão inicial auditada.',
                'supersedes': '',
                'attachments-TOTAL_FORMS': '0',
                'attachments-INITIAL_FORMS': '0',
                'attachments-MIN_NUM_FORMS': '0',
                'attachments-MAX_NUM_FORMS': '1000',
                'approvals-TOTAL_FORMS': '0',
                'approvals-INITIAL_FORMS': '0',
                'approvals-MIN_NUM_FORMS': '0',
                'approvals-MAX_NUM_FORMS': '1000',
                'distributions-TOTAL_FORMS': '0',
                'distributions-INITIAL_FORMS': '0',
                'distributions-MIN_NUM_FORMS': '0',
                'distributions-MAX_NUM_FORMS': '1000',
            },
        )

        assert response.status_code == 302, self._response_form_errors(response)
        controlled_document = ControlledDocument.objects.get(title='Auditoria de criação')
        assert controlled_document.code.startswith('DOC-')
        assert controlled_document.code != 'POL-CREATION-AUDIT'
        creation_audit = DocumentAuditTrail.objects.get(
            document=controlled_document,
            action=DocumentAuditTrail.Action.CREATED,
        )
        assert creation_audit.actor == self.user
        assert creation_audit.reason == controlled_document.change_summary

    def test_gxp_resources_block_generic_hard_delete(self):
        formula = MasterFormula.objects.create(
            product=self.product,
            code='FRM-RETENTION',
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=self.unit,
        )
        response = self.client.post(
            reverse(
                'app:resource_delete',
                kwargs={
                    'module_slug': 'formulations',
                    'resource_slug': 'formulas',
                    'pk': formula.pk,
                },
            )
        )

        # Formulations remain editable master data; regulated execution records are retained.
        assert response.status_code == 302

        from documents.models import ControlledDocument

        controlled_document = ControlledDocument.objects.create(
            document_type=ControlledDocument.DocumentType.POLICY,
            code='POL-RETENTION',
            title='Política retida',
            area='Qualidade',
            version='1.0',
            effective_from=timezone.localdate(),
            owner=self.user,
            content='Conteúdo controlado.',
            change_summary='Emissão inicial.',
        )
        response = self.client.post(
            reverse(
                'app:resource_delete',
                kwargs={
                    'module_slug': 'documents',
                    'resource_slug': 'controlled-documents',
                    'pk': controlled_document.pk,
                },
            )
        )

        assert response.status_code == 403
        assert ControlledDocument.objects.filter(pk=controlled_document.pk).exists()

    def test_formula_form_creates_multiple_components_in_same_post(self):
        formula = MasterFormula.objects.create(
            product=self.product,
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=self.unit,
        )
        response = self.client.post(
            self._formula_edit_url(formula),
            {
                'version': '1',
                'status': MasterFormula.Status.DRAFT,
                'batch_size': '100.0000',
                'batch_unit': str(self.unit.pk),
                'expected_yield_percent': '98.5000',
                'effective_from': '',
                'effective_to': '',
                'copied_from': '',
                'notes': 'Fórmula criada com componentes inline.',
                'components-TOTAL_FORMS': '4',
                'components-INITIAL_FORMS': '0',
                'components-MIN_NUM_FORMS': '0',
                'components-MAX_NUM_FORMS': '1000',
                **self._component_payload(0, 10, self.materials[0], FormulaComponent.Role.ACTIVE),
                **self._component_payload(
                    1, 20, self.materials[1], FormulaComponent.Role.EXCIPIENT
                ),
                **self._component_payload(
                    2, 30, self.materials[2], FormulaComponent.Role.PACKAGING
                ),
                **self._component_payload(
                    3, 40, self.materials[3], FormulaComponent.Role.PACKAGING
                ),
            },
        )

        assert response.status_code == 302, self._response_form_errors(response)
        formula.refresh_from_db()
        assert formula.notes == 'Fórmula criada com componentes inline.'
        assert formula.code == f'MF-{formula.pk}'
        assert formula.components.count() == 4
        assert list(
            formula.components.order_by('line_number').values_list('line_number', flat=True)
        ) == [
            10,
            20,
            30,
            40,
        ]
        from governance.models import GovernanceAuditLog

        audit = GovernanceAuditLog.objects.get(
            action='ui.resource.updated',
            target_model='MasterFormula',
            target_record_id=str(formula.pk),
        )
        assert audit.user == self.user
        assert audit.safe_context['inline_resources']['components'] == 4

    def test_formula_edit_form_loads_existing_components(self):
        formula = MasterFormula.objects.create(
            product=self.product,
            code='FRM-EDIT',
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=self.unit,
        )
        component = FormulaComponent.objects.create(
            formula=formula,
            line_number=10,
            material=self.materials[0],
            role=FormulaComponent.Role.ACTIVE,
            quantity=Decimal('2.0000'),
            unit=self.unit,
        )

        response = self.client.get(
            reverse(
                'app:resource_edit',
                kwargs={
                    'module_slug': 'formulations',
                    'resource_slug': 'formulas',
                    'pk': formula.pk,
                },
            )
        )

        assert response.status_code == 200
        formset = response.context['inline_formsets'][0]['formset']
        assert formset.initial_form_count() == 1
        assert formset.forms[0].instance == component
        content = response.content.decode()
        assert 'name="components-0-line_number"' in content
        assert f'value="{component.pk}"' in content

    def test_formula_edit_form_omits_copied_from_traceability_field(self):
        formula = MasterFormula.objects.create(
            product=self.product,
            code='FRM-EDIT-NO-SOURCE',
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=self.unit,
        )

        response = self.client.get(self._formula_edit_url(formula))

        assert response.status_code == 200
        assert 'copied_from' not in response.context['form'].fields
        assert 'name="copied_from"' not in response.content.decode()

    def test_formula_edit_updates_and_deletes_existing_components(self):
        formula, first = self._formula_with_component('FRM-EDIT-POST', quantity='2.0000')
        second = FormulaComponent.objects.create(
            formula=formula,
            line_number=20,
            material=self.materials[1],
            role=FormulaComponent.Role.EXCIPIENT,
            quantity=Decimal('3.0000'),
            unit=self.unit,
        )
        payload = {
            **self._formula_payload(formula.code),
            'components-TOTAL_FORMS': '2',
            'components-INITIAL_FORMS': '2',
            'components-MIN_NUM_FORMS': '0',
            'components-MAX_NUM_FORMS': '1000',
            **self._existing_component_payload(0, first, quantity='5.0000'),
            **self._existing_component_payload(1, second, quantity='3.0000'),
            'components-1-DELETE': 'on',
        }

        response = self.client.post(self._formula_edit_url(formula), payload)

        assert response.status_code == 302, self._response_form_errors(response)
        first.refresh_from_db()
        assert first.quantity == Decimal('5.0000')
        assert not FormulaComponent.objects.filter(pk=second.pk).exists()

    def test_formula_edit_child_failure_rolls_back_parent_and_existing_child(self):
        formula, component = self._formula_with_component('FRM-EDIT-ROLLBACK', quantity='2.0000')
        payload = {
            **self._formula_payload(formula.code),
            'notes': 'Alteração que precisa ser revertida.',
            'components-TOTAL_FORMS': '1',
            'components-INITIAL_FORMS': '1',
            'components-MIN_NUM_FORMS': '0',
            'components-MAX_NUM_FORMS': '1000',
            **self._existing_component_payload(0, component, quantity='9.0000'),
        }

        with patch.object(FormulaComponent, 'save', side_effect=RuntimeError('storage failure')):
            with self.assertRaisesMessage(RuntimeError, 'storage failure'):
                self.client.post(self._formula_edit_url(formula), payload)

        formula.refresh_from_db()
        component.refresh_from_db()
        assert formula.notes == ''
        assert component.quantity == Decimal('2.0000')

    def test_child_save_failure_rolls_back_parent_and_children(self):
        formula = MasterFormula.objects.create(
            product=self.product,
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=self.unit,
            notes='Notas preservadas pelo rollback.',
        )
        payload = {
            **self._formula_payload('FRM-ROLLBACK'),
            'components-TOTAL_FORMS': '1',
            'components-INITIAL_FORMS': '0',
            'components-MIN_NUM_FORMS': '0',
            'components-MAX_NUM_FORMS': '1000',
            **self._component_payload(0, 10, self.materials[0], FormulaComponent.Role.ACTIVE),
        }

        with patch.object(FormulaComponent, 'save', side_effect=RuntimeError('storage failure')):
            with self.assertRaisesMessage(RuntimeError, 'storage failure'):
                self.client.post(self._formula_edit_url(formula), payload)

        formula.refresh_from_db()
        assert formula.notes == 'Notas preservadas pelo rollback.'
        assert FormulaComponent.objects.count() == 0

    def test_child_add_permission_is_enforced_before_atomic_save(self):
        user = get_user_model().objects.create_user(
            email='formula-operator@example.com',
            password='S3curePass!123',
            username='Operador de Fórmulas',
        )
        self.client.force_login(user)
        child_add_permission = Permission.objects.get(
            content_type__app_label='formulations', codename='add_formulacomponent'
        )
        user.user_permissions.remove(child_add_permission)
        user._perm_cache = set(user.get_all_permissions())
        user._perm_cache.discard('formulations.add_formulacomponent')

        response = self.client.post(
            reverse(
                'app:resource_create',
                kwargs={'module_slug': 'formulations', 'resource_slug': 'formulas'},
            ),
            {
                **self._formula_payload('FRM-NO-CHILD-PERMISSION'),
                'components-TOTAL_FORMS': '1',
                'components-INITIAL_FORMS': '0',
                'components-MIN_NUM_FORMS': '0',
                'components-MAX_NUM_FORMS': '1000',
                **self._component_payload(0, 10, self.materials[0], FormulaComponent.Role.ACTIVE),
            },
        )

        assert response.status_code == 403
        assert not MasterFormula.objects.filter(code='FRM-NO-CHILD-PERMISSION').exists()
        assert FormulaComponent.objects.count() == 0

    def test_component_resource_form_validates_without_legacy_scope_context(self):
        formula = MasterFormula.objects.create(
            product=self.product,
            code='FRM-COMP',
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=self.unit,
        )
        request = type('Request', (), {'user': self.user})()
        form_class = build_resource_form(get_resource('formulations', 'components'))

        form = form_class(
            {
                'formula': str(formula.pk),
                'line_number': '10',
                'material': str(self.materials[0].pk),
                'role': FormulaComponent.Role.ACTIVE,
                'quantity': '1.0000',
                'unit': str(self.unit.pk),
                'expected_loss_percent': '0.0000',
                'conversion_factor': '1.000000',
                'is_active': 'on',
            },
            request=request,
        )

        assert form.is_valid(), form.errors

    def _component_payload(self, index, line_number, material, role):
        return {
            f'components-{index}-id': '',
            f'components-{index}-formula': '',
            f'components-{index}-line_number': str(line_number),
            f'components-{index}-material': str(material.pk),
            f'components-{index}-role': role,
            f'components-{index}-quantity': str(Decimal('1.0000') * index + Decimal('1.0000')),
            f'components-{index}-unit': str(self.unit.pk),
            f'components-{index}-expected_loss_percent': '0.0000',
            f'components-{index}-conversion_factor': '1.000000',
            f'components-{index}-is_active': 'on',
        }

    def _formula_with_component(self, code, *, quantity):
        formula = MasterFormula.objects.create(
            product=self.product,
            code=code,
            version=1,
            batch_size=Decimal('100.0000'),
            batch_unit=self.unit,
        )
        component = FormulaComponent.objects.create(
            formula=formula,
            line_number=10,
            material=self.materials[0],
            role=FormulaComponent.Role.ACTIVE,
            quantity=Decimal(quantity),
            unit=self.unit,
        )
        return formula, component

    def _existing_component_payload(self, index, component, *, quantity):
        return {
            f'components-{index}-id': str(component.pk),
            f'components-{index}-formula': str(component.formula_id),
            f'components-{index}-line_number': str(component.line_number),
            f'components-{index}-material': str(component.material_id),
            f'components-{index}-role': component.role,
            f'components-{index}-quantity': quantity,
            f'components-{index}-unit': str(component.unit_id),
            f'components-{index}-expected_loss_percent': str(component.expected_loss_percent),
            f'components-{index}-conversion_factor': str(component.conversion_factor),
            f'components-{index}-is_active': 'on',
        }

    def _formula_edit_url(self, formula):
        return reverse(
            'app:resource_edit',
            kwargs={
                'module_slug': 'formulations',
                'resource_slug': 'formulas',
                'pk': formula.pk,
            },
        )

    def _formula_edit_url(self, formula):
        return reverse(
            'app:resource_edit',
            kwargs={
                'module_slug': 'formulations',
                'resource_slug': 'formulas',
                'pk': formula.pk,
            },
        )

    def _formula_payload(self, code):
        return {
            'product': str(self.product.pk),
            'code': code,
            'version': '1',
            'status': MasterFormula.Status.DRAFT,
            'batch_size': '100.0000',
            'batch_unit': str(self.unit.pk),
            'expected_yield_percent': '98.5000',
            'effective_from': '',
            'effective_to': '',
            'copied_from': '',
            'notes': 'Teste do contrato transacional de formulários inline.',
        }

    def _priority_inline_expectations(self):
        return [
            ('formulations', 'formulas', 'components', 'Componentes da fórmula'),
            ('production', 'orders', 'material-consumptions', 'Matérias-primas'),
            ('production', 'orders', 'outputs', 'Produtos acabados'),
            ('production', 'orders', 'operations', 'Processos'),
            ('production', 'orders', 'labor-entries', 'Colaboradores'),
            ('procurement', 'orders', 'items', 'Itens do pedido'),
            ('procurement', 'receipts', 'items', 'Itens do recebimento'),
            ('documents', 'controlled-documents', 'attachments', 'Anexos documentais'),
            ('documents', 'controlled-documents', 'approvals', 'Aprovações documentais'),
            ('documents', 'controlled-documents', 'distributions', 'Distribuições documentais'),
            ('deviations', 'events', 'investigations', 'Investigações de desvio'),
            ('deviations', 'events', 'impact-assessments', 'Avaliações de impacto'),
            ('deviations', 'events', 'approvals', 'Aprovações de desvio'),
            ('deviations', 'events', 'evidences', 'Evidências de desvio'),
            ('capa', 'records', 'actions', 'Ações CAPA'),
            ('capa', 'records', 'evidences', 'Evidências CAPA'),
            ('capa', 'records', 'approvals', 'Aprovações CAPA'),
            ('capa', 'records', 'effectiveness-checks', 'Verificações de eficácia'),
            ('audits', 'plans', 'checklist-items', 'Checklist de auditoria'),
            ('audits', 'plans', 'findings', 'Achados de auditoria'),
            ('audits', 'plans', 'evidences', 'Evidências de auditoria'),
            ('audits', 'findings', 'actions', 'Ações de auditoria'),
            ('risks', 'records', 'assessments', 'Avaliações de risco'),
            ('risks', 'records', 'controls', 'Controles de risco'),
            ('risks', 'records', 'actions', 'Ações de mitigação'),
            ('risks', 'records', 'reviews', 'Revisões de risco'),
            ('risks', 'records', 'alerts', 'Alertas de risco'),
            ('recalls', 'campaigns', 'impacted-customers', 'Clientes impactados'),
            ('recalls', 'campaigns', 'communications', 'Comunicações de recall'),
            ('recalls', 'campaigns', 'reports', 'Relatório de efetividade'),
        ]

    def _response_form_errors(self, response):
        if not response.context:
            return 'Sem contexto de formulário.'
        inline_errors = []
        for inline in response.context.get('inline_formsets', []):
            formset = inline['formset']
            inline_errors.append(
                {
                    'non_form_errors': list(formset.non_form_errors()),
                    'form_errors': [form.errors for form in formset.forms],
                }
            )
        return {
            'form_errors': response.context['form'].errors,
            'inline_errors': inline_errors,
        }
