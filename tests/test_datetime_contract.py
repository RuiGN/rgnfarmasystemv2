"""Unchanged Django datetime contracts; standalone mode forbids .env and DB access."""

import os
from pathlib import Path
import sys
import unittest

if __name__ == '__main__':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    # Install the dotenv guard BEFORE any project/Django settings import.
    import environ

    environ.Env.read_env = classmethod(lambda *args, **kwargs: None)
    os.environ['DJANGO_SETTINGS_MODULE'] = 'core.settings.test'
    os.environ['TEST_DATABASE_URL'] = (
        'postgresql://unused@127.0.0.1:9/datetime_contract_no_database'
    )
    os.environ['DATABASE_URL'] = os.environ['TEST_DATABASE_URL']
    from django.db.backends.base.base import BaseDatabaseWrapper

    def forbidden_connection(*_args, **_kwargs):
        raise AssertionError('This datetime contract must never access any database.')

    BaseDatabaseWrapper.ensure_connection = forbidden_connection
    import django

    django.setup()

from django import forms
from django.test import override_settings
from django.utils import timezone
from base.ui.forms import _apply_widget_metadata


class DateTimeContractTests(unittest.TestCase):
    def make_form(self, data=None, **field_options):
        field = forms.DateTimeField(**field_options)
        _apply_widget_metadata('deadline', field)
        form_class = type('TemporalContractForm', (forms.Form,), {'deadline': field})
        return form_class(data=data)

    @override_settings(TIME_ZONE='America/Sao_Paulo', USE_TZ=True)
    def test_canonical_iso_seconds_are_cleaned_in_server_timezone(self):
        with timezone.override('America/Sao_Paulo'):
            form = self.make_form({'deadline': '2026-10-21T09:51:17'})
            self.assertTrue(form.is_valid(), form.errors)
            value = form.cleaned_data['deadline']
            self.assertEqual(value.isoformat(), '2026-10-21T09:51:17-03:00')
            self.assertEqual(value.second, 17)
            rendered = str(self.make_form(initial=value)['deadline'])
            self.assertIn('value="2026-10-21T09:51:17"', rendered)
            self.assertIn('type="datetime-local"', rendered)
            self.assertIn('step="1"', rendered)
            self.assertNotIn('data-mask', rendered)

    def test_empty_optional_required_and_invalid_are_still_server_decisions(self):
        optional = self.make_form({'deadline': ''}, required=False)
        self.assertTrue(optional.is_valid())
        self.assertIsNone(optional.cleaned_data['deadline'])
        for value in [
            '',
            '2026-02-30T09:51:17',
            '2026-10-21T25:51:18',
            'T09:51:18',
            '2026-10-21T',
            'not-a-date',
        ]:
            with self.subTest(value=value):
                invalid = self.make_form({'deadline': value})
                self.assertFalse(invalid.is_valid())
                self.assertIn('deadline', invalid.errors)
                self.assertIn('aria-invalid="true"', str(invalid['deadline']))
                if value:
                    self.assertFalse(self.make_form({'deadline': value}, required=False).is_valid())

    def test_disabled_ignores_forged_post_and_keeps_initial(self):
        from datetime import datetime

        initial = datetime(2026, 10, 21, 9, 51, 17)
        form = self.make_form({'deadline': '2030-01-01T00:00:01'}, disabled=True, initial=initial)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data['deadline'].replace(tzinfo=None), initial)

    def test_action_and_regular_fields_share_the_exact_metadata(self):
        from base.ui.actions.forms import _build_field
        from base.ui.actions.types import ActionField, FieldKind

        action = _build_field(
            ActionField(name='deadline', label='Prazo', kind=FieldKind.DATETIME), None, None
        )
        regular = self.make_form().fields['deadline']
        for widget in [action.widget, regular.widget]:
            self.assertEqual(widget.input_type, 'datetime-local')
            self.assertEqual(widget.format, '%Y-%m-%dT%H:%M:%S')
            self.assertEqual(widget.attrs['step'], '1')


if __name__ == '__main__':
    unittest.main(verbosity=2)
