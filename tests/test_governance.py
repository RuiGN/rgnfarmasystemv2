from decimal import Decimal
from io import StringIO
from typing import cast

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from base.modules import OperationalModule


User = get_user_model()


def create_user(email):
    return User.objects.create_user(username=email, email=email, password='S3curePass!123')


def create_recife_location():
    from auxiliary.models import City, StateProvince

    state = StateProvince.objects.create(
        name='Pernambuco',
    )
    city = City.objects.create(
        name='Recife',
        state=state,
    )
    return state, city


class GovernanceModelTests(TestCase):
    def test_institution_settings_is_single_instance(self):
        from governance.models import InstitutionSettings

        pernambuco, recife = create_recife_location()
        InstitutionSettings.objects.create(
            trade_name='RGN Farma',
            legal_name='RGN Farma Sistemas Ltda',
            document='12.345.678/0001-90',
            tax_regime=InstitutionSettings.TaxRegime.LUCRO_REAL,
            state_ref=pernambuco,
            city_ref=recife,
        )

        assert InstitutionSettings.objects.count() == 1
        instance = InstitutionSettings.objects.get()
        assert str(instance) == 'RGN Farma'
        assert instance.is_active is True

    def test_rf30_governance_models_are_global_and_auditable(self):
        from governance.models import (
            DemoScenarioLoad,
            GovernanceAuditLog,
            GovernanceCatalogItem,
            GovernanceParameter,
        )

        owner = create_user('governance.owner@example.com')
        other_user = create_user('governance.other@example.com')

        retention_parameter = GovernanceParameter.objects.create(
            scope=GovernanceParameter.Scope.RETENTION,
            module=OperationalModule.DOCUMENTS,
            key='document_retention_days',
            value_type=GovernanceParameter.ValueType.DAYS,
            value=3650,
            default_value=1825,
            rules={'min': 365},
            updated_by=owner,
        )
        approval_parameter = GovernanceParameter.objects.create(
            scope=GovernanceParameter.Scope.APPROVAL,
            module=OperationalModule.FINANCE,
            key='approval_limit_brl',
            value_type=GovernanceParameter.ValueType.DECIMAL,
            value='15000.50',
            default_value='5000.00',
            rules={'min': 0},
            updated_by=owner,
        )
        invalid_parameter = GovernanceParameter(
            scope=GovernanceParameter.Scope.WORKFLOW,
            module=OperationalModule.CAPA,
            key='capa_priority',
            value_type=GovernanceParameter.ValueType.CHOICE,
            value='urgent',
            rules={'choices': ['low', 'medium', 'high']},
            updated_by=owner,
        )
        alternate_owner_parameter = GovernanceParameter(
            scope=GovernanceParameter.Scope.GLOBAL,
            module=OperationalModule.QUALITY,
            key='alternate_owner',
            value_type=GovernanceParameter.ValueType.STRING,
            value='allowed',
            updated_by=other_user,
        )
        parent_status = GovernanceCatalogItem.objects.create(
            code='OPEN',
            catalog_type=GovernanceCatalogItem.CatalogType.STATUS,
            module=OperationalModule.DEVIATIONS,
            label='Aberto',
            value='open',
            color='warning',
            metadata={'blocks_closure': True},
        )
        child_status = GovernanceCatalogItem.objects.create(
            code='INVESTIGATION',
            catalog_type=GovernanceCatalogItem.CatalogType.STATUS,
            module=OperationalModule.DEVIATIONS,
            label='Em investigacao',
            value='investigation',
            parent=parent_status,
            metadata={'requires_owner': True},
        )
        other_parent = GovernanceCatalogItem.objects.create(
            code='OTHER',
            catalog_type=GovernanceCatalogItem.CatalogType.STATUS,
            module=OperationalModule.DEVIATIONS,
            label='Status alternativo',
            value='other',
        )
        invalid_catalog = GovernanceCatalogItem(
            code='CROSS',
            catalog_type=GovernanceCatalogItem.CatalogType.STATUS,
            module=OperationalModule.DEVIATIONS,
            label='Status invalido',
            value='cross',
            parent=other_parent,
        )
        audit_log = GovernanceAuditLog.record(
            log_type=GovernanceAuditLog.LogType.FUNCTIONAL,
            severity=GovernanceAuditLog.Severity.INFO,
            module=OperationalModule.QUALITY,
            action='governance.test',
            user=owner,
            message='Evento funcional de governanca.',
            safe_context={
                'token': 'hidden',
                'payload': {'visible': 'ok', 'password': 'hidden'},
                'count': 2,
            },
        )
        demo_load = DemoScenarioLoad.objects.create(
            scenario=DemoScenarioLoad.Scenario.QUALITY_DEVIATION,
            requested_by=owner,
        )
        demo_load.run(user=owner)
        demo_load.refresh_from_db()

        with pytest.raises(ValidationError) as invalid_parameter_error:
            invalid_parameter.full_clean()
        alternate_owner_parameter.full_clean()
        invalid_catalog.full_clean()

        assert retention_parameter.typed_value() == 3650
        assert approval_parameter.typed_value() == Decimal('15000.50')
        assert child_status.parent == parent_status
        assert demo_load.status == DemoScenarioLoad.Status.SUCCEEDED
        assert demo_load.records_created['parameters'] >= 1
        assert demo_load.records_created['catalog_items'] >= 1
        assert 'value' in invalid_parameter_error.value.message_dict
        assert 'token' not in str(audit_log.safe_context).lower()
        assert 'password' not in str(audit_log.safe_context).lower()
        assert audit_log.safe_context['payload']['visible'] == 'ok'
        assert GovernanceAuditLog.objects.filter(action='demo.load.succeeded').exists()


@pytest.mark.legacy_api_permissions
class GovernanceApiTests(TestCase):
    def test_rf30_governance_api_uses_global_actions_and_demo_loads(self):
        from governance.models import (
            DemoScenarioLoad,
            GovernanceAuditLog,
            GovernanceCatalogItem,
            GovernanceParameter,
        )

        user = create_user('governance.api@example.com')
        create_user('governance.other.api@example.com')
        other_parent = GovernanceCatalogItem.objects.create(
            code='OTHER2',
            catalog_type=GovernanceCatalogItem.CatalogType.STATUS,
            module=OperationalModule.DEVIATIONS,
            label='Status alternativo',
            value='other',
        )
        client = APIClient()
        client.force_authenticate(user)

        parameter_response = client.post(
            '/api/governance/parameters/',
            {
                'scope': GovernanceParameter.Scope.RETENTION,
                'module': OperationalModule.DOCUMENTS,
                'key': 'document_retention_days',
                'value_type': GovernanceParameter.ValueType.DAYS,
                'value': 3650,
                'default_value': 1825,
                'rules': {'min': 365},
                'description': 'Retencao de documentos controlados.',
            },
            format='json',
        )
        parent_response = client.post(
            '/api/governance/catalog-items/',
            {
                'catalog_type': GovernanceCatalogItem.CatalogType.STATUS,
                'module': OperationalModule.DEVIATIONS,
                'code': 'OPEN',
                'label': 'Aberto',
                'value': 'open',
                'color': 'warning',
                'metadata': {'blocks_closure': True},
            },
            format='json',
        )
        invalid_catalog_response = client.post(
            '/api/governance/catalog-items/',
            {
                'catalog_type': GovernanceCatalogItem.CatalogType.STATUS,
                'module': OperationalModule.DEVIATIONS,
                'code': 'CROSS',
                'label': 'Status invalido',
                'value': 'cross',
                'parent': other_parent.id,
            },
            format='json',
        )
        child_response = client.post(
            '/api/governance/catalog-items/',
            {
                'catalog_type': GovernanceCatalogItem.CatalogType.STATUS,
                'module': OperationalModule.DEVIATIONS,
                'code': 'INVESTIGATION',
                'label': 'Em investigacao',
                'value': 'investigation',
                'parent': parent_response.json()['id'],
            },
            format='json',
        )
        demo_load_response = client.post(
            '/api/governance/demo-loads/',
            {'scenario': DemoScenarioLoad.Scenario.QUALITY_DEVIATION},
            format='json',
        )
        run_response = client.post(
            f'/api/governance/demo-loads/{demo_load_response.json()["id"]}/run/',
        )
        parameter_list = client.get('/api/governance/parameters/')
        catalog_list = client.get('/api/governance/catalog-items/')
        audit_log_list = client.get('/api/governance/audit-logs/')
        audit_log_create = client.post(
            '/api/governance/audit-logs/',
            {'action': 'forbidden'},
            format='json',
        )

        assert parameter_response.status_code == 201
        assert parameter_response.json()['updated_by'] == user.id
        assert parent_response.status_code == 201
        assert invalid_catalog_response.status_code == 201
        assert child_response.status_code == 201
        assert demo_load_response.status_code == 201
        assert demo_load_response.json()['requested_by'] == user.id
        assert run_response.status_code == 200
        assert run_response.json()['status'] == DemoScenarioLoad.Status.SUCCEEDED
        assert parameter_list.status_code == 200
        assert catalog_list.status_code == 200
        assert audit_log_list.status_code == 200
        assert audit_log_create.status_code == 405
        assert GovernanceAuditLog.objects.filter(action='demo.load.succeeded').exists()


class GovernanceCommandTests(TestCase):
    def test_rf30_demo_load_command_creates_multiple_scenarios(self):
        from governance.models import (
            DemoScenarioLoad,
            GovernanceCatalogItem,
            GovernanceParameter,
        )

        stdout = StringIO()

        call_command(
            'load_demo_scenario',
            scenario=[
                DemoScenarioLoad.Scenario.BASE_MASTER_DATA,
                DemoScenarioLoad.Scenario.QUALITY_DEVIATION,
            ],
            stdout=stdout,
        )

        output = stdout.getvalue()
        assert (
            DemoScenarioLoad.objects.filter(status=DemoScenarioLoad.Status.SUCCEEDED).count() == 2
        )
        assert GovernanceParameter.objects.filter(key='document_retention_days').exists()
        assert GovernanceCatalogItem.objects.filter(
            catalog_type=GovernanceCatalogItem.CatalogType.DOCUMENT_TYPE
        ).exists()
        assert cast(str, DemoScenarioLoad.Scenario.BASE_MASTER_DATA) in output
        assert cast(str, DemoScenarioLoad.Scenario.QUALITY_DEVIATION) in output

    def test_full_demo_populates_representative_records_and_is_idempotent(self):
        from ai_agents.models import AIAgentProfile
        from audits.models import AuditProgram
        from capa.models import CapaRecord
        from crm.models import SalesOrder
        from deviations.models import QualityEvent
        from documents.models import ControlledDocument
        from finance.models import FinancialTitle
        from fiscal.models import FiscalDocument, FiscalEmailDelivery
        from formulations.models import MasterFormula
        from governance.models import DemoScenarioLoad
        from inventory.models import StockLot
        from integrations.models import ApiClientApplication, IntegrationConnector
        from masters.models import BusinessPartner, Product
        from planning.models import MRPSuggestion
        from procurement.models import PurchaseOrder
        from production.models import ProductionOrder
        from qa.models import QAReview
        from quality.models import QualitySample
        from recalls.models import RecallCampaign
        from reports.models import ReportDefinition
        from risks.models import RiskRecord
        from training.models import TrainingSession
        from workflow.models import ApprovalTask

        stdout = StringIO()

        call_command(
            'load_demo_scenario',
            scenario=[DemoScenarioLoad.Scenario.FULL_DEMO],
            stdout=stdout,
        )

        expected_models = [
            Product,
            BusinessPartner,
            MasterFormula,
            ProductionOrder,
            MRPSuggestion,
            PurchaseOrder,
            StockLot,
            FinancialTitle,
            FiscalDocument,
            FiscalEmailDelivery,
            SalesOrder,
            QualitySample,
            QAReview,
            ControlledDocument,
            QualityEvent,
            CapaRecord,
            RiskRecord,
            AuditProgram,
            RecallCampaign,
            TrainingSession,
            ApprovalTask,
            ReportDefinition,
            ApiClientApplication,
            IntegrationConnector,
        ]
        # Legacy AI profiles are deliberately no longer created by the demo seeder.
        assert not AIAgentProfile.objects.exists()
        first_counts = {model: model.objects.count() for model in expected_models}

        assert DemoScenarioLoad.objects.filter(
            scenario=DemoScenarioLoad.Scenario.FULL_DEMO,
            status=DemoScenarioLoad.Status.SUCCEEDED,
        ).exists()
        assert Product.objects.filter(code__startswith='DEMO-').count() >= 6
        assert FiscalEmailDelivery.objects.filter(
            recipient_email='cliente.demo@example.com'
        ).exists()
        assert not AIAgentProfile.objects.exists()
        assert all(count > 0 for count in first_counts.values())

        call_command(
            'load_demo_scenario',
            scenario=[DemoScenarioLoad.Scenario.FULL_DEMO],
            stdout=StringIO(),
        )

        second_counts = {model: model.objects.count() for model in expected_models}
        assert second_counts == first_counts
        assert cast(str, DemoScenarioLoad.Scenario.FULL_DEMO) in stdout.getvalue()
