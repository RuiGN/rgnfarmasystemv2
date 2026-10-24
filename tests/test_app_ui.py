import base64
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path
import re
import tempfile
import unicodedata
from unittest.mock import patch

import pytest
from django import forms
from django.contrib.auth.models import Permission
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from audits.models import AuditProgram
from auxiliary.models import City, StateProvince
from base.ui.forms import _apply_widget_metadata, build_resource_form
from base.ui.registry import get_modules, get_resource
from base.ui.views import ResourceCreateView
from capa.models import CapaRecord
from compliance.models import RecordStatusHistory
from documents.models import DocumentAuditTrail
from documents.models import ControlledDocument
from files.models import ProtectedFile
from governance.models import GovernanceParameter, InstitutionSettings
from masters.models import Product, UnitOfMeasure
from production.models import ProductionOrder
from risks.models import RiskRecord
from tests.test_production import create_released_manufacturing_set
from workflow.models import WorkflowNotification


def grant_model_perm(user, model, action):
    permission = Permission.objects.get(
        content_type__app_label=model._meta.app_label,
        content_type__model=model._meta.model_name,
        codename=f'{action}_{model._meta.model_name}',
    )
    user.user_permissions.add(permission)


def without_accents(value):
    return ''.join(
        character
        for character in unicodedata.normalize('NFKD', value)
        if not unicodedata.combining(character)
    )


def assert_executed_sql_orders_newest_then_pk(sql, model, timestamp_column):
    normalized = ' '.join(str(sql).lower().translate(str.maketrans('', '', '"`[]')).split())
    expected_table = re.escape(model._meta.db_table.lower())
    expected_pk_column = re.escape(model._meta.pk.column.lower())
    order_pattern = (
        rf'\border by\s+{expected_table}\.{re.escape(timestamp_column)}\s+desc\s*,\s*'
        rf'{expected_table}\.{expected_pk_column}\s+desc\b'
    )
    assert re.search(order_pattern, normalized), normalized
    return normalized


def test_query_transform_replaces_page_and_keeps_authorized_filter_multivalues(rf):
    try:
        from base.templatetags.ui_query import query_transform
    except ModuleNotFoundError:
        pytest.fail('A tag query_transform ainda não foi implementada.')

    request = rf.get(
        '/app/?status=pending&priority=urgent&priority=high&page=2&lookup__icontains=x'
    )
    context = {
        'request': request,
        'allowed_query_params': ('status', 'priority', 'page'),
    }

    assert query_transform(context, page=3) == (
        'status=pending&priority=urgent&priority=high&page=3'
    )


def test_datetime_advanced_filters_emit_safe_range_controls(rf):
    from base.ui.views import build_advanced_filters

    request = rf.get('/app/workflow/tasks/?due_at_from=2026-08-28T09:30&due_at_to=2026-99-99T18:00')

    definitions = build_advanced_filters(
        get_resource('workflow', 'tasks'),
        request.GET,
    )
    due_at = next(item for item in definitions if item['name'] == 'due_at')

    assert due_at['kind'] == 'datetime'
    assert due_at['from_name'] == 'due_at_from'
    assert due_at['to_name'] == 'due_at_to'
    assert due_at['to_value'] == '2026-99-99T18:00'
    assert due_at['from_invalid'] is False
    assert due_at['to_invalid'] is True
    assert due_at['has_submitted_value'] is True
    assert [lookup for lookup, _value in due_at['query_filters']] == ['due_at__gte']
    assert due_at['active_count'] == 1


class AppUiFoundationTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username='qa@example.com',
            email='qa@example.com',
            password='S3curePass!123',
        )
        self.admin = self.User.objects.create_superuser(
            username='admin@example.com', email='admin@example.com', password='S3curePass!123'
        )
        UnitOfMeasure.objects.create(
            code='kg-recife',
            name='Quilograma Recife',
            symbol='kg',
        )
        UnitOfMeasure.objects.create(
            code='kg-goiania',
            name='Quilograma Goiania',
            symbol='kg',
        )

    def test_app_index_requires_login(self):
        response = self.client.get('/app/')

        assert response.status_code == 302
        assert response['Location'].startswith('/accounts/login/')

    def test_governance_parameter_form_base_hook_composes_domain_form(self):
        resource = get_resource('governance', 'parameters')

        assert 'form_base' in resource.__dataclass_fields__

        class ProbeGovernanceParameterForm(forms.ModelForm):
            domain_form_marker = True

            class Meta:
                model = GovernanceParameter
                fields = ()

        configured_resource = replace(resource, form_base=ProbeGovernanceParameterForm)
        form_class = build_resource_form(configured_resource)

        assert issubclass(form_class, ProbeGovernanceParameterForm)
        assert form_class.domain_form_marker is True

    def test_governance_parameter_updated_by_actor_hook_assigns_request_user(self):
        resource = get_resource('governance', 'parameters')

        assert 'actor_field' in resource.__dataclass_fields__

        view = ResourceCreateView()
        view.request = type('Request', (), {'user': self.user})()
        view.get_resource = lambda: replace(resource, actor_field='updated_by')
        parameter = GovernanceParameter(
            scope=GovernanceParameter.Scope.GLOBAL,
            module='governance',
            key='ui_actor_probe',
            value_type=GovernanceParameter.ValueType.STRING,
            value='ativo',
        )

        prepared = view.prepare_object_for_save(parameter, action='create')

        assert prepared.updated_by == self.user

    def test_login_template_uses_design_system_auth_shell(self):
        response = self.client.get(reverse('accounts:login'))

        assert response.status_code == 200
        content = response.content.decode()
        assert 'vendor/duralux/css/bootstrap.min.css' in content
        assert 'vendor/duralux/images/favicon.svg' in content
        assert 'data-ui="auth-login"' in content
        assert 'class="form-control"' in content
        assert 'resource-input-group' not in content
        assert 'data-field-icon=' not in content

    def test_login_presents_cosmetics_traceability_story_without_legacy_copy(self):
        response = self.client.get(reverse('accounts:login'))

        assert response.status_code == 200
        content = response.content.decode()
        assert 'data-ui="auth-login"' in content
        assert 'data-auth-story' in content
        assert 'data-auth-trace' in content
        for label in ('Formulação', 'Produção', 'Qualidade', 'NF-e'):
            assert label in content
        assert 'vendor/duralux/images/logo_login.webp' in content
        assert content.count('name="username"') == 1
        assert content.count('name="password"') == 1
        assert content.count('<button type="submit"') == 1
        assert 'data-ui="global-footer"' in content
        for forbidden_copy in ('Farmacovigilância', 'ERP farmacêutico', '92 Relatórios'):
            assert forbidden_copy not in content

    def test_login_field_errors_use_project_validation_markup(self):
        response = self.client.post(reverse('accounts:login'), {'username': '', 'password': ''})

        assert response.status_code == 200
        content = response.content.decode()
        assert 'id="id_username_errors"' in content
        assert 'id="id_password_errors"' in content
        assert 'role="alert"' in content
        assert 'aria-invalid="true"' in content
        assert 'aria-describedby="id_username_errors"' in content
        assert 'aria-describedby="id_password_errors"' in content

    def test_institution_logo_updates_login_and_base_layout_branding(self):
        state = StateProvince.objects.create(
            name='Pernambuco',
        )
        city = City.objects.create(
            name='Recife',
            state=state,
        )
        InstitutionSettings.objects.create(
            trade_name='Farmácia Utilizadora QA',
            legal_name='Farmácia Utilizadora QA Ltda',
            document='12.345.678/0001-90',
            tax_regime=InstitutionSettings.TaxRegime.LUCRO_REAL,
            state_ref=state,
            city_ref=city,
            logo='institution/logos/farmacia-utilizadora-qa.png',
        )

        login_response = self.client.get(reverse('accounts:login'))
        assert login_response.status_code == 200
        login_content = login_response.content.decode()
        assert 'institution/logos/farmacia-utilizadora-qa.png' in login_content
        assert 'alt="Farmácia Utilizadora QA"' in login_content
        assert 'logo_farm_system.webp' not in login_content

        self.client.force_login(self.user)
        app_response = self.client.get('/app/')
        assert app_response.status_code == 200
        app_content = app_response.content.decode()
        assert 'institution/logos/farmacia-utilizadora-qa.png' in app_content
        assert 'Início Farmácia Utilizadora QA' in app_content
        assert '>Farmácia Utilizadora QA</span>' in app_content
        assert 'Instância única' not in app_content
        assert 'logo_farm_system.webp' not in app_content

    def test_permission_denied_template_uses_design_system_state(self):
        self.client.force_login(self.user)
        session = self.client.session
        session.save()

        response = self.client.get('/app/masters/products/')

        assert response.status_code == 403
        content = response.content.decode()
        assert 'data-ui="permission-denied"' in content
        assert 'class="avatar-text' in content

    def test_operational_menu_hides_legacy_access_resources(self):
        self.client.force_login(self.user)
        session = self.client.session
        session.save()

        response = self.client.get('/app/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Usuários e acessos' not in content
        assert '/app/base/' not in content

    def test_authenticated_layout_hides_global_rag_chat_without_permission(self):
        self.client.force_login(self.user)
        response = self.client.get('/app/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'id="rag-chat-root"' not in content
        assert 'rag-chat.js' not in content

    def test_authenticated_layout_loads_global_rag_chat_with_permission(self):
        self.user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label='knowledge',
                codename='view_ragchatsession',
            )
        )
        self.client.force_login(self.user)

        response = self.client.get('/app/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'id="rag-chat-root"' in content
        assert 'data-rag-chat-endpoint="/api/knowledge/chat/"' in content
        assert 'rag-chat.js' in content
        assert 'somente leitura' in content
        assert 'data-bs-toggle="offcanvas"' in content
        assert 'offcanvas offcanvas-end rag-chat__panel' in content

    def test_header_exposes_unread_workflow_notification_count(self):
        grant_model_perm(self.user, WorkflowNotification, 'view')
        WorkflowNotification.objects.create(
            category=WorkflowNotification.Category.APPROVAL,
            recipient=self.user,
            title='Aprovação pendente',
            message='Revisar registro.',
            source_module=WorkflowNotification.SourceModule.QUALITY,
        )
        self.client.force_login(self.user)
        session = self.client.session
        session.save()

        response = self.client.get('/app/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'data-ui="workflow-notifications"' in content
        assert '>1<' in content
        assert 'Central de workflow' in content

    def test_dashboard_does_not_render_global_rag_chat_widget(self):
        self.client.force_login(self.user)

        response = self.client.get('/', follow=True)

        assert response.status_code == 200
        assert response.redirect_chain == [('/app/', 302)]
        content = response.content.decode()
        assert 'id="rag-chat-root"' not in content
        assert 'rag-chat.js' not in content

    def test_dashboard_hub_does_not_show_local_instance_copy(self):
        template = Path('templates/dashboards/hub.html').read_text()

        assert 'Dados da instância local' not in template

    def test_rag_chat_offcanvas_uses_reference_width_contract(self):
        css = Path('static/css/app.css').read_text()

        panel = re.search(r'\.rag-chat \.rag-chat__panel\s*\{(?P<body>[^}]*)\}', css)

        assert panel is not None
        assert re.search(r'width:\s*min\(560px,\s*96vw\)', panel.group('body'))

    def test_foundation_module_is_not_exposed_to_customer_app(self):
        self.client.force_login(self.user)
        session = self.client.session
        session.save()

        response = self.client.get('/app/base/')

        assert response.status_code == 404

    def test_resource_detail_and_form_expose_design_system_regions(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()
        unit = UnitOfMeasure.objects.first()

        detail = self.client.get(
            reverse(
                'app:resource_detail',
                kwargs={'module_slug': 'masters', 'resource_slug': 'units', 'pk': unit.pk},
            )
        )
        form = self.client.get('/app/masters/units/new/')

        assert detail.status_code == 200
        assert 'data-ui="resource-detail"' in detail.content.decode()
        assert 'class="table table-hover align-middle' in detail.content.decode()
        assert form.status_code == 200
        assert 'data-ui="resource-form"' in form.content.decode()

    def test_detail_layout_places_operational_summary_beside_production_data(self):
        unit, product, _material, formula, _component, route = create_released_manufacturing_set(
            suffix='detail-layout'
        )
        order = ProductionOrder.objects.create(
            order_number='OP-DETAIL-001',
            batch_number='LOTE-DETAIL-001',
            product=product,
            formula=formula,
            route=route,
            planned_quantity=Decimal('100.0000'),
            unit=unit,
            responsible=self.admin,
            scheduled_end=date(2026, 8, 31),
            status=ProductionOrder.Status.IN_PROGRESS,
        )
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse(
                'app:resource_detail',
                kwargs={'module_slug': 'production', 'resource_slug': 'orders', 'pk': order.pk},
            )
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert 'data-ui="detail-layout"' in content
        assert 'col-xl-8' in content
        assert 'col-xl-4' in content
        assert 'Responsável' in content
        assert 'Fim previsto' in content
        assert 'Em execução' in content

    def test_detail_layout_keeps_simple_unit_full_width_without_sidebar(self):
        self.client.force_login(self.admin)
        unit = UnitOfMeasure.objects.first()

        response = self.client.get(
            reverse(
                'app:resource_detail',
                kwargs={'module_slug': 'masters', 'resource_slug': 'units', 'pk': unit.pk},
            )
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert 'data-ui="detail-layout"' in content
        assert 'class="col-12"' in content
        assert 'data-ui="detail-summary"' not in content

    def test_resource_form_uses_neutral_titles_for_plural_resource_labels(self):
        template = Path('templates/app/resource_form.html').read_text()

        assert (
            "{% if form_mode == 'edit' %}Editar registro{% else %}Novo registro{% endif %} "
            '- {{ resource.label }}'
        ) in template

    def test_empty_state_and_pagination_use_design_system_markup(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()

        response = self.client.get('/app/files/protected-files/')

        assert response.status_code == 200
        assert 'data-ui="empty-state"' in response.content.decode()
        assert 'data-ui="pagination"' in Path('templates/app/includes/pagination.html').read_text()

    def test_resource_lists_define_status_badge_contract(self):
        template = Path('templates/app/resource_list.html').read_text()
        component = Path('templates/includes/components/status_badge.html').read_text()

        assert (
            "{% include 'includes/components/status_badge.html' with status=cell.status field_name=cell.field %}"
            in template
        )
        assert 'status.label' in component
        assert 'status.icon' in component
        assert 'aria-hidden="true"' in component
        assert 'data-field-status="{{ field_name }}"' in component
        assert 'rounded-circle' not in component

    def test_status_resources_expose_choice_filter_and_apply_it(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()
        response = self.client.get('/app/quality/analyses/?status=pending')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'name="status"' in content
        assert 'value="pending"' in content
        assert 'selected' in content

    def test_pagination_uses_authorized_query_transform(self):
        template = Path('templates/app/includes/pagination.html').read_text()

        assert '{% load ui_query %}' in template
        assert (
            '{% query_transform page=page_obj.previous_page_number as previous_query %}' in template
        )
        assert '{% query_transform page=i as page_query %}' in template
        assert '{% query_transform page=page_obj.next_page_number as next_query %}' in template
        assert 'status={{ status_filter }}' not in template

    def test_active_resources_expose_boolean_filter_and_apply_it(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()
        response = self.client.get('/app/masters/units/?is_active=1')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'name="is_active"' in content
        assert 'value="1"' in content
        assert 'selected' in content

    def test_resource_list_boolean_values_are_displayed_in_portuguese(self):
        UnitOfMeasure.objects.create(
            code='un-inativa',
            name='Unidade inativa',
            symbol='un',
            is_active=False,
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()

        response = self.client.get('/app/masters/units/')

        assert response.status_code == 200
        content = response.content.decode()
        cells = re.findall(r'<td\b[^>]*>(.*?)</td>', content, re.S)
        values = [re.sub(r'<[^>]+>', '', cell).strip() for cell in cells]
        assert 'Sim' in values
        assert 'Não' in values
        assert 'True' not in values
        assert 'False' not in values

    def test_created_at_resources_expose_date_range_filters(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()
        response = self.client.get(
            '/app/masters/units/?created_from=2026-01-01&created_to=2026-12-31'
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert 'name="created_from"' in content
        assert 'name="created_to"' in content
        assert 'value="2026-01-01"' in content
        assert 'value="2026-12-31"' in content

    def test_resource_lists_expose_safe_column_ordering(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()
        response = self.client.get('/app/masters/units/?ordering=-name')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'name="ordering"' in content
        assert 'value="-name"' in content
        assert 'selected' in content

    def test_resource_filters_expose_clear_filters_action(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()
        response = self.client.get('/app/masters/units/?q=Recife&is_active=1')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Limpar filtros' in content
        assert 'href="/app/masters/units/"' in content

    def test_resource_list_exposes_filtered_csv_export(self):
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()
        response = self.client.get('/app/masters/units/export/?q=Recife&ordering=-name')

        assert response.status_code == 200
        assert response['Content-Type'].startswith('text/csv')
        content = response.content.decode()
        assert 'Nome' in content
        assert 'Quilograma Recife' in content
        assert 'Quilograma Goiania' not in content

    def test_advanced_filter_registry_uses_only_declared_model_fields(self):
        assert get_resource('production', 'orders').advanced_filter_fields == (
            'priority',
            'scheduled_end',
        )
        assert get_resource('deviations', 'events').advanced_filter_fields == (
            'severity',
            'criticality',
        )
        assert get_resource('capa', 'records').advanced_filter_fields == ('due_date',)
        assert get_resource('workflow', 'tasks').advanced_filter_fields == (
            'criticality',
            'due_at',
        )

    def test_advanced_filters_apply_choices_and_dates_but_ignore_undeclared_lookups(self):
        unit, product, _material, formula, _component, route = create_released_manufacturing_set(
            'advanced-filter'
        )
        urgent = ProductionOrder.objects.create(
            order_number='OP-FILTRO-URGENTE',
            product=product,
            formula=formula,
            route=route,
            planned_quantity=Decimal('10.0000'),
            unit=unit,
            priority=ProductionOrder.Priority.URGENT,
            scheduled_end=date(2026, 9, 15),
        )
        normal = ProductionOrder.objects.create(
            order_number='OP-FILTRO-NORMAL',
            product=product,
            formula=formula,
            route=route,
            planned_quantity=Decimal('20.0000'),
            unit=unit,
            priority=ProductionOrder.Priority.NORMAL,
            scheduled_end=date(2026, 8, 10),
        )
        self.client.force_login(self.admin)

        filtered = self.client.get(
            '/app/production/orders/?priority=urgent&scheduled_end_from=2026-09-01'
        )
        undeclared = self.client.get('/app/production/orders/?priority__icontains=urg')

        assert filtered.status_code == 200
        assert [row['object'].pk for row in filtered.context['rows']] == [urgent.pk]
        assert 'resource-advanced-scheduled_end_from-error' not in filtered.content.decode()
        assert {row['object'].pk for row in undeclared.context['rows']} >= {urgent.pk, normal.pk}

    def test_any_submitted_advanced_value_opens_panel_even_when_invalid(self):
        self.client.force_login(self.admin)

        invalid_choice = self.client.get('/app/production/orders/?priority=desconhecida')
        invalid_date = self.client.get('/app/production/orders/?scheduled_end_from=2026-99-99')

        for response in (invalid_choice, invalid_date):
            assert response.status_code == 200
            content = response.content.decode()
            assert 'aria-expanded="true"' in content
            assert 'id="filtros-avancados" class="collapse show"' in content
            assert response.context['active_filter_count'] == 0

    def test_invalid_advanced_date_shows_accessible_feedback_with_raw_value(self):
        self.client.force_login(self.admin)

        response = self.client.get('/app/production/orders/?scheduled_end_from=2026-99-99')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'value="2026-99-99"' in content
        assert 'data-submitted-value="2026-99-99"' in content
        assert 'aria-invalid="true"' in content
        assert 'aria-describedby="resource-advanced-scheduled_end_from-error"' in content
        assert 'id="resource-advanced-scheduled_end_from-error"' in content
        assert 'Valor informado: 2026-99-99.' in content
        assert 'Informe uma data válida.' in content
        assert response.context['active_filter_count'] == 0

    def test_invalid_advanced_filter_values_are_preserved_without_filtering(self):
        unit, product, _material, formula, _component, route = create_released_manufacturing_set(
            'invalid-filter'
        )
        orders = {
            ProductionOrder.objects.create(
                order_number=f'OP-INVALIDO-{number}',
                product=product,
                formula=formula,
                route=route,
                planned_quantity=Decimal('10.0000'),
                unit=unit,
                priority=priority,
                scheduled_end=date(2026, 9, number),
            ).pk
            for number, priority in (
                (1, ProductionOrder.Priority.URGENT),
                (2, ProductionOrder.Priority.NORMAL),
            )
        }
        self.client.force_login(self.admin)

        response = self.client.get(
            '/app/production/orders/?priority=desconhecida&scheduled_end_from=2026-99-99'
        )

        assert response.status_code == 200
        assert {row['object'].pk for row in response.context['rows']} >= orders
        assert response.context['active_filter_count'] == 0
        controls = {item['name']: item for item in response.context['advanced_filters']}
        assert controls['priority']['value'] == 'desconhecida'
        assert controls['scheduled_end']['from_value'] == '2026-99-99'

    def test_active_filter_count_excludes_search_ordering_and_page(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            '/app/production/orders/?q=OP&ordering=order_number&page=1'
            '&status=draft&priority=urgent&scheduled_end_to=2026-12-31'
        )

        assert response.status_code == 200
        assert response.context['active_filter_count'] == 3

    def test_allowed_query_params_and_export_url_are_normalized(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            '/app/production/orders/?priority=urgent&priority=high&page=2'
            '&ordering=-order_number&lookup__icontains=indevido'
        )

        assert response.status_code == 200
        assert response.context['allowed_query_params'] == (
            'q',
            'status',
            'is_active',
            'created_from',
            'created_to',
            'ordering',
            'page',
            'priority',
            'scheduled_end_from',
            'scheduled_end_to',
        )
        assert response.context['export_url'].endswith(
            '?ordering=-order_number&priority=urgent&priority=high'
        )
        assert 'page=' not in response.context['export_url']
        assert 'lookup' not in response.context['export_url']

    def test_advanced_filter_panel_only_appears_for_configured_resources(self):
        self.client.force_login(self.admin)

        configured = self.client.get('/app/production/orders/')
        unconfigured = self.client.get('/app/masters/units/')

        assert configured.status_code == 200
        assert 'Filtros avançados' in configured.content.decode()
        assert unconfigured.status_code == 200
        assert 'Filtros avançados' not in unconfigured.content.decode()

    def test_resource_detail_defines_semantic_status_region(self):
        template = Path('templates/app/resource_detail.html').read_text()
        summary_template = Path('templates/includes/components/detail_summary.html').read_text()

        assert (
            "{% include 'includes/components/status_badge.html' with status=detail_status %}"
            in template
        )
        assert (
            "{% include 'includes/components/status_badge.html' with status=item.status %}"
            in summary_template
        )


class AppUiPermissionTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username='permissoes@example.com',
            email='permissoes@example.com',
            password='S3curePass!123',
        )
        self.client.force_login(self.user)
        session = self.client.session
        session.save()

    def add_model_perm(self, model, action):
        grant_model_perm(self.user, model, action)
        self.user = self.User.objects.get(pk=self.user.pk)

    def test_sidebar_and_module_resources_follow_django_view_permissions(self):
        denied = self.client.get('/app/masters/products/')
        assert denied.status_code == 403

        self.add_model_perm(Product, 'view')

        response = self.client.get('/app/')
        assert response.status_code == 200
        navigation = response.content.decode().split('</nav>', 1)[0]
        assert 'href="/app/masters/"' in navigation
        assert 'href="/app/finance/"' not in navigation

        module_response = self.client.get('/app/masters/')
        assert module_response.status_code == 200
        module_content = module_response.content.decode()
        assert 'Produtos' in module_content
        assert 'Unidades de medida' not in module_content

        allowed = self.client.get('/app/masters/products/')
        assert allowed.status_code == 200

        navigation = allowed.content.decode().split('</nav>', 1)[0]
        assert 'aria-current="page"' in navigation
        assert 'aria-expanded="true"' in navigation

    def test_specialized_workspaces_follow_module_view_permissions(self):
        assert self.client.get('/app/workspaces/quality/').status_code == 403

    def test_sidebar_groups_resources_as_submenus_for_each_module(self):
        self.add_model_perm(Product, 'view')

        response = self.client.get('/app/')

        assert response.status_code == 200
        navigation = response.content.decode().split('</nav>', 1)[0]
        assert 'nxl-menu-group' in navigation
        assert 'class="nxl-submenu"' in navigation
        assert 'href="/app/masters/products/"' in navigation
        assert 'Produtos' in navigation
        assert 'href="/app/masters/units/"' not in navigation

    def test_open_sidebar_group_overrides_duralux_inline_submenu_state(self):
        css = Path('static/css/app.css').read_text()

        assert re.search(
            r'\.nxl-menu-group\[open\]\s*>\s*\.nxl-submenu\s*\{'
            r'[^}]*display:\s*block\s*!important',
            css,
            re.S,
        )

    def test_sidebar_menu_is_scrollable(self):
        css = Path('static/css/app.css').read_text()
        duralux_css = Path('static/vendor/duralux/css/theme.min.css').read_text()

        assert re.search(r'\.nxl-navigation\s*\{[^}]*position:\s*fixed', duralux_css, re.S)
        assert re.search(
            r'\.nxl-navigation\s+\.navbar-content\s*\{[^}]*height:\s*calc\(100vh - 80px\)',
            duralux_css,
            re.S,
        )
        assert re.search(r'\.navbar-content\s*\{[^}]*scrollbar-width:\s*thin', css, re.S)
        assert '.nxl-submenu' in css

    def test_dashboard_menu_is_hidden_when_no_dashboard_is_authorized(self):
        self.add_model_perm(Product, 'view')

        response = self.client.get('/app/')
        navigation = response.content.decode().split('</nav>', 1)[0]

        assert '>Painéis<' not in navigation
        assert '>Administração<' in navigation
        assert 'Cadastros mestres' in navigation

    def test_create_change_and_delete_follow_django_model_permissions(self):
        self.add_model_perm(Product, 'view')

        response = self.client.get('/app/masters/products/new/')
        assert response.status_code == 403

        self.add_model_perm(Product, 'add')
        response = self.client.get('/app/masters/products/new/')
        assert response.status_code == 200

    def test_read_only_audit_trails_cannot_be_created_changed_or_deleted(self):
        admin = self.User.objects.create_superuser(
            username='audit-admin@example.com',
            email='audit-admin@example.com',
            password='S3curePass!123',
        )
        document = ControlledDocument.objects.create(
            code='DOC-1',
            document_type=ControlledDocument.DocumentType.SOP,
            title='Procedimento auditado',
            area='Garantia da qualidade',
            effective_from=timezone.localdate(),
            owner=admin,
            change_summary='Criacao controlada.',
        )
        audit_trail = DocumentAuditTrail.objects.create(
            document=document,
            action=DocumentAuditTrail.Action.CREATED,
            actor=admin,
            snapshot='Registro congelado ALCOA+.',
        )
        self.client.force_login(admin)
        session = self.client.session
        session.save()

        detail = self.client.get(f'/app/documents/audit-trail/{audit_trail.pk}/')
        assert detail.status_code == 200
        detail_content = detail.content.decode()
        assert 'Editar' not in detail_content
        assert 'Excluir' not in detail_content

        assert self.client.get('/app/documents/audit-trail/new/').status_code == 403
        assert (
            self.client.get(f'/app/documents/audit-trail/{audit_trail.pk}/edit/').status_code == 403
        )
        assert (
            self.client.post(f'/app/documents/audit-trail/{audit_trail.pk}/delete/').status_code
            == 403
        )
        assert DocumentAuditTrail.objects.filter(pk=audit_trail.pk).exists()


class WorkflowNotificationResourceScopeTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='notificacao.escopo@example.com',
            email='notificacao.escopo@example.com',
            password='S3curePass!123',
        )
        self.other_user = get_user_model().objects.create_user(
            username='notificacao.terceiro@example.com',
            email='notificacao.terceiro@example.com',
            password='S3curePass!123',
        )
        grant_model_perm(self.user, WorkflowNotification, 'view')
        self.own_notification = self._create_notification(
            self.user,
            'Notificação exclusiva da usuária autenticada',
        )
        self.other_notification = self._create_notification(
            self.other_user,
            'Notificação sigilosa de outra usuária',
        )
        self.client.force_login(self.user)

    @staticmethod
    def _create_notification(recipient, title):
        return WorkflowNotification.objects.create(
            category=WorkflowNotification.Category.ALERT,
            recipient=recipient,
            title=title,
            message='Mensagem operacional com destinatário definido.',
            source_module=WorkflowNotification.SourceModule.QUALITY,
        )

    def test_global_view_permission_still_scopes_list_detail_and_export_to_recipient(self):
        list_response = self.client.get('/app/workflow/notifications/')
        own_detail = self.client.get(f'/app/workflow/notifications/{self.own_notification.pk}/')
        other_detail = self.client.get(f'/app/workflow/notifications/{self.other_notification.pk}/')
        export_response = self.client.get('/app/workflow/notifications/export/')

        assert list_response.status_code == 200
        assert self.own_notification.title in list_response.content.decode()
        assert self.other_notification.title not in list_response.content.decode()
        assert own_detail.status_code == 200
        assert self.own_notification.title in own_detail.content.decode()
        assert other_detail.status_code == 404
        assert export_response.status_code == 200
        exported = export_response.content.decode()
        assert self.own_notification.title in exported
        assert self.other_notification.title not in exported


class AppUiPersistedAuditTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.admin = self.User.objects.create_superuser(
            username='auditoria.real@example.com',
            email='auditoria.real@example.com',
            password='S3curePass!123',
            first_name='Ana',
            last_name='Silva',
        )
        self.client.force_login(self.admin)

    def create_document(self, code='DOC-AUD-001'):
        return ControlledDocument.objects.create(
            code=code,
            document_type=ControlledDocument.DocumentType.SOP,
            title='Procedimento com auditoria persistida',
            area='Garantia da qualidade',
            effective_from=timezone.localdate(),
            owner=self.admin,
            change_summary='Emissão inicial controlada.',
        )

    def create_capa(self, title='CAPA com histórico persistido'):
        return CapaRecord.objects.create(
            source_type=CapaRecord.SourceType.IMPROVEMENT,
            source_reference='MELHORIA-AUD-001',
            title=title,
            root_cause='Causa raiz confirmada.',
            action_plan='Executar e verificar o plano aprovado.',
            owner=self.admin,
            due_date=timezone.localdate() + timedelta(days=30),
            effectiveness_criteria='Ausência de recorrência por três lotes.',
            opened_by=self.admin,
        )

    def test_controlled_document_detail_renders_real_audit_entries_newest_first(self):
        document = self.create_document()
        older = DocumentAuditTrail.objects.create(
            document=document,
            action=DocumentAuditTrail.Action.CREATED,
            actor=self.admin,
            snapshot='{"version": "1.0", "status": "draft"}',
            reason='Emissão inicial.',
        )
        newer = DocumentAuditTrail.objects.create(
            document=document,
            action=DocumentAuditTrail.Action.SUBMITTED,
            actor=self.admin,
            snapshot='{"version": "1.0", "status": "in_review"}',
            reason='Revisão periódica.',
        )
        older_at = timezone.make_aware(datetime(2026, 8, 26, 9, 5))
        newer_at = timezone.make_aware(datetime(2026, 8, 27, 14, 30))
        DocumentAuditTrail.objects.filter(pk=older.pk).update(created_at=older_at)
        DocumentAuditTrail.objects.filter(pk=newer.pk).update(created_at=newer_at)

        response = self.client.get(f'/app/documents/controlled-documents/{document.pk}/')

        assert response.status_code == 200
        content = response.content.decode()
        audit_html = content.split('aria-labelledby="audit-trail-title"', maxsplit=1)[1].split(
            '</section>', maxsplit=1
        )[0]
        assert audit_html.index('Submetido') < audit_html.index('Criado')
        assert 'Ana Silva' in content
        assert 'status' in content
        assert 'in_review' in content
        assert 'Revisão periódica.' in content
        assert '27/08/2026 14:30' in content
        assert '26/08/2026 09:05' in content
        assert 'datetime="2026-08-27T14:30:00' in content

    def test_controlled_document_audit_escapes_all_persisted_xss_payloads(self):
        document = self.create_document()
        actor_payload = '<img src=x onerror=alert("ator")>'
        snapshot_payload = '<script>alert("snapshot")</script>'
        reason_payload = '<svg onload=alert("motivo")>Motivo</svg>'
        self.admin.first_name = actor_payload
        self.admin.last_name = ''
        self.admin.save(update_fields=['first_name', 'last_name'])
        event = DocumentAuditTrail.objects.create(
            document=document,
            # A ação é uma choice controlada; payload livre não pertence a esse campo.
            action=DocumentAuditTrail.Action.REVIEWED,
            actor=self.admin,
            snapshot=snapshot_payload,
            reason=reason_payload,
        )
        assert event.action in DocumentAuditTrail.Action.values

        response = self.client.get(f'/app/documents/controlled-documents/{document.pk}/')

        assert response.status_code == 200
        content = response.content.decode()
        audit_html = content.split('aria-labelledby="audit-trail-title"', maxsplit=1)[1].split(
            '</section>', maxsplit=1
        )[0]
        assert str(escape(actor_payload)) in audit_html
        assert str(escape(snapshot_payload)) in audit_html
        assert str(escape(reason_payload)) in audit_html
        assert actor_payload not in audit_html
        assert snapshot_payload not in audit_html
        assert reason_payload not in audit_html
        assert '<img' not in audit_html
        assert '<script' not in audit_html
        assert '<svg' not in audit_html

    def test_capa_detail_uses_exact_generic_history_identity(self):
        capa = self.create_capa()
        other_capa = self.create_capa('Outra CAPA')
        expected = RecordStatusHistory.record_transition(
            instance=capa,
            previous_status=CapaRecord.Status.DRAFT,
            new_status=CapaRecord.Status.OPEN,
            action='capa.submit',
            actor=self.admin,
            reason='Submissão autorizada pela Garantia da Qualidade.',
        )
        RecordStatusHistory.objects.create(
            source_module='risks',
            target_model='CapaRecord',
            target_record_id=str(capa.pk),
            previous_status='draft',
            new_status='ignored-risk-app',
            action='contaminação.app',
            actor=self.admin,
        )
        RecordStatusHistory.objects.create(
            source_module='capa',
            target_model='RiskRecord',
            target_record_id=str(capa.pk),
            previous_status='draft',
            new_status='ignored-model',
            action='contaminação.modelo',
            actor=self.admin,
        )
        RecordStatusHistory.record_transition(
            instance=other_capa,
            previous_status=CapaRecord.Status.DRAFT,
            new_status=CapaRecord.Status.IN_PROGRESS,
            action='contaminação.pk',
            actor=self.admin,
        )

        response = self.client.get(f'/app/capa/records/{capa.pk}/')

        assert response.status_code == 200
        content = response.content.decode()
        assert expected.action in content
        assert CapaRecord.Status.DRAFT in content
        assert CapaRecord.Status.OPEN in content
        assert 'Submissão autorizada pela Garantia da Qualidade.' in content
        assert 'Ana Silva' in content
        assert 'contaminação.app' not in content
        assert 'contaminação.modelo' not in content
        assert 'contaminação.pk' not in content

    def test_generic_adapter_uses_one_query_custom_limit_and_stable_tie_order(self):
        from base.ui.audit import get_audit_entries

        capa = self.create_capa()
        other_capa = self.create_capa('CAPA com PK diferente')
        second_actor = self.User.objects.create_user(
            username='bruno.auditoria@example.com',
            email='bruno.auditoria@example.com',
            password='S3curePass!123',
            first_name='Bruno',
            last_name='Lima',
        )
        third_actor = self.User.objects.create_user(
            username='carla.auditoria@example.com',
            email='carla.auditoria@example.com',
            password='S3curePass!123',
            first_name='Carla',
            last_name='Souza',
        )
        RecordStatusHistory.record_transition(
            instance=capa,
            previous_status='draft',
            new_status='open',
            action='capa.older',
            actor=self.admin,
        )
        tie_first = RecordStatusHistory.record_transition(
            instance=capa,
            previous_status='open',
            new_status='in_progress',
            action='capa.tie_first',
            actor=second_actor,
        )
        tie_second = RecordStatusHistory.record_transition(
            instance=capa,
            previous_status='in_progress',
            new_status='pending_approval',
            action='capa.tie_second',
            actor=third_actor,
        )
        tied_at = timezone.now() + timedelta(days=1)
        RecordStatusHistory.objects.filter(pk__in=(tie_first.pk, tie_second.pk)).update(
            occurred_at=tied_at
        )
        contaminant_at = tied_at + timedelta(days=1)
        RecordStatusHistory.objects.create(
            source_module='risks',
            target_model='CapaRecord',
            target_record_id=str(capa.pk),
            previous_status='draft',
            new_status='wrong_app',
            action='contaminação.app.futura',
            actor=self.admin,
            occurred_at=contaminant_at,
        )
        RecordStatusHistory.objects.create(
            source_module='capa',
            target_model='RiskRecord',
            target_record_id=str(capa.pk),
            previous_status='draft',
            new_status='wrong_class',
            action='contaminação.classe.futura',
            actor=self.admin,
            occurred_at=contaminant_at,
        )
        RecordStatusHistory.record_transition(
            instance=other_capa,
            previous_status='draft',
            new_status='wrong_pk',
            action='contaminação.pk.futura',
            actor=self.admin,
        )
        RecordStatusHistory.objects.filter(
            source_module='capa',
            target_model='CapaRecord',
            target_record_id=str(other_capa.pk),
        ).update(occurred_at=contaminant_at)

        with self.assertNumQueries(1), CaptureQueriesContext(connection) as queries:
            entries = get_audit_entries(capa, limit=2)

        assert len(entries) == 2
        assert len(queries) == 1
        executed_sql = assert_executed_sql_orders_newest_then_pk(
            queries[0]['sql'], RecordStatusHistory, 'occurred_at'
        )
        assert re.search(r'\blimit\s+2\b', executed_sql), executed_sql
        assert [entry.action_label for entry in entries] == [
            'capa.tie_second',
            'capa.tie_first',
        ]
        assert [entry.actor_label for entry in entries] == [
            'Carla Souza',
            'Bruno Lima',
        ]

    def test_detail_with_no_history_renders_true_empty_state(self):
        capa = self.create_capa()

        response = self.client.get(f'/app/capa/records/{capa.pk}/')

        assert response.status_code == 200
        assert (
            'Nenhum evento de auditoria disponível para este registro.' in response.content.decode()
        )

    def test_unauthorized_detail_does_not_build_audit_entries(self):
        document = self.create_document()
        unauthorized = self.User.objects.create_user(
            username='sem.auditoria@example.com',
            email='sem.auditoria@example.com',
            password='S3curePass!123',
        )
        self.client.force_login(unauthorized)

        with patch('base.ui.views.get_audit_entries') as getter:
            response = self.client.get(f'/app/documents/controlled-documents/{document.pk}/')

        assert response.status_code == 403
        getter.assert_not_called()

    def test_demonstrative_audit_content_is_absent_from_template(self):
        template = Path('templates/app/includes/audit_trail.html').read_text()

        assert 'Operador Sistema' not in template
        assert '2026-07-19 14:30:22' not in template
        assert '{% now' not in template
        assert 'Exportar relatório' not in template


class AppUiSprint38ResourceTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.admin = self.User.objects.create_superuser(
            username='admin@example.com', email='admin@example.com', password='S3curePass!123'
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()

    def test_sprint_38_modules_expose_expected_resources(self):
        expected = {
            'masters': [
                'Unidades de medida',
                'Categorias',
                'Produtos',
                'Parceiros',
                'Sites',
                'Armazens',
                'Locais de estoque',
            ],
            'formulations': ['Formulas mestras', 'Componentes', 'Roteiros', 'Etapas de roteiro'],
            'production': ['Ordens de producao', 'Consumos de material'],
            'planning': [
                'Politicas de planejamento',
                'MPS',
                'Linhas MPS',
                'Posicoes de estoque',
                'Execucoes MRP',
                'Sugestoes MRP',
                'Recursos de capacidade',
                'Cargas de capacidade',
            ],
            'procurement': [
                'Requisicoes',
                'Itens de requisicao',
                'RFQs',
                'Cotacoes de fornecedor',
                'Qualificacao de fornecedor',
                'Pedidos de compra',
                'Itens de pedido',
                'Recebimentos',
                'Itens de recebimento',
            ],
            'inventory': ['Lotes', 'Saldos', 'Movimentos', 'Genealogia de lotes'],
        }

        for module_slug, labels in expected.items():
            response = self.client.get(f'/app/{module_slug}/')

            assert response.status_code == 200
            content = response.content.decode()
            for label in labels:
                assert without_accents(label) in without_accents(content)

    def test_master_resource_list_uses_single_instance_global_scope(self):
        UnitOfMeasure.objects.create(code='g', name='Grama', symbol='g')
        UnitOfMeasure.objects.create(code='mL', name='Mililitro', symbol='mL')

        response = self.client.get('/app/masters/units/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Grama' in content
        assert 'Mililitro' in content

    def test_product_form_uses_single_instance_global_related_choices(self):
        UnitOfMeasure.objects.create(code='g2', name='Grama', symbol='g')
        UnitOfMeasure.objects.create(code='mL2', name='Mililitro', symbol='mL')

        response = self.client.get('/app/masters/products/new/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Grama' in content
        assert 'Mililitro' in content
        assert 'name="created_at"' not in content


class AppUiSprint39ResourceTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.admin = self.User.objects.create_superuser(
            username='admin-sprint39@example.com',
            email='admin-sprint39@example.com',
            password='S3curePass!123',
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()

    def test_sprint_39_modules_expose_expected_resources(self):
        expected = {
            'costing': [
                'Elementos de custo',
                'Custos padrao',
                'Simulacoes de custo',
                'Capturas de custo',
                'Fechamentos mensais',
                'Snapshots de custo',
            ],
            'finance': [
                'Plano de contas',
                'Categorias financeiras',
                'Contas financeiras',
                'Titulos financeiros',
                'Baixas financeiras',
                'Fluxo de caixa',
                'Fechamentos financeiros',
            ],
            'fiscal': [
                'Empresas fiscais',
                'Municipios fiscais',
                'Unidades fiscais',
                'NCMs',
                'CFOPs',
                'Situacoes tributarias',
                'Regras tributarias',
                'Documentos fiscais',
                'Itens de documento fiscal',
                'Impostos fiscais',
                'Apuracoes fiscais',
                'Livros fiscais',
                'Obrigacoes fiscais',
                'Auditoria fiscal',
            ],
            'crm': [
                'Grupos de clientes',
                'Canais de venda',
                'Representantes',
                'Perfis comerciais',
                'Contatos de clientes',
                'Campanhas',
                'Oportunidades',
                'Propostas comerciais',
                'Itens de proposta',
                'Contratos comerciais',
                'Pedidos de venda',
                'Itens de pedido de venda',
                'Interacoes com clientes',
                'Reclamacoes de clientes',
            ],
        }

        for module_slug, labels in expected.items():
            response = self.client.get(f'/app/{module_slug}/')

            assert response.status_code == 200
            content = response.content.decode()
            for label in labels:
                assert without_accents(label) in without_accents(content)

    def test_operational_menu_links_to_sprint_39_html_modules(self):
        response = self.client.get('/app/')

        assert response.status_code == 200
        navigation = response.content.decode().split('</nav>', 1)[0]
        assert 'href="/app/costing/"' in navigation
        assert 'href="/app/finance/"' in navigation
        assert 'href="/app/fiscal/"' in navigation
        assert 'href="/app/crm/"' in navigation

    def test_standard_cost_form_uses_single_instance_global_related_choices(self):
        active_unit = UnitOfMeasure.objects.create(code='kg2', name='Quilograma', symbol='kg')
        other_unit = UnitOfMeasure.objects.create(code='mL3', name='Mililitro', symbol='mL')
        Product.objects.create(
            code='p1',
            description='Produto Recife',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            status=Product.Status.APPROVED,
            unit=active_unit,
        )
        Product.objects.create(
            code='p2',
            description='Produto Goiania',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            status=Product.Status.APPROVED,
            unit=other_unit,
        )

        response = self.client.get('/app/costing/standard-costs/new/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Produto Recife' in content
        assert 'Produto Goiania' in content


class AppUiSprint40ResourceTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.admin = self.User.objects.create_superuser(
            username='admin-sprint40@example.com',
            email='admin-sprint40@example.com',
            password='S3curePass!123',
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()

    def create_controlled_document(self, code, title):
        return ControlledDocument.objects.create(
            document_type=ControlledDocument.DocumentType.SOP,
            code=code,
            title=title,
            area='Garantia da qualidade',
            effective_from=timezone.localdate(),
            owner=self.admin,
            change_summary='Criacao controlada.',
        )

    def test_sprint_40_modules_expose_expected_resources(self):
        expected = {
            'quality': [
                'Especificacoes analiticas',
                'Amostras de qualidade',
                'Analises de qualidade',
                'Resultados analiticos',
                'Investigacoes laboratoriais',
                'Documentos de qualidade',
            ],
            'qa': [
                'Revisoes QA',
                'Checklist de batch record',
                'Liberacoes de lote',
                'Bloqueios QA',
                'Requisitos de treinamento',
                'Registros de treinamento',
                'Regras de atividades criticas',
            ],
            'documents': [
                'Documentos controlados',
                'Anexos documentais',
                'Relacionamentos documentais',
                'Aprovacoes documentais',
                'Distribuicoes documentais',
                'Auditoria documental',
            ],
            'deviations': [
                'Eventos de qualidade',
                'Evidencias de desvio',
                'Investigacoes de desvio',
                'Avaliacoes de impacto',
                'Aprovacoes de desvio',
                'Links de desvio',
            ],
            'capa': [
                'Registros CAPA',
                'Acoes CAPA',
                'Evidencias CAPA',
                'Verificacoes de eficacia',
                'Aprovacoes CAPA',
                'Notificacoes CAPA',
            ],
            'changes': [
                'Controles de mudanca',
                'Itens afetados',
                'Avaliacoes de mudanca',
                'Acoes de mudanca',
                'Aprovacoes de mudanca',
                'Avaliacoes de estoque',
            ],
        }

        for module_slug, labels in expected.items():
            response = self.client.get(f'/app/{module_slug}/')

            assert response.status_code == 200
            content = response.content.decode()
            for label in labels:
                assert without_accents(label) in without_accents(content)

    def test_operational_menu_links_to_sprint_40_html_modules(self):
        response = self.client.get('/app/')

        assert response.status_code == 200
        navigation = response.content.decode().split('</nav>', 1)[0]
        assert 'href="/app/quality/"' in navigation
        assert 'href="/app/qa/"' in navigation
        assert 'href="/app/documents/"' in navigation
        assert 'href="/app/deviations/"' in navigation
        assert 'href="/app/capa/"' in navigation
        assert 'href="/app/changes/"' in navigation

    def test_document_resource_list_uses_single_instance_global_scope(self):
        self.create_controlled_document('POP-REC', 'Procedimento Recife')
        self.create_controlled_document('POP-GYN', 'Procedimento Goiania')

        response = self.client.get('/app/documents/controlled-documents/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Procedimento Recife' in content
        assert 'Procedimento Goiania' in content

    def test_document_relationship_form_uses_single_instance_global_related_choices(self):
        self.create_controlled_document('DOC-REC', 'Documento Recife')
        self.create_controlled_document('DOC-GYN', 'Documento Goiania')

        response = self.client.get('/app/documents/relationships/new/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'DOC-REC v1.0' in content
        assert 'DOC-GYN v1.0' in content

    def test_hash_based_document_attachments_are_read_only_in_html_crud(self):
        response = self.client.get('/app/documents/attachments/new/')

        assert response.status_code == 403

    def test_controlled_document_form_hides_workflow_audit_fields(self):
        response = self.client.get('/app/documents/controlled-documents/new/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'name="owner"' in content
        assert 'name="submitted_by"' not in content
        assert 'name="submitted_at"' not in content
        assert 'name="approved_by"' not in content
        assert 'name="approved_at"' not in content
        assert 'name="published_by"' not in content
        assert 'name="cancelled_at"' not in content

    def test_document_audit_trail_is_read_only_in_html_crud(self):
        response = self.client.get('/app/documents/audit-trail/new/')

        assert response.status_code == 403


class AppUiSprint41ResourceTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.admin = self.User.objects.create_superuser(
            username='admin-sprint41@example.com',
            email='admin-sprint41@example.com',
            password='S3curePass!123',
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()

    def create_audit_program(self, number, title):
        return AuditProgram.objects.create(
            program_number=number,
            audit_type=AuditProgram.AuditType.INTERNAL,
            title=title,
            year=timezone.localdate().year,
            scope='Escopo de auditoria GMP.',
            criteria='BPF, POPs e requisitos internos.',
            owner=self.admin,
            starts_on=timezone.localdate(),
            ends_on=timezone.localdate(),
        )

    def test_sprint_41_modules_expose_expected_resources(self):
        expected = {
            'audits': [
                'Programas de auditoria',
                'Planos de auditoria',
                'Checklist de auditoria',
                'Achados de auditoria',
                'Evidências de auditoria',
                'Ações de auditoria',
                'Links de achados',
                'Relatórios de auditoria',
            ],
            'risks': [
                'Registros de risco',
                'Avaliações de risco',
                'Controles de risco',
                'Ações de mitigação',
                'Links de risco',
                'Revisões de risco',
                'Alertas de risco',
            ],
            'recalls': [
                'Reclamacoes de mercado',
                'Devolucoes de produto',
                'Campanhas de recall',
                'Clientes impactados',
                'Comunicacoes de recall',
                'Relatorios de efetividade',
            ],
        }

        for module_slug, labels in expected.items():
            response = self.client.get(f'/app/{module_slug}/')

            assert response.status_code == 200
            content = response.content.decode()
            for label in labels:
                assert without_accents(label) in without_accents(content)

    def test_operational_menu_links_to_sprint_41_html_modules(self):
        response = self.client.get('/app/')

        assert response.status_code == 200
        navigation = response.content.decode().split('</nav>', 1)[0]
        assert 'href="/app/audits/"' in navigation
        assert 'href="/app/risks/"' in navigation
        assert 'href="/app/recalls/"' in navigation

    def test_risk_record_list_uses_single_instance_global_scope(self):
        RiskRecord.objects.create(
            risk_category=RiskRecord.RiskCategory.QUALITY,
            title='Risco Recife',
            process_area='Garantia da qualidade',
            owner=self.admin,
            due_date=timezone.localdate(),
            next_review_date=timezone.localdate(),
        )
        RiskRecord.objects.create(
            risk_category=RiskRecord.RiskCategory.QUALITY,
            title='Risco Goiania',
            process_area='Garantia da qualidade',
            owner=self.admin,
            due_date=timezone.localdate(),
            next_review_date=timezone.localdate(),
        )

        response = self.client.get('/app/risks/records/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Risco Recife' in content
        assert 'Risco Goiania' in content

    def test_audit_plan_form_uses_single_instance_global_related_choices(self):
        self.create_audit_program('AUD-REC', 'Programa Recife')
        self.create_audit_program('AUD-GYN', 'Programa Goiania')

        response = self.client.get('/app/audits/plans/new/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'AUD-REC' in content
        assert 'AUD-GYN' in content

    def test_hash_based_evidences_alerts_and_reports_are_read_only(self):
        protected_paths = (
            '/app/audits/evidences/new/',
            '/app/risks/alerts/new/',
            '/app/recalls/communications/new/',
        )

        for path in protected_paths:
            response = self.client.get(path)

            assert response.status_code == 403


class AppUiSprint42ResourceTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.admin = self.User.objects.create_superuser(
            username='admin-sprint42@example.com',
            email='admin-sprint42@example.com',
            password='S3curePass!123',
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()

    def create_protected_file(self):
        return ProtectedFile.objects.create(
            file_number='ARQ-REC',
            source_module=ProtectedFile.SourceModule.QUALITY,
            source_model='QualityDocument',
            source_record_id='QD-001',
            file_type=ProtectedFile.FileType.EVIDENCE,
            origin=ProtectedFile.Origin.UPLOAD,
            criticality=ProtectedFile.Criticality.HIGH,
            confidentiality=ProtectedFile.Confidentiality.CONFIDENTIAL,
            title='Evidencia protegida',
            file_name='evidencia.pdf',
            file_reference='/srv/private/evidencia.pdf',
            mime_type='application/pdf',
            file_size=128,
            content_hash='hash-evidencia-recife',
            responsible=self.admin,
            uploaded_by=self.admin,
        )

    def test_sprint_42_modules_expose_expected_resources(self):
        expected = {
            'training': [
                'Cargos',
                'Funcoes',
                'Competencias',
                'Requisitos de treinamento',
                'Matriz de treinamento',
                'Sessoes de treinamento',
                'Inscricoes de treinamento',
                'Regras de atividade critica',
                'Indicadores de treinamento',
            ],
            'files': [
                'Arquivos protegidos',
                'Regras de acesso',
                'Links seguros',
                'Trilha de arquivos',
            ],
            'reports': [
                'Definições de relatório',
                'Painéis',
                'Widgets de painel',
                'Execuções de relatório',
                'Agendamentos de relatório',
                'Notificações de relatório',
            ],
            'workflow': [
                'Notificações de workflow',
                'Filas de aprovação',
                'Tarefas de aprovação',
                'Delegações',
                'Comentários de workflow',
                'Anexos de workflow',
                'Tarefas assíncronas',
                'Histórico de workflow',
            ],
            'integrations': ['Conectores', 'Clientes API', 'Logs de API', 'Eventos de integração'],
            'ai_agents': [
                'Perfis de agente IA',
                'Execucoes de agente IA',
                'Sugestoes de IA',
                'Auditoria de prompts',
            ],
            'governance': [
                'Parametros de governanca',
                'Catalogos de governanca',
                'Logs de governanca',
                'Cargas demo',
            ],
            'compliance': [
                'Politicas transversais',
                'Historico de status',
                'Execucoes criticas',
                'Checklist de compliance',
            ],
        }

        for module_slug, labels in expected.items():
            response = self.client.get(f'/app/{module_slug}/')

            assert response.status_code == 200
            content = response.content.decode()
            for label in labels:
                assert without_accents(label) in without_accents(content)

    def test_operational_menu_links_to_sprint_42_html_modules(self):
        response = self.client.get('/app/')

        assert response.status_code == 200
        navigation = response.content.decode().split('</nav>', 1)[0]
        for module_slug in (
            'training',
            'files',
            'reports',
            'workflow',
            'integrations',
            'ai_agents',
            'governance',
            'compliance',
        ):
            assert f'href="/app/{module_slug}/"' in navigation

    def test_protected_files_do_not_expose_file_references_in_html_detail(self):
        protected_file = self.create_protected_file()

        response = self.client.get(f'/app/files/protected-files/{protected_file.pk}/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Evidencia protegida' in content
        assert '/srv/private/evidencia.pdf' not in content
        assert 'hash-evidencia-recife' not in content

    def test_logs_audit_and_generated_resources_are_read_only(self):
        protected_paths = (
            '/app/files/protected-files/new/',
            '/app/files/audit-trail/new/',
            '/app/reports/executions/new/',
            '/app/workflow/history/new/',
            '/app/integrations/call-logs/new/',
            '/app/ai_agents/prompt-audit/new/',
            '/app/governance/audit-logs/new/',
            '/app/compliance/status-history/new/',
        )

        for path in protected_paths:
            response = self.client.get(path)

            assert response.status_code == 403

    def test_integration_secret_fields_are_not_exposed_in_forms(self):
        connector_response = self.client.get('/app/integrations/connectors/new/')
        api_client_response = self.client.get('/app/integrations/api-clients/new/')

        assert connector_response.status_code == 200
        assert api_client_response.status_code == 200
        assert 'name="secret_reference"' not in connector_response.content.decode()
        assert 'name="secret_hash"' not in api_client_response.content.decode()


class AppUiSprint43ReadinessTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.admin = self.User.objects.create_superuser(
            username='admin-sprint43@example.com',
            email='admin-sprint43@example.com',
            password='S3curePass!123',
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()

    def create_protected_file(self):
        return ProtectedFile.objects.create(
            file_number='ARQ-S43',
            source_module=ProtectedFile.SourceModule.QUALITY,
            source_model='QualityDocument',
            source_record_id='QD-S43',
            file_type=ProtectedFile.FileType.EVIDENCE,
            origin=ProtectedFile.Origin.UPLOAD,
            criticality=ProtectedFile.Criticality.HIGH,
            confidentiality=ProtectedFile.Confidentiality.CONFIDENTIAL,
            title='Evidencia Sprint 43',
            file_name='evidencia-s43.pdf',
            file_reference='/srv/private/evidencia-s43.pdf',
            content_hash='hash-sprint-43',
            responsible=self.admin,
            uploaded_by=self.admin,
        )

    def test_base_layout_exposes_accessibility_landmarks(self):
        response = self.client.get('/app/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'class="skip-link" href="#main-content"' in content
        assert 'class="nxl-navigation" aria-label="Navegação principal"' in content
        assert 'vendor/duralux/images/logo_header.webp' in content
        assert 'vendor/duralux/images/favicon.svg' in content
        assert 'id="main-content" class="nxl-container app-shell" tabindex="-1"' in content
        assert 'role="status" aria-live="polite"' in Path('templates/base.html').read_text()

    def test_collapsed_sidebar_controls_keep_accessible_names(self):
        template = Path('templates/includes/sidebar.html').read_text()

        assert 'aria-label="Aplicativos"' in template
        assert 'title="Aplicativos"' in template
        assert 'aria-label="{{ workspace.navigation_label }}"' in template
        assert 'title="{{ workspace.navigation_label }}"' in template
        assert 'aria-label="{{ module.label }}"' in template
        assert 'title="{{ module.label }}"' in template

    def test_sidebar_groups_use_accessible_toggle_controls(self):
        template = Path('templates/includes/sidebar.html').read_text()
        base_template = Path('templates/base.html').read_text()
        script = Path('static/js/sidebar-accessibility.js').read_text()

        assert '<button type="button" class="nxl-link sidebar-menu-toggle"' in template
        assert 'aria-controls="sidebar-dashboard-submenu"' in template
        assert 'aria-controls="sidebar-module-{{ module.slug }}-submenu"' in template
        assert 'id="sidebar-module-{{ module.slug }}-submenu"' in template
        assert 'aria-expanded="' in template
        assert 'sidebar-accessibility.js' in base_template
        assert 'aria-expanded' in script
        assert 'aria-controls' in script

    def test_sidebar_toggle_stops_click_before_duralux_parent_handler(self):
        script = Path('static/js/sidebar-accessibility.js').read_text()

        assert "button.addEventListener('click', function (event)" in script
        assert 'event.stopPropagation();' in script

    def test_mobile_shell_preserves_duralux_main_content_contract(self):
        css = Path('static/css/app.css').read_text()

        assert '@media (max-width: 960px)' not in css
        assert 'left: 80px !important;' not in css
        assert 'margin-left: 80px;' not in css
        assert 'left: 64px !important;' not in css
        assert 'margin-left: 64px;' not in css
        assert re.search(
            r'@media\s*\(max-width:\s*1024px\).*?'
            r'\.nxl-header\s*\{[^}]*left:\s*0\s*!important',
            css,
            re.S,
        )
        assert re.search(
            r'@media\s*\(max-width:\s*1024px\).*?'
            r'\.nxl-container\s*\{[^}]*margin-left:\s*0',
            css,
            re.S,
        )

    def test_mobile_resource_layout_preserves_duralux_page_header_spacing(self):
        css = Path('static/css/app.css').read_text()

        assert '.nxl-content {\n    padding:' not in css
        assert '.nxl-content {\n        padding:' not in css
        assert re.search(r'(?m)^\.page-header\s*\{[^}]*\}', css) is None
        assert re.search(
            r'@media\s*\(max-width:\s*767\.98px\).*?'
            r'\[data-ui="resource-filters"\]\s*\{[^}]*padding:\s*16px\s*!important',
            css,
            re.S,
        )

    def test_base_layout_loads_local_duralux_design_system_assets(self):
        response = self.client.get('/app/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'static/vendor/duralux/css/bootstrap.min.css' in content
        assert 'static/vendor/duralux/css/theme.min.css' in content
        assert 'static/vendor/duralux/js/vendors.min.js' in content
        assert 'static/vendor/duralux/images/favicon.svg' in content

    def test_app_css_preserves_duralux_feather_icon_mapping(self):
        css = Path('static/css/app.css').read_text()

        assert '[class^="feather-"]::before' not in css
        assert '[class*=" feather-"]::before' not in css

    def test_shell_color_overrides_do_not_replace_duralux_theme_contract(self):
        css = Path('static/css/app.css').read_text()

        nxl_link_block = re.search(
            r'\.nxl-navigation\s+\.navbar-content\s+\.nxl-link\s*\{(?P<body>[^}]*)\}',
            css,
            re.S,
        )
        assert nxl_link_block is not None
        assert 'color:' not in nxl_link_block.group('body')
        assert re.search(
            r'\.nxl-navigation\s+\.navbar-content\s+\.nxl-caption\s*\{[^}]*color:\s*#98a2b3',
            css,
            re.S,
        )

    def test_app_templates_expose_reusable_design_system_components(self):
        response = self.client.get('/app/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'data-ui="module-grid"' in content
        assert 'class="card stretch stretch-full' in content
        assert 'class="avatar-text' in content

    def test_operations_workspace_exposes_single_instance_operational_metrics(self):
        response = self.client.get('/app/workspaces/operations/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Cockpit operacional' in content
        assert 'Ordens em execução' in content
        assert 'Lotes em estoque' in content
        assert 'Amostras pendentes' in content
        assert 'href="/app/production/orders/"' in content

    def test_quality_workspace_exposes_quality_workflow_metrics(self):
        response = self.client.get('/app/workspaces/quality/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Cockpit de qualidade' in content
        assert 'Amostras em análise' in content
        assert 'Análises pendentes' in content
        assert 'Investigações abertas' in content
        assert 'href="/app/quality/samples/"' in content

    def test_workflow_workspace_exposes_approval_and_async_job_metrics(self):
        response = self.client.get('/app/workspaces/workflow/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Central de workflow' in content
        assert 'Aprovações pendentes' in content
        assert 'Notificações não lidas' in content
        assert 'Jobs em execução' in content
        assert 'href="/app/workflow/tasks/"' in content

    def test_resource_list_uses_design_system_table_and_filter_components(self):
        self.create_protected_file()
        response = self.client.get('/app/files/protected-files/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'data-ui="resource-filters"' in content
        assert (
            'class="table table-hover align-middle mb-0"'
            in Path('templates/app/resource_list.html').read_text()
        )
        assert re.search(r'class="card stretch stretch-full(?: [^"]*)?"', content)
        assert 'data-ui="resource-panel"' in content

    def test_all_modules_and_resource_lists_are_smoke_navigable(self):
        for module in get_modules():
            module_response = self.client.get(f'/app/{module.slug}/')

            assert module_response.status_code == 200
            for resource in module.resources:
                list_response = self.client.get(f'/app/{module.slug}/{resource.slug}/')

                assert list_response.status_code == 200
                assert 'data-ui="resource-filters"' in list_response.content.decode()

    def test_read_only_resource_lists_have_clear_state_and_accessible_tables(self):
        self.create_protected_file()

        response = self.client.get('/app/files/protected-files/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Somente leitura' in content
        assert 'Novo registro' not in content
        assert re.search(
            r'<caption\b[^>]*class="visually-hidden"[^>]*>\s*Arquivos protegidos', content
        )
        assert 'scope="col"' in content

    def test_invalid_form_fields_are_announced_to_assistive_technology(self):
        response = self.client.post(
            '/app/fiscal/companies/new/',
            {
                'legal_name': 'Empresa com documento invalido',
                'document': '11.111.111/1111-11',
                'state_registration': '',
                'municipal_registration': '',
                'tax_regime': 'lucro_real',
                'is_active': 'on',
            },
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert 'aria-invalid="true"' in content
        assert 'aria-describedby="id_document_errors"' in content
        assert 'id="id_document_errors"' in content
        assert 'role="alert"' in content

    def test_permission_denied_uses_clear_html_message(self):
        response = self.client.get('/app/files/protected-files/new/')

        assert response.status_code == 403
        content = response.content.decode()
        assert 'Acesso negado' in content
        assert 'Usuario sem permissao para criar este recurso.' in without_accents(content)

    def test_templates_have_no_placeholder_operational_links(self):
        for template_path in Path('templates').rglob('*.html'):
            content = template_path.read_text()

            assert 'href="#"' not in content
            assert "href='#'" not in content

    def test_crud_extension_documentation_exists(self):
        content = Path('TEMPLATES.md').read_text()

        assert 'Como adicionar novos recursos ao CRUD HTML generico' in content
        assert 'ResourceConfig' in content
        assert 'read_only=True' in content
        assert 'form_fields' in content


class AppUiFormEnhancementTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.admin = self.User.objects.create_superuser(
            username='admin-forms@example.com',
            email='admin-forms@example.com',
            password='S3curePass!123',
        )
        self.client.force_login(self.admin)
        session = self.client.session
        session.save()

    def _governance_parameter_form(self, *, value_type, value, default_value, rules=None):
        resource = get_resource('governance', 'parameters')
        form_class = build_resource_form(resource)
        instance = GovernanceParameter(
            scope=GovernanceParameter.Scope.GLOBAL,
            module='governance',
            key=f'typed_{value_type}',
            value_type=value_type,
            value=value,
            default_value=default_value,
            rules=rules or {},
        )
        return form_class(instance=instance)

    def test_governance_parameter_typed_controls_follow_value_type(self):
        resource = get_resource('governance', 'parameters')

        assert resource.form_base.__name__ == 'GovernanceParameterForm'
        assert resource.actor_field == 'updated_by'
        assert resource.list_display == (
            'scope',
            'module',
            'key',
            'value',
            'value_type',
            'is_active',
        )

        cases = (
            (GovernanceParameter.ValueType.BOOLEAN, True, False, {}, forms.BooleanField),
            (GovernanceParameter.ValueType.INTEGER, 5, 2, {}, forms.IntegerField),
            (GovernanceParameter.ValueType.DAYS, 30, 7, {}, forms.IntegerField),
            (GovernanceParameter.ValueType.DECIMAL, '12.50', '5.00', {}, forms.DecimalField),
            (
                GovernanceParameter.ValueType.CHOICE,
                'manual',
                'automatic',
                {'choices': ['manual', 'automatic']},
                forms.ChoiceField,
            ),
            (GovernanceParameter.ValueType.STRING, 'ativo', 'inativo', {}, forms.CharField),
            (GovernanceParameter.ValueType.JSON, {'enabled': True}, {}, {}, forms.JSONField),
        )

        for value_type, value, default_value, rules, field_class in cases:
            form = self._governance_parameter_form(
                value_type=value_type,
                value=value,
                default_value=default_value,
                rules=rules,
            )
            assert isinstance(form.fields['value'], field_class)
            assert form.fields['value'].widget.attrs['data-governance-value'] == 'current'
            assert form.fields['default_value'].widget.attrs['data-governance-value'] == 'default'
            assert form.fields['value_type'].widget.attrs['data-governance-value-type'] == 'true'
            assert form.fields['rules'].widget.attrs['data-governance-rules'] == 'true'

        boolean_form = self._governance_parameter_form(
            value_type=GovernanceParameter.ValueType.BOOLEAN,
            value=True,
            default_value=True,
        )
        assert isinstance(boolean_form.fields['default_value'], forms.TypedChoiceField)
        assert boolean_form['default_value'].value() == 'true'

    def test_governance_parameter_typed_form_coerces_submitted_values(self):
        resource = get_resource('governance', 'parameters')
        form_class = build_resource_form(resource)
        cases = (
            (GovernanceParameter.ValueType.BOOLEAN, None, '', {}, False, {}),
            (GovernanceParameter.ValueType.INTEGER, '7', '3', {}, 7, 3),
            (GovernanceParameter.ValueType.DAYS, '30', '7', {}, 30, 7),
            (GovernanceParameter.ValueType.DECIMAL, '12.50', '5.00', {}, '12.50', '5.00'),
            (
                GovernanceParameter.ValueType.CHOICE,
                'manual',
                'automatic',
                {'choices': ['manual', 'automatic']},
                'manual',
                'automatic',
            ),
            (GovernanceParameter.ValueType.STRING, 'ativo', '', {}, 'ativo', {}),
            (
                GovernanceParameter.ValueType.JSON,
                '{"enabled": true}',
                '["fallback"]',
                {},
                {'enabled': True},
                ['fallback'],
            ),
        )

        for value_type, value, default_value, rules, expected_value, expected_default in cases:
            data = {
                'scope': GovernanceParameter.Scope.GLOBAL,
                'module': 'governance',
                'key': f'coerce_{value_type}',
                'value_type': value_type,
                'default_value': default_value,
                'rules': json.dumps(rules),
                'description': '',
                'is_active': 'on',
            }
            if value is not None:
                data['value'] = value

            form = form_class(data=data)

            assert form.is_valid(), form.errors.as_json()
            assert form.cleaned_data['value'] == expected_value
            assert form.cleaned_data['default_value'] == expected_default

    def test_governance_parameter_typed_choice_rejects_missing_or_unknown_rules(self):
        form_class = build_resource_form(get_resource('governance', 'parameters'))

        for key, rules in (
            ('missing_choices', {}),
            ('unknown_choice', {'choices': ['manual']}),
        ):
            form = form_class(
                data={
                    'scope': GovernanceParameter.Scope.GLOBAL,
                    'module': 'governance',
                    'key': key,
                    'value_type': GovernanceParameter.ValueType.CHOICE,
                    'value': 'automatic',
                    'default_value': '',
                    'rules': json.dumps(rules),
                    'description': '',
                    'is_active': 'on',
                }
            )

            assert not form.is_valid()
            assert 'value' in form.errors

    def test_governance_parameter_typed_html_update_sets_authenticated_actor(self):
        parameter = GovernanceParameter.objects.create(
            scope=GovernanceParameter.Scope.QUALITY,
            module='qa',
            key='typed_html_actor',
            value_type=GovernanceParameter.ValueType.BOOLEAN,
            value=True,
            default_value=True,
        )

        response = self.client.post(
            reverse(
                'app:resource_edit',
                kwargs={
                    'module_slug': 'governance',
                    'resource_slug': 'parameters',
                    'pk': parameter.pk,
                },
            ),
            {
                'scope': GovernanceParameter.Scope.QUALITY,
                'module': 'qa',
                'key': 'typed_html_actor',
                'value_type': GovernanceParameter.ValueType.BOOLEAN,
                'default_value': '',
                'rules': '{}',
                'description': '',
                'is_active': 'on',
            },
        )

        assert response.status_code == 302
        parameter.refresh_from_db()
        assert parameter.value is False
        assert parameter.default_value == {}
        assert parameter.updated_by == self.admin

    def test_governance_parameter_javascript_switches_controls_safely(self):
        script = Path('static/js/app-form-enhancements.js').read_text()

        assert 'function initGovernanceParameterForm' in script
        assert "addEventListener('change'" in script
        assert "addEventListener('input'" in script
        assert 'rules.choices' in script
        assert 'replacement.name = control.name' in script
        assert "replaceControl('current'" in script
        assert "replaceControl('default'" in script
        assert 'innerHTML' not in script

    def test_generic_forms_use_semantic_input_types_and_masks(self):
        response = self.client.get('/app/masters/partners/new/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'name="document"' in content
        assert 'data-mask="cpf-cnpj"' in content
        assert 'name="email"' in content
        assert 'type="email"' in content
        assert 'name="phone"' in content
        assert 'type="tel"' in content
        assert 'data-mask="phone"' in content
        assert 'name="qualification_valid_until"' in content
        assert 'type="date"' in content

    def test_formula_date_inputs_have_a_single_native_date_type(self):
        from decimal import Decimal

        from formulations.models import MasterFormula
        from masters.models import Product, UnitOfMeasure

        # A fórmula nasce do produto: o formulário em branco não existe.
        unit = UnitOfMeasure.objects.create(code='UI-KG', name='Quilograma', symbol='kg')
        product = Product.objects.create(
            code='UI-CREME',
            description='Creme UI',
            unit=unit,
            item_type=Product.ItemType.FINISHED_PRODUCT,
            status=Product.Status.APPROVED,
        )
        formula = MasterFormula.objects.create(
            product=product,
            version=1,
            batch_size=Decimal('100'),
            batch_unit=unit,
        )
        response = self.client.get(f'/app/formulations/formulas/{formula.pk}/edit/')

        assert response.status_code == 200
        content = response.content.decode()
        for field_name in ('effective_from', 'effective_to'):
            date_input = re.search(rf'<input[^>]+name="{field_name}"[^>]*>', content)
            assert date_input is not None
            assert date_input.group(0).count('type="date"') == 1
            assert 'type="text"' not in date_input.group(0)

    def test_cpf_cnpj_fields_have_masks_and_server_validation(self):
        response = self.client.get('/app/fiscal/companies/new/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'name="document"' in content
        assert 'data-mask="cpf-cnpj"' in content
        assert 'data-validate="cpf-cnpj"' in content

        response = self.client.post(
            '/app/fiscal/companies/new/',
            {
                'legal_name': 'Empresa com documento invalido',
                'document': '11.111.111/1111-11',
                'state_registration': '',
                'municipal_registration': '',
                'tax_regime': 'lucro_real',
                'is_active': 'on',
            },
        )

        assert response.status_code == 200
        assert 'CPF/CNPJ invalido.' in without_accents(response.content.decode())

    def test_form_template_loads_masks_validation_and_cep_lookup_script(self):
        response = self.client.get('/app/fiscal/companies/new/')

        assert response.status_code == 200
        assert 'app-form-enhancements.js' in response.content.decode()

        script = Path('static/js/app-form-enhancements.js').read_text()
        assert '/app/cep-lookup/' in script
        assert 'data-address-target' in script
        assert 'validateCpf' in script
        assert 'validateCnpj' in script

    def test_generic_forms_assign_responsive_field_sizes(self):
        response = self.client.get('/app/fiscal/companies/new/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'form-field--lg' in content
        assert 'form-field--sm' in content
        assert 'form-field--xs' in content
        assert 'data-field-size="lg"' in content
        assert 'data-field-size="sm"' in content
        assert 'data-field-size="xs"' in content

        document_field = forms.CharField()
        state_field = forms.CharField()
        notes_field = forms.CharField(widget=forms.Textarea)

        _apply_widget_metadata('document', document_field)
        _apply_widget_metadata('state', state_field)
        _apply_widget_metadata('description', notes_field)

        assert document_field.rgn_layout_class == 'form-field--sm'
        assert state_field.rgn_layout_class == 'form-field--xs'
        assert notes_field.rgn_layout_class == 'form-field--full'
        assert document_field.widget.attrs['data-field-size'] == 'sm'
        assert 'control-size--sm' in document_field.widget.attrs['class']

    def test_future_common_field_names_receive_masks_and_address_targets(self):
        phone_field = forms.CharField()
        cep_field = forms.CharField()
        street_field = forms.CharField()

        _apply_widget_metadata('mobile_phone', phone_field)
        _apply_widget_metadata('billing_cep', cep_field)
        _apply_widget_metadata('billing_street', street_field)

        assert phone_field.widget.attrs['data-mask'] == 'phone'
        assert phone_field.widget.attrs['type'] == 'tel'
        assert phone_field.rgn_layout_class == 'form-field--sm'
        assert cep_field.widget.attrs['data-mask'] == 'cep'
        assert cep_field.widget.attrs['data-cep-source'] == 'true'
        assert cep_field.rgn_layout_class == 'form-field--xs'
        assert street_field.widget.attrs['data-address-target'] == 'street'
        assert street_field.rgn_layout_class == 'form-field--lg'

    def test_widget_metadata_adds_specific_placeholders_without_decorative_icons(self):
        document_field = forms.CharField(label='CPF/CNPJ')
        email_field = forms.EmailField(label='Email')
        date_field = forms.DateField(label='Validade')
        money_field = forms.DecimalField(label='Valor total')
        phone_field = forms.CharField(label='Telefone')
        url_field = forms.URLField(label='Portal', assume_scheme='https')
        quantity_field = forms.DecimalField(label='Quantidade planejada')
        percent_field = forms.DecimalField(label='Percentual aprovado')
        file_field = forms.FileField(label='Evidência')

        _apply_widget_metadata('document', document_field)
        _apply_widget_metadata('email', email_field)
        _apply_widget_metadata('valid_until', date_field)
        _apply_widget_metadata('total_amount', money_field)
        _apply_widget_metadata('phone', phone_field)
        _apply_widget_metadata('portal_url', url_field)
        _apply_widget_metadata('planned_quantity', quantity_field)
        _apply_widget_metadata('approved_percent', percent_field)
        _apply_widget_metadata('evidence_file', file_field)

        assert document_field.widget.attrs['placeholder'] == '000.000.000-00 ou 00.000.000/0000-00'
        assert email_field.widget.attrs['placeholder'] == 'nome@empresa.com'
        assert money_field.widget.attrs['placeholder'] == '0,00'
        assert phone_field.widget.attrs['placeholder'] == '(00) 00000-0000'
        assert url_field.widget.attrs['placeholder'] == 'https://exemplo.com'
        assert quantity_field.widget.attrs['placeholder'] == '0,0000'
        assert percent_field.widget.attrs['placeholder'] == '0,00%'
        fields = (
            document_field,
            email_field,
            date_field,
            money_field,
            phone_field,
            url_field,
            quantity_field,
            percent_field,
            file_field,
        )
        for field in fields:
            assert 'data-icon' not in field.widget.attrs
            assert not hasattr(field, 'rgn_icon')

    def test_resource_form_renders_fields_without_decorative_icons(self):
        response = self.client.get('/app/fiscal/companies/new/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'name="document"' in content
        assert 'resource-input-group' not in content
        assert 'resource-input-icon' not in content
        assert 'data-field-icon=' not in content

    def test_location_forms_render_normalized_labels_only(self):
        self.client.force_login(self.admin)
        expectations = (
            (
                'fiscal',
                'companies',
                {'Cidade', 'UF'},
                {
                    'município',
                    'Município',
                    'município normalizado',
                    'Município normalizado',
                    'Estado',
                    'UF normalizada',
                },
            ),
            (
                'masters',
                'partners',
                {'Cidade', 'UF', 'Número', 'Complemento'},
                {'cidade normalizada', 'Cidade normalizada', 'UF/estado normalizado'},
            ),
            (
                'masters',
                'sites',
                {'Cidade', 'UF', 'Número', 'Complemento'},
                {'cidade normalizada', 'Cidade normalizada', 'UF/estado normalizado'},
            ),
            (
                'procurement',
                'orders',
                {'Cidade', 'UF', 'Número', 'Complemento'},
                {'cidade de entrega', 'Cidade de entrega', 'UF de entrega'},
            ),
            (
                'training',
                'sessions',
                {'Cidade', 'UF', 'Número', 'Complemento'},
                {'cidade do local', 'Cidade do local', 'UF do local'},
            ),
        )

        for module_slug, resource_slug, expected_labels, forbidden_labels in expectations:
            with self.subTest(module=module_slug, resource=resource_slug):
                response = self.client.get(
                    reverse(
                        'app:resource_create',
                        kwargs={
                            'module_slug': module_slug,
                            'resource_slug': resource_slug,
                        },
                    )
                )

                assert response.status_code == 200
                html = response.content.decode()
                field_labels = {
                    re.sub(r'<[^>]+>', '', label).strip()
                    for label in re.findall(r'<label[^>]*>(.*?)</label>', html, flags=re.S)
                }
                for label in expected_labels:
                    assert label in field_labels
                for label in forbidden_labels:
                    assert label not in field_labels


class ReportCatalogTask6UiTests(TestCase):
    def setUp(self):
        from finance.models import FinancialTitle
        from reports.catalog import sync_curated_report_catalog
        from reports.models import ReportDefinition, ReportExecution

        self.ReportDefinition = ReportDefinition
        self.ReportExecution = ReportExecution
        self.user = get_user_model().objects.create_user(
            username='report.catalog@example.com',
            email='report.catalog@example.com',
            password='S3curePass!123',
        )
        for model, action in (
            (ReportDefinition, 'view'),
            (ReportExecution, 'add'),
            (ReportExecution, 'view'),
            (ProtectedFile, 'view'),
            (FinancialTitle, 'view'),
        ):
            grant_model_perm(self.user, model, action)
        sync_curated_report_catalog(ReportDefinition)
        self.client.force_login(self.user)

    def test_catalog_groups_only_active_system_reports_allowed_by_domain_without_technical_json(
        self,
    ):
        self.ReportDefinition.objects.create(
            code='USER-REPORT-TASK6',
            title='Relatório particular oculto',
            module=self.ReportDefinition.Module.FINANCE,
            category=self.ReportDefinition.Category.OPERATIONAL,
            allowed_export_formats=['csv'],
            query_config={'source': 'secret.User'},
            required_filters=[],
            owner=self.user,
        )
        self.ReportDefinition.objects.filter(code='REL-FIN-004').update(is_active=False)

        with CaptureQueriesContext(connection) as queries:
            response = self.client.get('/app/reports/catalog/')

        assert response.status_code == 200
        assert len(queries) <= 8
        content = response.content.decode()
        assert 'Contas a receber em aberto e vencidas' in content
        assert 'Contas a pagar em aberto e vencidas' in content
        for export_format in ('pdf', 'xlsx', 'csv'):
            assert f'data-export-format="{export_format}"' in content
        assert 'Resultado financeiro por período' not in content
        assert 'Posição de estoque' not in content
        assert 'Relatório particular oculto' not in content
        assert 'finance.receivables_open_overdue' not in content
        assert 'secret.User' not in content
        assert [group['module'] for group in response.context['report_groups']] == ['finance']

    def test_catalog_is_consultable_without_add_but_run_get_and_post_fail_closed(self):
        from finance.models import FinancialTitle

        viewer = get_user_model().objects.create_user(
            username='report.viewer@example.com',
            email='report.viewer@example.com',
        )
        grant_model_perm(viewer, self.ReportDefinition, 'view')
        grant_model_perm(viewer, FinancialTitle, 'view')
        self.client.force_login(viewer)
        definition = self.ReportDefinition.objects.get(code='REL-FIN-001')
        count_before = self.ReportExecution.objects.count()

        catalog = self.client.get('/app/reports/catalog/')
        get_response = self.client.get(f'/app/reports/catalog/{definition.pk}/run/')
        post_response = self.client.post(
            f'/app/reports/catalog/{definition.pk}/run/',
            {'export_format': 'csv'},
        )

        assert catalog.status_code == 200
        assert 'Consulta disponível; execução não autorizada' in catalog.content.decode()
        assert f'href="/app/reports/catalog/{definition.pk}/run/"' not in (catalog.content.decode())
        assert get_response.status_code == 403
        assert post_response.status_code == 403
        assert self.ReportExecution.objects.count() == count_before

    def test_run_form_builds_exact_supported_server_schema_and_choice_values(self):
        definition = self.ReportDefinition.objects.get(code='REL-FIN-003')
        self.ReportDefinition.objects.filter(pk=definition.pk).update(
            filter_schema={
                'period_start': {'type': 'date', 'label': 'Data inicial'},
                'status': {
                    'type': 'choice',
                    'label': 'Situação',
                    'choices': [
                        {'value': 'open', 'label': 'Em aberto'},
                        {'value': 'paid', 'label': 'Pago'},
                    ],
                },
                'lot': {'type': 'text', 'label': 'Lote'},
                'customer': {'type': 'integer', 'label': 'Cliente'},
            },
            required_filters=['period_start', 'status'],
        )

        response = self.client.get(f'/app/reports/catalog/{definition.pk}/run/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'name="period_start"' in content
        assert 'type="date"' in content
        assert 'name="status"' in content
        assert '<option value="open">Em aberto</option>' in content
        assert '<option value="paid">Pago</option>' in content
        assert 'name="lot"' in content
        assert 'type="text"' in content
        assert 'name="customer"' in content
        assert 'type="number"' in content
        assert content.count('required') >= 3
        assert 'name="executor_key"' not in content
        assert 'name="query_config"' not in content

        count_before = self.ReportExecution.objects.count()
        forged = self.client.post(
            f'/app/reports/catalog/{definition.pk}/run/',
            {
                'export_format': 'csv',
                'period_start': '2026-07-01',
                'status': 'forged',
                'lot': '',
                'customer': '',
            },
        )
        assert forged.status_code == 200
        assert 'Faça uma escolha válida' in forged.content.decode()
        assert self.ReportExecution.objects.count() == count_before

    def test_run_form_fails_closed_for_unsupported_or_malformed_schema(self):
        definition = self.ReportDefinition.objects.get(code='REL-FIN-003')
        for schema in (
            {'status': {'type': 'hidden', 'label': 'Segredo'}},
            {
                'status': {
                    'type': 'choice',
                    'label': 'Situação',
                    'choices': [{'label': 'Sem valor'}],
                }
            },
        ):
            with self.subTest(schema=schema):
                self.ReportDefinition.objects.filter(pk=definition.pk).update(
                    filter_schema=schema,
                    required_filters=[],
                )
                response = self.client.get(f'/app/reports/catalog/{definition.pk}/run/')
                assert response.status_code == 404

    def test_direct_run_get_and_post_deny_missing_domain_permission_without_execution(self):
        definition = self.ReportDefinition.objects.get(code='REL-EST-001')
        count_before = self.ReportExecution.objects.count()

        get_response = self.client.get(f'/app/reports/catalog/{definition.pk}/run/')
        post_response = self.client.post(
            f'/app/reports/catalog/{definition.pk}/run/',
            {'export_format': 'csv'},
        )

        assert get_response.status_code == 403
        assert post_response.status_code == 403
        assert self.ReportExecution.objects.count() == count_before

    def test_run_form_renders_csrf_accessible_required_errors_and_controls(self):
        definition = self.ReportDefinition.objects.get(code='REL-FIN-003')

        response = self.client.post(
            f'/app/reports/catalog/{definition.pk}/run/',
            {'export_format': 'csv'},
        )

        assert response.status_code == 200
        content = response.content.decode()
        assert 'name="csrfmiddlewaretoken"' in content
        assert 'role="alert"' in content
        assert 'aria-invalid="true"' in content
        assert 'Data inicial' in content
        assert 'Data final' in content
        assert 'Gerar relatório' in content
        assert 'Cancelar' in content

    def test_valid_run_uses_server_definition_and_redirects_to_protected_download(self):
        definition = self.ReportDefinition.objects.get(code='REL-FIN-001')
        key = base64.urlsafe_b64encode(b'6' * 32).decode('ascii')

        with tempfile.TemporaryDirectory() as media_root:
            with self.settings(
                MEDIA_ROOT=media_root,
                DATA_ENCRYPTION_KEYS=f'task6:{key}',
                DATA_ENCRYPTION_KEY_ID='task6',
            ):
                response = self.client.post(
                    f'/app/reports/catalog/{definition.pk}/run/',
                    {
                        'export_format': 'csv',
                        'executor_key': 'attacker.executor',
                        'query_config': '{"source": "auth.User"}',
                        'requested_by': '999999',
                    },
                )

        assert response.status_code == 302
        execution = self.ReportExecution.objects.get()
        assert execution.status == self.ReportExecution.Status.COMPLETED
        assert execution.definition == definition
        assert execution.requested_by == self.user
        assert response['Location'] == (f'/api/reports/executions/{execution.pk}/download/')
        definition.refresh_from_db()
        assert definition.executor_key == 'finance.receivables_open_overdue'

    def test_reports_module_uses_catalog_entry_and_hides_raw_definitions_without_change(self):
        response = self.client.get('/app/reports/')

        assert response.status_code == 200
        content = response.content.decode()
        assert 'Catálogo de relatórios' in content
        assert 'href="/app/reports/catalog/"' in content
        assert 'href="/app/reports/definitions/"' not in content
        assert self.client.get('/app/reports/definitions/').status_code == 403

        grant_model_perm(self.user, self.ReportDefinition, 'change')
        response = self.client.get('/app/reports/')
        assert 'href="/app/reports/definitions/"' in response.content.decode()
