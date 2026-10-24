from pathlib import Path
from html.parser import HTMLParser
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]
PAGE_HEADER_TEMPLATES = sorted(
    path.relative_to(ROOT / 'templates').as_posix()
    for path in (ROOT / 'templates').rglob('*.html')
    if 'class="page-header-title"' in path.read_text()
)


@pytest.mark.parametrize('template', PAGE_HEADER_TEMPLATES)
def test_page_heading_does_not_render_descriptive_subtitle(template):
    source = (ROOT / 'templates' / template).read_text()
    title = re.search(r'<div class="page-header-title">(.*?)</div>', source, re.S)
    assert title is not None
    assert not re.search(r'<p\b', title.group(1))


@pytest.mark.parametrize(('size', 'height', 'width'), [('lg', 40, 120), ('sm', 36, 48)])
def test_application_brand_logo_uses_compact_css_without_inline_override(size, height, width):
    source = (ROOT / 'templates/base.html').read_text()
    image = re.search(rf'<img\b[^>]*class="logo logo-{size} app-brand-logo"[^>]*>', source)
    assert image is not None
    assert 'style=' not in image.group(0)
    css = (ROOT / 'static/css/app.css').read_text()
    selector = f'.nxl-navigation .m-header .b-brand .logo.logo-{size}.app-brand-logo'
    rule = re.search(re.escape(selector) + r'\s*\{([^}]+)\}', css)
    assert rule is not None
    assert f'max-height: {height}px !important;' in rule.group(1)
    assert f'max-width: {width}px !important;' in rule.group(1)


@pytest.mark.parametrize('template', PAGE_HEADER_TEMPLATES)
def test_breadcrumb_precedes_the_current_page_heading_in_dom_order(template):
    source = (ROOT / 'templates' / template).read_text()
    assert source.index('class="breadcrumb') < source.index('class="page-header-title"')


def test_page_heading_stacks_breadcrumb_and_title_without_shell_overrides():
    css = (ROOT / 'static/css/app.css').read_text()
    rule = re.search(r'(?m)^\.page-header \.page-header-left\s*\{([^}]+)\}', css)
    assert rule is not None
    assert 'flex-direction: column;' in rule.group(1)
    assert 'flex: 1 1 auto;' in rule.group(1)
    assert 'align-items: flex-start !important;' in rule.group(1)
    breadcrumb = re.search(r'(?m)^\.page-header \.breadcrumb\s*\{([^}]+)\}', css)
    assert breadcrumb is not None
    assert 'margin: 0 !important;' in breadcrumb.group(1)
    assert 'direction: ltr;' in breadcrumb.group(1)


def test_stacked_page_heading_removes_the_duralux_inline_separator():
    css = (ROOT / 'static/css/app.css').read_text()
    selector = '.page-header .page-header-left .page-header-title :is(h1, h5)'
    rule = re.search(re.escape(selector) + r'\s*\{([^}]+)\}', css)
    assert rule is not None
    assert 'border: 0;' in rule.group(1)
    assert 'padding: 0;' in rule.group(1)


class HeaderParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.depth = 0
        self.text = []
        self.headings = 0
        self.current_pages = 0
        self.links = []
        self.ids = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'div':
            if self.depth:
                self.depth += 1
            elif 'page-header' in attrs.get('class', '').split():
                self.depth = 1
        if self.depth:
            if attrs.get('id'):
                self.ids.append(attrs['id'])
            self.headings += tag == 'h1'
            self.current_pages += attrs.get('aria-current') == 'page'
            if tag == 'a':
                self.links.append(attrs.get('href'))

    def handle_endtag(self, tag):
        if self.depth and tag == 'div':
            self.depth -= 1

    def handle_data(self, data):
        if self.depth and data.strip():
            self.text.append(' '.join(data.split()))


def test_shared_compact_header_renders_current_page_once():
    from django.template.loader import render_to_string

    header = HeaderParser(
        render_to_string(
            'includes/page_header.html',
            {
                'compact': True,
                'page_title': 'Fluxo de trabalho',
                'breadcrumbs': [
                    {'label': 'Aplicativos', 'url': '/app/'},
                    {'label': 'Fluxo de trabalho'},
                ],
            },
        )
    )

    assert header.text == ['Aplicativos', 'Fluxo de trabalho']
    assert header.headings == 1
    assert header.current_pages == 1
    assert header.links == ['/app/']


@pytest.fixture
def render_header(settings):
    from django.template.loader import render_to_string

    settings.STORAGES = {
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
    return lambda template, context: HeaderParser(
        render_to_string(template, {'csrf_token': 'synthetic-template-token', **context})
    )


def test_workflow_workspace_uses_the_compact_shared_header(render_header):
    from base.ui.workspaces import get_workspace

    header = render_header('workspaces/workspace.html', {'workspace': get_workspace('workflow')})

    assert header.text == ['Aplicativos', 'Fluxo de trabalho']
    assert header.headings == 1
    assert header.current_pages == 1
    assert header.links == ['/app/']


def test_module_header_preserves_its_back_link_without_duplicate_ancestor(render_header):
    from base.ui.registry import get_module

    header = render_header(
        'app/module.html',
        {'module': get_module('workflow'), 'resources': []},
    )

    assert header.text == ['Aplicativos', 'Fluxo de trabalho', 'Voltar aos Aplicativos']
    assert header.links == ['/app/', '/app/']
    assert header.headings == 1
    assert header.current_pages == 1
    assert 'section-0' in header.ids


@pytest.mark.parametrize('can_add', [True, False])
def test_resource_list_header_keeps_ancestors_and_authorized_actions(render_header, can_add):
    from django.test import RequestFactory
    from django.urls import reverse

    from base.ui.registry import get_module, get_resource

    module = get_module('masters')
    resource = get_resource('masters', 'products')
    header = render_header(
        'app/resource_list.html',
        {
            'module': module,
            'resource': resource,
            'can_add': can_add,
            'request': RequestFactory().get('/app/masters/products/'),
        },
    )

    assert header.text[:3] == ['Aplicativos', module.label, resource.label]
    assert header.text.count(resource.label) == 1
    assert header.headings == 1
    assert header.current_pages == 1
    assert header.links[:2] == ['/app/', '/app/masters/']
    create_url = reverse('app:resource_create', args=['masters', 'products'])
    assert (create_url in header.links) is can_add
    assert ('Somente leitura' in header.text) is not can_add
    assert 'section-0' in header.ids


@pytest.mark.parametrize('surface', ['action', 'denied'])
def test_compact_state_headers_do_not_repeat_the_current_leaf(render_header, surface):
    from types import SimpleNamespace

    from base.ui.registry import get_module, get_resource

    if surface == 'denied':
        template, context = 'app/permission_denied.html', {}
        expected = ['Aplicativos', 'Acesso negado']
        links = ['/app/']
    else:
        module = get_module('workflow')
        resource = get_resource('workflow', 'tasks')
        template = 'app/resource_action_form.html'
        context = {
            'module': module,
            'resource': resource,
            'action': SimpleNamespace(label='Aprovar'),
        }
        expected = ['Aplicativos', module.label, resource.label, 'Aprovar']
        links = ['/app/', '/app/workflow/', '/app/workflow/tasks/']

    header = render_header(template, context)

    assert header.text == expected
    assert header.links == links
    assert header.headings == 1
    assert header.current_pages == 1
    assert 'section-0' in header.ids


def test_dashboard_header_preserves_the_selector_without_a_duplicate_title(render_header):
    config = {'title': 'Executivo', 'module': 'production'}
    header = render_header(
        'dashboards/hub.html',
        {
            'dashboard': config,
            'dashboard_slug': 'executive',
            'dashboard_options': {'executive': config},
        },
    )

    assert header.text == ['Painéis', 'Executivo', 'Selecionar dashboard', 'Executivo']
    assert header.headings == 1
    assert header.current_pages == 1
    assert 'dashboard-selector' in header.ids


@pytest.mark.parametrize('can_reuse', [True, False])
def test_formula_cockpit_keeps_identity_and_permission_gated_actions(render_header, can_reuse):
    from types import SimpleNamespace

    from base.ui.registry import get_module

    formula = SimpleNamespace(
        pk=42,
        code='MF-42',
        version=2,
        product=SimpleNamespace(pk=3, description='Creme cosmético'),
        batch_unit=SimpleNamespace(symbol='kg'),
    )
    module = get_module('formulations')
    header = render_header(
        'app/master_formula_cockpit.html',
        {'formula': formula, 'module': module, 'can_reuse': can_reuse},
    )

    expected = ['Aplicativos', module.label, 'MF-42 v2', 'Ciclo de abastecimento']
    if can_reuse:
        expected.append('Reaproveitar fórmula')
    assert header.text == expected + ['Voltar à fórmula']
    assert header.text.count('Ciclo de abastecimento') == 1
    assert header.headings == 1
    assert header.current_pages == 1
    assert header.links[:3] == ['/app/', '/app/formulations/', '/app/formulations/formulas/42/']
    assert header.links[-1] == '/app/formulations/formulas/42/'
    assert 'section-0' in header.ids


# The shared include renders a loop, so it has no fixed trail to inspect; the
# render-based tests above cover it.
STATIC_HEADER_TEMPLATES = [
    template for template in PAGE_HEADER_TEMPLATES if template != 'includes/page_header.html'
]


def _header_block(template):
    source = (ROOT / 'templates' / template).read_text()
    start = source.index('class="breadcrumb')
    end = source.index('</div>', source.index('class="page-header-title"'))
    return source[start:end]


def _crumb_labels(block):
    return [
        re.sub(r'<[^>]+>', '', item).strip()
        for item in re.findall(r'<li class="breadcrumb-item[^"]*">(.*?)</li>', block, re.S)
    ]


@pytest.mark.parametrize('template', STATIC_HEADER_TEMPLATES)
def test_breadcrumb_trail_never_repeats_a_name(template):
    labels = _crumb_labels(_header_block(template))
    assert len(labels) == len(set(labels)), f'Migalhas repetidas em {template}: {labels}'


@pytest.mark.parametrize('template', STATIC_HEADER_TEMPLATES)
def test_last_breadcrumb_is_an_ancestor_not_the_current_heading(template):
    """The trail carries ancestors; the heading names the current page once."""

    block = _header_block(template)
    labels = _crumb_labels(block)
    if not labels:
        return
    heading = re.search(r'<(h1|h5)\b[^>]*>(.*?)</\1>', block, re.S)
    assert heading is not None, template
    title = re.sub(r'<[^>]+>', '', heading.group(2)).strip()
    assert labels[-1] != title, (
        f'{template}: a última migalha "{labels[-1]}" repete o título da página.'
    )


@pytest.mark.parametrize('template', STATIC_HEADER_TEMPLATES)
def test_application_root_crumb_has_a_single_name(template):
    block = _header_block(template)
    for label in re.findall(r"""<a href="\{% url 'app:index' %\}">([^<]+)</a>""", block):
        assert label == 'Aplicativos', (
            f'{template}: /app/ aparece como "{label}"; use sempre "Aplicativos".'
        )

def test_no_template_renders_the_legacy_non_compact_page_heading():
    """O cabeçalho antigo (ul.breadcrumb + h5.m-b-10) perde a seta e amplia o título."""
    offenders = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / 'templates').rglob('*.html')
        if path.name != 'page_header.html'
        and ('class="page-header-title"' in (text := path.read_text()) or 'h5 class="m-b-10"' in text)
    )
    assert offenders == []


def test_every_page_heading_uses_the_compact_breadcrumb_structure():
    """A seta vem do separador de ol.breadcrumb; o título é o último item, em h1.fs-14."""
    for path in (ROOT / 'templates').rglob('*.html'):
        text = path.read_text()
        # base.html apenas declara o bloco; os includes compartilhados são a fonte.
        if 'class="page-header"' not in text or path.name == 'page_header.html':
            continue
        assert '<ol class="breadcrumb' in text, path
        assert 'breadcrumb-item active" aria-current="page"' in text, path
        assert 'h1 class="fs-14 fw-semibold mb-0 d-inline"' in text, path
