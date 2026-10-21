from pathlib import Path
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from base.ui.personal_area import build_personal_area
from capa.models import CapaRecord
from deviations.models import QualityEvent
from training.models import TrainingEnrollment, TrainingRequirement
from workflow.models import ApprovalQueue, ApprovalTask, WorkflowNotification


PERSONAL_AREA_MODELS = (
    ApprovalTask,
    WorkflowNotification,
    QualityEvent,
    CapaRecord,
    TrainingEnrollment,
)


def grant_view_permission(user, model):
    user.user_permissions.add(
        Permission.objects.get(
            content_type__app_label=model._meta.app_label,
            content_type__model=model._meta.model_name,
            codename=f'view_{model._meta.model_name}',
        )
    )


class PersonalAreaServiceTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='minha-area@example.com',
            email='minha-area@example.com',
            password='MinhaAreaSecure!123',
        )
        self.other_user = get_user_model().objects.create_user(
            username='outra-area@example.com',
            email='outra-area@example.com',
            password='MinhaAreaSecure!123',
        )
        self.request = RequestFactory().get('/app/minha-area/')
        self.request.user = self.user
        self.queue = ApprovalQueue.objects.create(
            code='APV-MINHA-AREA',
            name='Aprovações da Minha Área',
            module=WorkflowNotification.SourceModule.QUALITY,
            profile_role='quality',
        )
        self.requirement = TrainingRequirement.objects.create(
            code='TR-MINHA-AREA',
            title='Boas práticas de fabricação',
            training_type=TrainingRequirement.TrainingType.REGULATORY,
            area='Garantia da qualidade',
            regulatory_requirement_reference='RDC 658/2022',
        )

    def create_records_for(self, user, suffix):
        approval = ApprovalTask.objects.create(
            queue=self.queue,
            title=f'Aprovação {suffix}',
            source_module=WorkflowNotification.SourceModule.QUALITY,
            source_model='QualityEvent',
            source_record_id=f'DEV-{suffix}',
            assigned_to=user,
            due_at=timezone.now() + timedelta(days=1),
        )
        notification = WorkflowNotification.objects.create(
            category=WorkflowNotification.Category.ALERT,
            recipient=user,
            title=f'Notificação {suffix}',
            message='Mensagem operacional individual.',
            source_module=WorkflowNotification.SourceModule.QUALITY,
            due_at=timezone.now() + timedelta(days=2),
        )
        deviation = QualityEvent.objects.create(
            event_type=QualityEvent.EventType.DEVIATION,
            origin=QualityEvent.Origin.MANUAL,
            area='Garantia da qualidade',
            severity=QualityEvent.Severity.MEDIUM,
            criticality=QualityEvent.Criticality.MAJOR,
            description=f'Desvio sob responsabilidade {suffix}.',
            detected_at=timezone.now(),
            responsible=user,
            opened_by=user,
        )
        capa = CapaRecord.objects.create(
            source_type=CapaRecord.SourceType.IMPROVEMENT,
            source_reference=f'MELHORIA-{suffix}',
            title=f'CAPA {suffix}',
            root_cause='Causa raiz confirmada.',
            action_plan='Executar ações e verificar a eficácia.',
            owner=user,
            due_date=timezone.localdate() + timedelta(days=3),
            effectiveness_criteria='Ausência de recorrência.',
            opened_by=user,
        )
        enrollment = TrainingEnrollment.objects.create(
            requirement=self.requirement,
            user=user,
            due_date=timezone.localdate() + timedelta(days=4),
        )
        return {
            'approvals': approval,
            'notifications': notification,
            'deviations': deviation,
            'capas': capa,
            'training': enrollment,
        }

    def test_returns_only_records_explicitly_assigned_to_request_user(self):
        for model in PERSONAL_AREA_MODELS:
            grant_view_permission(self.user, model)
        own_records = self.create_records_for(self.user, 'PRÓPRIO')
        foreign_records = self.create_records_for(self.other_user, 'TERCEIRO')

        sections = {section.key: section for section in build_personal_area(self.request)}

        self.assertEqual(set(sections), set(own_records))
        for key, own_record in own_records.items():
            with self.subTest(section=key):
                identifiers = {item.identifier for item in sections[key].items}
                self.assertIn(own_record.pk, identifiers)
                self.assertNotIn(foreign_records[key].pk, identifiers)

    def test_omits_section_and_query_when_model_view_permission_is_missing(self):
        grant_view_permission(self.user, ApprovalTask)
        self.create_records_for(self.user, 'RESTRITO')

        with CaptureQueriesContext(connection) as queries:
            sections = build_personal_area(self.request)

        self.assertEqual(tuple(section.key for section in sections), ('approvals',))
        sql = '\n'.join(query['sql'].lower() for query in queries)
        self.assertIn(ApprovalTask._meta.db_table.lower(), sql)
        for model in PERSONAL_AREA_MODELS[1:]:
            with self.subTest(model=model.__name__):
                self.assertNotIn(model._meta.db_table.lower(), sql)

    def test_permitted_empty_section_exposes_pt_br_empty_state(self):
        grant_view_permission(self.user, CapaRecord)

        sections = build_personal_area(self.request)

        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0].key, 'capas')
        self.assertEqual(sections[0].items, ())
        self.assertEqual(
            sections[0].empty_message,
            'Nenhuma CAPA sob sua responsabilidade.',
        )


class PersonalAreaViewTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='pagina-minha-area@example.com',
            email='pagina-minha-area@example.com',
            password='MinhaAreaSecure!123',
        )

    def test_requires_authentication(self):
        response = self.client.get(reverse('app:personal_area'))

        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('accounts:login'), response.url)

    def test_renders_pt_br_empty_state_for_permitted_section(self):
        grant_view_permission(self.user, CapaRecord)
        self.client.force_login(self.user)

        response = self.client.get(reverse('app:personal_area'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'app/personal_area.html')
        self.assertContains(response, 'Minha área')
        self.assertContains(response, 'Pendências e atividades sob sua responsabilidade')
        self.assertContains(response, 'Nenhuma CAPA sob sua responsabilidade.')
        self.assertContains(response, '<h2 id="personal-area-capas-heading"', html=False)

    def test_without_queue_permissions_does_not_claim_all_work_is_complete(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('app:personal_area'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Nenhuma fila pessoal disponível')
        self.assertNotContains(
            response, 'Todas as suas tarefas operacionais e aprovações estão em dia.'
        )

    def test_page_does_not_render_another_users_record(self):
        grant_view_permission(self.user, CapaRecord)
        own_capa = CapaRecord.objects.create(
            source_type=CapaRecord.SourceType.IMPROVEMENT,
            source_reference='MELHORIA-PESSOAL',
            title='CAPA pessoal autorizada',
            root_cause='Causa raiz confirmada.',
            action_plan='Executar o plano aprovado.',
            owner=self.user,
            due_date=timezone.localdate() + timedelta(days=5),
            effectiveness_criteria='Ausência de recorrência.',
        )
        other_user = get_user_model().objects.create_user(
            username='pagina-outra-area@example.com',
            email='pagina-outra-area@example.com',
            password='MinhaAreaSecure!123',
        )
        CapaRecord.objects.create(
            source_type=CapaRecord.SourceType.IMPROVEMENT,
            source_reference='MELHORIA-SIGILOSA',
            title='CAPA sigilosa de outra pessoa',
            root_cause='Causa raiz de outro escopo.',
            action_plan='Plano restrito.',
            owner=other_user,
            due_date=timezone.localdate() + timedelta(days=7),
            effectiveness_criteria='Critério restrito.',
        )
        self.client.force_login(self.user)

        response = self.client.get(reverse('app:personal_area'))

        self.assertContains(response, own_capa.title)
        self.assertNotContains(response, 'CAPA sigilosa de outra pessoa')

    def test_sidebar_marks_personal_area_as_current_page(self):
        self.client.force_login(self.user)

        response = self.client.get(reverse('app:personal_area'))
        navigation = response.content.decode().split('</nav>', 1)[0]

        self.assertIn('aria-label="Minha área"', navigation)
        self.assertIn('aria-current="page"', navigation)

    def test_template_uses_responsive_accessible_contract(self):
        template = Path('templates/app/personal_area.html').read_text()

        self.assertEqual(template.count('<h1'), 1)
        self.assertIn('aria-labelledby="personal-area-heading"', template)
        self.assertIn('class="col-12 col-xl-6"', template)
        self.assertIn('{% empty %}', template)

    def test_activity_copy_shrinks_without_pushing_status_outside_the_card(self):
        template = Path('templates/app/personal_area.html').read_text()

        self.assertIn('class="flex-grow-1 overflow-hidden"', template)
        self.assertIn('title="{{ item.title }}"', template)
