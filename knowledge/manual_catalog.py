from pathlib import Path

from django.conf import settings

from base.ui.registry import get_modules
from knowledge.step_by_step_manual import get_step_by_step
from knowledge.models import content_hash


CORPUS_REVISION = 'manual-v2'


DOC_SLUGS = {'masters': 'master-data', 'ai_agents': 'ai-agents'}


def _manual_content(module):
    lines = [
        f'# Manual do módulo {module.label}',
        '',
        module.description,
        '',
        'Este módulo faz parte do manual de utilização do RGN Farma System.',
        'Use os caminhos de menu e as permissões abaixo para operar a funcionalidade.',
        '',
        '## Recursos',
    ]
    for resource in module.resources:
        permission = resource.permission_name(resource.view_permission_action)
        lines.extend(
            (
                f'### {resource.label}',
                f'- Caminho técnico: /app/{module.slug}/{resource.slug}/',
                f'- Permissão de consulta: {permission}',
                f'- Recursos somente leitura: {"sim" if resource.read_only else "não"}',
                f'- Campos exibidos: {", ".join(resource.list_display)}.',
            )
        )
        if resource.form_fields:
            lines.append(f'- Campos de cadastro: {", ".join(resource.form_fields)}.')
        if resource.inlines:
            lines.append(
                '- Itens relacionados: '
                + ', '.join(inline.key for inline in resource.inlines)
                + '.'
            )
        lines.append('')

    # Adicionar instruções passo-a-passo
    step_by_step = get_step_by_step(module.slug)
    if step_by_step:
        lines.append('## Instruções passo-a-passo')
        lines.append(step_by_step.strip())
        lines.append('')

    return '\n'.join(lines)


def manual_entries():
    architecture_root = Path(settings.BASE_DIR) / 'docs' / 'architecture'
    entries = []
    for module in get_modules():
        document_slug = DOC_SLUGS.get(module.slug, module.slug.replace('_', '-'))
        document_path = architecture_root / f'{document_slug}.md'
        parts = [_manual_content(module)]
        if document_path.is_file():
            parts.append(document_path.read_text(encoding='utf-8'))
        corpus_content = '\n\n'.join(parts)
        corpus_hash = content_hash(corpus_content)
        entries.append(
            {
                'code': f'RGN-ERP-MODULE-{module.slug.upper().replace("-", "_")}',
                'title': f'Manual do ERP - {module.label}',
                'source_type': 'system_manual',
                'publisher': 'RGN Farma System',
                'jurisdiction': 'BR',
                'version': f'{CORPUS_REVISION}-{corpus_hash[:16]}',
                'url': f'https://rgnfarmasystem.rgnsystems.com.br/app/{module.slug}/',
                'is_official': True,
                'chat_eligible': True,
                'manual_content': corpus_content,
                'metadata': {
                    'module_slug': module.slug,
                    'corpus': 'erp_manual',
                    'corpus_revision': CORPUS_REVISION,
                    'corpus_hash': corpus_hash,
                },
            }
        )
    return entries
