from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from deviations.models import QualityEvent
from production.models import ProductionOrder
from documents.models import ControlledDocument
from formulations.models import MasterFormula
from ai_agents.models import AIAgentProfile
from knowledge.models import RAGChatSession
from masters.models import Product, UnitOfMeasure
from tests.test_production import create_released_manufacturing_set


def grant_model_perm(user, model, action):
    permission = Permission.objects.get(
        content_type__app_label=model._meta.app_label,
        content_type__model=model._meta.model_name,
        codename=f'{action}_{model._meta.model_name}',
    )
    user.user_permissions.add(permission)


class AdditionalResourceViewsTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.user = self.User.objects.create_user(
            username='qa@example.com',
            email='qa@example.com',
            password='S3curePass!123',
        )
        self.client.force_login(self.user)

        # Grant view permissions to see modules/resources
        grant_model_perm(self.user, QualityEvent, 'view')
        grant_model_perm(self.user, ProductionOrder, 'view')
        grant_model_perm(self.user, ControlledDocument, 'view')
        grant_model_perm(self.user, MasterFormula, 'view')
        grant_model_perm(self.user, AIAgentProfile, 'view')
        grant_model_perm(self.user, Product, 'view')

    def test_kanban_view_resolves_and_renders_properly(self):
        QualityEvent.objects.create(
            event_type=QualityEvent.EventType.DEVIATION,
            origin=QualityEvent.Origin.MANUAL,
            area='Embalagem',
            description='Desvio de teste',
            detected_at=timezone.now(),
            status=QualityEvent.Status.OPEN,
        )

        response = self.client.get(
            reverse(
                'app:resource_kanban',
                kwargs={'module_slug': 'deviations', 'resource_slug': 'events'},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Kanban - Eventos de qualidade')
        self.assertContains(response, 'Desvio de teste')

    def test_kanban_view_raises_404_when_disabled(self):
        response = self.client.get(
            reverse(
                'app:resource_kanban',
                kwargs={'module_slug': 'masters', 'resource_slug': 'products'},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_gantt_view_resolves_and_renders_properly(self):
        unit, product, _, formula, _, route = create_released_manufacturing_set(suffix='gantt')
        ProductionOrder.objects.create(
            order_number='OP-TEST-GANTT',
            product=product,
            formula=formula,
            route=route,
            planned_quantity=Decimal('100.0000'),
            unit=unit,
        )

        response = self.client.get(
            reverse(
                'app:resource_gantt',
                kwargs={'module_slug': 'production', 'resource_slug': 'orders'},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'PCP Gantt')
        self.assertContains(response, 'OP-TEST-GANTT')

    def test_gantt_view_raises_404_when_disabled(self):
        response = self.client.get(
            reverse(
                'app:resource_gantt',
                kwargs={'module_slug': 'masters', 'resource_slug': 'products'},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_document_viewer_resolves_and_renders_properly(self):
        doc = ControlledDocument.objects.create(
            document_type=ControlledDocument.DocumentType.SOP,
            code='POP-TEST-VIEWER',
            title='Procedimento Teste',
            area='Garantia da qualidade',
            effective_from=timezone.localdate(),
            owner=self.user,
            change_summary='Inicial.',
        )

        response = self.client.get(
            reverse(
                'app:resource_viewer',
                kwargs={
                    'module_slug': 'documents',
                    'resource_slug': 'controlled-documents',
                    'pk': doc.pk,
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Leitura EDMS')
        self.assertContains(response, 'POP-TEST-VIEWER')

    def test_document_viewer_raises_404_when_disabled(self):
        unit = UnitOfMeasure.objects.create(code='KG-T2', name='Quilograma', symbol='kg')
        prod = Product.objects.create(
            code='PA-T2',
            description='Produto Teste 2',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=unit,
            status=Product.Status.APPROVED,
        )
        response = self.client.get(
            reverse(
                'app:resource_viewer',
                kwargs={'module_slug': 'masters', 'resource_slug': 'products', 'pk': prod.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_tree_view_resolves_and_renders_properly(self):
        unit = UnitOfMeasure.objects.create(code='KG-T3', name='Quilograma', symbol='kg')
        prod = Product.objects.create(
            code='PA-T3',
            description='Produto Teste 3',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=unit,
            status=Product.Status.APPROVED,
        )
        formula = MasterFormula.objects.create(
            product=prod,
            code='F-TEST-TREE',
            version=1,
            status=MasterFormula.Status.APPROVED,
            batch_size=Decimal('100.0000'),
            batch_unit=unit,
            effective_from=timezone.localdate(),
        )

        response = self.client.get(
            reverse(
                'app:resource_tree',
                kwargs={
                    'module_slug': 'formulations',
                    'resource_slug': 'formulas',
                    'pk': formula.pk,
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Árvore estrutural')
        self.assertContains(response, 'F-TEST-TREE')

    def test_tree_view_raises_404_when_disabled(self):
        unit = UnitOfMeasure.objects.create(code='KG-T4', name='Quilograma', symbol='kg')
        prod = Product.objects.create(
            code='PA-T4',
            description='Produto Teste 4',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=unit,
            status=Product.Status.APPROVED,
        )
        response = self.client.get(
            reverse(
                'app:resource_tree',
                kwargs={'module_slug': 'masters', 'resource_slug': 'products', 'pk': prod.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_chat_view_resolves_and_renders_properly(self):
        grant_model_perm(self.user, RAGChatSession, 'view')
        profile = AIAgentProfile.objects.create(
            code='AI-TEST-CHAT',
            name='Agente Teste',
            agent_type=AIAgentProfile.AgentType.SUMMARY,
            source_module=AIAgentProfile.SourceModule.DOCUMENTS,
            provider=AIAgentProfile.Provider.OPENAI,
            model_name='gpt-4o',
            system_prompt='Teste',
            allowed_source_modules=[AIAgentProfile.SourceModule.DOCUMENTS],
            created_by=self.user,
        )

        response = self.client.get(
            reverse(
                'app:resource_chat',
                kwargs={
                    'module_slug': 'ai_agents',
                    'resource_slug': 'profiles',
                    'pk': profile.pk,
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Agente IA')
        self.assertContains(response, 'Agente Teste')
        self.assertContains(response, 'data-rag-chat-endpoint="/api/knowledge/chat/"')
        self.assertContains(response, 'rag-chat.js')
        self.assertContains(response, 'name="question"')
        self.assertContains(response, 'Assistente de consulta — somente leitura')

    def test_chat_view_raises_404_when_disabled(self):
        unit = UnitOfMeasure.objects.create(code='KG-T5', name='Quilograma', symbol='kg')
        prod = Product.objects.create(
            code='PA-T5',
            description='Produto Teste 5',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=unit,
            status=Product.Status.APPROVED,
        )
        response = self.client.get(
            reverse(
                'app:resource_chat',
                kwargs={'module_slug': 'masters', 'resource_slug': 'products', 'pk': prod.pk},
            )
        )
        self.assertEqual(response.status_code, 404)

    def test_execution_view_resolves_and_renders_properly(self):
        grant_model_perm(self.user, ProductionOrder, 'change')
        unit, product, _, formula, _, route = create_released_manufacturing_set(suffix='exec')
        order = ProductionOrder.objects.create(
            order_number='OP-TEST-EXEC',
            product=product,
            formula=formula,
            route=route,
            planned_quantity=Decimal('100.0000'),
            unit=unit,
        )

        response = self.client.get(
            reverse(
                'app:resource_execute',
                kwargs={
                    'module_slug': 'production',
                    'resource_slug': 'orders',
                    'pk': order.pk,
                },
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Batch Record')
        self.assertContains(response, 'OP-TEST-EXEC')

    def test_execution_view_raises_404_when_disabled(self):
        unit = UnitOfMeasure.objects.create(code='KG-T7', name='Quilograma', symbol='kg')
        prod = Product.objects.create(
            code='PA-T7',
            description='Produto Teste 7',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=unit,
            status=Product.Status.APPROVED,
        )
        response = self.client.get(
            reverse(
                'app:resource_execute',
                kwargs={'module_slug': 'masters', 'resource_slug': 'products', 'pk': prod.pk},
            )
        )
        self.assertEqual(response.status_code, 404)
