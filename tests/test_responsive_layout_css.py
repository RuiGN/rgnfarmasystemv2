from pathlib import Path
import gzip
import json
import re

from django.conf import settings
from django.core.management import call_command
from django.test import override_settings


ROOT = Path(__file__).resolve().parents[1]


def test_mobile_navigation_toggle_has_an_accessible_pt_br_label():
    template = (ROOT / 'templates' / 'base.html').read_text()

    assert (
        'class="nxl-head-mobile-toggler" id="mobile-collapse" aria-label="Abrir menu de navegação"'
    ) in template


def test_advanced_filters_use_accessible_bootstrap_collapse_only_when_configured():
    template = (ROOT / 'templates' / 'app' / 'includes' / 'search_filters.html').read_text()

    assert '{% if advanced_filters %}' in template
    assert 'data-bs-toggle="collapse"' in template
    assert 'aria-controls="filtros-avancados"' in template
    assert 'aria-expanded=' in template
    assert 'Filtros avançados' in template
    assert '{{ active_filter_count }}' in template
    assert 'id="filtros-avancados"' in template


def test_detail_summary_uses_scoped_readable_layout_styles():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()
    template = (ROOT / 'templates' / 'app' / 'resource_detail.html').read_text()

    assert 'data-ui="detail-layout"' in template
    assert 'col-xl-8' in template
    assert 'col-xl-4' in template
    assert '.detail-summary__list' in css
    assert '.detail-summary__value { overflow-wrap: anywhere; }' in css


def test_app_css_does_not_override_duralux_mobile_shell_offsets():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()

    assert '@media (max-width: 960px)' not in css
    assert 'left: 80px !important;' not in css
    assert 'margin-left: 80px;' not in css
    assert 'left: 64px !important;' not in css
    assert 'margin-left: 64px;' not in css


def test_app_css_preserves_duralux_mobile_breakpoint_with_zero_shell_offset():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()

    assert '@media (max-width: 1024px)' in css
    assert '.nxl-header {\n        left: 0 !important;\n    }' in css
    assert '.nxl-container {\n        margin-left: 0;\n    }' in css


def test_app_css_does_not_override_duralux_main_content_shell_spacing():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()

    assert '.nxl-content {\n    padding:' not in css
    assert '.nxl-content {\n        padding:' not in css
    page_header_block = re.search(r'(?m)^\\.page-header\\s*\\{[^}]*\\}', css)
    assert page_header_block is None


def test_app_css_preserves_duralux_container_shell_height():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()

    container_block = re.search(r'(?m)^\.nxl-container\s*\{(?P<body>[^}]*)\}', css)
    assert container_block is not None
    assert re.search(r'margin-left:\s*280px', container_block.group('body'))
    assert 'min-height: 100vh' not in container_block.group('body')
    assert 'display: flex' not in container_block.group('body')
    assert 'flex-direction: column' not in container_block.group('body')
    assert '.nxl-container > .nxl-content' not in css
    assert '.nxl-container > .footer' not in css


def test_base_brand_logo_preserves_duralux_shell_dimensions_without_dark_filter():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()

    brand_block = re.search(
        r'(?m)^\.nxl-navigation\s+\.m-header\s+\.b-brand\s*\{(?P<body>[^}]*)\}',
        css,
    )
    assert brand_block is not None
    assert re.search(r'width:\s*100%', brand_block.group('body'))
    assert re.search(r'max-width:\s*232px', brand_block.group('body'))
    assert re.search(r'justify-content:\s*center', brand_block.group('body'))

    logo_lg_block = re.search(r'(?m)^\.b-brand\s+\.logo-lg\s*\{(?P<body>[^}]*)\}', css)
    assert logo_lg_block is not None
    assert re.search(r'max-height:\s*66px', logo_lg_block.group('body'))
    assert re.search(r'max-width:\s*232px', logo_lg_block.group('body'))
    assert re.search(r'width:\s*100%', logo_lg_block.group('body'))
    assert re.search(r'height:\s*auto', logo_lg_block.group('body'))
    assert 'width: 300px' not in logo_lg_block.group('body')
    assert 'height: 96px' not in logo_lg_block.group('body')

    logo_sm_block = re.search(r'(?m)^\.b-brand\s+\.logo-sm\s*\{(?P<body>[^}]*)\}', css)
    assert logo_sm_block is not None
    assert re.search(r'max-height:\s*54px', logo_sm_block.group('body'))
    assert re.search(r'max-width:\s*64px', logo_sm_block.group('body'))
    assert re.search(r'width:\s*100%', logo_sm_block.group('body'))
    assert re.search(r'height:\s*auto', logo_sm_block.group('body'))
    assert re.search(
        r'html\.app-skin-dark\s+\.nxl-navigation\s+\.m-header\s+\.app-brand-logo\s*\{'
        r'[^}]*filter:\s*none\s*!important',
        css,
        re.S,
    )


def test_rag_chat_component_styles_do_not_leak_into_duralux_resource_templates():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()

    unscoped_selectors = [
        line.strip()
        for line in css.splitlines()
        if '.rag-chat__' in line and '{' in line and not line.lstrip().startswith('.rag-chat ')
    ]
    assert unscoped_selectors == []


def test_rag_chat_toggle_remains_accessible_with_footer_in_document_flow():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()

    footer_block = re.search(r'(?m)^\.app-footer\s*\{(?P<body>[^}]*)\}', css)
    chat_block = re.search(
        r'(?m)^\.rag-chat \.rag-chat__toggle\s*\{(?P<body>[^}]*)\}',
        css,
    )
    mobile_block = re.search(
        r'@media \(max-width: 575\.98px\)\s*\{(?P<body>.*?)'
        r'(?=\n@media \(max-width: 360px\))',
        css,
        re.S,
    )

    assert footer_block is not None
    assert chat_block is not None
    assert mobile_block is not None

    chat_z_index = int(re.search(r'z-index:\s*(\d+)', chat_block.group('body')).group(1))

    assert chat_z_index > 0
    assert re.search(r'position:\s*static', footer_block.group('body'))
    assert 'z-index:' not in footer_block.group('body')
    assert re.search(r'bottom:\s*90px', chat_block.group('body'))
    assert re.search(
        r'\.rag-chat \.rag-chat__toggle\s*\{[^}]*bottom:\s*20px',
        mobile_block.group('body'),
        re.S,
    )


def test_duralux_feather_font_face_does_not_prefer_problematic_ttf_asset():
    css_paths = [
        ROOT / 'static' / 'vendor' / 'duralux' / 'css' / 'vendors.min.css',
        ROOT / 'staticfiles' / 'vendor' / 'duralux' / 'css' / 'vendors.min.css',
    ]

    for css_path in css_paths:
        if not css_path.exists():
            continue
        css = css_path.read_text()
        match = re.search(r'@font-face\{[^}]*font-family:feather[^}]*\}', css)

        assert match is not None, css_path
        font_face = match.group(0)
        assert 'feather.woff' in font_face, css_path
        assert 'feather.ttf' not in font_face, css_path
        assert 'feather.svg' not in font_face, css_path


def test_collected_static_includes_resource_actions_script(tmp_path):
    source = ROOT / 'static' / 'js' / 'resource-actions.js'
    collected_root = tmp_path / 'staticfiles'
    storage_config = {
        **settings.STORAGES,
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }

    assert source.exists()

    with override_settings(
        STATIC_ROOT=collected_root,
        STORAGES=storage_config,
    ):
        call_command(
            'collectstatic',
            interactive=False,
            clear=True,
            verbosity=0,
        )

    collected = collected_root / 'js' / 'resource-actions.js'
    assert collected.exists()
    assert collected.read_text() == source.read_text()


def test_duralux_css_files_do_not_reference_missing_source_maps():
    css_paths = [
        ROOT / root / 'vendor' / 'duralux' / 'css' / filename
        for root in ('static', 'staticfiles')
        for filename in ('bootstrap.min.css', 'theme.min.css', 'vendors.min.css')
    ]

    for css_path in css_paths:
        if not css_path.exists():
            continue
        css = css_path.read_text()
        assert 'sourceMappingURL=' not in css, css_path


def test_collected_duralux_compressed_css_matches_static_asset_policy():
    gzip_paths = [
        ROOT / 'staticfiles' / 'vendor' / 'duralux' / 'css' / filename
        for filename in (
            'bootstrap.min.css.gz',
            'theme.min.css.gz',
            'vendors.min.css.gz',
        )
    ]

    for gzip_path in gzip_paths:
        if not gzip_path.exists():
            continue
        with gzip.open(gzip_path, 'rt') as compressed:
            css = compressed.read()
        assert 'sourceMappingURL=' not in css, gzip_path
        assert 'feather.ttf' not in css, gzip_path
        assert 'feather.svg' not in css, gzip_path


def test_duralux_source_map_files_are_valid_json_when_present():
    map_paths = [
        path
        for root in ('static', 'staticfiles')
        for path in (ROOT / root / 'vendor' / 'duralux').rglob('*.map')
    ]

    for map_path in map_paths:
        content = map_path.read_text()
        assert content.strip(), map_path
        payload = json.loads(content)
        assert payload.get('version') == 3, map_path
        assert isinstance(payload.get('sources'), list), map_path
        assert isinstance(payload.get('names'), list), map_path
        assert isinstance(payload.get('mappings'), str), map_path


def test_resource_action_templates_use_duralux_components_instead_of_custom_visual_classes():
    sources = '\n'.join(
        (ROOT / path).read_text()
        for path in (
            'templates/app/includes/resource_actions.html',
            'templates/app/resource_action_form.html',
            'static/css/app.css',
        )
    )

    forbidden = (
        'domain-actions',
        'domain-actions__',
        ' domain-action ',
        'domain-action--',
        'action-form-card',
        'action-form-card__',
        'action-form__',
        'action-confirmation',
    )
    for token in forbidden:
        assert token not in sources


def test_app_css_does_not_keep_removed_platform_surface_styles():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()

    assert 'platform-' not in css
    assert 'support-session-banner' not in css


def test_core_app_navigation_templates_do_not_use_custom_card_or_table_skins():
    sources = '\n'.join(
        path.read_text() for path in sorted((ROOT / 'templates' / 'app').rglob('*.html'))
    )
    sources += '\n' + (ROOT / 'static' / 'css' / 'app.css').read_text()

    forbidden = (
        'module-card',
        'resource-card',
        'app-panel',
        'resource-table',
    )
    for token in forbidden:
        assert token not in sources


def test_dashboard_templates_use_bootstrap_duralux_layouts_instead_of_custom_grid_skins():
    sources = '\n'.join(
        path.read_text()
        for directory in ('dashboard', 'dashboards')
        for path in sorted((ROOT / 'templates' / directory).rglob('*.html'))
    )
    sources += '\n' + (ROOT / 'static' / 'css' / 'app.css').read_text()

    forbidden = (
        'dashboard-page-header',
        'dashboard-intro',
        'dashboard-kpi-grid',
        'dashboard-kpi-card',
        'dashboard-content-grid',
        'dashboard-grid',
        'dashboard-empty',
    )
    for token in forbidden:
        assert token not in sources


def test_login_brand_logo_is_isolated_from_generic_duralux_logo_class():
    template = (ROOT / 'templates' / 'registration' / 'login.html').read_text()
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()

    assert 'class="logo login-brand-logo"' not in template
    assert 'class="login-brand-logo"' in template
    assert re.search(
        r'(?m)^\.auth-brand\s+\.login-brand-logo\s*\{[^}]*max-width:\s*320px\s*!important'
        r'[^}]*height:\s*auto\s*!important',
        css,
        re.S,
    )


def test_cosmetics_login_styles_are_scoped_responsive_and_motion_safe():
    css_path = ROOT / 'static' / 'css' / 'auth.css'
    template = (ROOT / 'templates' / 'registration' / 'login.html').read_text()

    assert css_path.exists()
    css = css_path.read_text()
    assert "{% static 'css/auth.css' %}" in template
    assert '#08162b' in css.casefold()
    assert '#3454d1' in css.casefold()
    assert '#36d6d0' in css.casefold()
    assert '#f4f7fb' in css.casefold()
    assert '#283c50' in css.casefold()
    assert '#ffffff' in css.casefold()
    layout = re.search(
        r'(?m)^\.auth-page-shell \.auth-layout\s*\{(?P<body>[^}]*)\}',
        css,
    )
    assert layout is not None
    assert re.search(r'width:\s*100%', layout.group('body'))
    assert re.search(r'padding:\s*0', layout.group('body'))
    assert '@media (max-width: 991.98px)' in css
    assert re.search(
        r'@media \(max-width: 991\.98px\).*?\.auth-page-shell \.auth-story\s*\{'
        r'[^}]*display:\s*none',
        css,
        re.S,
    )
    assert '@media (max-height: 640px)' in css
    assert ':focus-visible' in css
    assert '@media (prefers-reduced-motion: reduce)' in css
    assert 'animation-duration: 0.01ms' in css
    assert 'animation-iteration-count: 1' in css
    assert 'transition-duration: 0.01ms' in css

    selectors = (
        line.strip().removesuffix('{').strip()
        for line in css.splitlines()
        if line.strip().endswith('{') and not line.strip().startswith('@')
    )
    assert all(
        selector.strip().startswith('.auth-page-shell')
        for selector_group in selectors
        for selector in selector_group.split(',')
    )


def test_minimenu_brand_header_collapses_with_duralux_sidebar_width():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()

    minimenu_header = re.search(
        r'(?m)^html\.minimenu\s+\.nxl-navigation\s+\.m-header\s*\{(?P<body>[^}]*)\}',
        css,
    )
    assert minimenu_header is not None
    assert re.search(r'width:\s*100px', minimenu_header.group('body'))
    assert re.search(r'justify-content:\s*center', minimenu_header.group('body'))

    minimenu_brand = re.search(
        r'(?m)^html\.minimenu\s+\.nxl-navigation\s+\.m-header\s+\.b-brand\s*\{(?P<body>[^}]*)\}',
        css,
    )
    assert minimenu_brand is not None
    assert re.search(r'max-width:\s*64px', minimenu_brand.group('body'))
    assert re.search(r'overflow:\s*hidden', minimenu_brand.group('body'))


def test_page_shells_push_the_global_footer_to_the_viewport_end():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()
    base = (ROOT / 'templates' / 'base.html').read_text()
    login = (ROOT / 'templates' / 'registration' / 'login.html').read_text()

    assert 'class="nxl-container app-shell"' in base
    assert '<body class="auth-page-shell">' in login
    assert 'min-vh-100' not in login

    authenticated_shell = re.search(
        r'(?m)^\.nxl-container\.app-shell\s*\{(?P<body>[^}]*)\}',
        css,
    )
    authenticated_content = re.search(
        r'(?m)^\.nxl-container\.app-shell\s*>\s*\.nxl-content\s*\{(?P<body>[^}]*)\}',
        css,
    )
    login_shell = re.search(
        r'(?m)^\.auth-page-shell\s*\{(?P<body>[^}]*)\}',
        css,
    )
    login_content = re.search(
        r'(?m)^\.auth-page-shell\s*>\s*\.auth-main\s*\{(?P<body>[^}]*)\}',
        css,
    )

    assert authenticated_shell is not None
    assert authenticated_content is not None
    assert login_shell is not None
    assert login_content is not None
    assert re.search(r'display:\s*flex', authenticated_shell.group('body'))
    assert re.search(r'flex-direction:\s*column', authenticated_shell.group('body'))
    assert re.search(
        r'min-height:\s*calc\(100dvh\s*-\s*80px\)',
        authenticated_shell.group('body'),
    )
    assert re.search(r'flex:\s*1\s+0\s+auto', authenticated_content.group('body'))
    assert re.search(r'display:\s*flex', login_shell.group('body'))
    assert re.search(r'flex-direction:\s*column', login_shell.group('body'))
    assert re.search(r'min-height:\s*100dvh', login_shell.group('body'))
    assert re.search(r'flex:\s*1\s+0\s+auto', login_content.group('body'))


def test_global_footer_stays_in_document_flow_without_covering_content():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()

    footer_block = re.search(r'(?m)^\.app-footer\s*\{(?P<body>[^}]*)\}', css)
    assert footer_block is not None
    footer_body = footer_block.group('body')
    assert re.search(r'position:\s*static', footer_body)
    assert re.search(r'flex:\s*0\s+0\s+auto', footer_body)
    assert not re.search(r'position:\s*fixed', footer_body)
    assert not re.search(r'(?:bottom|z-index):', footer_body)


def test_mobile_global_footer_stacks_its_metadata():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()
    mobile_block = re.search(
        r'@media \(max-width: 575\.98px\)\s*\{(?P<body>.*?)'
        r'(?=\n@media \(max-width: 360px\))',
        css,
        re.S,
    )

    assert mobile_block is not None
    assert re.search(
        r'\.app-footer\s*\{[^}]*flex-direction:\s*column',
        mobile_block.group('body'),
        re.S,
    )
    assert re.search(
        r'\.app-footer\s*\{[^}]*align-items:\s*flex-start',
        mobile_block.group('body'),
        re.S,
    )


def test_resource_detail_header_wraps_actions_below_title_at_tablet_width():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()
    template = (ROOT / 'templates' / 'app' / 'resource_detail.html').read_text()

    assert 'class="page-header resource-detail-page-header"' in template

    tablet_block = re.search(
        r'@media \(min-width: 768px\) and \(max-width: 991\.98px\)\s*\{'
        r'(?P<body>.*?)(?=\n@media|\Z)',
        css,
        re.S,
    )
    assert tablet_block is not None
    tablet_css = tablet_block.group('body')
    assert re.search(
        r'\.resource-detail-page-header\s*\{[^}]*flex-wrap:\s*wrap',
        tablet_css,
        re.S,
    )
    assert re.search(
        r'\.resource-detail-page-header \.page-header-left\s*\{[^}]*width:\s*100%',
        tablet_css,
        re.S,
    )
    assert re.search(
        r'\.resource-detail-page-header \.page-header-right\s*\{[^}]*width:\s*100%',
        tablet_css,
        re.S,
    )
    assert re.search(
        r'\.resource-detail-page-header \.page-header-right-items-wrapper\s*\{'
        r'[^}]*flex-wrap:\s*wrap',
        tablet_css,
        re.S,
    )


def test_resource_tables_contain_intrinsic_width_without_page_overflow():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()

    table_overflow_block = re.search(
        r'\[data-ui="resource-panel"\] \.table-responsive,\s*'
        r'\[data-ui="detail-layout"\] \.table-responsive\s*\{(?P<body>[^}]*)\}',
        css,
        re.S,
    )

    assert table_overflow_block is not None
    assert re.search(r'max-width:\s*100%', table_overflow_block.group('body'))
    assert re.search(r'overflow-x:\s*auto', table_overflow_block.group('body'))


def test_audit_trail_uses_intrinsic_height_inside_responsive_detail_column():
    audit_template = (ROOT / 'templates' / 'app' / 'includes' / 'audit_trail.html').read_text()
    detail_template = (ROOT / 'templates' / 'app' / 'resource_detail.html').read_text()

    opening_section = re.search(r'<section\s+class="([^"]+)"', audit_template)
    primary_section = re.search(
        r'<section\s+class="([^"]+)"\s+data-ui="detail-content">',
        detail_template,
    )

    assert opening_section is not None
    assert primary_section is not None
    assert 'stretch' not in opening_section.group(1).split()
    assert 'stretch-full' not in opening_section.group(1).split()
    assert 'stretch' not in primary_section.group(1).split()
    assert 'stretch-full' not in primary_section.group(1).split()


def test_resource_filters_and_pagination_use_bootstrap_duralux_controls():
    filters = (ROOT / 'templates' / 'app' / 'includes' / 'search_filters.html').read_text()
    pagination = (ROOT / 'templates' / 'app' / 'includes' / 'pagination.html').read_text()

    assert 'class="row g-3 align-items-end"' in filters
    assert 'col-md-3 col-xl-2' not in filters
    assert 'class="btn btn-light-brand"' not in filters
    assert 'class="btn btn-icon btn-light-brand"' in filters
    assert 'pagination pagination-separated' not in pagination
    assert (
        'class="list-unstyled d-flex align-items-center gap-2 mb-0 pagination-common-style"'
        in pagination
    )


def test_detail_profile_and_summary_keep_intrinsic_height_when_stacked():
    detail = (ROOT / 'templates/app/resource_detail.html').read_text()
    summary = (ROOT / 'templates/includes/components/detail_summary.html').read_text()
    layout = detail.split('data-ui="detail-layout"', 1)[1]
    profile = re.search(r'<div\s+class="([^"]*\bcard\b[^"]*)"', layout)
    operational_summary = re.search(r'<section\s+class="([^"]+)"', summary)

    assert profile is not None and operational_summary is not None
    for card in (profile, operational_summary):
        assert {'stretch', 'stretch-full'}.isdisjoint(card.group(1).split())
