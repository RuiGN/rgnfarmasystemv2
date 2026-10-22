from dataclasses import FrozenInstanceError
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.db import connection
from django.http import Http404
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from base.ui.context_processors import sidebar_menu
from base.ui.deadlines import build_workspace_deadlines
from base.ui.presentation import NotificationPreview, ProgressMetric
from base.ui.views import WorkspaceView
from base.ui.workspaces import WORKSPACES, WorkspaceConfig, WorkspaceContent, get_workspace
from inventory.models import StockLot
from production.models import ProductionOrder
from qa.models import BatchRecordChecklistItem, QAReview
from quality.models import LaboratoryInvestigation, QualityAnalysis, QualitySample
from tests.test_production import create_released_manufacturing_set
from workflow.models import ApprovalQueue, ApprovalTask, AsyncJobStatus, WorkflowNotification


def grant_view_permission(user, model):
    user.user_permissions.add(
        Permission.objects.get(
            content_type__app_label=model._meta.app_label,
            content_type__model=model._meta.model_name,
            codename=f'view_{model._meta.model_name}',
        )
    )


class WorkspaceConfigurationTests(SimpleTestCase):
    def test_registry_contains_the_three_approved_workspaces(self):
        self.assertEqual(set(WORKSPACES), {'operations', 'quality', 'workflow'})
        self.assertEqual(get_workspace('operations').module_slug, 'production')
        self.assertEqual(get_workspace('quality').module_slug, 'quality')
        self.assertEqual(get_workspace('workflow').module_slug, 'workflow')

    def test_unknown_workspace_returns_none(self):
        self.assertIsNone(get_workspace('missing'))

    def test_workspace_configuration_is_immutable(self):
        workspace = get_workspace('operations')

        with self.assertRaises(FrozenInstanceError):
            workspace.title = 'Alterado'

    def test_workspace_navigation_metadata_and_urls_are_centralized(self):
        expectations = {
            'operations': (
                'app:operations_workspace',
                'Cockpit operacional',
                'feather-activity',
                10,
                '/app/workspaces/operations/',
            ),
            'quality': (
                'app:quality_workspace',
                'Cockpit de qualidade',
                'feather-check-square',
                20,
                '/app/workspaces/quality/',
            ),
            'workflow': (
                'app:workflow_workspace',
                'Central de workflow',
                'feather-git-pull-request',
                30,
                '/app/workspaces/workflow/',
            ),
        }

        for slug, expected in expectations.items():
            with self.subTest(slug=slug):
                workspace = get_workspace(slug)
                actual = (
                    workspace.route_name,
                    workspace.navigation_label,
                    workspace.icon,
                    workspace.order,
                    workspace.navigation_url,
                )
                self.assertEqual(actual, expected)

    def test_legacy_workspace_templates_are_removed_and_contract_is_documented(self):
        from pathlib import Path

        legacy_templates = (
            Path('templates/workspaces/operations.html'),
            Path('templates/workspaces/quality.html'),
            Path('templates/workspaces/workflow.html'),
        )
        documentation = Path('TEMPLATES.md').read_text()

        self.assertTrue(all(not path.exists() for path in legacy_templates))
        self.assertIn('workspaces/workspace.html', documentation)
        self.assertIn('/app/', documentation)
        self.assertIn('WorkspaceConfig', documentation)

    def test_workspace_navigation_contract_is_documented(self):
        from pathlib import Path

        documentation = Path('TEMPLATES.md').read_text()

        self.assertIn('sidebar_workspaces', documentation)
        self.assertIn('route_name', documentation)
        self.assertIn('navigation_label', documentation)
        self.assertIn('links não autorizados', documentation)


class WorkspaceContentBuilderTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username='workspace-builder@example.com',
            email='workspace-builder@example.com',
            password='WorkspaceSecure!123',
        )

    def request_for(self, user=None):
        request = RequestFactory().get('/app/workspaces/')
        request.user = user or self.admin
        return request

    def test_builders_preserve_metric_labels_and_primary_links(self):
        expectations = {
            'operations': (
                ('Ordens em execução', 'Lotes em estoque', 'Amostras pendentes'),
                '/app/production/orders/',
            ),
            'quality': (
                ('Amostras em análise', 'Análises pendentes', 'Investigações abertas'),
                '/app/quality/samples/',
            ),
            'workflow': (
                ('Aprovações pendentes', 'Notificações não lidas', 'Jobs em execução'),
                '/app/workflow/tasks/',
            ),
        }

        for slug, (labels, primary_url) in expectations.items():
            with self.subTest(slug=slug):
                content = get_workspace(slug).build_content(self.request_for())
                self.assertEqual(tuple(metric.label for metric in content.metrics), labels)
                self.assertEqual(content.metrics[0].url, primary_url)

    def test_workflow_notifications_are_scoped_to_request_user(self):
        other_user = get_user_model().objects.create_user(
            username='workspace-other@example.com',
            email='workspace-other@example.com',
            password='WorkspaceSecure!123',
        )
        for recipient in (self.admin, other_user, other_user):
            WorkflowNotification.objects.create(
                category=WorkflowNotification.Category.ALERT,
                recipient=recipient,
                title='Alerta de teste',
                message='Mensagem de teste',
                source_module=WorkflowNotification.SourceModule.QUALITY,
            )

        content = get_workspace('workflow').build_content(self.request_for())
        metric = next(item for item in content.metrics if item.label == 'Notificações não lidas')

        self.assertEqual(metric.value, 1)

    def test_builders_query_only_models_with_exact_view_permission(self):
        cases = (
            (
                'operations',
                ProductionOrder,
                ('Ordens em execução',),
                (StockLot, QualitySample),
            ),
            (
                'quality',
                QualitySample,
                ('Amostras em análise',),
                (QualityAnalysis, LaboratoryInvestigation),
            ),
            (
                'workflow',
                ApprovalTask,
                ('Aprovações pendentes',),
                (WorkflowNotification, AsyncJobStatus),
            ),
        )

        for slug, allowed_model, expected_labels, forbidden_models in cases:
            with self.subTest(slug=slug):
                user = get_user_model().objects.create_user(
                    username=f'escopo-{slug}@example.com',
                    email=f'escopo-{slug}@example.com',
                    password='WorkspaceSecure!123',
                )
                grant_view_permission(user, allowed_model)
                request = self.request_for(user)
                with CaptureQueriesContext(connection) as queries:
                    content = get_workspace(slug).build_content(request)

                self.assertEqual(
                    tuple(metric.label for metric in content.metrics),
                    expected_labels,
                )
                sql = '\n'.join(query['sql'].lower() for query in queries)
                for model in forbidden_models:
                    self.assertNotIn(model._meta.db_table.lower(), sql)


class WorkspaceAccessTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='workspace@example.com',
            email='workspace@example.com',
            password='WorkspaceSecure!123',
        )
        self.admin = get_user_model().objects.create_superuser(
            username='workspace-admin@example.com',
            email='workspace-admin@example.com',
            password='WorkspaceSecure!123',
        )

    def navigation_context_for(self, user):
        request = RequestFactory().get('/app/')
        request.user = user
        return sidebar_menu(request)

    def test_context_exposes_only_authorized_workspaces_in_configured_order(self):
        context = self.navigation_context_for(self.user)
        self.assertEqual(context['sidebar_workspaces'], ())

        grant_view_permission(self.user, ProductionOrder)
        self.user = get_user_model().objects.get(pk=self.user.pk)
        context = self.navigation_context_for(self.user)
        self.assertEqual(
            tuple(workspace.slug for workspace in context['sidebar_workspaces']),
            ('operations',),
        )

        admin_context = self.navigation_context_for(self.admin)
        self.assertEqual(
            tuple(workspace.slug for workspace in admin_context['sidebar_workspaces']),
            ('operations', 'quality', 'workflow'),
        )

    def test_notification_query_is_skipped_without_workflow_access(self):
        grant_view_permission(self.user, ProductionOrder)

        with patch(
            'base.ui.context_processors.WorkflowNotification.objects.filter'
        ) as notification_filter:
            context = self.navigation_context_for(self.user)

        notification_filter.assert_not_called()
        self.assertFalse(context['can_view_workflow_workspace'])
        self.assertEqual(context['unread_workflow_notifications'], 0)

    def test_anonymous_navigation_context_exposes_safe_empty_defaults(self):
        request = RequestFactory().get('/accounts/login/')
        request.user = AnonymousUser()

        context = sidebar_menu(request)

        self.assertEqual(context['sidebar_workspaces'], ())
        self.assertFalse(context['show_dashboard_navigation'])
        self.assertFalse(context['can_view_workflow_workspace'])

    def test_existing_route_names_and_paths_are_preserved(self):
        self.assertEqual(reverse('app:operations_workspace'), '/app/workspaces/operations/')
        self.assertEqual(reverse('app:quality_workspace'), '/app/workspaces/quality/')
        self.assertEqual(reverse('app:workflow_workspace'), '/app/workspaces/workflow/')

    def test_workspace_requires_login(self):
        response = self.client.get(reverse('app:operations_workspace'))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response['Location'].startswith(reverse('accounts:login')))

    def test_all_workspaces_render_the_shared_template(self):
        self.client.force_login(self.admin)

        for route_name in (
            'app:operations_workspace',
            'app:quality_workspace',
            'app:workflow_workspace',
        ):
            with self.subTest(route_name=route_name):
                response = self.client.get(reverse(route_name))
                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(response, 'workspaces/workspace.html')
                self.assertContains(response, 'data-ui="workspace"')

    def test_authenticated_workflow_header_has_one_current_page_and_preserves_module_link(self):
        from tests.test_compact_page_header import HeaderParser

        self.client.force_login(self.admin)
        response = self.client.get(reverse('app:workflow_workspace'))
        self.assertEqual(response.status_code, 200)
        header = HeaderParser(response.content.decode())

        self.assertEqual(header.text, ['Aplicativos', 'Fluxo de trabalho'])
        self.assertEqual(header.headings, 1)
        self.assertEqual(header.current_pages, 1)
        self.assertEqual(header.links, ['/app/'])
        self.assertContains(response, 'href="/app/workflow/"')
        self.assertTemplateUsed(response, 'includes/page_header.html')

    def test_compact_navigation_does_not_grant_workflow_access(self):
        from tests.test_compact_page_header import HeaderParser

        self.client.force_login(self.user)
        response = self.client.get(reverse('app:workflow_workspace'))
        self.assertEqual(response.status_code, 403)
        header = HeaderParser(response.content.decode())

        self.assertEqual(header.text, ['Aplicativos', 'Acesso negado'])
        self.assertEqual(header.current_pages, 1)

    def test_workspace_renders_accessible_progress_metric_when_target_exists(self):
        self.client.force_login(self.admin)

        content = WorkspaceContent(
            metrics=(
                ProgressMetric(
                    'Ordens em execução',
                    1,
                    'feather-play-circle',
                    'primary',
                    'Produção',
                    reverse('app:resource_list', args=('production', 'orders')),
                    2,
                ),
            ),
            quick_links=(),
        )
        with patch.object(WorkspaceConfig, 'build_content', return_value=content):
            response = self.client.get(reverse('app:operations_workspace'))

        self.assertContains(response, 'data-ui="progress-metric"')
        self.assertContains(response, 'role="progressbar"')
        self.assertContains(response, 'aria-valuenow="')
        self.assertContains(response, 'Ver detalhes')

    def test_user_without_module_permission_receives_403(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('app:operations_workspace'))

        self.assertEqual(response.status_code, 403)

    def test_unknown_direct_workspace_configuration_raises_404(self):
        request = RequestFactory().get('/app/workspaces/missing/')
        request.user = self.admin

        with self.assertRaises(Http404):
            WorkspaceView.as_view(workspace_slug='missing')(request)

    def test_metric_cards_are_filtered_by_model_permission(self):
        grant_view_permission(self.user, ProductionOrder)
        self.client.force_login(self.user)

        response = self.client.get(reverse('app:operations_workspace'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Ordens em execução')
        self.assertNotContains(response, 'Lotes em estoque')
        self.assertNotContains(response, 'Amostras pendentes')
        self.assertNotContains(response, '>Planejamento<')

    def test_shell_hides_unauthorized_workspaces_and_workflow_bell(self):
        grant_view_permission(self.user, ProductionOrder)
        self.client.force_login(self.user)

        response = self.client.get(reverse('app:index'))
        navigation = response.content.decode().split('</nav>', 1)[0]

        self.assertContains(response, 'href="/app/workspaces/operations/"')
        self.assertNotIn('href="/app/workspaces/quality/"', navigation)
        self.assertNotIn('href="/app/workspaces/workflow/"', navigation)
        self.assertNotContains(response, 'data-ui="workflow-notifications"')

    def test_superuser_sees_workspaces_in_configured_order(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('app:index'))
        navigation = response.content.decode().split('</nav>', 1)[0]
        positions = tuple(
            navigation.index(f'href="{get_workspace(slug).navigation_url}"')
            for slug in ('operations', 'quality', 'workflow')
        )

        self.assertEqual(positions, tuple(sorted(positions)))

    def test_active_workspace_has_accessible_current_state(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('app:operations_workspace'))

        self.assertContains(
            response,
            'href="/app/workspaces/operations/" class="nxl-link" aria-current="page"',
            html=False,
        )


class WorkflowNotificationPreviewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='notification-preview@example.com',
            email='notification-preview@example.com',
            password='WorkspaceSecure!123',
        )
        self.other_user = get_user_model().objects.create_user(
            username='notification-preview-other@example.com',
            email='notification-preview-other@example.com',
            password='WorkspaceSecure!123',
        )

    def create_notification(self, recipient, title, created_at, **kwargs):
        notification = WorkflowNotification.objects.create(
            category=WorkflowNotification.Category.ALERT,
            recipient=recipient,
            title=title,
            message='Acompanhe esta notificação operacional.',
            source_module=WorkflowNotification.SourceModule.QUALITY,
            **kwargs,
        )
        WorkflowNotification.objects.filter(pk=notification.pk).update(created_at=created_at)
        notification.refresh_from_db()
        return notification

    def test_notification_preview_normalizes_operational_presentation(self):
        notification = self.create_notification(
            self.user,
            'Notificação crítica',
            timezone.now(),
            criticality=WorkflowNotification.Criticality.CRITICAL,
        )

        preview = NotificationPreview.from_model(notification)

        self.assertEqual(preview.title, 'Notificação crítica')
        self.assertEqual(preview.criticality_label, 'Crítica')
        self.assertEqual(preview.source_module_label, 'Qualidade')
        self.assertEqual(preview.icon, 'feather-alert-octagon')
        self.assertTrue(preview.is_unread)
        self.assertEqual(
            preview.url,
            reverse('app:resource_detail', args=('workflow', 'notifications', notification.pk)),
        )

    def test_dropdown_is_scoped_ordered_limited_and_uses_accessible_content(self):
        grant_view_permission(self.user, WorkflowNotification)
        now = timezone.now()
        for index in range(6):
            self.create_notification(
                self.user,
                f'Notificação da usuária {index}',
                now - timedelta(minutes=index),
                criticality=WorkflowNotification.Criticality.HIGH,
            )
        self.create_notification(
            self.other_user,
            'Notificação de outro usuário',
            now + timedelta(minutes=1),
        )
        context = sidebar_menu(self.request_for(self.user))
        self.client.force_login(self.user)

        response = self.client.get(reverse('app:index'))

        self.assertEqual(len(context['workflow_notification_previews']), 5)
        self.assertEqual(context['unread_workflow_notifications'], 6)
        self.assertContains(response, 'data-ui="workflow-notifications"')
        self.assertContains(response, 'aria-label="6 notificações não lidas"')
        self.assertContains(response, 'Ver todas as notificações')
        self.assertContains(response, 'Notificação da usuária 0')
        self.assertContains(response, 'Notificação da usuária 4')
        self.assertNotContains(response, 'Notificação da usuária 5')
        self.assertNotContains(response, 'Notificação de outro usuário')
        self.assertContains(response, 'aria-expanded="false"')
        self.assertContains(response, '<time datetime="', html=False)
        self.assertContains(response, 'Não lida')
        self.assertContains(response, 'Qualidade')
        content = response.content.decode()
        self.assertLess(
            content.index('Notificação da usuária 0'),
            content.index('Notificação da usuária 4'),
        )

    def test_dropdown_shows_empty_state_when_authorized_user_has_no_notifications(self):
        grant_view_permission(self.user, WorkflowNotification)
        self.client.force_login(self.user)

        response = self.client.get(reverse('app:index'))

        self.assertContains(response, 'Nenhuma notificação recente.')
        self.assertContains(response, 'Ver todas as notificações')

    def test_notification_query_is_skipped_without_exact_notification_permission(self):
        grant_view_permission(self.user, ApprovalTask)

        with patch(
            'base.ui.context_processors.WorkflowNotification.objects.filter'
        ) as notification_filter:
            context = sidebar_menu(self.request_for(self.user))

        notification_filter.assert_not_called()
        self.assertTrue(context['can_view_workflow_workspace'])
        self.assertFalse(context['can_preview_workflow_notifications'])
        self.assertEqual(context['workflow_notification_previews'], ())
        self.assertEqual(context['unread_workflow_notifications'], 0)

    @staticmethod
    def request_for(user):
        request = RequestFactory().get('/app/')
        request.user = user
        return request


class WorkspaceDeadlineBuilderTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='workspace-deadlines@example.com',
            email='workspace-deadlines@example.com',
            password='WorkspaceSecure!123',
        )
        self.other_user = get_user_model().objects.create_user(
            username='workspace-deadlines-other@example.com',
            email='workspace-deadlines-other@example.com',
            password='WorkspaceSecure!123',
        )

    def request_for(self, user=None):
        request = RequestFactory().get('/app/workspaces/')
        request.user = user or self.user
        return request

    def create_order(self, order_number, due_date, status=ProductionOrder.Status.RELEASED):
        unit, product, _material, formula, _component, route = create_released_manufacturing_set(
            suffix=order_number
        )
        return ProductionOrder.objects.create(
            order_number=order_number,
            product=product,
            formula=formula,
            route=route,
            planned_quantity=Decimal('100.0000'),
            unit=unit,
            status=status,
            scheduled_end=due_date,
        )

    def create_approval_task(self, *, assigned_to, due_at, title):
        queue = ApprovalQueue.objects.create(
            code=f'APV-{title}',
            name=f'Fila {title}',
            module=WorkflowNotification.SourceModule.QUALITY,
            profile_role='quality',
        )
        task = ApprovalTask.objects.create(
            queue=queue,
            title=title,
            description=f'Descrição de {title}.',
            source_module=WorkflowNotification.SourceModule.QUALITY,
            source_model='QualityEvent',
            source_record_id=f'REF-{title}',
            assigned_to=assigned_to,
            due_at=due_at,
        )
        generated_notification = WorkflowNotification.objects.get(
            recipient=assigned_to,
            title=f'Aprovação pendente: {title}',
        )
        generated_notification.status = WorkflowNotification.Status.ARCHIVED
        generated_notification.archived_at = timezone.now()
        generated_notification.save(update_fields=['status', 'archived_at', 'updated_at'])
        return task

    def test_builder_orders_authorized_items_and_excludes_terminal_or_foreign_records(self):
        grant_view_permission(self.user, ProductionOrder)
        grant_view_permission(self.user, ApprovalTask)
        grant_view_permission(self.user, WorkflowNotification)
        now = timezone.now()
        active_order = self.create_order('OP-ATIVA', timezone.localdate() + timedelta(days=3))
        self.create_order(
            'OP-ENCERRADA',
            timezone.localdate() - timedelta(days=2),
            status=ProductionOrder.Status.CLOSED,
        )
        approval = self.create_approval_task(
            assigned_to=self.user,
            due_at=now - timedelta(days=1),
            title='Aprovação vencida',
        )
        self.create_approval_task(
            assigned_to=self.other_user,
            due_at=now - timedelta(days=1),
            title='Aprovação de outro usuário',
        )
        notification = WorkflowNotification.objects.create(
            category=WorkflowNotification.Category.DUE_DATE,
            recipient=self.user,
            title='Notificação futura',
            message='Acompanhe o prazo informado.',
            source_module=WorkflowNotification.SourceModule.QUALITY,
            due_at=now + timedelta(days=1),
        )
        WorkflowNotification.objects.create(
            category=WorkflowNotification.Category.DUE_DATE,
            recipient=self.user,
            title='Notificação arquivada',
            message='Não deve aparecer.',
            source_module=WorkflowNotification.SourceModule.QUALITY,
            due_at=now - timedelta(days=2),
            status=WorkflowNotification.Status.ARCHIVED,
            archived_at=now,
        )

        operations = build_workspace_deadlines(self.request_for(), 'operations')
        workflow = build_workspace_deadlines(self.request_for(), 'workflow')

        assert tuple(item.title for item in operations) == ('OP-ATIVA',)
        assert operations[0].url == reverse(
            'app:resource_detail', args=('production', 'orders', active_order.pk)
        )
        assert tuple(item.title for item in workflow) == (
            'Aprovação vencida',
            'Notificação futura',
        )
        assert workflow[0].url == reverse(
            'app:resource_detail', args=('workflow', 'tasks', approval.pk)
        )
        assert workflow[1].url == reverse(
            'app:resource_detail', args=('workflow', 'notifications', notification.pk)
        )
        assert workflow[0].temporal_label == 'Vencido'
        assert build_workspace_deadlines(self.request_for(), 'workflow', limit=1) == (workflow[0],)

    def test_builder_uses_quality_checklist_due_date_only_with_permission(self):
        grant_view_permission(self.user, BatchRecordChecklistItem)
        review = QAReview.objects.create(
            review_type=QAReview.ReviewType.PRODUCTION_ORDER,
            title='Revisão de prazo de checklist',
        )
        pending = BatchRecordChecklistItem.objects.create(
            review=review,
            title='Conferir reconciliação',
            due_date=timezone.localdate() + timedelta(days=1),
        )
        BatchRecordChecklistItem.objects.create(
            review=review,
            title='Checklist concluído',
            status=BatchRecordChecklistItem.Status.COMPLETED,
            due_date=timezone.localdate() - timedelta(days=1),
            evidence_reference='evidências/checklist.pdf',
            completed_by=self.user,
            completed_at=timezone.now(),
        )

        deadlines = build_workspace_deadlines(self.request_for(), 'quality')

        assert tuple(item.title for item in deadlines) == ('Conferir reconciliação',)
        assert deadlines[0].url == reverse(
            'app:resource_detail', args=('qa', 'checklist-items', pending.pk)
        )

    def test_builder_does_not_query_or_expose_unauthorized_source(self):
        review = QAReview.objects.create(
            review_type=QAReview.ReviewType.PRODUCTION_ORDER,
            title='Revisão para prazo de checklist',
        )
        BatchRecordChecklistItem.objects.create(
            review=review,
            title='Conferir reconciliação',
            due_date=timezone.localdate() + timedelta(days=1),
        )

        with CaptureQueriesContext(connection) as queries:
            deadlines = build_workspace_deadlines(self.request_for(), 'quality')

        assert deadlines == ()
        assert BatchRecordChecklistItem._meta.db_table.lower() not in '\n'.join(
            query['sql'].lower() for query in queries
        )

    def test_workspace_view_exposes_and_renders_deadlines(self):
        grant_view_permission(self.user, ProductionOrder)
        self.create_order('OP-RENDER', timezone.localdate())
        self.client.force_login(self.user)

        response = self.client.get(reverse('app:operations_workspace'))

        self.assertContains(response, 'data-ui="operational-deadlines"')
        self.assertContains(response, 'OP-RENDER')
        self.assertContains(response, 'Vence hoje')
