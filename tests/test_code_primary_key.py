import pytest
from django.apps import apps

from base.models import SingleInstanceModel
from base.sequences import AutoCodeMixin
from masters.models import Product, UnitOfMeasure

pytestmark = pytest.mark.django_db


def _unsaved_product(**kwargs):
    unit, _ = UnitOfMeasure.objects.get_or_create(
        code='IDPK-UNIT', defaults={'name': 'Unidade de teste', 'symbol': 'un'}
    )
    return Product(
        description='Produto sintético',
        item_type=Product.ItemType.RAW_MATERIAL,
        unit=unit,
        **kwargs,
    )


def _product(**kwargs):
    product = _unsaved_product(**kwargs)
    product.save(force_insert=True)
    return product


def test_auto_code_uses_real_primary_key_without_padding():
    product = _product(pk=412)

    assert product.code == 'PRD-412'
    product.refresh_from_db()
    assert product.code == f'{Product.CODE_PREFIX}-{product.pk}'


def test_generated_primary_key_code_is_final_in_creation_signal():
    from django.db.models.signals import post_save

    from base.models import IdentifierSequence

    seen = []

    def record_creation(sender, instance, created, **kwargs):
        seen.append((instance.pk, instance.code, created))

    post_save.connect(record_creation, sender=Product)
    try:
        product = _product()
    finally:
        post_save.disconnect(record_creation, sender=Product)

    assert product.code == f'PRD-{product.pk}'
    assert seen == [(product.pk, product.code, True)]
    assert not IdentifierSequence.objects.filter(namespace='masters.product:code:global').exists()


def test_explicit_primary_key_is_formatted_as_its_database_integer():
    product = _product(pk='0042')

    assert product.pk == 42
    assert product.code == 'PRD-42'


@pytest.mark.parametrize(
    ('prefix', 'max_length', 'message'), [('  ', 64, 'prefixo'), ('PRD', 5, 'max_length')]
)
def test_automatic_code_rejects_invalid_format_atomically(monkeypatch, prefix, max_length, message):
    from django.core.exceptions import ImproperlyConfigured

    monkeypatch.setattr(Product, 'CODE_PREFIX', prefix)
    monkeypatch.setattr(Product._meta.get_field('code'), 'max_length', max_length)
    with pytest.raises(ImproperlyConfigured, match=message):
        _product()
    assert not Product.objects.exists()


@pytest.mark.parametrize('kwargs', [{'force_update': True}, {'update_fields': ['description']}])
def test_forced_update_without_primary_key_retains_django_semantics(kwargs):
    from django.db import transaction

    product = _unsaved_product()

    with pytest.raises(ValueError, match='no primary key'), transaction.atomic():
        product.save(**kwargs)

    assert product.pk is None
    assert product.code == ''
    assert not Product.objects.exists()


@pytest.mark.parametrize('creating', [True, False])
@pytest.mark.parametrize('empty_fields', [list, tuple, lambda: iter(())])
def test_empty_update_fields_is_a_noop(creating, empty_fields):
    if creating:
        product = _unsaved_product()
    else:
        product = _product(code='LEGADO-SEM-CODIGO')
        Product.objects.filter(pk=product.pk).update(code='')
        product.refresh_from_db()
    original_pk = product.pk
    original_count = Product.objects.count()

    product.save(update_fields=empty_fields())

    assert product.pk == original_pk
    assert product.code == ''
    assert Product.objects.count() == original_count
    if not creating:
        product.refresh_from_db()
        assert product.code == ''


@pytest.mark.parametrize('failure_stage', ['format', 'signal'])
def test_failed_automatic_save_restores_its_identity_for_retry(monkeypatch, failure_stage):
    from django.core.exceptions import ImproperlyConfigured
    from django.db.models.signals import post_save

    product = _unsaved_product()
    original_db = product._state.db

    def refuse_creation(sender, instance, **kwargs):
        raise RuntimeError('Falha sintética após inserir')

    with monkeypatch.context() as patches:
        if failure_stage == 'format':
            patches.setattr(Product._meta.get_field('code'), 'max_length', 4)
            error = ImproperlyConfigured
        else:
            post_save.connect(refuse_creation, sender=Product)
            error = RuntimeError
        try:
            with pytest.raises(error):
                product.save()
        finally:
            post_save.disconnect(refuse_creation, sender=Product)

    assert product.pk is None
    assert product.code == ''
    assert product._state.adding is True
    assert product._state.db == original_db
    assert not Product.objects.exists()

    product.save()
    assert Product.objects.count() == 1
    assert product.code == f'PRD-{product.pk}'


@pytest.mark.parametrize('force_insert', [(UnitOfMeasure,), None, 0])
def test_invalid_force_insert_is_not_silently_replaced(force_insert):
    from django.db import transaction

    product = _unsaved_product()
    with pytest.raises(TypeError), transaction.atomic():
        product.save(force_insert=force_insert)
    assert not Product.objects.exists()


def test_missing_primary_key_sequence_fails_before_inserting(monkeypatch):
    from django.core.exceptions import ImproperlyConfigured

    product = _unsaved_product()
    monkeypatch.setattr(Product._meta.pk, 'column', 'description')

    with pytest.raises(ImproperlyConfigured, match='sequência'):
        product.save()

    assert product.pk is None
    assert product.code == ''
    assert not Product.objects.exists()


@pytest.mark.parametrize(
    'model',
    [
        model
        for model in apps.get_models()
        if issubclass(model, AutoCodeMixin) and model.CODE_PREFIX
    ],
    ids=lambda model: model._meta.label,
)
def test_shared_formatter_covers_every_registered_auto_code_model(monkeypatch, model):
    written = []
    monkeypatch.setattr(
        SingleInstanceModel,
        'save',
        lambda instance, *args, **kwargs: written.append((instance.pk, instance.code)),
    )
    instance = model(pk=412)

    AutoCodeMixin.save(instance, using='default')

    assert written == [(412, f'{model.CODE_PREFIX}-412')]


@pytest.mark.parametrize('force_insert', [True, False, (Product,), ()])
def test_valid_force_insert_options_retain_creation_semantics(force_insert):
    product = _unsaved_product()
    product.save(force_insert=force_insert)

    assert product.code == f'PRD-{product.pk}'
    assert Product.objects.get(pk=product.pk).code == product.code


def test_explicit_database_alias_does_not_get_overridden(monkeypatch):
    product = _unsaved_product()

    def refuse_router(*args, **kwargs):
        raise AssertionError('O alias explícito deve prevalecer sobre o router')

    monkeypatch.setattr('base.sequences.router.db_for_write', refuse_router)
    product.save(using='default')

    assert product._state.db == 'default'
    assert product.code == f'PRD-{product.pk}'


@pytest.mark.parametrize('code', ['PRD-0042', 'CODIGO-DESCRITIVO'])
def test_explicit_codes_are_not_renumbered(code):
    product = _product(code=code)
    product.description = 'Descrição atualizada'
    product.save(update_fields=['description'])
    product.refresh_from_db()

    assert product.code == code


def test_official_code_without_prefix_is_preserved():
    from auxiliary.models import Currency

    currency = Currency.objects.create(code='BRL', name='Real brasileiro')
    assert currency.code == 'BRL'


def test_admin_creation_uses_the_real_primary_key(client):
    from django.contrib.auth import get_user_model
    from django.urls import reverse

    from masters.models import MasterCategory

    user = get_user_model().objects.create_superuser('code-admin', 'code-admin@example.com', None)
    client.force_login(user)
    response = client.post(
        reverse('admin:masters_mastercategory_add'),
        {'name': 'Família cosmética', 'kind': MasterCategory.Kind.FAMILY, 'is_active': 'on'},
    )

    assert response.status_code == 302
    category = MasterCategory.objects.get(name='Família cosmética')
    assert category.code == f'CAT-{category.pk}'


def test_deleted_primary_key_is_not_reused_for_the_next_code():
    first = _product()
    deleted_pk, deleted_code = first.pk, first.code
    first.delete()

    second = _product()

    assert second.pk > deleted_pk
    assert second.code == f'PRD-{second.pk}'
    assert second.code != deleted_code


def test_explicit_code_collision_does_not_renumber_or_modify_records():
    from django.db import IntegrityError, transaction

    existing = _product(pk=900_000_003, code='PRD-412')
    product = _unsaved_product(pk=412)

    with pytest.raises(IntegrityError), transaction.atomic():
        product.save()

    assert product.pk == 412
    assert product.code == ''
    assert product._state.adding
    assert Product.objects.count() == 1
    assert Product.objects.get(pk=existing.pk).code == 'PRD-412'


def test_empty_force_insert_tuple_never_overwrites_an_existing_primary_key():
    from django.db import IntegrityError, connection, transaction

    with connection.cursor() as cursor:
        cursor.execute('SELECT nextval(pg_get_serial_sequence(%s, %s))', ['masters_product', 'id'])
        occupied_pk = cursor.fetchone()[0] + 1
    existing = _product(pk=occupied_pk, code='CODIGO-PRESERVADO')
    product = _unsaved_product()
    product.created_at = existing.created_at

    with pytest.raises(IntegrityError) as error, transaction.atomic():
        product.save(force_insert=())

    assert error.value.__cause__.sqlstate == '23505'
    existing.refresh_from_db()
    assert existing.code == 'CODIGO-PRESERVADO'
    assert product.pk is None
    assert product.code == ''
    assert Product.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_creations_use_distinct_real_primary_keys():
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from django.db import close_old_connections, connection

    unit = UnitOfMeasure.objects.create(code='CONCURRENT-ID', name='Unidade', symbol='un')
    start = Barrier(2, timeout=10)

    def create_product(number):
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET statement_timeout = '15s'")
                cursor.execute("SET lock_timeout = '10s'")
            start.wait()
            product = Product.objects.create(
                description=f'Produto concorrente {number}',
                item_type=Product.ItemType.RAW_MATERIAL,
                unit_id=unit.pk,
            )
            return product.pk, product.code
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(create_product, number) for number in range(2)]
        pairs = [future.result(timeout=25) for future in results]

    assert len({pk for pk, _ in pairs}) == 2
    assert all(code == f'PRD-{pk}' for pk, code in pairs)
    assert list(Product.objects.order_by('pk').values_list('pk', 'code')) == sorted(pairs)
