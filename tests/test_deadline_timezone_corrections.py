"""Deadline presentation follows the active local calendar without database access."""

from datetime import UTC, date, datetime, time, timedelta

import pytest
from django.utils import timezone

from base.ui.deadlines import _deadline_tone
from base.ui.presentation import DeadlineItem


@pytest.fixture
def frozen_now(monkeypatch):
    now = datetime(2026, 10, 3, 1, tzinfo=UTC)
    monkeypatch.setattr(timezone, 'now', lambda: now)
    return now


def test_previous_local_day_is_overdue_not_today(frozen_now):
    with timezone.override('America/Recife'):
        due_at = frozen_now - timedelta(days=1)
        item = DeadlineItem('Prazo', '', due_at, 'danger', 'feather-alert-triangle', '/app/')

        assert timezone.localdate() == datetime(2026, 10, 2).date()
        assert item.temporal_label == 'Vencido'


def test_previous_local_day_uses_danger_tone_and_icon(frozen_now):
    with timezone.override('America/Recife'):
        due_at = frozen_now - timedelta(days=1)

        assert _deadline_tone(due_at) == ('danger', 'feather-alert-triangle')


EXPECTED_PRESENTATIONS = {
    'overdue': ('danger', 'feather-alert-triangle'),
    'today': ('warning', 'feather-clock'),
    'future': ('primary', 'feather-calendar'),
}


def assert_deadline_presentation(due_at, expected_label, state):
    tone, icon = _deadline_tone(due_at)
    item = DeadlineItem('Prazo', '', due_at, tone, icon, '/app/')

    assert item.temporal_label == expected_label
    assert (item.tone, item.icon) == EXPECTED_PRESENTATIONS[state]
    assert item.due_at is due_at


@pytest.mark.parametrize(
    ('zone', 'now_iso', 'due_iso', 'expected_label', 'state'),
    [
        # Recife: both sides of local midnight and UTC midnight.
        ('America/Recife', '2026-10-03T01:00Z', '2026-10-02T02:59:59Z', 'Vencido', 'overdue'),
        ('America/Recife', '2026-10-03T01:00Z', '2026-10-02T03:00Z', 'Vence hoje', 'today'),
        ('America/Recife', '2026-10-03T01:00Z', '2026-10-02T23:59:59Z', 'Vence hoje', 'today'),
        ('America/Recife', '2026-10-03T01:00Z', '2026-10-03T00:00Z', 'Vence hoje', 'today'),
        ('America/Recife', '2026-10-03T01:00Z', '2026-10-03T02:59:59Z', 'Vence hoje', 'today'),
        (
            'America/Recife',
            '2026-10-03T01:00Z',
            '2026-10-03T03:00Z',
            'Vence em 03/10/2026',
            'future',
        ),
        # Tokyo: the local calendar is ahead of UTC.
        ('Asia/Tokyo', '2026-10-02T23:00Z', '2026-10-02T14:59:59Z', 'Vencido', 'overdue'),
        ('Asia/Tokyo', '2026-10-02T23:00Z', '2026-10-02T15:00Z', 'Vence hoje', 'today'),
        ('Asia/Tokyo', '2026-10-02T23:00Z', '2026-10-02T23:59:59Z', 'Vence hoje', 'today'),
        ('Asia/Tokyo', '2026-10-02T23:00Z', '2026-10-03T00:00Z', 'Vence hoje', 'today'),
        ('Asia/Tokyo', '2026-10-02T23:00Z', '2026-10-03T14:59:59Z', 'Vence hoje', 'today'),
        ('Asia/Tokyo', '2026-10-02T23:00Z', '2026-10-03T15:00Z', 'Vence em 04/10/2026', 'future'),
        # The frozen current instant also crosses local midnight exactly.
        (
            'America/Recife',
            '2026-10-03T02:59:59Z',
            '2026-10-03T03:00Z',
            'Vence em 03/10/2026',
            'future',
        ),
        ('America/Recife', '2026-10-03T03:00Z', '2026-10-03T03:00Z', 'Vence hoje', 'today'),
        (
            'Asia/Tokyo',
            '2026-10-02T14:59:59Z',
            '2026-10-02T15:00Z',
            'Vence em 03/10/2026',
            'future',
        ),
        ('Asia/Tokyo', '2026-10-02T15:00Z', '2026-10-02T15:00Z', 'Vence hoje', 'today'),
        # Non-UTC source offsets must not be treated as the active timezone.
        ('America/Recife', '2026-10-03T01:00Z', '2026-10-03T10:00+09:00', 'Vence hoje', 'today'),
        ('Asia/Tokyo', '2026-10-03T01:00Z', '2026-10-02T20:00-05:00', 'Vence hoje', 'today'),
        # Large offsets and UTC itself.
        ('Pacific/Kiritimati', '2026-10-03T01:00Z', '2026-10-02T09:59:59Z', 'Vencido', 'overdue'),
        ('Pacific/Kiritimati', '2026-10-03T01:00Z', '2026-10-02T10:00Z', 'Vence hoje', 'today'),
        ('Pacific/Pago_Pago', '2026-10-03T01:00Z', '2026-10-02T10:59:59Z', 'Vencido', 'overdue'),
        ('Pacific/Pago_Pago', '2026-10-03T01:00Z', '2026-10-02T11:00Z', 'Vence hoje', 'today'),
        ('UTC', '2026-10-03T00:00Z', '2026-10-02T23:59:59Z', 'Vencido', 'overdue'),
        ('UTC', '2026-10-03T00:00Z', '2026-10-03T00:00Z', 'Vence hoje', 'today'),
        ('UTC', '2026-10-03T23:59:59Z', '2026-10-04T00:00Z', 'Vence em 04/10/2026', 'future'),
        # Month and year boundaries retain Brazilian date formatting.
        ('Asia/Tokyo', '2026-12-31T14:00Z', '2026-12-31T15:00Z', 'Vence em 01/01/2027', 'future'),
    ],
)
def test_aware_deadlines_follow_active_calendar(
    monkeypatch, zone, now_iso, due_iso, expected_label, state
):
    monkeypatch.setattr(timezone, 'now', lambda: datetime.fromisoformat(now_iso))
    due_at = datetime.fromisoformat(due_iso)
    with timezone.override(zone):
        assert_deadline_presentation(due_at, expected_label, state)


@pytest.mark.parametrize(
    ('zone', 'local_today', 'future_label'),
    [
        ('America/Recife', date(2026, 10, 2), 'Vence em 03/10/2026'),
        ('Asia/Tokyo', date(2026, 10, 3), 'Vence em 04/10/2026'),
        ('Pacific/Kiritimati', date(2026, 10, 3), 'Vence em 04/10/2026'),
        ('Pacific/Pago_Pago', date(2026, 10, 2), 'Vence em 03/10/2026'),
    ],
)
@pytest.mark.parametrize('kind', ['date', 'naive_midnight', 'naive_end_of_day'])
@pytest.mark.parametrize(
    ('days', 'state', 'label'),
    [(-1, 'overdue', 'Vencido'), (0, 'today', 'Vence hoje'), (1, 'future', None)],
)
def test_dates_and_naive_datetimes_keep_local_calendar(
    frozen_now, zone, local_today, future_label, kind, days, state, label
):
    due_at = local_today + timedelta(days=days)
    if kind != 'date':
        due_at = datetime.combine(
            due_at, time.min if kind == 'naive_midnight' else time(23, 59, 59)
        )
        assert timezone.is_naive(due_at)
    with timezone.override(zone):
        assert timezone.localdate() == local_today
        assert_deadline_presentation(due_at, label or future_label, state)


def test_same_instant_uses_each_active_timezone_not_project_default(frozen_now):
    due_at = datetime(2026, 10, 2, 12, tzinfo=UTC)
    with timezone.override('America/Recife'):
        assert_deadline_presentation(due_at, 'Vence hoje', 'today')
    with timezone.override('Asia/Tokyo'):
        assert_deadline_presentation(due_at, 'Vencido', 'overdue')
