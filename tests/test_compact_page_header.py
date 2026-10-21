from pathlib import Path
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
