from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from costing.models import ProductionCostCapture
from deviations.models import QualityEvent
from formulations.models import FormulaComponent, ManufacturingRoute, MasterFormula
from masters.models import Product, UnitOfMeasure
from production.models import (
    MaterialConsumption,
    ProductionLaborEntry,
    ProductionOperationExecution,
    ProductionOrder,
    ProductionOutput,
)
from quality.models import QualitySample


class ProductionOrderCockpitUiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='operador-producao',
            email='producao@example.com',
            password='Password123!',
        )
        self.client.force_login(self.user)

        # Permissão base para visualizar a ordem de produção
        view_order_perm = Permission.objects.get(
            content_type__app_label='production', codename='view_productionorder'
        )
        self.user.user_permissions.add(view_order_perm)

        self.unit_kg = UnitOfMeasure.objects.create(code='KG', name='Quilograma', symbol='kg')
        self.unit_un = UnitOfMeasure.objects.create(code='UN', name='Unidade', symbol='un')

        self.finished_product = Product.objects.create(
            code='PA-SERUM-01',
            description='Sérum Facial Vitamina C 30ml',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=self.unit_un,
            status=Product.Status.APPROVED,
        )

        self.raw_material = Product.objects.create(
            code='MP-VITC-01',
            description='Vitamina C Estabilizada Pó',
            item_type=Product.ItemType.RAW_MATERIAL,
            unit=self.unit_kg,
            status=Product.Status.APPROVED,
        )

        today = timezone.now().date()
        self.formula = MasterFormula.objects.create(
            product=self.finished_product,
            code='MF-SERUM-01',
            version=1,
            status=MasterFormula.Status.APPROVED,
            batch_size=Decimal('500.0000'),
            batch_unit=self.unit_un,
            effective_from=today,
            expected_yield_percent=Decimal('99.0000'),
        )

        self.component = FormulaComponent.objects.create(
            formula=self.formula,
            line_number=1,
            material=self.raw_material,
            role=FormulaComponent.Role.ACTIVE,
            quantity=Decimal('25.0000'),
            unit=self.unit_kg,
            expected_loss_percent=Decimal('1.0000'),
        )

        self.route = ManufacturingRoute.objects.create(
            product=self.finished_product,
            formula=self.formula,
            code='ROT-SERUM-01',
            version=1,
            status=ManufacturingRoute.Status.APPROVED,
            effective_from=today,
        )

        self.order = ProductionOrder.objects.create(
            order_number='OP-2026-001',
            batch_number='LOT-2026-001',
            product=self.finished_product,
            formula=self.formula,
            route=self.route,
            planned_quantity=Decimal('500.0000'),
            unit=self.unit_un,
            status=ProductionOrder.Status.IN_PROGRESS,
            priority=ProductionOrder.Priority.NORMAL,
            scheduled_start=today,
            scheduled_end=today + timedelta(days=2),
            production_line='Linha de Envase 01',
            responsible=self.user,
        )

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()
        url = reverse('app:production_order_cockpit', kwargs={'pk': self.order.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response['Location'])

    def test_user_without_view_permission_is_denied(self):
        self.user.user_permissions.clear()
        url = reverse('app:production_order_cockpit', kwargs={'pk': self.order.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 403)

    def test_cockpit_404_for_nonexistent_order(self):
        url = reverse('app:production_order_cockpit', kwargs={'pk': 999999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_authorized_user_can_view_cockpit_structure(self):
        url = reverse('app:production_order_cockpit', kwargs={'pk': self.order.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')
        self.assertIn('Cockpit da ordem de produção', content)
        self.assertIn(self.order.order_number, content)
        self.assertIn(self.order.batch_number, content)
        self.assertIn(self.finished_product.description, content)
        self.assertIn('1. Ficha e planejamento', content)
        self.assertIn('2. Materiais e pesagem', content)
        self.assertIn('3. Fases e mão de obra', content)
        self.assertIn('4. Controle em processo (IPC)', content)
        self.assertIn('5. Desvios e ocorrências', content)
        self.assertIn('6. Rendimento e custos', content)

    def test_detail_page_exposes_cockpit_button_for_authorized_user(self):
        detail_url = reverse(
            'app:resource_detail',
            kwargs={
                'module_slug': 'production',
                'resource_slug': 'orders',
                'pk': self.order.pk,
            },
        )
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)

        cockpit_url = reverse('app:production_order_cockpit', kwargs={'pk': self.order.pk})
        self.assertContains(response, cockpit_url)
        self.assertContains(response, 'Cockpit da OP')

    def test_detail_page_hides_cockpit_button_without_permission(self):
        self.user.user_permissions.clear()
        detail_url = reverse(
            'app:resource_detail',
            kwargs={
                'module_slug': 'production',
                'resource_slug': 'orders',
                'pk': self.order.pk,
            },
        )
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 403)

    def test_cockpit_renders_related_data_across_tabs(self):
        # Conceder todas as permissões das seções ao usuário
        perms = Permission.objects.filter(
            content_type__app_label__in=['production', 'quality', 'deviations', 'costing'],
            codename__in=[
                'view_materialconsumption',
                'view_productionoperationexecution',
                'view_productionlaborentry',
                'view_qualitysample',
                'view_qualityevent',
                'view_productionoutput',
                'view_productioncostcapture',
            ],
        )
        self.user.user_permissions.add(*perms)

        # 1. Consumo de material
        MaterialConsumption.objects.create(
            order=self.order,
            component=self.component,
            material=self.raw_material,
            planned_quantity=Decimal('25.0000'),
            actual_quantity=Decimal('24.8000'),
            loss_quantity=Decimal('0.2000'),
            unit=self.unit_kg,
            lot_number='LOTE-MP-VITC-99',
            quality_status='approved',
        )

        # 2. Operação e Mão de Obra
        now = timezone.now()
        ProductionOperationExecution.objects.create(
            order=self.order,
            sequence=1,
            operation='Mistura e Dissolução da Fase Ativa',
            work_center='Misturador M-01',
            status=ProductionOperationExecution.Status.COMPLETED,
            planned_minutes=Decimal('45.00'),
            actual_minutes=Decimal('40.00'),
            started_at=now - timedelta(hours=3),
            ended_at=now - timedelta(hours=2),
            recorded_by=self.user,
        )
        ProductionLaborEntry.objects.create(
            order=self.order,
            user=self.user,
            role='Operador Líder',
            started_at=now - timedelta(hours=3),
            ended_at=now - timedelta(hours=1),
            duration_minutes=Decimal('120.00'),
            hourly_cost=Decimal('50.00'),
            notes='Operação executada dentro dos parâmetros normais.',
        )

        # 3. Amostra de Controle em Processo (IPC)
        QualitySample.objects.create(
            sample_number='AMOSTRA-IPC-001',
            sample_type=QualitySample.SampleType.PRODUCTION,
            product=self.finished_product,
            source_production_order=self.order,
            quantity=Decimal('50.0000'),
            unit=self.unit_kg,
            status=QualitySample.Status.APPROVED,
            collection_point='Tanque Reator R-01',
            collected_by=self.user,
            collected_at=now - timedelta(hours=1),
        )

        # 4. Desvio de Qualidade
        QualityEvent.objects.create(
            event_number='DEV-PROD-2026-001',
            event_type=QualityEvent.EventType.DEVIATION,
            origin=QualityEvent.Origin.PRODUCTION,
            product=self.finished_product,
            area='Produção',
            severity=QualityEvent.Severity.LOW,
            criticality=QualityEvent.Criticality.MINOR,
            status=QualityEvent.Status.OPEN,
            description='Oscilação mínima de velocidade no agitador.',
            detected_at=now,
            responsible=self.user,
            opened_by=self.user,
            opened_at=now,
        )

        # 5. Saída de Produto Acabado
        ProductionOutput.objects.create(
            order=self.order,
            product=self.finished_product,
            lot_number='LOT-2026-001',
            sublot_number='SUB-A',
            planned_quantity=Decimal('500.0000'),
            produced_quantity=Decimal('498.0000'),
            unit=self.unit_un,
            status=ProductionOutput.Status.PENDING,
        )

        # 6. Apuração de Custos
        ProductionCostCapture.objects.create(
            production_order=self.order,
            period_start=now.date() - timedelta(days=2),
            period_end=now.date(),
            planned_cost=Decimal('12500.00'),
            actual_material_cost=Decimal('9800.00'),
            actual_labor_cost=Decimal('1500.00'),
            actual_machine_cost=Decimal('1000.00'),
            total_actual_cost=Decimal('12300.00'),
            variance_amount=Decimal('-200.00'),
        )

        url = reverse('app:production_order_cockpit', kwargs={'pk': self.order.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')
        # Verificar dados renderizados nas abas correspondentes
        self.assertIn('LOTE-MP-VITC-99', content)
        self.assertIn('Mistura e Dissolução da Fase Ativa', content)
        self.assertIn('Operador Líder', content)
        self.assertIn('AMOSTRA-IPC-001', content)
        self.assertIn('DEV-PROD-2026-001', content)
        self.assertIn('SUB-A', content)
        self.assertIn('R$ 12300,00', content)

    def test_segregation_of_duties_warnings_rendered_when_lacking_submodule_permissions(self):
        # Usuário só tem permissão de view_productionorder
        url = reverse('app:production_order_cockpit', kwargs={'pk': self.order.pk})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        content = response.content.decode('utf-8')
        # Avisos de permissão ausente devem ser renderizados nas abas restritas
        self.assertIn('Você não possui permissão para consultar os consumos de materiais desta ordem', content)
        self.assertIn('Você não possui permissão para visualizar as operações e mão de obra desta ordem', content)
        self.assertIn('Você não possui permissão para consultar as amostras de controle de qualidade desta ordem', content)
        self.assertIn('Você não possui permissão para consultar os desvios e não conformidades', content)
        self.assertIn('Você não possui permissão para visualizar as saídas e apropriação de custos desta ordem', content)
