from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from capa.models import CapaAction, CapaRecord, EffectivenessCheck
from deviations.models import (
    DeviationApproval,
    DeviationEvidence,
    DeviationImpactAssessment,
    DeviationInvestigation,
    DeviationLink,
    QualityEvent,
)
from inventory.models import StockLot, StockQualityStatus
from masters.models import Product, UnitOfMeasure


class QualityEventCockpitUiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='qa-investigator',
            email='investigator@example.com',
            password='Password123!',
        )
        self.client.force_login(self.user)

        # Permissão base para visualizar o evento de qualidade
        view_event_perm = Permission.objects.get(
            content_type__app_label='deviations', codename='view_qualityevent'
        )
        self.user.user_permissions.add(view_event_perm)

        self.unit_un = UnitOfMeasure.objects.create(code='UN', name='Unidade', symbol='un')

        self.product = Product.objects.create(
            code='PA-SERUM-01',
            description='Sérum Facial Antioxidante Vitamina C',
            item_type=Product.ItemType.FINISHED_PRODUCT,
            unit=self.unit_un,
            status=Product.Status.APPROVED,
        )

        today = timezone.now().date()
        self.lot = StockLot.objects.create(
            product=self.product,
            lot_number='LOT-SRM-2026-01',
            quality_status=StockQualityStatus.QUARANTINE,
            manufacturing_date=today,
            expiry_date=today + timedelta(days=730),
        )

        self.event = QualityEvent.objects.create(
            event_type=QualityEvent.EventType.NONCONFORMITY,
            origin=QualityEvent.Origin.QUALITY_CONTROL,
            area='Controle Físico-Químico',
            product=self.product,
            stock_lot=self.lot,
            severity=QualityEvent.Severity.HIGH,
            criticality=QualityEvent.Criticality.MAJOR,
            status=QualityEvent.Status.UNDER_INVESTIGATION,
            description='Desvio de pH identificado no doseamento intermediário do granel.',
            detected_at=timezone.now(),
            responsible=self.user,
            opened_by=self.user,
        )

        self.cockpit_url = reverse('app:quality_event_cockpit', kwargs={'pk': self.event.pk})

    def test_anonymous_user_is_redirected_to_login(self):
        self.client.logout()
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/login/', response.url)

    def test_user_without_permission_receives_403(self):
        unauthorized_user = get_user_model().objects.create_user(
            username='user-no-perm',
            email='noperm@example.com',
            password='Password123!',
        )
        self.client.force_login(unauthorized_user)
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 403)

    def test_cockpit_renders_executive_kpis_and_identification(self):
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)

        # Título e Identificação ALCOA+
        self.assertContains(response, self.event.event_number)
        self.assertContains(response, 'Não conformidade')
        self.assertContains(response, 'Controle Físico-Químico')
        self.assertContains(response, 'PA-SERUM-01')
        self.assertContains(response, 'LOT-SRM-2026-01')
        self.assertContains(response, 'Desvio de pH identificado no doseamento intermediário')

        # Badges e KPIs
        self.assertContains(response, 'Em investigação')
        self.assertContains(response, 'Severidade: Alta')
        self.assertContains(response, 'Criticidade: Maior')
        self.assertContains(response, 'Classificação sanitária')
        self.assertContains(response, 'Investigação de causa raiz')
        self.assertContains(response, 'Avaliação de impacto 8D')
        self.assertContains(response, 'Plano CAPA e ações')

    def test_sod_evidence_tab_permissions(self):
        evidence = DeviationEvidence.objects.create(
            event=self.event,
            title='Laudo Analítico Fora de Especificação',
            file_reference='laudos/2026/dev-001-laudo.pdf',
            content_hash='a1b2c3d4e5f67890abcdef1234567890abcdef1234567890abcdef1234567890',
            uploaded_by=self.user,
            notes='Ensaio analítico duplicado confirmou resultado fora de especificação.',
        )

        # Sem permissão de evidência -> Alerta de Segregação de Deveres (SoD)
        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Segregação de deveres: você não possui permissão para visualizar as evidências')
        self.assertNotContains(response, 'Laudo Analítico Fora de Especificação')

        # Com permissão de evidência -> Tabela renderizada com hash ALCOA+
        perm = Permission.objects.get(
            content_type__app_label='deviations', codename='view_deviationevidence'
        )
        self.user.user_permissions.add(perm)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Laudo Analítico Fora de Especificação')
        self.assertContains(response, 'laudos/2026/dev-001-laudo.pdf')
        self.assertContains(response, 'a1b2c3d4e5f6')

    def test_sod_investigation_tab_permissions(self):
        investigation = DeviationInvestigation.objects.create(
            event=self.event,
            investigator=self.user,
            status=DeviationInvestigation.Status.OPEN,
            immediate_actions='Interrupção imediata do envasamento e segregação do lote.',
            containment_actions='Bloqueio físico do pallet no almoxarifado em quarentena.',
        )

        # Sem permissão -> Alerta SoD
        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Segregação de deveres: você não possui permissão para visualizar as investigações')

        # Com permissão -> Conteúdo renderizado
        perm = Permission.objects.get(
            content_type__app_label='deviations', codename='view_deviationinvestigation'
        )
        self.user.user_permissions.add(perm)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Interrupção imediata do envasamento')
        self.assertContains(response, 'Bloqueio físico do pallet')

    def test_sod_impact_tab_permissions(self):
        impact = DeviationImpactAssessment.objects.create(
            event=self.event,
            impacts_quality=True,
            impacts_safety=False,
            impacts_efficacy=True,
            impacts_regulatory=False,
            impacts_patient=False,
            impacts_inventory=True,
            impacts_cost=True,
            impacts_deadline=False,
            summary='Impacto na especificação físico-química do produto e retenção de estoque.',
            is_completed=False,
            assessed_by=self.user,
        )

        # Sem permissão -> Alerta SoD
        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Segregação de deveres: você não possui permissão para visualizar a avaliação de impacto')

        # Com permissão -> Matriz 8D renderizada
        perm = Permission.objects.get(
            content_type__app_label='deviations', codename='view_deviationimpactassessment'
        )
        self.user.user_permissions.add(perm)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Qualidade do produto')
        self.assertContains(response, 'Segurança sanitária')
        self.assertContains(response, 'Eficácia cosmética')
        self.assertContains(response, 'Assuntos regulatórios / ANVISA')
        self.assertContains(response, 'Impacto Crítico')
        self.assertContains(response, 'Sem impacto')
        self.assertContains(response, 'Impacto na especificação físico-química')

    def test_sod_capa_tab_permissions(self):
        capa = CapaRecord.objects.create(
            source_type=CapaRecord.SourceType.DEVIATION,
            deviation_event=self.event,
            title='Calibração e Ajuste do Medidor de pH',
            root_cause='Eletrodo descalibrado por desvio de temperatura do tampão padrão.',
            action_plan='Recalibração do eletrodo e revisão do POP de checagem diária.',
            owner=self.user,
            due_date=timezone.now().date() + timedelta(days=15),
            status=CapaRecord.Status.IN_PROGRESS,
        )
        action = CapaAction.objects.create(
            capa=capa,
            action_type=CapaAction.ActionType.CORRECTIVE,
            title='Substituição do eletrodo de pH',
            description='Instalar eletrodo novo calibrado com certificado RBC.',
            responsible=self.user,
            due_date=timezone.now().date() + timedelta(days=5),
            status=CapaAction.Status.PENDING,
        )

        # Sem permissão -> Alerta SoD
        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Segregação de deveres: você não possui permissão para visualizar os planos CAPA')

        # Com permissão de CAPA e Ações
        perm_capa = Permission.objects.get(
            content_type__app_label='capa', codename='view_caparecord'
        )
        perm_action = Permission.objects.get(
            content_type__app_label='capa', codename='view_capaaction'
        )
        self.user.user_permissions.add(perm_capa, perm_action)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Calibração e Ajuste do Medidor de pH')
        self.assertContains(response, 'Eletrodo descalibrado')
        self.assertContains(response, 'Substituição do eletrodo de pH')
        self.assertContains(response, 'Corretiva')

    def test_sod_approvals_and_closure_checklist(self):
        approval = DeviationApproval.objects.create(
            event=self.event,
            approver=self.user,
            role=DeviationApproval.Role.QA,
            required=True,
            decision=DeviationApproval.Decision.PENDING,
        )

        # Sem permissão -> Alerta SoD
        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Segregação de deveres: você não possui permissão para visualizar as aprovações')

        # Com permissão de aprovações
        perm_appr = Permission.objects.get(
            content_type__app_label='deviations', codename='view_deviationapproval'
        )
        self.user.user_permissions.add(perm_appr)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Garantia da Qualidade')
        self.assertContains(response, 'Obrigatória')
        self.assertContains(response, 'Pendente')

        # Checklist de Encerramento Regulatório exibido
        self.assertContains(response, 'Checklist para encerramento sanitário')
        self.assertContains(response, 'Investigação Concluída com Causa Raiz')
        self.assertContains(response, 'Avaliação de Impacto Regulatório Concluída')
        self.assertContains(response, 'Aprovações Multidisciplinares Obrigatórias')
        self.assertContains(response, 'Ações CAPA Concluídas')

    def test_closure_readiness_and_closed_event_display(self):
        # Conceder todas as permissões SoD
        for app_label, codename in [
            ('deviations', 'view_deviationinvestigation'),
            ('deviations', 'view_deviationimpactassessment'),
            ('deviations', 'view_deviationapproval'),
            ('deviations', 'change_qualityevent'),
            ('capa', 'view_caparecord'),
            ('capa', 'view_capaaction'),
        ]:
            perm = Permission.objects.get(content_type__app_label=app_label, codename=codename)
            self.user.user_permissions.add(perm)

        # 1. Criar investigação concluída
        inv = DeviationInvestigation.objects.create(
            event=self.event,
            investigator=self.user,
            status=DeviationInvestigation.Status.OPEN,
            immediate_actions='Ações imediatas adotadas.',
            containment_actions='Contenção realizada.',
        )
        inv.conclude(
            root_cause='Falha térmica no sensor de pH.',
            impact_conclusion='Sem impacto em outros lotes da mesma campanha.',
            conclusion='Lote reprovado tecnicamente e descartado conforme procedimento.',
            user=self.user,
        )

        # 2. Criar avaliação de impacto concluída
        impact = DeviationImpactAssessment.objects.create(
            event=self.event,
            impacts_quality=True,
            summary='Impacto restrito ao pH do lote.',
            is_completed=False,
            assessed_by=self.user,
        )
        impact.complete(user=self.user)

        # 3. Criar aprovação aprovada
        approval = DeviationApproval.objects.create(
            event=self.event,
            approver=self.user,
            role=DeviationApproval.Role.QA,
            required=True,
            decision=DeviationApproval.Decision.PENDING,
        )
        approval.approve(user=self.user, comments='Aprovado pela Garantia da Qualidade.')

        # 4. CAPA com ação concluída
        capa = CapaRecord.objects.create(
            source_type=CapaRecord.SourceType.DEVIATION,
            deviation_event=self.event,
            title='Calibração e Ajuste do Medidor de pH',
            root_cause='Sensor de pH defeituoso.',
            action_plan='Substituição do sensor.',
            owner=self.user,
            due_date=timezone.now().date() + timedelta(days=10),
            status=CapaRecord.Status.IN_PROGRESS,
            requires_effectiveness_check=False,
        )
        action = CapaAction.objects.create(
            capa=capa,
            action_type=CapaAction.ActionType.CORRECTIVE,
            title='Instalar novo sensor',
            description='Novo sensor instalado.',
            responsible=self.user,
            due_date=timezone.now().date(),
            status=CapaAction.Status.PENDING,
            evidence_required=False,
        )
        action.complete(user=self.user, completion_notes='Sensor instalado com sucesso.')

        # Todos os critérios atendidos -> Mensagem de aptidão para encerramento
        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Todos os critérios regulatórios foram satisfeitos')
        self.assertContains(response, 'Encerrar evento de qualidade')

        # Agora encerramos o evento formalmente
        self.event.close(summary='Evento encerrado após conclusão de ações corretivas.', user=self.user)

        response = self.client.get(self.cockpit_url)
        self.assertContains(response, 'Evento formalmente encerrado')
        self.assertContains(response, 'Evento encerrado após conclusão de ações corretivas.')

    def test_resource_detail_view_contains_cockpit_button(self):
        detail_url = reverse(
            'app:resource_detail',
            kwargs={'module_slug': 'deviations', 'resource_slug': 'events', 'pk': self.event.pk},
        )
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Cockpit do evento / CAPA')
        self.assertContains(response, self.cockpit_url)
