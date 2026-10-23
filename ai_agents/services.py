import json
import warnings
from typing import Any

from django.conf import settings
from typing_extensions import TypedDict


class AgentGraphState(TypedDict, total=False):
    run_id: int
    agent_code: str
    agent_type: str
    source_module: str
    source_model: str
    source_record_id: str
    system_prompt: str
    prompt_text: str
    model_name: str
    provider: str
    configuration: dict[str, Any]
    input_payload: dict[str, Any]
    raw_output: str
    output_payload: dict[str, Any]
    output_text: str
    suggestions: list[dict[str, Any]]
    graph_engine: str


def run_ai_agent_graph(run):
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='.*allowed_objects.*', category=Warning)
        from langgraph.graph import END, START, StateGraph

    builder = StateGraph(AgentGraphState)
    builder.add_node('prepare_prompt', _prepare_prompt)
    builder.add_node('invoke_model', _invoke_model)
    builder.add_node('parse_output', _parse_output)
    builder.add_edge(START, 'prepare_prompt')
    builder.add_edge('prepare_prompt', 'invoke_model')
    builder.add_edge('invoke_model', 'parse_output')
    builder.add_edge('parse_output', END)
    graph = builder.compile()
    state = graph.invoke(
        {
            'run_id': run.pk,
            'agent_code': run.agent.code,
            'agent_type': run.agent.agent_type,
            'source_module': run.source_module,
            'source_model': run.source_model,
            'source_record_id': run.source_record_id,
            'system_prompt': run.agent.system_prompt,
            'prompt_text': run.prompt_text,
            'model_name': run.model_name,
            'provider': run.agent.provider,
            'configuration': run.agent.configuration or {},
            'input_payload': run.input_payload or {},
        }
    )
    return {
        'graph_engine': state.get('graph_engine', 'langgraph'),
        'output_payload': state.get('output_payload') or {},
        'output_text': state.get('output_text') or '',
        'suggestions': state.get('suggestions') or [],
    }


def _prepare_prompt(state: AgentGraphState) -> AgentGraphState:
    return {
        'prompt_text': state['prompt_text'],
        'graph_engine': 'langgraph',
    }


def _invoke_model(state: AgentGraphState) -> AgentGraphState:
    if _should_use_local(state):
        return {'raw_output': json.dumps(_local_structured_output(state), ensure_ascii=False)}
    return _invoke_external_model(state)


def _invoke_external_model(state: AgentGraphState) -> AgentGraphState:
    from langchain_core.messages import HumanMessage, SystemMessage
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(model=state['model_name'], temperature=0)
    response = model.invoke(
        [
            SystemMessage(content=state['system_prompt']),
            HumanMessage(content=_json_contract_prompt(state)),
        ]
    )
    return {'raw_output': getattr(response, 'content', str(response))}


def _parse_output(state: AgentGraphState) -> AgentGraphState:
    raw_output = state.get('raw_output') or '{}'
    try:
        parsed = json.loads(raw_output)
    except json.JSONDecodeError:
        parsed = {
            'summary': raw_output,
            'classification': 'requires_review',
            'suggestions': [],
        }
    suggestions = parsed.get('suggestions') if isinstance(parsed.get('suggestions'), list) else []
    output_payload = {
        'summary': parsed.get('summary', ''),
        'classification': parsed.get('classification', 'requires_review'),
        'insights': parsed.get('insights', []),
        'risks': parsed.get('risks', []),
        'warnings': parsed.get('warnings', []),
        'engine': 'langgraph',
        'provider': state.get('provider'),
        'model_name': state.get('model_name'),
    }
    output_text = parsed.get('summary') or raw_output
    return {
        'output_payload': output_payload,
        'output_text': output_text,
        'suggestions': suggestions,
        'graph_engine': 'langgraph',
    }


def _should_use_local(state: AgentGraphState):
    configuration = state.get('configuration') or {}
    if configuration.get('force_local') is True:
        return True
    if state.get('provider') == 'local':
        return True
    return not bool(getattr(settings, 'OPENAI_API_KEY', ''))


def _json_contract_prompt(state: AgentGraphState):
    return (
        'Responda exclusivamente em JSON com as chaves summary, classification, '
        'insights, risks e suggestions. Cada suggestion deve conter '
        'suggestion_type, title, description e confidence.\n\n'
        f'Prompt: {state["prompt_text"]}'
    )


def _local_structured_output(state: AgentGraphState):
    payload = state.get('input_payload') or {}
    title = payload.get('title') or payload.get('code') or state.get('source_record_id')
    content = payload.get('content') or payload.get('description') or payload.get('text') or ''
    summary = _compact_text(
        f'Análise de {state.get("source_module")} para {title}: {content}',
        limit=420,
    )
    suggestions = [
        {
            'suggestion_type': 'root_cause',
            'title': 'Revisar causa raiz',
            'description': 'Validar se a causa raiz está suportada por evidências e dados do registro.',
            'confidence': '0.76',
        },
        {
            'suggestion_type': 'action',
            'title': 'Definir ação controlada',
            'description': 'Avaliar ação corretiva/preventiva com responsável, prazo e evidência objetiva.',
            'confidence': '0.74',
        },
        {
            'suggestion_type': 'attention',
            'title': 'Checar dados críticos',
            'description': 'Confirmar integridade ALCOA+ dos campos críticos antes de decisão final.',
            'confidence': '0.72',
        },
        {
            'suggestion_type': 'risk',
            'title': 'Avaliar risco residual',
            'description': 'Revisar impacto em lote, paciente, processo, fornecedor e obrigações regulatórias.',
            'confidence': '0.70',
        },
        {
            'suggestion_type': 'inconsistency',
            'title': 'Procurar inconsistências',
            'description': 'Comparar descrição, classificação, evidências e conclusão antes da aprovação humana.',
            'confidence': '0.68',
        },
    ]
    return {
        'summary': summary,
        'classification': _classification_for(state.get('agent_type')),
        'insights': [
            'Priorizar registros com impacto regulatório, qualidade ou segurança.',
            'Manter decisão humana documentada antes de aplicar qualquer sugestão.',
        ],
        'risks': [
            'Uso de sugestão sem revisão humana.',
            'Entrada incompleta ou sem evidência objetiva.',
        ],
        'suggestions': suggestions,
    }


def _classification_for(agent_type):
    mapping = {
        'summary': 'summary_requires_review',
        'classification': 'classification_requires_review',
        'document_search': 'document_search_requires_review',
        'root_cause': 'root_cause_requires_review',
        'action_suggestion': 'action_requires_review',
        'risk_insight': 'risk_requires_review',
        'regulatory_review': 'regulatory_requires_review',
        'process_insight': 'process_requires_review',
    }
    return mapping.get(agent_type, 'requires_review')


def _compact_text(value, limit=420):
    text = ' '.join(str(value).split())
    if len(text) <= limit:
        return text
    return f'{text[: limit - 3]}...'


def run_workflow_gate_agent(
    source_module: str,
    source_model: str,
    record_id: str,
    input_payload: dict,
    agent_code: str | None = None,
) -> dict | None:
    """
    Executa agente de workflow gate para os módulos aplicáveis.
    Retorna None se nenhum agente compatível estiver ativo.
    """
    from ai_agents.models import AIAgentProfile

    query = AIAgentProfile.objects.filter(
        agent_type=AIAgentProfile.AgentType.WORKFLOW_GATE,
        source_module=source_module,
        is_active=True,
    )
    if agent_code:
        query = query.filter(code=agent_code)

    agent = query.first()
    if not agent:
        return None

    run = agent.create_run(
        source_module=source_module,
        source_model=source_model,
        source_record_id=record_id,
        input_payload=input_payload,
    )
    run.execute()

    threshold = float(agent.configuration.get('approval_threshold', 0.80))
    output = run.output_payload or {}

    # Try to extract confidence directly from output payload, defaulting to 1.0 if not found but has a positive classification
    confidence = float(output.get('confidence', 0.0))
    classification = output.get('classification', '')

    if confidence == 0.0:
        if classification in ['approved', 'aprovado', 'pass']:
            confidence = 1.0
        elif classification in ['rejected', 'rejeitado', 'fail']:
            confidence = 0.0

    approved = confidence >= threshold

    return {
        'approved': approved,
        'confidence': confidence,
        'suggestions': list(
            run.suggestions.values('title', 'description', 'confidence', 'suggestion_type')
        )
        if hasattr(run, 'suggestions')
        else [],
        'summary': output.get('summary', run.output_text),
    }
