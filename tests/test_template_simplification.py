"""Document reading must show stored evidence, not decorative compliance demos."""

from pathlib import Path
from types import SimpleNamespace
import re

import pytest
from django import forms
from django.contrib.auth import get_user_model
from django.template.loader import get_template, render_to_string
from django.urls import reverse
from django.utils import timezone

from base.ui.forms import _apply_widget_metadata
from base.ui.registry import get_module, get_resource
from documents.models import ControlledDocument


TEMPLATES = Path(__file__).resolve().parents[1] / 'templates'


@pytest.mark.parametrize(
    'name', sorted(str(path.relative_to(TEMPLATES)) for path in TEMPLATES.rglob('*.html'))
)
def test_every_local_template_compiles(name):
    assert get_template(name)


def test_native_related_select_enhancement_is_loaded_with_defer():
    html = render_to_string('base.html')
    assert re.search(r'<script[^>]+src="[^"]*js/related-fields\.js"[^>]*\bdefer', html)


@pytest.mark.django_db
@pytest.mark.parametrize('editing', [False, True])
def test_floating_assistant_does_not_cover_form_inputs_but_remains_on_read_pages(client, editing):
    user = get_user_model().objects.create_superuser(
        username='unobstructed-editor', email='unobstructed@example.com', password=None
    )
    client.force_login(user)
    route = '/app/masters/categories/new/' if editing else '/app/'
    response = client.get(route)
    assert response.status_code == 200
    html = response.content.decode()
    assert ('id="rag-chat-root"' in html) is not editing
    assert ('js/rag-chat.js' in html) is not editing


@pytest.mark.parametrize('template', ['resource_execution_board.html', 'report_run.html'])
def test_shared_editors_do_not_render_labels_or_grid_cells_for_hidden_fields(template):
    form = forms.Form(data={'description': '', 'token': 'hidden-state'})
    form.fields['description'] = forms.CharField(label='Descrição', help_text='Texto útil.')
    form.fields['token'] = forms.CharField(widget=forms.HiddenInput())
    _apply_widget_metadata('description', form.fields['description'])
    html = render_to_string(
        f'app/{template}',
        {
            'form': form,
            'module': get_module('production'),
            'resource': get_resource('production', 'orders'),
            'object': SimpleNamespace(pk=1),
            'definition': SimpleNamespace(title='Relatório de teste', code='RPT'),
        },
    )
    assert html.count('name="token"') == 1
    assert 'for="id_token"' not in html
    assert html.count('for="id_description"') == 1
    assert 'Texto útil.' in html
    assert 'id="id_description_errors"' in html
    assert 'form-field--full' in html


@pytest.mark.django_db
def test_document_reader_shows_saved_content_without_fabricated_signing(client):
    user = get_user_model().objects.create_superuser(
        username='simple-doc-reader', email='simple-doc-reader@example.com', password=None
    )
    client.force_login(user)
    document = ControlledDocument.objects.create(
        document_type=ControlledDocument.DocumentType.SOP,
        title='Preparo de emulsão cosmética',
        area='Produção',
        owner=user,
        effective_from=timezone.localdate(),
        change_summary='Versão inicial para teste isolado.',
        content='Pesar a fase aquosa.\n<script>alert("not executable")</script>',
    )
    response = client.get(
        reverse(
            'app:resource_viewer',
            kwargs={
                'module_slug': 'documents',
                'resource_slug': 'controlled-documents',
                'pk': document.pk,
            },
        )
    )
    assert response.status_code == 200
    html = response.content.decode()
    assert 'Pesar a fase aquosa.' in html
    assert '&lt;script&gt;' in html
    assert '<script>alert(' not in html
    assert 'Conteúdo do documento original será renderizado' not in html
    assert 'CÓPIA CONTROLADA' not in html
    assert 'Li e Entendi' not in html
    assert 'CFR 21 Part 11' not in html
    assert document.code in html
    assert document.get_status_display() in html


@pytest.mark.django_db
@pytest.mark.parametrize('has_access', [False, True])
def test_document_reader_retains_access_control_and_honest_empty_state(client, has_access):
    manager = get_user_model().objects
    create = manager.create_superuser if has_access else manager.create_user
    user = create(username='document-empty-state', email='doc-empty@example.com', password=None)
    document = ControlledDocument.objects.create(
        document_type=ControlledDocument.DocumentType.SOP,
        title='Documento ainda sem conteúdo',
        area='Qualidade',
        owner=user,
        effective_from=timezone.localdate(),
        change_summary='Teste isolado de estado vazio e acesso.',
    )
    client.force_login(user)
    response = client.get(
        reverse(
            'app:resource_viewer',
            kwargs={
                'module_slug': 'documents',
                'resource_slug': 'controlled-documents',
                'pk': document.pk,
            },
        )
    )
    assert response.status_code == (200 if has_access else 403)
    html = response.content.decode()
    if has_access:
        assert 'Este documento ainda não possui conteúdo cadastrado.' in html
    else:
        assert document.title not in html
        assert document.code not in html
