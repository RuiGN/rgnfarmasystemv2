from __future__ import annotations

import hashlib
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone


class DemoSeeder:
    def __init__(self, user=None):
        self.requested_by = user
        self.today = timezone.localdate()
        self.now = timezone.now()
        self.counts = {}
        self.refs = {}

    def run_full_demo(self):
        with transaction.atomic():
            self._seed_users()
            self._seed_auxiliary()
            self._seed_masters()
            self._seed_governance()
            self._seed_formulation_production_planning()
            self._seed_procurement_inventory()
            self._seed_costing_finance_fiscal()
            self._seed_crm()
            self._seed_quality_and_qa()
            self._seed_documents_deviations_capa_risks_audits()
            self._seed_recalls()
            self._seed_support_modules()
            self._seed_ai_agents()
        return self.counts

    def _upsert(self, model, count_key, lookup, defaults=None):
        defaults = defaults or {}
        payload = {**defaults}
        if any(field.name == 'updated_at' for field in model._meta.fields):
            payload.setdefault('updated_at', self.now)
        queryset = model.objects.filter(**lookup)
        existing = queryset.first()
        if existing:
            if payload:
                queryset.update(**payload)
            obj = model.objects.get(pk=existing.pk)
        else:
            create_payload = {**lookup, **payload}
            obj = model(**create_payload)
            obj.save_base(force_insert=True)
        self.counts[count_key] = self.counts.get(count_key, 0) + 1
        return obj

    @transaction.atomic
    def _upsert_finance(self, model, count_key, lookup, defaults):
        from finance.models import FinancialTitle

        obj = model.objects.select_for_update().filter(**lookup).first()
        if obj is None:
            obj = model(**lookup, **defaults)
            obj.save()
            if model is FinancialTitle:
                obj.approve(user=self.refs['finance_user'])
        else:
            # A demo rerun may refresh metadata, never economics or ledger evidence.
            changed = []
            for field, value in defaults.items():
                if field in model.BULK_METADATA_FIELDS and getattr(obj, field) != value:
                    setattr(obj, field, value)
                    changed.append(field)
            if changed:
                obj.save(update_fields=[*changed, 'updated_at'])
        self.counts[count_key] = self.counts.get(count_key, 0) + 1
        return obj

    def _hash(self, value):
        return hashlib.sha256(value.encode('utf-8')).hexdigest()

    def _seed_users(self):
        from django.contrib.auth.models import Group

        from base.roles import OperationalRole

        demo_password = settings.DEMO_USER_PASSWORD
        if not demo_password:
            raise ImproperlyConfigured(
                'DEMO_USER_PASSWORD must be configured before loading the full demo scenario.'
            )

        User = get_user_model()
        users = {}
        for email, role, name in [
            ('demo.admin@example.com', OperationalRole.ADMIN, 'Administrador Demo'),
            ('demo.quality@example.com', OperationalRole.QUALITY, 'Qualidade Demo'),
            ('demo.production@example.com', OperationalRole.PRODUCTION, 'Producao Demo'),
            ('demo.regulatory@example.com', OperationalRole.REGULATORY, 'Regulatorio Demo'),
            ('demo.finance@example.com', OperationalRole.FINANCE, 'Financeiro Demo'),
        ]:
            user = User.objects.filter(email=email).first()
            if user is None:
                user = User.objects.create_user(
                    username=name,
                    email=email,
                    password=demo_password,
                )
            else:
                updates: dict[str, object] = {}
                if user.username != name:
                    updates['username'] = name
                if not user.is_active:
                    updates['is_active'] = True
                if updates:
                    for field, value in updates.items():
                        setattr(user, field, value)
                    user.save(update_fields=[*updates.keys(), 'updated_at'])
            first_name, last_name = name.split(' ', 1)
            if user.first_name != first_name or user.last_name != last_name:
                user.first_name = first_name
                user.last_name = last_name
                user.save(update_fields=['first_name', 'last_name', 'updated_at'])
            users[role] = user
            group, _ = Group.objects.get_or_create(name=role)
            user.groups.add(group)
        self.refs['users'] = users
        self.refs['admin_user'] = users[OperationalRole.ADMIN]
        self.refs['quality_user'] = users[OperationalRole.QUALITY]
        self.refs['production_user'] = users[OperationalRole.PRODUCTION]
        self.refs['regulatory_user'] = users[OperationalRole.REGULATORY]
        self.refs['finance_user'] = users[OperationalRole.FINANCE]

    def _seed_auxiliary(self):
        from auxiliary.models import (
            BusinessArea,
            BusinessProcess,
            CatalogType,
            CatalogValue,
            City,
            CommercialTerm,
            Country,
            Currency,
            Department,
            ImpactLevel,
            OrganizationalRole,
            StateProvince,
            SystemModel,
            SystemModule,
        )

        quality_area = self._upsert(
            BusinessArea,
            'auxiliary.business_areas',
            {'code': 'DEMO-QA'},
            {'name': 'Garantia da Qualidade'},
        )
        production_area = self._upsert(
            BusinessArea,
            'auxiliary.business_areas',
            {'code': 'DEMO-PROD'},
            {'name': 'Producao'},
        )
        regulatory_area = self._upsert(
            BusinessArea,
            'auxiliary.business_areas',
            {'code': 'DEMO-REG'},
            {'name': 'Assuntos Regulatorios'},
        )
        quality_process = self._upsert(
            BusinessProcess,
            'auxiliary.business_processes',
            {'code': 'DEMO-QA-RELEASE'},
            {'name': 'Liberacao de lote', 'area': quality_area},
        )
        self._upsert(
            Department,
            'auxiliary.departments',
            {'code': 'DEMO-QC'},
            {'name': 'Controle de Qualidade', 'area': quality_area},
        )
        qa_role = self._upsert(
            OrganizationalRole,
            'auxiliary.roles',
            {'code': 'DEMO-QA-ANALYST'},
            {'name': 'Analista QA'},
        )
        country = self._upsert(
            Country,
            'auxiliary.countries',
            {'name': 'Brasil'},
            {},
        )
        state = self._upsert(
            StateProvince,
            'auxiliary.states',
            {'name': 'Pernambuco'},
            {},
        )
        city = self._upsert(
            City,
            'auxiliary.cities',
            {'name': 'Recife', 'state': state},
            {},
        )
        currency = self._upsert(
            Currency,
            'auxiliary.currencies',
            {'code': 'BRL'},
            {'name': 'Real brasileiro', 'numeric_code': '986', 'symbol': 'R$'},
        )
        payment_term = self._upsert(
            CommercialTerm,
            'auxiliary.commercial_terms',
            {'code': 'DEMO-PAY-30'},
            {'name': '30 dias', 'term_type': CommercialTerm.TermType.PAYMENT, 'days': 30},
        )
        delivery_term = self._upsert(
            CommercialTerm,
            'auxiliary.commercial_terms',
            {'code': 'DEMO-CIF'},
            {'name': 'CIF Recife', 'term_type': CommercialTerm.TermType.DELIVERY, 'days': 7},
        )
        severity_high = self._upsert(
            ImpactLevel,
            'auxiliary.impact_levels',
            {'code': 'DEMO-HIGH'},
            {
                'name': 'Alto',
                'level_type': ImpactLevel.LevelType.CRITICALITY,
                'weight': 3,
                'color': 'danger',
            },
        )
        module_refs = {}
        model_refs = {}
        for code, label in [
            ('quality', 'Qualidade'),
            ('qa', 'Garantia da Qualidade'),
            ('fiscal', 'Fiscal'),
            ('finance', 'Financeiro'),
            ('documents', 'Documentos'),
            ('workflow', 'Workflow'),
        ]:
            module_refs[code] = self._upsert(
                SystemModule,
                'auxiliary.system_modules',
                {'code': code},
                {'name': label, 'app_label': code, 'menu_label': label},
            )
        for app_label, model_name in [
            ('quality', 'QualitySample'),
            ('fiscal', 'FiscalDocument'),
            ('documents', 'ControlledDocument'),
            ('workflow', 'ApprovalTask'),
        ]:
            model_refs[f'{app_label}.{model_name}'] = self._upsert(
                SystemModel,
                'auxiliary.system_models',
                {'code': f'{app_label}.{model_name}'},
                {
                    'name': model_name,
                    'module': module_refs.get(app_label),
                    'app_label': app_label,
                    'model_name': model_name,
                },
            )
        catalog_type = self._upsert(
            CatalogType,
            'auxiliary.catalog_types',
            {'code': 'DEMO-STATUS'},
            {'name': 'Status demo', 'target_field': 'status'},
        )
        self._upsert(
            CatalogValue,
            'auxiliary.catalog_values',
            {'code': 'DEMO-OPEN'},
            {'name': 'Aberto', 'catalog_type': catalog_type, 'value': 'open', 'order': 10},
        )
        self.refs.update(
            {
                'quality_area': quality_area,
                'production_area': production_area,
                'regulatory_area': regulatory_area,
                'quality_process': quality_process,
                'qa_role': qa_role,
                'country': country,
                'state': state,
                'city': city,
                'currency': currency,
                'payment_term': payment_term,
                'delivery_term': delivery_term,
                'severity_high': severity_high,
                'module_refs': module_refs,
                'model_refs': model_refs,
            }
        )

    def _seed_masters(self):
        from masters.models import (
            BusinessPartner,
            MasterCategory,
            Product,
            Site,
            StorageLocation,
            UnitOfMeasure,
            Warehouse,
        )

        kg = self._upsert(
            UnitOfMeasure,
            'masters.units',
            {'code': 'KG'},
            {'name': 'Quilograma', 'symbol': 'kg'},
        )
        un = self._upsert(
            UnitOfMeasure,
            'masters.units',
            {'code': 'UN'},
            {'name': 'Unidade', 'symbol': 'un'},
        )
        cx = self._upsert(
            UnitOfMeasure,
            'masters.units',
            {'code': 'CX'},
            {'name': 'Caixa', 'symbol': 'cx'},
        )
        category = self._upsert(
            MasterCategory,
            'masters.categories',
            {'kind': MasterCategory.Kind.CATEGORY, 'code': 'DEMO-COS'},
            {'name': 'Cosméticos demo'},
        )
        product_line = self._upsert(
            MasterCategory,
            'masters.categories',
            {
                'kind': MasterCategory.Kind.PRODUCT_LINE,
                'code': 'DEMO-SKIN',
            },
            {'name': 'Cuidados com a pele'},
        )
        form = self._upsert(
            MasterCategory,
            'masters.categories',
            {
                'kind': MasterCategory.Kind.COSMETIC_FORM,
                'code': 'DEMO-EMUL',
            },
            {'name': 'Emulsão'},
        )
        application_area = self._upsert(
            MasterCategory,
            'masters.categories',
            {
                'kind': MasterCategory.Kind.APPLICATION_AREA,
                'code': 'DEMO-CORPO',
            },
            {'name': 'Corpo'},
        )
        products = {}
        product_specs = [
            (
                'DEMO-PROD-HIDRATANTE',
                'Loção hidratante corporal',
                Product.ItemType.FINISHED_PRODUCT,
                un,
                '33049990',
            ),
            (
                'DEMO-PROD-SABONETE',
                'Sabonete líquido facial',
                Product.ItemType.FINISHED_PRODUCT,
                un,
                '34013000',
            ),
            (
                'DEMO-MAT-ATIVO-GLIC',
                'Glicerina vegetal',
                Product.ItemType.RAW_MATERIAL,
                kg,
                '29054500',
            ),
            (
                'DEMO-MAT-ESPESSANTE',
                'Espessante cosmético',
                Product.ItemType.EXCIPIENT,
                kg,
                '39123930',
            ),
            (
                'DEMO-MAT-EMB-FRASCO',
                'Frasco plástico com válvula',
                Product.ItemType.PACKAGING,
                un,
                '39204900',
            ),
            (
                'DEMO-MAT-CARTUCHO',
                'Cartucho secundario',
                Product.ItemType.PACKAGING,
                un,
                '48192000',
            ),
        ]
        for code, description, item_type, unit, ncm in product_specs:
            products[code] = self._upsert(
                Product,
                'masters.products',
                {'code': code},
                {
                    'description': description,
                    'item_type': item_type,
                    'unit': unit,
                    'category': category,
                    'product_line': product_line
                    if item_type == Product.ItemType.FINISHED_PRODUCT
                    else None,
                    'cosmetic_form': form
                    if item_type == Product.ItemType.FINISHED_PRODUCT
                    else None,
                    'application_area': application_area
                    if item_type == Product.ItemType.FINISHED_PRODUCT
                    else None,
                    'status': Product.Status.APPROVED,
                    'storage_condition': '15 a 30 C, protegido da umidade',
                    'shelf_life_days': 730,
                    'requires_quality_release': True,
                    'requires_approved_supplier': item_type
                    in {
                        Product.ItemType.RAW_MATERIAL,
                        Product.ItemType.EXCIPIENT,
                        Product.ItemType.PACKAGING,
                    },
                    'fiscal_ncm': ncm,
                },
            )
        partners = {}
        partner_specs = [
            (
                'DEMO-FORN-API',
                'Fornecedor API Demo Ltda',
                BusinessPartner.PartnerType.SUPPLIER,
                '11222333000181',
            ),
            (
                'DEMO-FORN-EMB',
                'Embalagens Demo Ltda',
                BusinessPartner.PartnerType.SUPPLIER,
                '22333444000192',
            ),
            (
                'DEMO-CLIENTE-01',
                'Drogaria Cliente Demo SA',
                BusinessPartner.PartnerType.CUSTOMER,
                '33444555000103',
            ),
            (
                'DEMO-DIST-01',
                'Distribuidora Demo Nordeste',
                BusinessPartner.PartnerType.DISTRIBUTOR,
                '44555666000114',
            ),
            (
                'DEMO-LAB-TERC',
                'Laboratorio Terceirizado Demo',
                BusinessPartner.PartnerType.OUTSOURCED_LAB,
                '55666777000125',
            ),
            ('DEMO-ANVISA', 'ANVISA Demo', BusinessPartner.PartnerType.REGULATORY_AUTHORITY, ''),
        ]
        for code, name, partner_type, document in partner_specs:
            partners[code] = self._upsert(
                BusinessPartner,
                'masters.partners',
                {'code': code},
                {
                    'legal_name': name,
                    'trade_name': name,
                    'document': document,
                    'partner_type': partner_type,
                    'qualification_status': BusinessPartner.QualificationStatus.QUALIFIED,
                    'qualification_valid_until': self.today.replace(year=self.today.year + 1),
                    'email': f'{code.lower()}@example.com',
                    'phone': '+55 81 3000-0000',
                    'state_ref': self.refs['state'],
                    'city_ref': self.refs['city'],
                    'is_active': True,
                    'is_blocked': False,
                },
            )
        site = self._upsert(
            Site,
            'masters.sites',
            {'code': 'DEMO-REC'},
            {
                'name': 'Planta Recife Demo',
                'site_type': Site.SiteType.PLANT,
                'state_ref': self.refs['state'],
                'city_ref': self.refs['city'],
            },
        )
        wh_raw = self._upsert(
            Warehouse,
            'masters.warehouses',
            {'site': site, 'code': 'DEMO-ALM-MP'},
            {
                'name': 'Almoxarifado de materias-primas',
                'warehouse_type': Warehouse.WarehouseType.RAW_MATERIAL,
            },
        )
        wh_finished = self._upsert(
            Warehouse,
            'masters.warehouses',
            {'site': site, 'code': 'DEMO-ALM-PA'},
            {
                'name': 'Almoxarifado de produto acabado',
                'warehouse_type': Warehouse.WarehouseType.FINISHED_PRODUCT,
            },
        )
        loc_raw = self._upsert(
            StorageLocation,
            'masters.locations',
            {'warehouse': wh_raw, 'code': 'DEMO-RUA-A'},
            {'name': 'Rua A - Quarentena'},
        )
        loc_finished = self._upsert(
            StorageLocation,
            'masters.locations',
            {'warehouse': wh_finished, 'code': 'DEMO-RUA-B'},
            {'name': 'Rua B - Liberados'},
        )
        self.refs.update(
            {
                'units': {'kg': kg, 'un': un, 'cx': cx},
                'products': products,
                'partners': partners,
                'site': site,
                'wh_raw': wh_raw,
                'wh_finished': wh_finished,
                'loc_raw': loc_raw,
                'loc_finished': loc_finished,
            }
        )

    def _seed_governance(self):
        from governance.models import DemoScenarioLoad, seed_demo_scenario

        counts = seed_demo_scenario(
            DemoScenarioLoad.Scenario.BASE_MASTER_DATA, user=self.requested_by
        )
        for key, value in counts.items():
            self.counts[key] = self.counts.get(key, 0) + value
        counts = seed_demo_scenario(
            DemoScenarioLoad.Scenario.QUALITY_DEVIATION, user=self.requested_by
        )
        for key, value in counts.items():
            self.counts[key] = self.counts.get(key, 0) + value

    def _seed_formulation_production_planning(self):
        from formulations.models import (
            FormulaComponent,
            ManufacturingRoute,
            MasterFormula,
            RouteStep,
        )
        from planning.models import (
            CapacityLoad,
            CapacityResource,
            InventoryPosition,
            MPSLine,
            MRPRun,
            MasterProductionSchedule,
            PlanningPolicy,
        )
        from production.models import MaterialConsumption, ProductionOrder

        product = self.refs['products']['DEMO-PROD-HIDRATANTE']
        api = self.refs['products']['DEMO-MAT-ATIVO-GLIC']
        excipient = self.refs['products']['DEMO-MAT-ESPESSANTE']
        unit = self.refs['units']['un']
        kg = self.refs['units']['kg']
        formula = self._upsert(
            MasterFormula,
            'formulations.formulas',
            {'product': product, 'version': 1},
            {
                'code': 'DEMO-FRM-HIDRATANTE',
                'status': MasterFormula.Status.APPROVED,
                'batch_size': Decimal('10000.0000'),
                'batch_unit': unit,
                'expected_yield_percent': Decimal('98.5000'),
                'effective_from': self.today,
                'approved_by': self.refs['quality_user'],
                'approved_at': self.now,
                'notes': 'Formula demo para testes.',
            },
        )
        component_api = self._upsert(
            FormulaComponent,
            'formulations.components',
            {'formula': formula, 'line_number': 10},
            {
                'material': api,
                'role': FormulaComponent.Role.ACTIVE,
                'quantity': Decimal('5.0000'),
                'unit': kg,
            },
        )
        self._upsert(
            FormulaComponent,
            'formulations.components',
            {'formula': formula, 'line_number': 20},
            {
                'material': excipient,
                'role': FormulaComponent.Role.EXCIPIENT,
                'quantity': Decimal('2.5000'),
                'unit': kg,
            },
        )
        route = self._upsert(
            ManufacturingRoute,
            'formulations.routes',
            {'product': product, 'version': 1},
            {
                'formula': formula,
                'code': 'DEMO-ROT-HIDRATANTE',
                'status': ManufacturingRoute.Status.APPROVED,
                'effective_from': self.today,
                'notes': 'Roteiro demo.',
            },
        )
        self._upsert(
            RouteStep,
            'formulations.route_steps',
            {'route': route, 'sequence': 10},
            {
                'operation': 'Pesagem e conferencia',
                'work_center': 'Sala de pesagem',
                'standard_time_minutes': Decimal('45.00'),
                'instructions': 'Conferir lote e status de qualidade antes da pesagem.',
            },
        )
        self._upsert(
            RouteStep,
            'formulations.route_steps',
            {'route': route, 'sequence': 20},
            {
                'operation': 'Emulsificação',
                'work_center': 'Sala de emulsificação',
                'standard_time_minutes': Decimal('180.00'),
                'instructions': 'Monitorar temperatura, homogeneidade e viscosidade.',
            },
        )
        order = self._upsert(
            ProductionOrder,
            'production.orders',
            {'order_number': 'DEMO-OP-0001'},
            {
                'batch_number': 'DEMO-LOTE-PA-0001',
                'product': product,
                'formula': formula,
                'route': route,
                'planned_quantity': Decimal('10000.0000'),
                'unit': unit,
                'status': ProductionOrder.Status.RELEASED,
                'scheduled_start': self.today,
                'scheduled_end': self.today + timezone.timedelta(days=2),
                'production_line': 'Linha solidos 1',
                'approved_by': self.refs['quality_user'],
                'approved_at': self.now,
                'released_by': self.refs['production_user'],
                'released_at': self.now,
                'notes': 'OP demo liberada.',
            },
        )
        self._upsert(
            MaterialConsumption,
            'production.consumptions',
            {'order': order, 'material': api},
            {
                'component': component_api,
                'planned_quantity': Decimal('5.0000'),
                'actual_quantity': Decimal('0.0000'),
                'unit': kg,
                'lot_number': 'DEMO-LOTE-MP-0001',
                'quality_status': MaterialConsumption.QualityStatus.APPROVED,
                'expiry_date': self.today + timezone.timedelta(days=365),
            },
        )
        for product_ref, source in [
            (product, PlanningPolicy.Source.PRODUCE),
            (api, PlanningPolicy.Source.BUY),
            (excipient, PlanningPolicy.Source.BUY),
        ]:
            self._upsert(
                PlanningPolicy,
                'planning.policies',
                {'product': product_ref},
                {
                    'preferred_source': source,
                    'safety_stock_quantity': Decimal('100.0000'),
                    'minimum_order_quantity': Decimal('100.0000'),
                    'order_multiple': Decimal('50.0000'),
                    'lead_time_days': 15,
                    'is_active': True,
                },
            )
            self._upsert(
                InventoryPosition,
                'planning.inventory_positions',
                {'product': product_ref},
                {
                    'unit': product_ref.unit,
                    'on_hand_quantity': Decimal('50.0000'),
                    'quarantine_quantity': Decimal('10.0000'),
                    'reserved_quantity': Decimal('0.0000'),
                    'incoming_purchase_quantity': Decimal('0.0000'),
                    'incoming_production_quantity': Decimal('0.0000'),
                    'expiry_date': self.today + timezone.timedelta(days=180),
                },
            )
        schedule = self._upsert(
            MasterProductionSchedule,
            'planning.mps',
            {'code': 'DEMO-MPS-01'},
            {
                'name': 'MPS demo trimestre',
                'period_start': self.today,
                'period_end': self.today + timezone.timedelta(days=90),
                'status': MasterProductionSchedule.Status.APPROVED,
            },
        )
        self._upsert(
            MPSLine,
            'planning.mps_lines',
            {
                'schedule': schedule,
                'product': product,
                'due_date': self.today + timezone.timedelta(days=30),
            },
            {
                'demand_quantity': Decimal('12000.0000'),
                'unit': unit,
                'source': MPSLine.Source.FORECAST,
                'customer_reference': 'Forecast demo',
            },
        )
        mrp_run = self._upsert(
            MRPRun,
            'planning.mrp_runs',
            {'schedule': schedule, 'scenario_name': 'DEMO-MRP-BASE'},
            {'status': MRPRun.Status.DRAFT, 'notes': 'Rodada MRP demo.'},
        )
        mrp_run.calculate()
        self.counts['planning.mrp_suggestions'] = (
            self.counts.get('planning.mrp_suggestions', 0) + mrp_run.suggestions.count()
        )
        resource = self._upsert(
            CapacityResource,
            'planning.capacity_resources',
            {'code': 'DEMO-LIN-SOL-01'},
            {
                'name': 'Linha de solidos 1',
                'resource_type': CapacityResource.ResourceType.LINE,
                'work_center': 'Compressao',
                'daily_capacity_minutes': Decimal('420.00'),
            },
        )
        self._upsert(
            CapacityLoad,
            'planning.capacity_loads',
            {
                'resource': resource,
                'period_date': self.today + timezone.timedelta(days=1),
            },
            {
                'run': mrp_run,
                'shift': '1o turno',
                'required_minutes': Decimal('360.00'),
                'available_minutes': Decimal('420.00'),
            },
        )
        self.refs.update(
            {'formula': formula, 'route': route, 'production_order': order, 'mrp_run': mrp_run}
        )

    def _seed_procurement_inventory(self):
        from inventory.models import (
            StockBalance,
            StockLot,
            StockLotGenealogy,
            StockMovement,
            StockQualityStatus,
        )
        from procurement.models import (
            PurchaseOrder,
            PurchaseOrderItem,
            PurchaseReceipt,
            PurchaseReceiptItem,
            PurchaseRequisition,
            PurchaseRequisitionItem,
            QuotationRequest,
            SupplierQualificationEvent,
            SupplierQuotation,
        )

        api = self.refs['products']['DEMO-MAT-ATIVO-GLIC']
        supplier = self.refs['partners']['DEMO-FORN-API']
        kg = self.refs['units']['kg']
        requisition = self._upsert(
            PurchaseRequisition,
            'procurement.requisitions',
            {'requisition_number': 'DEMO-REQ-0001'},
            {
                'source': PurchaseRequisition.Source.MRP,
                'status': PurchaseRequisition.Status.APPROVED,
                'requested_by': self.refs['production_user'],
                'justification': 'Reposicao de materia-prima para MPS demo.',
                'submitted_at': self.now,
                'approved_by': self.refs['finance_user'],
                'approved_at': self.now,
            },
        )
        req_item = self._upsert(
            PurchaseRequisitionItem,
            'procurement.requisition_items',
            {'requisition': requisition, 'product': api},
            {
                'quantity': Decimal('25.0000'),
                'unit': kg,
                'needed_by': self.today + timezone.timedelta(days=20),
            },
        )
        rfq = self._upsert(
            QuotationRequest,
            'procurement.rfqs',
            {'rfq_number': 'DEMO-COT-0001'},
            {
                'requisition': requisition,
                'status': QuotationRequest.Status.APPROVED,
                'due_date': self.today + timezone.timedelta(days=5),
                'terms': 'Cotacao demo',
                'approved_by': self.refs['finance_user'],
                'approved_at': self.now,
            },
        )
        quote = self._upsert(
            SupplierQuotation,
            'procurement.quotations',
            {'rfq': rfq, 'supplier': supplier},
            {
                'status': SupplierQuotation.Status.SELECTED,
                'quoted_quantity': Decimal('25.0000'),
                'unit_price': Decimal('180.0000'),
                'currency': 'BRL',
                'currency_ref': self.refs['currency'],
                'lead_time_days': 15,
                'payment_term_ref': self.refs['payment_term'],
                'delivery_term_ref': self.refs['delivery_term'],
                'supplier_performance_score': Decimal('95.00'),
                'valid_until': self.today + timezone.timedelta(days=30),
            },
        )
        self._upsert(
            SupplierQualificationEvent,
            'procurement.supplier_qualification_events',
            {
                'supplier': supplier,
                'event_type': SupplierQualificationEvent.EventType.DOCUMENT,
                'event_date': self.today,
            },
            {
                'valid_until': self.today + timezone.timedelta(days=365),
                'severity': 'low',
                'severity_ref': self.refs['severity_high'],
                'blocks_purchases': False,
                'description': 'Certificado BPF demo vigente.',
            },
        )
        order = self._upsert(
            PurchaseOrder,
            'procurement.orders',
            {'order_number': 'DEMO-PC-0001'},
            {
                'supplier': supplier,
                'requisition': requisition,
                'source_quotation': quote,
                'status': PurchaseOrder.Status.APPROVED,
                'issue_date': self.today,
                'expected_delivery_date': self.today + timezone.timedelta(days=15),
                'payment_term_ref': self.refs['payment_term'],
                'delivery_term_ref': self.refs['delivery_term'],
                'currency_ref': self.refs['currency'],
                'freight_amount': Decimal('150.0000'),
                'total_amount': Decimal('4650.0000'),
                'approved_by': self.refs['finance_user'],
                'approved_at': self.now,
            },
        )
        order_item = self._upsert(
            PurchaseOrderItem,
            'procurement.order_items',
            {'order': order, 'product': api},
            {
                'requisition_item': req_item,
                'quantity': Decimal('25.0000'),
                'unit': kg,
                'unit_price': Decimal('180.0000'),
                'tax_amount': Decimal('0.0000'),
                'expected_delivery_date': self.today + timezone.timedelta(days=15),
            },
        )
        receipt = self._upsert(
            PurchaseReceipt,
            'procurement.receipts',
            {'receipt_number': 'DEMO-REC-0001'},
            {
                'order': order,
                'status': PurchaseReceipt.Status.STOCK_POSTED,
                'fiscal_document_number': 'DEMO-NFE-ENT-0001',
                'fiscal_received_at': self.now,
                'physical_received_at': self.now,
                'quality_status': PurchaseReceipt.QualityStatus.APPROVED,
                'stock_entry_status': PurchaseReceipt.StockEntryStatus.POSTED,
                'received_by': self.refs['production_user'],
            },
        )
        receipt_item = self._upsert(
            PurchaseReceiptItem,
            'procurement.receipt_items',
            {'receipt': receipt, 'order_item': order_item},
            {
                'product': api,
                'received_quantity': Decimal('25.0000'),
                'accepted_quantity': Decimal('25.0000'),
                'unit': kg,
                'lot_number': 'DEMO-LOTE-MP-0001',
                'expiry_date': self.today + timezone.timedelta(days=365),
            },
        )
        lot_mp = self._upsert(
            StockLot,
            'inventory.lots',
            {
                'product': api,
                'lot_number': 'DEMO-LOTE-MP-0001',
                'sublot_number': '',
            },
            {
                'quality_status': StockQualityStatus.APPROVED,
                'supplier': supplier,
                'source_purchase_receipt_item': receipt_item,
                'manufacturing_date': self.today - timezone.timedelta(days=30),
                'expiry_date': self.today + timezone.timedelta(days=365),
                'notes': 'Lote demo aprovado.',
            },
        )
        lot_pa = self._upsert(
            StockLot,
            'inventory.lots',
            {
                'product': self.refs['products']['DEMO-PROD-HIDRATANTE'],
                'lot_number': 'DEMO-LOTE-PA-0001',
                'sublot_number': '',
            },
            {
                'quality_status': StockQualityStatus.QUARANTINE,
                'source_production_order': self.refs['production_order'],
                'manufacturing_date': self.today,
                'expiry_date': self.today + timezone.timedelta(days=730),
                'notes': 'Lote de produto acabado em quarentena.',
            },
        )
        self._upsert(
            StockBalance,
            'inventory.balances',
            {
                'product': api,
                'lot': lot_mp,
                'warehouse': self.refs['wh_raw'],
                'location': self.refs['loc_raw'],
                'quality_status': StockQualityStatus.APPROVED,
            },
            {'quantity': Decimal('25.0000'), 'reserved_quantity': Decimal('5.0000'), 'unit': kg},
        )
        self._upsert(
            StockBalance,
            'inventory.balances',
            {
                'product': self.refs['products']['DEMO-PROD-HIDRATANTE'],
                'lot': lot_pa,
                'warehouse': self.refs['wh_finished'],
                'location': self.refs['loc_finished'],
                'quality_status': StockQualityStatus.QUARANTINE,
            },
            {
                'quantity': Decimal('10000.0000'),
                'reserved_quantity': Decimal('0.0000'),
                'unit': self.refs['units']['un'],
            },
        )
        self._upsert(
            StockMovement,
            'inventory.movements',
            {'movement_number': 'DEMO-MOV-0001'},
            {
                'movement_type': StockMovement.MovementType.RECEIPT,
                'product': api,
                'lot': lot_mp,
                'quantity': Decimal('25.0000'),
                'unit': kg,
                'quality_status': StockQualityStatus.APPROVED,
                'to_warehouse': self.refs['wh_raw'],
                'to_location': self.refs['loc_raw'],
                'source_purchase_receipt_item': receipt_item,
                'movement_date': self.now,
                'reason': 'Recebimento demo',
            },
        )
        self._upsert(
            StockLotGenealogy,
            'inventory.genealogy',
            {'input_lot': lot_mp, 'output_lot': lot_pa},
            {
                'relation_type': 'consumed',
                'quantity': Decimal('5.0000'),
                'unit': kg,
                'production_order': self.refs['production_order'],
                'notes': 'Genealogia demo MP para PA.',
            },
        )
        self.refs.update(
            {
                'purchase_order': order,
                'purchase_receipt': receipt,
                'stock_lot_mp': lot_mp,
                'stock_lot_pa': lot_pa,
            }
        )

    def _seed_costing_finance_fiscal(self):
        from costing.models import CostElement, StandardCost
        from finance.models import (
            ChartOfAccount,
            FinancialAccount,
            FinancialCategory,
            FinancialTitle,
        )
        from fiscal.models import (
            FiscalCompany,
            FiscalDocument,
            FiscalDocumentItem,
            FiscalEmailDelivery,
            FiscalMunicipality,
            FiscalNCM,
            FiscalOperationCode,
            FiscalUnit,
            TaxRule,
            TaxSituation,
        )

        product = self.refs['products']['DEMO-PROD-HIDRATANTE']
        customer = self.refs['partners']['DEMO-CLIENTE-01']
        account = self._upsert(
            ChartOfAccount,
            'finance.chart_accounts',
            {'code': 'DEMO-1.1.01'},
            {'name': 'Clientes nacionais demo', 'account_type': ChartOfAccount.AccountType.ASSET},
        )
        category = self._upsert(
            FinancialCategory,
            'finance.categories',
            {'code': 'DEMO-REC-COS'},
            {
                'name': 'Receita de cosméticos demo',
                'category_type': FinancialCategory.CategoryType.RECEIVABLE,
                'chart_account': account,
            },
        )
        # These locks live until the outer full-demo transaction commits. Match
        # ledger title -> account order, including reruns of an existing title.
        FinancialTitle.objects.select_for_update().filter(title_number='DEMO-CR-0001').first()
        bank = self._upsert_finance(
            FinancialAccount,
            'finance.accounts',
            {'code': 'DEMO-BANK'},
            {
                'name': 'Conta bancaria demo',
                'account_type': FinancialAccount.AccountType.BANK,
                'bank_name': 'Banco Demo',
                'agency_number': '0001',
                'account_number': '12345-6',
                'opening_balance': Decimal('100000.0000'),
            },
        )
        self._upsert(
            CostElement,
            'costing.cost_elements',
            {'code': 'DEMO-MAT'},
            {'name': 'Materiais diretos', 'category': CostElement.Category.MATERIAL},
        )
        standard_cost = self._upsert(
            StandardCost,
            'costing.standard_costs',
            {
                'product': product,
                'version': 'DEMO-2026',
            },
            {
                'effective_from': self.today,
                'standard_quantity': Decimal('1.0000'),
                'unit': product.unit,
                'material_cost': Decimal('1.2500'),
                'labor_cost': Decimal('0.3500'),
                'overhead_cost': Decimal('0.2200'),
            },
        )
        if standard_cost.status == StandardCost.Status.DRAFT:
            standard_cost.approve(user=self.refs['finance_user'])
        title = self._upsert_finance(
            FinancialTitle,
            'finance.titles',
            {'title_number': 'DEMO-CR-0001'},
            {
                'title_type': FinancialTitle.TitleType.RECEIVABLE,
                'source_type': FinancialTitle.SourceType.SALE,
                'partner': customer,
                'category': category,
                'financial_account': bank,
                'sale_reference': 'DEMO-PV-0001',
                'status': FinancialTitle.Status.PENDING,
                'issue_date': self.today,
                'due_date': self.today + timezone.timedelta(days=30),
                'original_amount': Decimal('25000.0000'),
            },
        )
        company = self._upsert(
            FiscalCompany,
            'fiscal.companies',
            {'document': '12345678000190'},
            {
                'legal_name': 'RGN Farma Demo Ltda',
                'state_registration': '123456789',
                'tax_regime': FiscalCompany.TaxRegime.LUCRO_REAL,
                'state_ref': self.refs['state'],
                'city_ref': self.refs['city'],
            },
        )
        municipality = self._upsert(
            FiscalMunicipality,
            'fiscal.municipalities',
            {'ibge_code': '2611606'},
            {
                'name': 'Recife',
                'state_ref': self.refs['state'],
                'city_ref': self.refs['city'],
            },
        )
        fiscal_unit = self._upsert(
            FiscalUnit,
            'fiscal.units',
            {'code': 'UN'},
            {'description': 'Unidade'},
        )
        ncm = self._upsert(
            FiscalNCM,
            'fiscal.ncms',
            {'code': '30049099'},
            {'description': 'Medicamentos demo'},
        )
        cfop = self._upsert(
            FiscalOperationCode,
            'fiscal.cfops',
            {'code': '5102'},
            {
                'description': 'Venda de mercadoria adquirida ou recebida de terceiros',
                'direction': FiscalOperationCode.Direction.OUTBOUND,
            },
        )
        tax_situation = self._upsert(
            TaxSituation,
            'fiscal.tax_situations',
            {'code': '00', 'tax_kind': 'icms', 'regime_kind': 'normal'},
            {'description': 'Tributada integralmente'},
        )
        self._upsert(
            TaxRule,
            'fiscal.tax_rules',
            {'name': 'DEMO-ICMS-18'},
            {
                'tax_kind': 'icms',
                'company': company,
                'product': product,
                'partner': customer,
                'ncm': ncm,
                'cfop': cfop,
                'tax_situation': tax_situation,
                'effective_from': self.today,
                'rate_percent': Decimal('18.0000'),
                'status': TaxRule.Status.APPROVED,
                'approved_by': self.refs['finance_user'],
                'approved_at': self.now,
            },
        )
        document = self._upsert(
            FiscalDocument,
            'fiscal.documents',
            {
                'company': company,
                'document_type': FiscalDocument.DocumentType.OUTBOUND,
                'number': 'DEMO-000001',
                'series': '1',
            },
            {
                'partner': customer,
                'operation_type': FiscalDocument.OperationType.SALE,
                'issue_date': self.today,
                'operation_date': self.today,
                'status': FiscalDocument.Status.APPROVED,
                'emission_status': FiscalDocument.EmissionStatus.NOT_SENT,
                'environment': FiscalDocument.Environment.HOMOLOGATION,
                'financial_title': title,
                'total_products': Decimal('25000.0000'),
                'total_taxes': Decimal('4500.0000'),
                'total_amount': Decimal('29500.0000'),
                'reviewed_by': self.refs['finance_user'],
                'reviewed_at': self.now,
                'approved_by': self.refs['finance_user'],
                'approved_at': self.now,
                'notes': 'Documento fiscal demo sem transmissao.',
            },
        )
        self._upsert(
            FiscalDocumentItem,
            'fiscal.document_items',
            {'document': document, 'line_number': 1},
            {
                'product': product,
                'fiscal_unit': fiscal_unit,
                'ncm': ncm,
                'cfop': cfop,
                'tax_situation': tax_situation,
                'quantity': Decimal('1000.0000'),
                'unit_price': Decimal('25.0000'),
            },
        )
        self._upsert(
            FiscalEmailDelivery,
            'fiscal.email_deliveries',
            {
                'document': document,
                'recipient_email': 'cliente.demo@example.com',
            },
            {
                'subject': 'NF-e demo RGN Farma',
                'body': 'Envio agendado de NF-e demo para testes locais.',
                'scheduled_at': self.now + timezone.timedelta(hours=1),
                'requested_by': self.refs['finance_user'],
            },
        )
        self.refs.update(
            {
                'financial_title': title,
                'fiscal_document': document,
                'fiscal_company': company,
                'fiscal_municipality': municipality,
            }
        )

    def _seed_crm(self):
        from crm.models import (
            CustomerContact,
            CustomerGroup,
            CustomerProfile,
            SalesChannel,
            SalesOrder,
            SalesOrderItem,
            SalesRepresentative,
        )

        customer = self.refs['partners']['DEMO-CLIENTE-01']
        product = self.refs['products']['DEMO-PROD-HIDRATANTE']
        group = self._upsert(
            CustomerGroup,
            'crm.customer_groups',
            {'code': 'DEMO-GRP-FARMA'},
            {'name': 'Rede farma demo'},
        )
        channel = self._upsert(
            SalesChannel,
            'crm.sales_channels',
            {'code': 'DEMO-DIRETO'},
            {'name': 'Venda direta demo', 'channel_type': SalesChannel.ChannelType.DIRECT},
        )
        representative = self._upsert(
            SalesRepresentative,
            'crm.representatives',
            {'code': 'DEMO-REP-01'},
            {
                'user': self.refs['admin_user'],
                'name': 'Representante Demo',
                'email': 'rep.demo@example.com',
                'territory': 'Nordeste',
                'commission_percent': Decimal('2.5000'),
            },
        )
        self._upsert(
            CustomerProfile,
            'crm.customer_profiles',
            {'customer': customer},
            {
                'group': group,
                'default_channel': channel,
                'representative': representative,
                'credit_limit': Decimal('500000.0000'),
                'payment_terms_days': 30,
                'price_list_code': 'DEMO-TAB-01',
            },
        )
        self._upsert(
            CustomerContact,
            'crm.customer_contacts',
            {'customer': customer, 'name': 'Comprador Demo'},
            {
                'role': 'Compras',
                'email': 'cliente.demo@example.com',
                'phone': '+55 81 3000-1111',
                'is_primary': True,
            },
        )
        order = self._upsert(
            SalesOrder,
            'crm.sales_orders',
            {'order_number': 'DEMO-PV-0001'},
            {
                'customer': customer,
                'channel': channel,
                'representative': representative,
                'requested_delivery_date': self.today + timezone.timedelta(days=10),
                'payment_terms_days': 30,
                'status': SalesOrder.Status.APPROVED,
                'total_amount': Decimal('25000.0000'),
                'approved_by': self.refs['finance_user'],
                'approved_at': self.now,
            },
        )
        self._upsert(
            SalesOrderItem,
            'crm.sales_order_items',
            {'order': order, 'product': product},
            {
                'quantity': Decimal('1000.0000'),
                'unit_price': Decimal('25.0000'),
                'promised_date': self.today + timezone.timedelta(days=10),
            },
        )
        self.refs['sales_order'] = order

    def _seed_quality_and_qa(self):
        from qa.models import BatchRecordChecklistItem, QAReview
        from quality.models import (
            AnalyticalSpecification,
            QualityAnalysis,
            QualityResult,
            QualitySample,
        )

        product = self.refs['products']['DEMO-PROD-HIDRATANTE']
        spec = self._upsert(
            AnalyticalSpecification,
            'quality.specifications',
            {
                'product': product,
                'stock_lot': None,
                'version': 'DEMO-1.0',
                'method_code': 'DEMO-MET-001',
                'parameter_name': 'Teor',
            },
            {
                'method_name': 'HPLC demo',
                'unit': self.refs['units']['un'],
                'lower_limit': Decimal('95.0000'),
                'upper_limit': Decimal('105.0000'),
                'acceptance_criteria': '95,0% a 105,0% do rotulo.',
                'status': AnalyticalSpecification.Status.APPROVED,
                'effective_from': self.today,
                'approved_by': self.refs['quality_user'],
                'approved_at': self.now,
            },
        )
        sample = self._upsert(
            QualitySample,
            'quality.samples',
            {'sample_number': 'DEMO-AMO-0001'},
            {
                'sample_type': QualitySample.SampleType.PRODUCTION,
                'product': product,
                'stock_lot': self.refs['stock_lot_pa'],
                'specification': spec,
                'source_production_order': self.refs['production_order'],
                'quantity': Decimal('30.0000'),
                'unit': self.refs['units']['un'],
                'status': QualitySample.Status.IN_ANALYSIS,
                'collected_by': self.refs['quality_user'],
                'collected_at': self.now,
                'received_by': self.refs['quality_user'],
                'received_at': self.now,
                'started_by': self.refs['quality_user'],
                'started_at': self.now,
            },
        )
        analysis = self._upsert(
            QualityAnalysis,
            'quality.analyses',
            {'analysis_number': 'DEMO-ANA-0001'},
            {
                'sample': sample,
                'specification': spec,
                'status': QualityAnalysis.Status.COMPLETED,
                'method_reference': 'DEMO-MET-001',
                'analyst': self.refs['quality_user'],
                'started_at': self.now,
                'completed_at': self.now,
            },
        )
        result = self._upsert(
            QualityResult,
            'quality.results',
            {'analysis': analysis, 'parameter_name': 'Teor'},
            {
                'specification': spec,
                'result_type': QualityResult.ResultType.QUANTITATIVE,
                'numeric_result': Decimal('99.5000'),
                'unit': self.refs['units']['un'],
                'result_status': QualityResult.ResultStatus.COMPLIANT,
                'recorded_by': self.refs['quality_user'],
                'recorded_at': self.now,
            },
        )
        review = self._upsert(
            QAReview,
            'qa.reviews',
            {'review_number': 'DEMO-RQA-0001'},
            {
                'review_type': QAReview.ReviewType.LOT_RELEASE,
                'title': 'Revisao de lote demo',
                'stock_lot': self.refs['stock_lot_pa'],
                'production_order': self.refs['production_order'],
                'status': QAReview.Status.IN_REVIEW,
                'submitted_by': self.refs['quality_user'],
                'submitted_at': self.now,
                'notes': 'Review demo para batch record.',
            },
        )
        self._upsert(
            BatchRecordChecklistItem,
            'qa.checklist_items',
            {'review': review, 'title': 'Conferir rendimento e desvios'},
            {
                'status': BatchRecordChecklistItem.Status.COMPLETED,
                'responsible': self.refs['quality_user'],
                'due_date': self.today + timezone.timedelta(days=2),
                'evidence_reference': 'DEMO-EVID-QA-001',
                'completed_by': self.refs['quality_user'],
                'completed_at': self.now,
            },
        )
        self.refs.update(
            {
                'quality_spec': spec,
                'quality_sample': sample,
                'quality_result': result,
                'qa_review': review,
            }
        )

    def _seed_documents_deviations_capa_risks_audits(self):
        from audits.models import AuditProgram
        from capa.models import CapaRecord
        from deviations.models import QualityEvent
        from documents.models import ControlledDocument
        from risks.models import RiskAssessment, RiskRecord

        document = self._upsert(
            ControlledDocument,
            'documents.controlled_documents',
            {'code': 'DEMO-POP-QA-001', 'version': '1.0'},
            {
                'document_type': ControlledDocument.DocumentType.SOP,
                'title': 'POP demo de liberacao de lote',
                'area': 'Garantia da Qualidade',
                'area_ref': self.refs['quality_area'],
                'status': ControlledDocument.Status.PUBLISHED,
                'effective_from': self.today,
                'valid_until': self.today + timezone.timedelta(days=730),
                'owner': self.refs['quality_user'],
                'content': 'Procedimento demo para testes de navegacao e RAG.',
                'change_summary': 'Emissao inicial demo.',
                'approved_by': self.refs['quality_user'],
                'approved_at': self.now,
                'published_by': self.refs['quality_user'],
                'published_at': self.now,
            },
        )
        event = self._upsert(
            QualityEvent,
            'deviations.events',
            {'event_number': 'DEMO-DEV-0001'},
            {
                'event_type': QualityEvent.EventType.DEVIATION,
                'origin': QualityEvent.Origin.PRODUCTION,
                'area': 'Producao',
                'area_ref': self.refs['production_area'],
                'product': self.refs['products']['DEMO-PROD-HIDRATANTE'],
                'stock_lot': self.refs['stock_lot_pa'],
                'controlled_document': document,
                'severity': QualityEvent.Severity.HIGH,
                'criticality': QualityEvent.Criticality.MAJOR,
                'severity_ref': self.refs['severity_high'],
                'criticality_ref': self.refs['severity_high'],
                'status': QualityEvent.Status.UNDER_INVESTIGATION,
                'description': 'Variação demo de peso medio durante compressao.',
                'detected_at': self.now,
                'responsible': self.refs['quality_user'],
                'opened_by': self.refs['production_user'],
                'opened_at': self.now,
            },
        )
        capa = self._upsert(
            CapaRecord,
            'capa.records',
            {'capa_number': 'DEMO-CAPA-0001'},
            {
                'source_type': CapaRecord.SourceType.DEVIATION,
                'deviation_event': event,
                'title': 'Ajustar controle em processo demo',
                'root_cause': 'Tendencia de setup fora da faixa operacional.',
                'action_plan': 'Revisar setup, treinar operadores e acompanhar tres lotes.',
                'owner': self.refs['quality_user'],
                'due_date': self.today + timezone.timedelta(days=45),
                'status': CapaRecord.Status.IN_PROGRESS,
                'requires_effectiveness_check': True,
                'effectiveness_criteria': 'Tres lotes consecutivos sem recorrencia.',
                'opened_by': self.refs['quality_user'],
                'opened_at': self.now,
            },
        )
        risk = self._upsert(
            RiskRecord,
            'risks.records',
            {'risk_number': 'DEMO-RSK-0001'},
            {
                'risk_category': RiskRecord.RiskCategory.QUALITY,
                'title': 'Risco demo de variacao de processo',
                'description': 'Possivel variacao de peso medio em compressao.',
                'process_area': 'Compressao',
                'process_ref': self.refs['quality_process'],
                'owner': self.refs['quality_user'],
                'due_date': self.today + timezone.timedelta(days=60),
                'next_review_date': self.today + timezone.timedelta(days=90),
                'status': RiskRecord.Status.IN_TREATMENT,
                'identified_by': self.refs['quality_user'],
                'identified_at': self.now,
                'initial_score': 12,
                'initial_level': RiskRecord.RiskLevel.HIGH,
                'residual_score': 6,
                'residual_level': RiskRecord.RiskLevel.MEDIUM,
            },
        )
        self._upsert(
            RiskAssessment,
            'risks.assessments',
            {
                'risk': risk,
                'assessment_type': RiskAssessment.AssessmentType.INITIAL,
            },
            {
                'method': RiskAssessment.Method.FMEA,
                'probability': 3,
                'severity': 4,
                'detectability': 1,
                'score': 12,
                'risk_level': RiskAssessment.RiskLevel.HIGH,
                'rationale': 'Avaliacao demo inicial.',
                'assessed_by': self.refs['quality_user'],
                'assessed_at': self.now,
            },
        )
        program = self._upsert(
            AuditProgram,
            'audits.programs',
            {'program_number': 'DEMO-AUDPRG-2026'},
            {
                'audit_type': AuditProgram.AuditType.INTERNAL,
                'title': 'Programa demo de auditorias GMP',
                'year': self.today.year,
                'scope': 'Produção, QC e QA.',
                'criteria': 'BPF, ALCOA+ e procedimentos internos.',
                'owner': self.refs['quality_user'],
                'starts_on': self.today,
                'ends_on': self.today + timezone.timedelta(days=180),
                'status': AuditProgram.Status.ACTIVE,
            },
        )
        self.refs.update(
            {
                'controlled_document': document,
                'quality_event': event,
                'capa': capa,
                'risk': risk,
                'audit_program': program,
            }
        )

    def _seed_recalls(self):
        from recalls.models import RecallCampaign

        product = self.refs['products']['DEMO-PROD-HIDRATANTE']
        recall = self._upsert(
            RecallCampaign,
            'recalls.campaigns',
            {'campaign_number': 'DEMO-RECALL-0001'},
            {
                'campaign_type': RecallCampaign.CampaignType.FIELD_CORRECTION,
                'trigger': RecallCampaign.Trigger.INTERNAL,
                'product': product,
                'stock_lot': self.refs['stock_lot_pa'],
                'deviation_event': self.refs['quality_event'],
                'capa': self.refs['capa'],
                'criticality': RecallCampaign.Criticality.MEDIUM,
                'criticality_ref': self.refs['severity_high'],
                'reason': 'Campanha demo para simular avaliacao de campo.',
                'decision_date': self.today,
                'target_completion_date': self.today + timezone.timedelta(days=30),
                'responsible': self.refs['quality_user'],
                'status': RecallCampaign.Status.DRAFT,
            },
        )
        self.refs.update({'recall': recall})

    def _seed_support_modules(self):
        from reports.models import DashboardWidget, DashboardWorkspace, ReportDefinition
        from training.models import (
            Competency,
            JobPosition,
            TrainingEnrollment,
            TrainingRequirement,
            TrainingSession,
        )
        from workflow.models import ApprovalQueue, ApprovalTask, WorkflowNotification

        position = self._upsert(
            JobPosition,
            'training.positions',
            {'code': 'DEMO-OP-SOL'},
            {
                'title': 'Operador de solidos demo',
                'area': 'Producao',
                'area_ref': self.refs['production_area'],
            },
        )
        competency = self._upsert(
            Competency,
            'training.competencies',
            {'code': 'DEMO-GMP'},
            {
                'name': 'BPF aplicada a solidos',
                'competency_type': Competency.CompetencyType.TECHNICAL,
            },
        )
        requirement = self._upsert(
            TrainingRequirement,
            'training.requirements',
            {'code': 'DEMO-TR-BPF'},
            {
                'title': 'Treinamento BPF demo',
                'training_type': TrainingRequirement.TrainingType.DOCUMENT,
                'area': 'Producao',
                'area_ref': self.refs['production_area'],
                'job_position': position,
                'competency': competency,
                'document': self.refs['controlled_document'],
                'validity_days': 365,
                'is_active': True,
            },
        )
        session = self._upsert(
            TrainingSession,
            'training.sessions',
            {'session_number': 'DEMO-TRS-0001'},
            {
                'requirement': requirement,
                'title': 'Turma demo BPF',
                'delivery_method': TrainingSession.DeliveryMethod.CLASSROOM,
                'scheduled_start': self.now + timezone.timedelta(days=7),
                'scheduled_end': self.now + timezone.timedelta(days=7, hours=2),
                'instructor': self.refs['quality_user'],
                'capacity': 20,
                'status': TrainingSession.Status.OPEN,
                'location': 'Sala treinamento demo',
            },
        )
        self._upsert(
            TrainingEnrollment,
            'training.enrollments',
            {
                'requirement': requirement,
                'user': self.refs['production_user'],
            },
            {
                'session': session,
                'status': TrainingEnrollment.Status.CONVOKED,
                'convoked_by': self.refs['quality_user'],
                'convoked_at': self.now,
            },
        )
        queue = self._upsert(
            ApprovalQueue,
            'workflow.queues',
            {'code': 'DEMO-QA-APPROVAL'},
            {
                'name': 'Aprovacoes QA demo',
                'module': WorkflowNotification.SourceModule.QUALITY,
                'module_ref': self.refs['module_refs'].get('quality'),
                'area': 'Garantia da Qualidade',
                'area_ref': self.refs['quality_area'],
                'profile_role': 'quality',
                'role_ref': self.refs['qa_role'],
                'criticality': WorkflowNotification.Criticality.HIGH,
                'criticality_ref': self.refs['severity_high'],
                'created_by': self.refs['quality_user'],
                'is_active': True,
                'description': 'Fila demo para aprovacoes de qualidade.',
            },
        )
        task = self._upsert(
            ApprovalTask,
            'workflow.tasks',
            {'task_number': 'DEMO-WF-0001'},
            {
                'queue': queue,
                'title': 'Aprovar documento fiscal demo',
                'description': 'Tarefa demo para validar workflow.',
                'source_module': WorkflowNotification.SourceModule.FISCAL,
                'source_module_ref': self.refs['module_refs'].get('fiscal'),
                'source_model': 'FiscalDocument',
                'source_model_ref': self.refs['model_refs'].get('fiscal.FiscalDocument'),
                'source_record_id': str(self.refs['fiscal_document'].id),
                'area': 'Fiscal',
                'criticality': WorkflowNotification.Criticality.MEDIUM,
                'amount': Decimal('29500.00'),
                'requested_by': self.refs['finance_user'],
                'assigned_to': self.refs['quality_user'],
                'due_at': self.now + timezone.timedelta(days=2),
            },
        )
        self._upsert(
            WorkflowNotification,
            'workflow.notifications',
            {
                'recipient': self.refs['quality_user'],
                'title': 'Tarefa demo pendente',
                'source_module': WorkflowNotification.SourceModule.QUALITY,
            },
            {
                'category': WorkflowNotification.Category.APPROVAL,
                'message': 'Ha uma tarefa demo aguardando aprovacao.',
                'source_module_ref': self.refs['module_refs'].get('quality'),
                'source_model_ref': self.refs['model_refs'].get('workflow.ApprovalTask'),
                'source_record_id': str(task.id),
                'criticality': WorkflowNotification.Criticality.MEDIUM,
                'criticality_ref': self.refs['severity_high'],
            },
        )
        report = self._upsert(
            ReportDefinition,
            'reports.definitions',
            {'code': 'DEMO-REL-QA'},
            {
                'title': 'Indicadores QA demo',
                'module': ReportDefinition.Module.QUALITY,
                'module_ref': self.refs['module_refs'].get('quality'),
                'category': ReportDefinition.Category.INDICATOR,
                'allowed_export_formats': ['pdf', 'xlsx'],
                'default_filters': {'demo': True},
                'owner': self.refs['quality_user'],
                'description': 'Relatorio demo de qualidade.',
            },
        )
        dashboard = self._upsert(
            DashboardWorkspace,
            'reports.dashboards',
            {'code': 'DEMO-DASH-QA'},
            {
                'title': 'Dashboard QA demo',
                'module': ReportDefinition.Module.QUALITY,
                'module_ref': self.refs['module_refs'].get('quality'),
                'owner': self.refs['quality_user'],
                'layout': {'demo': True},
            },
        )
        self._upsert(
            DashboardWidget,
            'reports.widgets',
            {'dashboard': dashboard, 'title': 'CAPAs abertas'},
            {
                'widget_type': DashboardWidget.WidgetType.KPI,
                'module': ReportDefinition.Module.QUALITY,
                'module_ref': self.refs['module_refs'].get('quality'),
                'report_definition': report,
                'position_row': 1,
                'position_column': 1,
                'width': 4,
                'height': 2,
                'configuration': {'source': 'capa'},
            },
        )
        self.refs.update({'training_session': session, 'approval_task': task, 'report': report})

    def _seed_ai_agents(self):
        from integrations.models import ApiClientApplication, IntegrationConnector

        connector = self._upsert(
            IntegrationConnector,
            'integrations.connectors',
            {'code': 'DEMO-NFE'},
            {
                'name': 'Conector NF-e demo',
                'provider_type': IntegrationConnector.ProviderType.FISCAL_SYSTEM,
                'base_url': 'https://homologacao.example.com/nfe',
                'status': IntegrationConnector.Status.ACTIVE,
                'responsible': self.refs['finance_user'],
                'configuration': {'demo': True},
            },
        )
        self._upsert(
            ApiClientApplication,
            'integrations.api_clients',
            {'code': 'DEMO-CLIENT'},
            {
                'name': 'Cliente API demo',
                'client_id': 'demo-client-id',
                'scopes': ['demo:read', 'demo:write'],
                'status': ApiClientApplication.Status.ACTIVE,
                'created_by': self.refs['admin_user'],
            },
        )
        self.refs['integration_connector'] = connector


def seed_full_demo(user=None):
    return DemoSeeder(user=user).run_full_demo()
