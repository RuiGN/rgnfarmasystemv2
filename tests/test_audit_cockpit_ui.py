from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from audits.models import (
    AuditChecklistItem,
    AuditEvidence,
    AuditFinding,
    AuditFindingLink,
    AuditFollowUpAction,
    AuditPlan,
    AuditProgram,
    AuditReport,
)
from auxiliary.models import BusinessArea
from capa.models import CapaRecord
from masters.models import BusinessPartner


class AuditCockpitUiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username='lead-auditor-qa',
            email='lead.auditor@example.com',
            password='Password123!',
            first_name='Mariana',
            last_name='Oliveira',
        )
        self.client.force_login(self.user)

        # Permissão base para visualizar planos de auditoria
        view_audit_perm = Permission.objects.get(
            content_type__app_label='audits', codename='view_auditplan'
        )
        self.user.user_permissions.add(view_audit_perm)

        # Fornecedor auditado (BusinessPartner)
        self.supplier = BusinessPartner.objects.create(
            code='FOR-088',
            legal_name='Química Fina Cosméticos e Insumos do Brasil Ltda',
            trade_name='Química Fina Cosméticos',
            document='44.555.666/0001-77',
            partner_type=BusinessPartner.PartnerType.SUPPLIER,
        )

        # Área de negócio normalizada
        self.area = BusinessArea.objects.create(name='Garantia da Qualidade', code='QA')

        # Programa Anual de Auditorias
        now = timezone.now()
        self.program = AuditProgram.objects.create(
            program_number='AUDPRG-2026-001',
            audit_type=AuditProgram.AuditType.SUPPLIER,
            title='Programa Anual de Qualificação Sanitária de Fornecedores 2026',
            year=2026,
            scope='Auditorias de Boas Práticas em fabricantes de matérias-primas e fragrâncias.',
            criteria='RDC ANVISA nº 48/2013 e ABNT NBR ISO 22716.',
            owner=self.user,
            starts_on=timezone.localdate().replace(month=1, day=1),
            ends_on=timezone.localdate().replace(month=12, day=31),
            status=AuditProgram.Status.ACTIVE,
        )

        # Plano de Auditoria em fase de Relatório (REPORTING)
        self.audit = AuditPlan.objects.create(
            audit_number='AUD-2026-0001',
            program=self.program,
            audit_type=AuditPlan.AuditType.SUPPLIER,
            supplier=self.supplier,
            title='Auditoria BPF de Fornecedor de Matéria-Prima Ativa',
            scope='Avaliação de conformidade com as Boas Práticas de Fabricação de insumos cosméticos e integridade de dados ALCOA+.',
            criteria='RDC ANVISA nº 48/2013 e ABNT NBR ISO 22716:2008.',
            agenda='09:00 - Reunião de Abertura\n10:00 - Inspeção da Planta Fabril e QC\n15:00 - Avaliação da Trilha de Auditoria\n16:30 - Reunião de Encerramento',
            lead_auditor=self.user,
            auditee_name='Química Fina Cosméticos Ltda',
            area='Garantia da Qualidade',
            area_ref=self.area,
            venue_street='Avenida Industrial Farmacêutica',
            venue_street_number='1500',
            venue_complement='Bloco B',
            venue_neighborhood='Distrito Industrial',
            venue_zipcode='13000-000',
            scheduled_start=now - timedelta(days=5),
            scheduled_end=now - timedelta(days=4),
            actual_start=now - timedelta(days=5),
            actual_end=now - timedelta(days=4),
            status=AuditPlan.Status.REPORTING,
            submitted_by=self.user,
            submitted_at=now - timedelta(days=10),
            started_by=self.user,
            completed_by=self.user,
        )

        # Itens de Checklist (1 Conforme, 1 Não Conforme)
        self.item_conform = AuditChecklistItem.objects.create(
            audit=self.audit,
            section='1. Sistema de Gestão da Qualidade',
            question='Existe procedimento operacional padrão vigente para controle de mudanças e qualificação de fornecedores?',
            requirement_reference='RDC ANVISA nº 48/2013 Art. 8º e ISO 22716 Seção 3',
            required=True,
            status=AuditChecklistItem.Status.CONFORM,
            answer_text='Procedimento SOP-QA-012 vigente, revisado e com evidências de aplicação registradas.',
            answered_by=self.user,
            answered_at=now - timedelta(days=5),
        )

        self.item_non_conform = AuditChecklistItem.objects.create(
            audit=self.audit,
            section='2. Controle de Qualidade & Laboratório',
            question='Os certificados de análise são emitidos com rastreabilidade analítica e aprovação formal antes da liberação?',
            requirement_reference='RDC ANVISA nº 48/2013 Art. 25 e ISO 22716 Seção 9',
            required=True,
            status=AuditChecklistItem.Status.NON_CONFORM,
            answer_text='Identificada liberação do lote QC-887 sem ensaio microbiológico obrigatório de contraprova.',
            answered_by=self.user,
            answered_at=now - timedelta(days=5),
        )

        # Achado de Auditoria (Finding) Maior
        self.finding = AuditFinding.objects.create(
            audit=self.audit,
            checklist_item=self.item_non_conform,
            classification=AuditFinding.Classification.NONCONFORMITY,
            criticality=AuditFinding.Criticality.MAJOR,
            title='Ausência de contraprova analítica microbiológica em lote de matéria-prima',
            description='Constatada a expedição do lote QC-887 sem a realização completa do ensaio microbiológico previsto na especificação técnica.',
            responsible=self.user,
            due_date=timezone.localdate() + timedelta(days=30),
            status=AuditFinding.Status.OPEN,
        )

        # Evidência Documental com Hash ALCOA+
        self.evidence = AuditEvidence.objects.create(
            audit=self.audit,
            finding=self.finding,
            title='Boletim de Análise Parcial Lote QC-887',
            file_reference='evidencias/auditorias/laudo_parcial_qc887.pdf',
            content_hash='e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855',
            uploaded_by=self.user,
            notes='Fotocópia do laudo com carimbo provisório sem assinatura do Responsável Técnico.',
        )

        # Ação Corretiva Concluída com Evidência Obrigatória
        self.action = AuditFollowUpAction.objects.create(
            finding=self.finding,
            title='Revisão do protocolo analítico e reanálise do lote de insumo',
            description='Executar ensaio microbiológico em duplicata e implementar trava sistêmica no ERP do fornecedor.',
            responsible=self.user,
            due_date=timezone.localdate() + timedelta(days=15),
            mandatory=True,
            evidence_required=True,
            status=AuditFollowUpAction.Status.COMPLETED,
            completion_notes='Ensaio microbiológico de contraprova executado com resultado aprovado; especificação atualizada no ERP.',
            evidence_reference='acoes/laudo_microbiologico_reanalise_qc887.pdf',
            content_hash='b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9',
            completed_by=self.user,
            completed_at=now - timedelta(days=1),
        )

        # CAPA e Vínculo Transversal
        self.capa = CapaRecord.objects.create(
            capa_number='CAPA-2026-0042',
            source_type=CapaRecord.SourceType.AUDIT,
            source_reference=self.audit.audit_number,
            title='Ação Preventiva para Protocolos Analíticos de Insumos Fornecidos',
            root_cause='Falta de checagem cruzada de testes laboratoriais antes da expedição.',
            action_plan='Atualização do procedimento operacional e parametrização de bloqueio no sistema de gestão.',
            owner=self.user,
            due_date=timezone.localdate() + timedelta(days=60),
            status=CapaRecord.Status.IN_PROGRESS,
        )

        self.finding_link = AuditFindingLink.objects.create(
            finding=self.finding,
            link_type=AuditFindingLink.LinkType.CAPA,
            capa=self.capa,
            reference_code='CAPA-2026-0042',
        )

        # Relatório Final Emitido
        self.report = AuditReport.objects.create(
            audit=self.audit,
            executive_summary='Auditoria sanitária de fornecedor realizada com foco no cumprimento das BPF e confiabilidade metrológica.',
            conclusion='Fornecedor aprovado com ressalvas, condicionado ao encerramento e eficácia do plano CAPA registrado.',
            status=AuditReport.Status.ISSUED,
            issued_by=self.user,
            issued_at=now - timedelta(days=1),
        )
        self.report.calculate_indicators()
        self.report.save()

        # URL do Cockpit
        self.cockpit_url = reverse('app:audit_cockpit', kwargs={'pk': self.audit.pk})

    def _grant_all_permissions(self):
        perms = Permission.objects.filter(
            content_type__app_label__in=['audits', 'capa', 'deviations', 'changes', 'documents', 'masters']
        )
        self.user.user_permissions.add(*perms)

    def test_cockpit_requires_authentication(self):
        self.client.logout()
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login/', response.url)

    def test_cockpit_requires_view_permission(self):
        self.user.user_permissions.clear()
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 403)

    def test_cockpit_nonexistent_audit_returns_404(self):
        url = reverse('app:audit_cockpit', kwargs={'pk': 999999})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_full_cockpit_renders_all_5_tabs_and_kpis(self):
        self._grant_all_permissions()
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')

        # Cabeçalho Executivo
        self.assertIn('AUD-2026-0001', content)
        self.assertIn('Auditoria BPF de Fornecedor de Matéria-Prima Ativa', content)
        self.assertIn('AUDPRG-2026-001', content)
        self.assertIn('Química Fina Cosméticos Ltda', content)
        self.assertIn('FOR-088', content)
        self.assertIn('Mariana Oliveira', content)

        # 5 Abas do Cockpit
        self.assertIn('Escopo, Cronograma & Equipe Auditora', content)
        self.assertIn('Checklist de Verificação BPF / ISO 22716', content)
        self.assertIn('Constatações, Evidências & Não-Conformidades', content)
        self.assertIn('Planos de Ação, CAPAs & Vínculos Transversais', content)
        self.assertIn('Relatório Final, Conclusão & Gates de Prontidão', content)

        # KPIs Executivos
        self.assertIn('Ciclo da Auditoria', content)
        self.assertIn('Conformidade Global', content)
        self.assertIn('50,0%', content)
        self.assertIn('Achados & Apontamentos', content)
        self.assertIn('2/2', content)
        self.assertIn('Planos de Ação (CAPA)', content)
        self.assertIn('100,0%', content)

        # Conteúdo da Aba 1 (Escopo, Cronograma, Local)
        self.assertIn('Avenida Industrial Farmacêutica, 1500 (Bloco B) - Distrito Industrial', content)
        self.assertIn('Avaliação de conformidade com as Boas Práticas de Fabricação de insumos cosméticos', content)
        self.assertIn('RDC ANVISA nº 48/2013 e ABNT NBR ISO 22716:2008', content)
        self.assertIn('09:00 - Reunião de Abertura', content)

        # Conteúdo da Aba 2 (Checklist de Verificação)
        self.assertIn('1. Sistema de Gestão da Qualidade', content)
        self.assertIn('Existe procedimento operacional padrão vigente para controle de mudanças', content)
        self.assertIn('Procedimento SOP-QA-012 vigente, revisado', content)
        self.assertIn('2. Controle de Qualidade &amp; Laboratório', content)
        self.assertIn('Identificada liberação do lote QC-887 sem ensaio microbiológico', content)

        # Conteúdo da Aba 3 (Achados e Evidências ALCOA+)
        self.assertIn('Ausência de contraprova analítica microbiológica em lote de matéria-prima', content)
        self.assertIn('Não conformidade', content)
        self.assertIn('Maior', content)
        self.assertIn('Boletim de Análise Parcial Lote QC-887', content)
        self.assertIn('e3b0c44298fc1c14', content)

        # Conteúdo da Aba 4 (Ações de Follow-up e Vínculos CAPA)
        self.assertIn('Revisão do protocolo analítico e reanálise do lote de insumo', content)
        self.assertIn('Ensaio microbiológico de contraprova executado com resultado aprovado', content)
        self.assertIn('b94d27b9934d', content)
        self.assertIn('CAPA-2026-0042', content)
        self.assertIn('Ação Preventiva para Protocolos Analíticos de Insumos Fornecidos', content)

        # Conteúdo da Aba 5 (Scorecard dos 5 Gates e Relatório)
        self.assertIn('Scorecard de Prontidão e Governança da Auditoria', content)
        self.assertIn('Gate 1: Planejamento & Escopo', content)
        self.assertIn('Gate 2: Execução do Checklist', content)
        self.assertIn('Gate 3: Evidenciação ALCOA+', content)
        self.assertIn('Gate 4: Planos de Ação & CAPA', content)
        self.assertIn('Gate 5: Relatório & Conclusão', content)
        self.assertIn('Auditoria sanitária de fornecedor realizada com foco no cumprimento das BPF', content)
        self.assertIn('Fornecedor aprovado com ressalvas, condicionado ao encerramento e eficácia', content)
        self.assertIn('Apta para encerramento formal', content)

    def test_sod_checklist_tab_permission_segmented(self):
        # Usuário possui apenas permissão básica de auditoria, sem permissão de checklist
        self.user.user_permissions.clear()
        view_audit_perm = Permission.objects.get(
            content_type__app_label='audits', codename='view_auditplan'
        )
        self.user.user_permissions.add(view_audit_perm)

        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Você não possui permissão para visualizar o checklist de auditoria.', content)
        self.assertNotIn('Procedimento SOP-QA-012 vigente, revisado', content)

    def test_sod_findings_tab_permission_segmented(self):
        # Usuário sem permissão de achados ou evidências
        self.user.user_permissions.clear()
        view_audit_perm = Permission.objects.get(
            content_type__app_label='audits', codename='view_auditplan'
        )
        self.user.user_permissions.add(view_audit_perm)

        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Você não possui permissão para visualizar achados e evidências de auditoria.', content)
        self.assertNotIn('Boletim de Análise Parcial Lote QC-887', content)

    def test_sod_actions_tab_permission_segmented(self):
        # Usuário sem permissão de ações ou vínculos
        self.user.user_permissions.clear()
        view_audit_perm = Permission.objects.get(
            content_type__app_label='audits', codename='view_auditplan'
        )
        self.user.user_permissions.add(view_audit_perm)

        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Você não possui permissão para visualizar planos de ação e vínculos CAPA.', content)
        self.assertNotIn('Revisão do protocolo analítico e reanálise do lote de insumo', content)

    def test_sod_report_tab_permission_segmented(self):
        # Usuário sem permissão de relatório
        self.user.user_permissions.clear()
        view_audit_perm = Permission.objects.get(
            content_type__app_label='audits', codename='view_auditplan'
        )
        self.user.user_permissions.add(view_audit_perm)

        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Você não possui permissão para visualizar o relatório e conclusão da auditoria.', content)
        self.assertNotIn('Fornecedor aprovado com ressalvas, condicionado ao encerramento', content)

    def test_audit_5_gates_evaluation_reporting_vs_closed(self):
        self._grant_all_permissions()
        response = self.client.get(self.cockpit_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['gates_passed_count'], 5)
        self.assertTrue(response.context['gate1_passed'])
        self.assertTrue(response.context['gate2_passed'])
        self.assertTrue(response.context['gate3_passed'])
        self.assertTrue(response.context['gate4_passed'])
        self.assertTrue(response.context['gate5_passed'])
        self.assertEqual(response.context['regulatory_verdict'], 'Apta para encerramento formal')
        self.assertEqual(response.context['regulatory_verdict_badge'], 'bg-success')

        # Encerramento formal da auditoria
        self.audit.close(
            summary='Auditoria formalmente encerrada após parecer favorável do Comitê de Qualidade e conclusão das ações.',
            user=self.user,
        )

        response_closed = self.client.get(self.cockpit_url)
        self.assertEqual(response_closed.status_code, 200)
        self.assertEqual(response_closed.context['gates_passed_count'], 5)
        self.assertEqual(
            response_closed.context['regulatory_verdict'],
            'Auditoria concluída & Encerrada',
        )
        self.assertEqual(response_closed.context['regulatory_verdict_badge'], 'bg-success')

    def test_resource_detail_renders_cockpit_button(self):
        detail_url = reverse(
            'app:resource_detail',
            kwargs={
                'module_slug': 'audits',
                'resource_slug': 'plans',
                'pk': self.audit.pk,
            },
        )
        response = self.client.get(detail_url)
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('Cockpit da auditoria (360°)', content)
        self.assertIn(self.cockpit_url, content)
