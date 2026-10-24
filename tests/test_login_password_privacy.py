"""A senha nunca pode ser exibida em tela, nem por controle nativo do navegador."""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_login_template_has_no_password_visibility_control():
    source = (ROOT / 'templates' / 'registration' / 'login.html').read_text()

    password_input = re.search(r'<input[^>]+type="password"[^>]*>', source)
    assert password_input is not None
    for marker in ('feather-eye', 'password-toggle', 'togglePassword', 'data-ui="password'):
        assert marker not in source, marker


def test_password_inputs_suppress_the_native_reveal_control():
    css = (ROOT / 'static' / 'css' / 'app.css').read_text()

    rule = re.search(
        r'input\[type="password"\]::-ms-reveal,\s*'
        r'input\[type="password"\]::-ms-clear\s*\{([^}]+)\}',
        css,
    )
    assert rule is not None, 'falta a regra que esconde o botão nativo de revelar senha'
    assert 'display: none !important;' in rule.group(1)


def test_no_template_renders_a_password_field_as_plain_text():
    offenders = []
    for path in (ROOT / 'templates').rglob('*.html'):
        source = path.read_text()
        for match in re.finditer(r'<input[^>]*name="[^"]*password[^"]*"[^>]*>', source):
            if 'type="text"' in match.group(0):
                offenders.append(path.relative_to(ROOT).as_posix())
    assert offenders == []
