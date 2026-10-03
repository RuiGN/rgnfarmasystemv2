from base.ui.actions.modules.ai_agents import ACTION_KEYS as ai_agents_keys
from base.ui.actions.modules.audits import ACTION_KEYS as audits_keys
from base.ui.actions.modules.capa import ACTION_KEYS as capa_keys
from base.ui.actions.modules.changes import ACTION_KEYS as changes_keys
from base.ui.actions.modules.compliance import ACTION_KEYS as compliance_keys
from base.ui.actions.modules.costing import ACTION_KEYS as costing_keys
from base.ui.actions.modules.crm import ACTION_KEYS as crm_keys
from base.ui.actions.modules.deviations import ACTION_KEYS as deviations_keys
from base.ui.actions.modules.documents import ACTION_KEYS as documents_keys
from base.ui.actions.modules.files import ACTION_KEYS as files_keys
from base.ui.actions.modules.finance import ACTION_KEYS as finance_keys
from base.ui.actions.modules.fiscal import ACTION_KEYS as fiscal_keys
from base.ui.actions.modules.governance import ACTION_KEYS as governance_keys
from base.ui.actions.modules.integrations import ACTION_KEYS as integrations_keys
from base.ui.actions.modules.inventory import ACTION_KEYS as inventory_keys
from base.ui.actions.modules.planning import ACTION_KEYS as planning_keys
from base.ui.actions.modules.procurement import ACTION_KEYS as procurement_keys
from base.ui.actions.modules.qa import ACTION_KEYS as qa_keys
from base.ui.actions.modules.quality import ACTION_KEYS as quality_keys
from base.ui.actions.modules.recalls import ACTION_KEYS as recalls_keys
from base.ui.actions.modules.reports import ACTION_KEYS as reports_keys
from base.ui.actions.modules.risks import ACTION_KEYS as risks_keys
from base.ui.actions.modules.training import ACTION_KEYS as training_keys
from base.ui.actions.modules.workflow import ACTION_KEYS as workflow_keys
from base.ui.actions.modules.production import PRODUCTION_ACTIONS


ACTION_KEYS = (
    *(('ai_agents', *key) for key in ai_agents_keys),
    *(('audits', *key) for key in audits_keys),
    *(('capa', *key) for key in capa_keys),
    *(('changes', *key) for key in changes_keys),
    *(('compliance', *key) for key in compliance_keys),
    *(('costing', *key) for key in costing_keys),
    *(('crm', *key) for key in crm_keys),
    *(('deviations', *key) for key in deviations_keys),
    *(('documents', *key) for key in documents_keys),
    *(('files', *key) for key in files_keys),
    *(('finance', *key) for key in finance_keys),
    *(('fiscal', *key) for key in fiscal_keys),
    *(('governance', *key) for key in governance_keys),
    *(('integrations', *key) for key in integrations_keys),
    *(('inventory', *key) for key in inventory_keys),
    *(('planning', *key) for key in planning_keys),
    *(('procurement', *key) for key in procurement_keys),
    *(('qa', *key) for key in qa_keys),
    *(('quality', *key) for key in quality_keys),
    *(('recalls', *key) for key in recalls_keys),
    *(('reports', *key) for key in reports_keys),
    *(('risks', *key) for key in risks_keys),
    *(('training', *key) for key in training_keys),
    *(('workflow', *key) for key in workflow_keys),
    *(
        (config.module_slug, config.resource_slug, config.action_name)
        for config in PRODUCTION_ACTIONS
    ),
)

__all__ = ('ACTION_KEYS', 'PRODUCTION_ACTIONS')
