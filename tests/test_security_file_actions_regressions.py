"""Permission selection does not require PostgreSQL or any network request."""

from types import SimpleNamespace

import pytest

from files.views import ProtectedFileViewSet


class SyntheticFileQuery:
    def __init__(self, identifiers):
        self.identifiers = identifiers

    def values(self, field):
        assert field == 'pk'
        return self.identifiers

    def filter(self, **kwargs):
        return SyntheticFileQuery([pk for pk in self.identifiers if pk in kwargs['pk__in']])


@pytest.mark.permission_strict
@pytest.mark.parametrize('action', ['download', 'generate_link'])
def test_download_only_file_grant_remains_usable_without_view_grant(monkeypatch, action):
    user = SimpleNamespace(is_authenticated=True, is_active=True)
    # The fake datastore grants only DOWNLOAD, not metadata VIEW.
    monkeypatch.setattr(
        'files.views.accessible_protected_files',
        lambda actor, permission='view': SyntheticFileQuery(
            [123] if permission == 'download' else []
        ),
    )
    view = ProtectedFileViewSet()
    view.request = SimpleNamespace(user=user, data={'purpose': 'download'})
    view.action = action
    view.queryset = SyntheticFileQuery([123])
    assert view.get_queryset().identifiers == [123]


@pytest.mark.parametrize('scenario', ['inactive_queue', 'over_limit'])
def test_superuser_role_override_does_not_bypass_queue_eligibility(scenario):
    from decimal import Decimal
    from workflow.models import ApprovalQueue, ApprovalTask

    queue = ApprovalQueue(
        module='quality',
        profile_role='quality',
        is_active=scenario != 'inactive_queue',
        approval_limit=Decimal('1.00') if scenario == 'over_limit' else Decimal('10.00'),
    )
    task = ApprovalTask(
        queue=queue,
        source_module='quality',
        amount=Decimal('2.00'),
        requested_by_id=1,
        assigned_to_id=2,
    )
    admin = SimpleNamespace(pk=2, is_superuser=True, is_active=True, is_authenticated=True)
    assert not task.can_approve(admin)
