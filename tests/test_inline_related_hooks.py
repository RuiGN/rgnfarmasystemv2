"""Pure inline-builder integration tests: no DB grant may hide eager queries."""

from base.ui.registry import InlineResourceConfig
from base.ui import views
from formulations.models import FormulaComponent


def test_inline_configures_dependencies_after_readonly_controls(monkeypatch):
    observed = []

    def configure(form):
        observed.append(form.fields['material'].disabled)

    monkeypatch.setattr(views, 'configure_related_fields', configure, raising=False)
    inline = InlineResourceConfig(
        'components',
        'Componentes',
        FormulaComponent,
        'formula',
        ('material',),
        read_only_fields=('material',),
    )
    views._build_inline_form_class(inline)()
    assert observed == [True]


def test_inline_clean_runs_shared_server_dependency_validator(monkeypatch):
    observed = []

    def validate(form, cleaned):
        observed.append(cleaned.copy())
        form.add_error(None, 'Dependência sintética recusada.')
        return cleaned

    monkeypatch.setattr(views, 'validate_related_fields', validate, raising=False)
    inline = InlineResourceConfig('components', 'Componentes', FormulaComponent, 'formula', ())
    form = views._build_inline_form_class(inline)({})
    assert not form.is_valid()
    assert observed == [{}]
    assert 'Dependência sintética recusada.' in form.non_field_errors()
