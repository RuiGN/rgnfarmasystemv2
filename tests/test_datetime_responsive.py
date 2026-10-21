"""Focused, DB-free browser contracts. Run directly; no conftest/settings/.env.

RGN_UI_BROWSER_TESTS=1 RGN_UI_CHROME=/installed/chrome .venv/bin/python tests/test_datetime_responsive.py
Artifacts/profile/basetemp must stay inside the caller's scratch directory.
"""

import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    'temporal_geometry', ROOT / 'tests/test_resource_form_temporal_geometry.py'
)
geometry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(geometry)


@unittest.skipUnless(os.environ.get('RGN_UI_BROWSER_TESTS') == '1', 'Opt-in local browser')
class ResponsiveDateTimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Factory:
            def mktemp(self, name):
                return Path(tempfile.mkdtemp(prefix=name, dir=os.environ['TMPDIR']))

        cls.browser = geometry.computed_browser.__wrapped__(Factory())
        cls.call = staticmethod(next(cls.browser))

    @classmethod
    def tearDownClass(cls):
        # Chromium on macOS can outlive SIGTERM while a native UI was used.
        # Ask our isolated browser to exit before the shared fixture reaps it.
        try:
            cls.call('Browser.close')
        finally:
            cls.browser.close()

    def evaluate(self, expression):
        result = self.call('Runtime.evaluate', expression=expression, returnByValue=True)
        self.assertNotIn('exceptionDetails', result)
        return result['result'].get('value')

    def setup_form(self, attributes='', width=320, enhance=True):
        self.call(
            'Emulation.setDeviceMetricsOverride',
            width=width,
            height=1000,
            deviceScaleFactor=1,
            mobile=False,
        )
        self.call('Page.navigate', url='about:blank')
        if 'step=' not in attributes:
            attributes += ' step="1"'
        content = (
            '<form class="resource-form no-loader"><label for="dt">Prazo</label>'
            '<input type="datetime-local" class="form-control" id="dt" name="deadline" '
            'value="2026-10-21T09:51:17" ' + attributes + '>'
            '<button type="submit">Salvar</button></form>'
        )
        self.evaluate('document.body.innerHTML=' + json.dumps(content))
        if enhance:
            self.evaluate((ROOT / 'static/js/app-form-enhancements.js').read_text())
            self.evaluate("document.dispatchEvent(new Event('DOMContentLoaded'))")

    def test_narrow_split_posts_single_original_iso_name_with_seconds(self):
        self.setup_form('required')
        state = self.evaluate("""(() => {
          const f=document.querySelector('form'), source=f.elements.deadline;
          const date=f.querySelector('[data-datetime-part="date"]');
          const time=f.querySelector('[data-datetime-part="time"]');
          return {date:date && date.value,time:time && time.value,
            post:Array.from(new FormData(f)),hidden:source.hidden,
            valid:f.checkValidity(),label:date && date.labels[0].textContent};
        })()""")
        self.assertEqual(state['date'], '2026-10-21')
        self.assertEqual(state['time'], '09:51:17')
        self.assertEqual(state['post'], [['deadline', '2026-10-21T09:51:17']])
        self.assertTrue(state['hidden'])
        self.assertTrue(state['valid'])
        self.assertTrue(state['label'])

    def test_source_is_not_a_second_visible_editor(self):
        self.setup_form()
        # Load real vendor/app CSS; Bootstrap overrides the UA hidden rule.
        for path in geometry.STYLES:
            self.evaluate(
                "(() => {const s=document.createElement('style');s.textContent="
                + json.dumps((ROOT / 'static' / path).read_text())
                + ';document.head.appendChild(s)})()'
            )
        self.assertEqual(
            self.evaluate("document.getElementById('dt').getBoundingClientRect().height"), 0
        )
        self.assertGreater(
            float(
                self.evaluate(
                    "parseFloat(getComputedStyle(document.querySelector('.datetime-split')).rowGap)||0"
                )
            ),
            0,
        )

    def test_invalid_editor_value_reaches_server_as_invalid_not_as_a_valid_optional_empty(self):
        self.setup_form()
        state = self.evaluate(
            """(() => {const t=document.getElementById('dt__time');t.value='25:51:18';t.dispatchEvent(new Event('input',{bubbles:true}));return {post:new FormData(document.querySelector('form')).get('deadline'),valid:document.querySelector('form').checkValidity()}})()"""
        )
        self.assertEqual(state, {'post': '2026-10-21T25:51:18', 'valid': False})

    def test_time_is_explicit_seconds_editor_without_a_clock_popup(self):
        self.setup_form()
        state = self.evaluate(
            "({type:document.getElementById('dt__time').type,pattern:document.getElementById('dt__time').pattern,pickers:Array.from(document.querySelectorAll('[data-datetime-picker]')).map(b=>b.dataset.datetimePicker)})"
        )
        self.assertEqual(state['type'], 'text')
        self.assertTrue(state['pattern'])
        self.assertEqual(state['pickers'], ['date'])

    def test_native_picker_has_a_keyboard_and_click_button(self):
        self.setup_form()
        buttons = self.evaluate(
            "Array.from(document.querySelectorAll('[data-datetime-picker]')).map(b=>({type:b.type,part:b.dataset.datetimePicker,label:b.getAttribute('aria-label')}))"
        )
        self.assertEqual([b['part'] for b in buttons], ['date'])
        self.assertTrue(all(b['type'] == 'button' and 'Prazo' in b['label'] for b in buttons))

    def test_joint_validation_clear_and_reset_preserve_original_contract(self):
        self.setup_form('required min="2026-10-21T09:00:00" max="2026-10-22T10:00:00"')
        state = self.evaluate("""(() => {
          const f=document.querySelector('form'), d=f.querySelector('[data-datetime-part="date"]');
          const t=f.querySelector('[data-datetime-part="time"]'), s=f.elements.deadline;
          function change(control,value){control.value=value;control.dispatchEvent(new Event('input',{bubbles:true}));}
          change(t,'10:01:23');change(d,'2026-10-22');
          const outside={post:new FormData(f).get('deadline'),valid:f.checkValidity(),message:t.validationMessage};
          change(t,'09:59:18');
          const inside={post:new FormData(f).get('deadline'),valid:f.checkValidity()};
          change(d,'');
          const partial={post:new FormData(f).get('deadline'),valid:f.checkValidity(),dateRequired:d.required};
          f.reset();
          return {outside,inside,partial,default:s.defaultValue};
        })()""")
        self.assertEqual(state['outside']['post'], '2026-10-22T10:01:23')
        self.assertFalse(state['outside']['valid'])
        self.assertTrue(state['outside']['message'])
        self.assertEqual(state['inside'], {'post': '2026-10-22T09:59:18', 'valid': True})
        self.assertEqual(
            state['partial'], {'post': 'T09:59:18', 'valid': False, 'dateRequired': True}
        )
        self.assertEqual(state['default'], '2026-10-21T09:51:17')
        self.assertEqual(
            self.evaluate(
                "[document.querySelector('[data-datetime-part=date]').value,document.querySelector('[data-datetime-part=time]').value]"
            ),
            ['2026-10-21', '09:51:17'],
        )

    def test_disabling_canonical_source_disables_both_editors_and_picker_buttons(self):
        self.setup_form('required')
        self.evaluate("document.getElementById('dt').disabled=true")
        state = self.evaluate(
            "({disabled:Array.from(document.querySelectorAll('[data-datetime-part],[data-datetime-picker]')).every(e=>e.disabled),post:Array.from(new FormData(document.querySelector('form'))),valid:document.querySelector('form').checkValidity()})"
        )
        self.assertEqual(state, {'disabled': True, 'post': [], 'valid': True})

    def test_keyboard_time_edit_updates_post_and_keeps_invalid_text_for_correction(self):
        self.setup_form()
        self.evaluate("document.getElementById('dt__time').focus()")

        def enter(text):
            for kind in ['keyDown', 'keyUp']:
                self.call(
                    'Input.dispatchKeyEvent',
                    type=kind,
                    key='a',
                    code='KeyA',
                    windowsVirtualKeyCode=65,
                    modifiers=4,
                    commands=['selectAll'] if kind == 'keyDown' else [],
                )
            self.call('Input.insertText', text=text)

        enter('10:22:59')
        self.assertEqual(
            self.evaluate("new FormData(document.querySelector('form')).get('deadline')"),
            '2026-10-21T10:22:59',
        )
        enter('25:22:59')
        self.assertEqual(
            self.evaluate(
                "({text:document.getElementById('dt__time').value,valid:document.querySelector('form').checkValidity(),post:new FormData(document.querySelector('form')).get('deadline')})"
            ),
            {'text': '25:22:59', 'valid': False, 'post': '2026-10-21T25:22:59'},
        )
        enter('09:51:18')
        self.assertEqual(
            self.evaluate("new FormData(document.querySelector('form')).get('deadline')"),
            '2026-10-21T09:51:18',
        )

    def test_fractional_seconds_keep_precision(self):
        self.setup_form('step="any"')
        state = self.evaluate("""(() => { const f=document.querySelector('form'),t=f.querySelector('[data-datetime-part=time]');
          t.value='09:51:17.123';t.dispatchEvent(new Event('input',{bubbles:true}));
          return {post:new FormData(f).get('deadline'),valid:f.checkValidity()};})()""")
        self.assertEqual(state, {'post': '2026-10-21T09:51:17.123', 'valid': True})

    def test_optional_partial_never_submits_as_a_valid_empty_value(self):
        self.setup_form()
        result = self.evaluate("""(() => {
          const f=document.querySelector('form'),s=f.elements.deadline;
          const [d,t]=f.querySelectorAll('[data-datetime-part]');
          d.value='';t.value='';t.dispatchEvent(new Event('input',{bubbles:true}));
          const empty={valid:f.checkValidity(),post:new FormData(f).get('deadline')};
          t.value='13:14:15';t.dispatchEvent(new Event('input',{bubbles:true}));
          return {empty,partial:f.checkValidity(),required:d.required};
        })()""")
        self.assertEqual(
            result, {'empty': {'valid': True, 'post': ''}, 'partial': False, 'required': True}
        )

    def test_full_datetime_step_uses_date_and_original_minimum_as_base(self):
        self.setup_form('min="2026-10-21T09:00:17" step="90"')
        result = self.evaluate("""(() => {
          const f=document.querySelector('form'),t=f.querySelector('[data-datetime-part=time]');
          t.value='09:01:47';t.dispatchEvent(new Event('input',{bubbles:true}));
          const valid=f.checkValidity();
          t.value='09:01:48';t.dispatchEvent(new Event('input',{bubbles:true}));
          return {valid,invalid:f.checkValidity()};
        })()""")
        self.assertEqual(result, {'valid': True, 'invalid': False})

    def test_wide_disabled_readonly_and_no_javascript_keep_native_contract(self):
        for attr, width in [('', 640), ('disabled', 320), ('readonly', 320)]:
            with self.subTest(attr=attr, width=width):
                self.setup_form(attr, width)
                state = self.evaluate(
                    "({parts:document.querySelectorAll('[data-datetime-part]').length,type:document.getElementById('dt').type,hidden:document.getElementById('dt').hidden})"
                )
                self.assertEqual(state, {'parts': 0, 'type': 'datetime-local', 'hidden': False})
        # With no JS the server markup/name/validation remain native, not hidden.
        self.setup_form('required', enhance=False)
        self.assertEqual(
            self.evaluate("Array.from(new FormData(document.querySelector('form')))"),
            [['deadline', '2026-10-21T09:51:17']],
        )
        self.assertFalse(self.evaluate("document.getElementById('dt').hidden"))

    def test_no_javascript_native_keyboard_edit_keeps_seconds(self):
        self.setup_form('required', enhance=False)

        def descendants(node):
            yield node
            for child in node.get('children', []) + node.get('shadowRoots', []):
                yield from descendants(child)

        nodes = self.call('DOM.getDocument', depth=-1, pierce=True)
        second = next(
            n
            for n in descendants(nodes['root'])
            if '-webkit-datetime-edit-second-field' in n.get('attributes', [])
        )
        self.call('DOM.focus', backendNodeId=second['backendNodeId'])
        for kind in ['keyDown', 'keyUp']:
            self.call(
                'Input.dispatchKeyEvent',
                type=kind,
                key='ArrowUp',
                code='ArrowUp',
                windowsVirtualKeyCode=38,
            )
        self.assertEqual(
            self.evaluate("new FormData(document.querySelector('form')).get('deadline')"),
            '2026-10-21T09:51:18',
        )

    def test_invalid_datetime_reveals_and_focuses_its_real_bootstrap_tab(self):
        self.setup_form(enhance=False)
        self.evaluate("""document.body.innerHTML=`<form class="no-loader">
          <div data-ui="resource-form-tabs"><div class="nav" role="tablist">
          <button id="tab-a" type="button" role="tab" class="active" data-bs-toggle="tab" data-bs-target="#pane-a" aria-controls="pane-a">Principal</button>
          <button id="tab-b" type="button" role="tab" data-bs-toggle="tab" data-bs-target="#pane-b" aria-controls="pane-b">Datas</button></div>
          <div class="tab-content"><div id="pane-a" class="tab-pane active" role="tabpanel">Principal</div>
          <div id="pane-b" class="tab-pane" role="tabpanel"><label for="at">Prazo</label><input id="at" name="at" type="datetime-local" step="1" required></div></div></div>
          <button id="save" type="submit">Salvar</button></form>`""")
        self.evaluate((ROOT / 'static/vendor/duralux/js/vendors.min.js').read_text())
        self.evaluate((ROOT / 'static/js/app-form-enhancements.js').read_text())
        self.evaluate((ROOT / 'static/js/resource-form-tabs.js').read_text())
        self.evaluate("document.dispatchEvent(new Event('DOMContentLoaded'))")
        self.evaluate("document.getElementById('save').click()")
        self.assertEqual(
            self.evaluate(
                "({pane:document.getElementById('pane-b').classList.contains('active'),focus:document.activeElement.dataset.datetimePart,valid:document.querySelector('form').checkValidity()})"
            ),
            {'pane': True, 'focus': 'date', 'valid': False},
        )

    def test_added_inline_is_enhanced_once_with_unique_ids_and_error_metadata(self):
        self.setup_form('aria-invalid="true" aria-describedby="dt-error"')
        self.evaluate(
            "document.querySelector('form').insertAdjacentHTML('beforeend','<div data-inline-formset-form><label for=id_lines-1-at>Coleta</label><input id=id_lines-1-at type=datetime-local name=lines-1-at step=1 required value=2026-10-22T13:14:15></div>')"
        )
        state = self.evaluate("""(() => {
          const nodes=Array.from(document.querySelectorAll('[id]'));
          return {count:document.querySelectorAll('.datetime-split').length,unique:new Set(nodes.map(e=>e.id)).size===nodes.length,
          post:Array.from(new FormData(document.querySelector('form'))),
          error:document.querySelector('[data-datetime-part=date]').getAttribute('aria-invalid'),
          described:document.querySelector('[data-datetime-part=date]').getAttribute('aria-describedby')};
        })()""")
        self.assertEqual(
            state,
            {
                'count': 2,
                'unique': True,
                'post': [
                    ['deadline', '2026-10-21T09:51:17'],
                    ['lines-1-at', '2026-10-22T13:14:15'],
                ],
                'error': 'true',
                'described': 'dt-error',
            },
        )


if __name__ == '__main__':
    unittest.main(verbosity=2)
