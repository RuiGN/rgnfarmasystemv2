import pytest

from auxiliary.cosmetics_seed import seed_cosmetics_auxiliary_data
from masters.models import MasterCategory
from reference_data.loaders import _load_hierarchy, apply_catalogs


pytestmark = pytest.mark.django_db


def test_catalog_loader_preserves_same_code_from_another_master_category_kind():
    seed_cosmetics_auxiliary_data()
    legacy = MasterCategory.objects.create(
        code='CAT-COS-FORM-EMULSAO',
        name='Grupo legado preservado',
        kind=MasterCategory.Kind.GROUP,
    )

    apply_catalogs()

    legacy.refresh_from_db()
    canonical = MasterCategory.objects.get(
        code='CAT-COS-FORM-EMULSAO',
        kind=MasterCategory.Kind.COSMETIC_FORM,
    )
    assert canonical.name == 'Emulsão'
    assert canonical.pk != legacy.pk
    assert legacy.kind == MasterCategory.Kind.GROUP
    assert legacy.name == 'Grupo legado preservado'


def test_master_category_parent_resolves_by_canonical_composite_identity():
    legacy_parent = MasterCategory.objects.create(
        code='CAT-COS-PARENT',
        name='Grupo legado com mesmo código',
        kind=MasterCategory.Kind.GROUP,
    )
    records = (
        ('CAT-COS-PARENT', 'Família canônica', MasterCategory.Kind.FAMILY, None),
        ('CAT-COS-CHILD', 'Categoria filha', MasterCategory.Kind.CATEGORY, 'CAT-COS-PARENT'),
    )

    _load_hierarchy(MasterCategory, records, type_field='kind')

    canonical_parent = MasterCategory.objects.get(
        code='CAT-COS-PARENT', kind=MasterCategory.Kind.FAMILY
    )
    child = MasterCategory.objects.get(code='CAT-COS-CHILD', kind=MasterCategory.Kind.CATEGORY)
    legacy_parent.refresh_from_db()
    assert child.parent == canonical_parent
    assert legacy_parent.kind == MasterCategory.Kind.GROUP
    assert legacy_parent.name == 'Grupo legado com mesmo código'
