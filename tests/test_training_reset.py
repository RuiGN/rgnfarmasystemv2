"""Selective training reset contracts; all fixtures are synthetic."""

from io import StringIO
import hashlib
import json
from types import SimpleNamespace

import pytest
from django.core.management import call_command, get_commands
from django.core.management.base import CommandError
from django.db import connection

from masters.models import Product, UnitOfMeasure


pytestmark = pytest.mark.django_db


def _existing_product():
    unit = UnitOfMeasure.objects.create(code='RESET-UNIT', name='Unidade sintética', symbol='un')
    return Product.objects.create(
        description='Negócio antigo sintético', item_type='raw_material', unit=unit
    )


def _execute(settings):
    settings.TRAINING_RESET_ENABLED = True
    output = StringIO()
    call_command(
        'reset_training_data',
        execute=True,
        expected_database=connection.settings_dict['NAME'],
        backup_receipt_sha256=hashlib.sha256(b'synthetic-backup-receipt').hexdigest(),
        stdout=output,
    )
    return json.loads(output.getvalue())


def test_reset_command_defaults_to_read_only_inspection():
    product = _existing_product()
    assert 'reset_training_data' in get_commands(), 'Falta o comando explícito de manutenção'
    output = StringIO()

    call_command('reset_training_data', stdout=output)

    result = json.loads(output.getvalue())
    assert result['mode'] == 'inspect'
    assert result['sequence_policy'] == 'CONTINUE IDENTITY'
    assert 'masters_product' in result['clear_tables']
    assert 'accounts_user' in result['preserved_tables']
    assert Product.objects.get(pk=product.pk).description == product.description


@pytest.mark.parametrize('invalid', ['opt_in', 'database', 'receipt', 'alias'])
def test_execution_guards_refuse_before_writing(settings, invalid):
    from governance import training_reset

    product = _existing_product()
    service = getattr(training_reset, 'reset_training_data', None)
    assert callable(service), 'Falta o serviço com guards de execução'
    settings.TRAINING_RESET_ENABLED = invalid != 'opt_in'
    arguments = {
        'expected_database': connection.settings_dict['NAME'],
        'backup_receipt_sha256': hashlib.sha256(b'synthetic-backup-receipt').hexdigest(),
    }
    if invalid == 'database':
        arguments['expected_database'] = 'not-this-database'
    elif invalid == 'receipt':
        arguments['backup_receipt_sha256'] = 'not-a-sha256'
    elif invalid == 'alias':
        arguments['using'] = 'not-authorized'

    expected = {
        'opt_in': 'TRAINING_RESET_ENABLED',
        'database': 'banco',
        'receipt': 'recibo',
        'alias': 'alias',
    }
    with pytest.raises(CommandError, match=expected[invalid]):
        service(**arguments)

    assert Product.objects.get(pk=product.pk).description == product.description


@pytest.mark.django_db(transaction=True)
def test_authorized_reset_preserves_access_and_reloads_only_catalogs(
    settings, tmp_path, monkeypatch
):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group, Permission

    from auxiliary.models import Country, Currency
    from base.models import IdentifierSequence
    from files.models import ProtectedFile, ProtectedFileAccessRule
    from django.core.files.storage import default_storage
    from reports.models import ReportDefinition

    product = _existing_product()
    user = get_user_model().objects.create_user(
        'reset-operator', 'reset@example.com', None, is_staff=True
    )
    group = Group.objects.create(name='Operadores sintéticos')
    permission = Permission.objects.get(content_type__app_label='masters', codename='view_product')
    user.groups.add(group)
    user.user_permissions.add(permission)
    group.permissions.add(permission)
    payload = b'Synthetic blob retained outside application screens.'
    blob = tmp_path / 'protected' / 'synthetic' / 'old.enc'
    blob.parent.mkdir(parents=True)
    blob.write_bytes(payload)
    attachment = ProtectedFile.objects.create(
        source_module=ProtectedFile.SourceModule.OPERATIONAL,
        source_model='Product',
        source_record_id=str(product.pk),
        file_type=ProtectedFile.FileType.DOCUMENT,
        origin=ProtectedFile.Origin.UPLOAD,
        title='Anexo sintético antigo',
        file_name='old.enc',
        file_reference='protected/synthetic/old.enc',
        content_hash=hashlib.sha256(payload).hexdigest(),
        uploaded_by=user,
    )
    ProtectedFileAccessRule.objects.create(
        protected_file=attachment,
        rule_type=ProtectedFileAccessRule.RuleType.USER,
        user=user,
        permission=ProtectedFileAccessRule.Permission.VIEW,
    )

    def reject_blob_deletion(_name):
        pytest.fail('O reset não pode excluir arquivos físicos.')

    settings.MEDIA_ROOT = str(tmp_path)
    monkeypatch.setattr(default_storage, 'delete', reject_blob_deletion)
    IdentifierSequence.objects.create(namespace='synthetic:daily:preserved', value=41)
    settings.TRAINING_RESET_ENABLED = True
    output = StringIO()

    try:
        call_command(
            'reset_training_data',
            execute=True,
            expected_database=connection.settings_dict['NAME'],
            backup_receipt_sha256=hashlib.sha256(b'synthetic-backup-receipt').hexdigest(),
            stdout=output,
        )
    except CommandError as error:
        pytest.fail(f'Execução autorizada ainda indisponível: {error}')

    result = json.loads(output.getvalue())
    assert result['mode'] == 'reset'
    assert result['preserved_equal'] is True
    assert result['counts']['masters_product'] == 0
    assert not Product.objects.exists()
    assert not ProtectedFile.objects.exists()
    assert not ProtectedFileAccessRule.objects.exists()
    assert blob.read_bytes() == payload
    user.refresh_from_db()
    assert user.is_active and user.is_staff and not user.is_superuser
    assert list(user.groups.values_list('pk', flat=True)) == [group.pk]
    assert list(user.user_permissions.values_list('pk', flat=True)) == [permission.pk]
    assert list(group.permissions.values_list('pk', flat=True)) == [permission.pk]
    assert IdentifierSequence.objects.get(namespace='synthetic:daily:preserved').value == 41
    assert Country.objects.count() == 193
    assert Currency.objects.get(code='BRL').name
    assert ReportDefinition.objects.filter(is_system_managed=True).count() == 15
    assert UnitOfMeasure.objects.get(code='UOM-KG').name == 'Kilograma'
    new_product = Product.objects.create(
        description='Produto novo',
        item_type='raw_material',
        unit=UnitOfMeasure.objects.get(code='UOM-KG'),
    )
    assert new_product.pk > product.pk
    assert new_product.code == f'PRD-{new_product.pk}'


def test_reset_refuses_an_outer_transaction(settings):
    product = _existing_product()
    assert connection.in_atomic_block
    with pytest.raises(CommandError, match='transação externa'):
        _execute(settings)
    assert Product.objects.filter(pk=product.pk).exists()


def test_inspection_refuses_custom_schema_beginning_with_pg():
    product = _existing_product()
    with connection.cursor() as cursor:
        cursor.execute('CREATE SCHEMA pgfoo')
    try:
        with pytest.raises(CommandError, match='Schema desconhecido'):
            call_command('reset_training_data', stdout=StringIO())
    finally:
        with connection.cursor() as cursor:
            cursor.execute('DROP SCHEMA pgfoo')
    assert Product.objects.filter(pk=product.pk).exists()


def test_inspection_refuses_unknown_physical_table():
    product = _existing_product()
    with connection.cursor() as cursor:
        cursor.execute('CREATE TABLE training_unknown (id bigint PRIMARY KEY)')
    try:
        with pytest.raises(CommandError, match='Tabela desconhecida'):
            call_command('reset_training_data', stdout=StringIO())
    finally:
        with connection.cursor() as cursor:
            cursor.execute('DROP TABLE training_unknown')
    assert Product.objects.filter(pk=product.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_inspection_refuses_fk_from_preserved_table_to_business():
    product = _existing_product()
    with connection.cursor() as cursor:
        cursor.execute(
            'ALTER TABLE auth_group ADD CONSTRAINT training_cross_scope FOREIGN KEY (id) REFERENCES masters_product(id) NOT VALID'
        )
    try:
        with pytest.raises(CommandError, match='FK de tabela preservada'):
            call_command('reset_training_data', stdout=StringIO())
    finally:
        with connection.cursor() as cursor:
            cursor.execute('ALTER TABLE auth_group DROP CONSTRAINT training_cross_scope')
    assert Product.objects.filter(pk=product.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_late_catalog_failure_rolls_back_truncation_and_partial_load(settings, monkeypatch):
    from governance import training_reset

    product = _existing_product()
    reached = []

    def partial_load():
        assert not Product.objects.exists()
        UnitOfMeasure.objects.create(code='ROLLBACK-U', name='Carga parcial', symbol='un')
        reached.append('references')

    def fail_reports(_model):
        assert reached == ['references']
        raise RuntimeError('falha tardia sintética de relatórios')

    monkeypatch.setattr(training_reset, 'seed_production_reference_data', partial_load)
    monkeypatch.setattr(training_reset, 'sync_curated_report_catalog', fail_reports)
    with pytest.raises(RuntimeError, match='falha tardia sintética'):
        _execute(settings)
    assert reached == ['references']
    assert Product.objects.get(pk=product.pk).description == product.description
    assert UnitOfMeasure.objects.filter(code='RESET-UNIT').exists()
    assert not UnitOfMeasure.objects.filter(code='ROLLBACK-U').exists()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize('mutation', ['identity', 'counter'])
def test_preserved_state_mutation_rolls_back_reset(settings, monkeypatch, mutation):
    from django.contrib.auth import get_user_model
    from base.models import IdentifierSequence
    from governance import training_reset

    product = _existing_product()
    user = get_user_model().objects.create_user(
        'untouched-operator', 'untouched@example.com', password=None
    )
    IdentifierSequence.objects.create(namespace='synthetic:counter:rollback', value=41)

    def bad_loader():
        if mutation == 'identity':
            get_user_model().objects.filter(pk=user.pk).update(is_active=False)
        else:
            IdentifierSequence.objects.filter(namespace='synthetic:counter:rollback').update(
                value=40
            )
        return SimpleNamespace(manifest_hashes={})

    monkeypatch.setattr(training_reset, 'seed_production_reference_data', bad_loader)
    monkeypatch.setattr(training_reset, 'sync_curated_report_catalog', lambda _model: None)
    with pytest.raises(CommandError, match='preservação falhou'):
        _execute(settings)
    user.refresh_from_db()
    assert user.is_active
    assert IdentifierSequence.objects.get(namespace='synthetic:counter:rollback').value == 41
    assert Product.objects.filter(pk=product.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_reset_refuses_silently_empty_reference_load(settings, monkeypatch):
    from governance import training_reset

    product = _existing_product()
    monkeypatch.setattr(
        training_reset,
        'seed_production_reference_data',
        lambda: SimpleNamespace(manifest_hashes={}),
    )
    monkeypatch.setattr(training_reset, 'sync_curated_report_catalog', lambda _model: None)
    with pytest.raises(CommandError, match='Catálogo obrigatório vazio'):
        _execute(settings)
    assert Product.objects.filter(pk=product.pk).exists()


@pytest.mark.parametrize(
    'corruption', ['preserved_identity', 'restart_identity', 'duplicate', 'identifier']
)
def test_inspection_rejects_manifest_corruption(monkeypatch, tmp_path, corruption):
    from governance import training_reset

    product = _existing_product()
    manifest = json.loads(training_reset.MANIFEST_PATH.read_text())
    if corruption == 'preserved_identity':
        manifest['preserved_tables'].remove('accounts_user')
        manifest['clear_tables'].append('accounts_user')
    elif corruption == 'restart_identity':
        manifest['sequence_policy'] = 'RESTART IDENTITY'
    elif corruption == 'duplicate':
        manifest['clear_tables'].append('masters_product')
    else:
        manifest['clear_tables'].append('invalid;table')
    fixture = tmp_path / 'manifest.json'
    fixture.write_text(json.dumps(manifest))
    monkeypatch.setattr(training_reset, 'MANIFEST_PATH', fixture)
    with pytest.raises(CommandError, match='Manifesto'):
        call_command('reset_training_data', stdout=StringIO())
    assert Product.objects.filter(pk=product.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_concurrent_reset_refuses_before_table_mutation(settings):
    from concurrent.futures import ThreadPoolExecutor
    from django.db import connections, transaction

    product = _existing_product()
    settings.TRAINING_RESET_ENABLED = True

    def competing_reset():
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = '8s'")
            _execute(settings)
        except CommandError as error:
            return str(error)
        finally:
            connections.close_all()
        pytest.fail('O segundo reset não pode ultrapassar o lock da manutenção.')

    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s))', ['rgn:training-reset:v1'])
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert (
                pool.submit(competing_reset).result(timeout=10)
                == 'Outra manutenção está em execução.'
            )
    assert Product.objects.filter(pk=product.pk).exists()
