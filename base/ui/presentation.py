from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from unicodedata import combining, normalize

from django.core.exceptions import FieldDoesNotExist
from django.urls import reverse
from django.utils import timezone
from django.utils.formats import date_format


@dataclass(frozen=True)
class StatusPresentation:
    """Estado semântico pronto para um componente visual acessível."""

    label: str
    tone: str
    icon: str


@dataclass(frozen=True)
class AuditEntry:
    """Evento persistido normalizado para apresentação somente leitura."""

    occurred_at: datetime
    actor_label: str
    action_label: str
    details: str
    reason: str
    status: StatusPresentation


def _normalize_status(value: Any) -> str:
    return ''.join(
        character for character in normalize('NFKD', str(value or '')) if not combining(character)
    ).lower()


def resolve_status(value: Any) -> StatusPresentation:
    """Classifica um estado sem alterar o rótulo visível ao usuário."""

    label = str(value or '')
    normalized = _normalize_status(label)

    if 'nao lida' in normalized:
        return StatusPresentation(label, 'warning', 'feather-clock')
    if any(token in normalized for token in ('nao enviad', 'nao conclu', 'nao liberad')):
        return StatusPresentation(label, 'danger', 'feather-alert-triangle')
    if any(
        token in normalized
        for token in (
            'nao aprov',
            'reprov',
            'rejeit',
            'bloque',
            'vencid',
            'oos',
            'cancel',
            'critic',
            'falh',
            'danger',
        )
    ):
        return StatusPresentation(label, 'danger', 'feather-alert-triangle')
    if any(token in normalized for token in ('pend', 'analis', 'em revis', 'proximo prazo')):
        return StatusPresentation(label, 'warning', 'feather-clock')
    if any(token in normalized for token in ('submet', 'process', 'execu')):
        return StatusPresentation(label, 'info', 'feather-loader')
    if any(token in normalized for token in ('rascunh', 'arquiv')):
        return StatusPresentation(label, 'secondary', 'feather-archive')
    if any(
        token in normalized
        for token in (
            'aprov',
            'liberad',
            'conclu',
            'encerr',
            'vigent',
            'enviad',
            'revisad',
            'ativo',
            'reconhec',
        )
    ):
        return StatusPresentation(label, 'success', 'feather-check-circle')
    return StatusPresentation(label, 'secondary', 'feather-info')


@dataclass(frozen=True)
class DetailSummaryItem:
    """Dado lateral de um registro, já pronto para apresentação."""

    field_name: str
    label: str
    value: str
    icon: str
    is_status: bool = False
    status: StatusPresentation | None = None


_DETAIL_IDENTIFIER_FIELDS = ('code', 'order_number', 'batch_number', 'document_number')
_DETAIL_PERSON_FIELDS = ('responsible', 'owner', 'assigned_to')
_DETAIL_DATE_FIELDS = (
    'due_date',
    'due_at',
    'scheduled_end',
    'valid_until',
    'expiry_date',
    'created_at',
    'updated_at',
)
_DETAIL_SUMMARY_FIELDS = (
    *_DETAIL_IDENTIFIER_FIELDS,
    *_DETAIL_PERSON_FIELDS,
    *_DETAIL_DATE_FIELDS,
)


def _format_detail_summary_value(value: Any) -> str:
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            value = timezone.localtime(value)
        return date_format(value, 'd/m/Y H:i')
    if isinstance(value, date):
        return date_format(value, 'd/m/Y')
    return str(value)


def build_detail_summary(obj: Any, status: Any) -> tuple[DetailSummaryItem, ...]:
    """Extrai somente os dados operacionais autorizados para a lateral."""

    items = []
    for field_name in _DETAIL_SUMMARY_FIELDS:
        try:
            field = obj._meta.get_field(field_name)
        except FieldDoesNotExist:
            continue

        value = getattr(obj, field_name, None)
        if value in (None, ''):
            continue

        icon = (
            'feather-hash'
            if field_name in _DETAIL_IDENTIFIER_FIELDS
            else 'feather-user'
            if field_name in _DETAIL_PERSON_FIELDS
            else 'feather-calendar'
        )
        items.append(
            DetailSummaryItem(
                field_name=field_name,
                label=str(field.verbose_name),
                value=_format_detail_summary_value(value),
                icon=icon,
            )
        )

    if status not in (None, '', '-'):
        try:
            status_label = str(obj._meta.get_field('status').verbose_name)
        except FieldDoesNotExist:
            status_label = 'status'
        items.append(
            DetailSummaryItem(
                field_name='status',
                label=status_label,
                value=str(status),
                icon='feather-activity',
                is_status=True,
                status=resolve_status(status),
            )
        )

    return tuple(items)


@dataclass(frozen=True)
class ProgressMetric:
    label: str
    value: int | float
    icon: str
    tone: str
    badge: str
    url: str
    target: int | float | None = None
    helper: str = ''
    required_permission: str = ''

    @property
    def has_progress(self) -> bool:
        return self.target is not None and self.target > 0

    @property
    def percent(self) -> int:
        target = self.target
        if target is None or target <= 0:
            return 0
        return max(0, min(100, round(float(self.value) / float(target) * 100)))

    def can_view(self, user: Any) -> bool:
        return not self.required_permission or user.has_perm(self.required_permission)


def _deadline_local_date(value: date | datetime) -> date:
    """Usa o calendário ativo; datas e datetimes naive já são locais."""
    if isinstance(value, datetime):
        if timezone.is_aware(value):
            return timezone.localtime(value).date()
        return value.date()
    return value


@dataclass(frozen=True)
class DeadlineItem:
    """Representa um prazo operacional que pode ser exibido no workspace."""

    title: str
    description: str
    due_at: date | datetime
    tone: str
    icon: str
    url: str

    @property
    def temporal_label(self) -> str:
        due_date = _deadline_local_date(self.due_at)
        today = timezone.localdate()
        if due_date < today:
            return 'Vencido'
        if due_date == today:
            return 'Vence hoje'
        return f'Vence em {date_format(due_date, "d/m/Y")}'


@dataclass(frozen=True)
class NotificationPreview:
    """Projeção autorizada de uma notificação para o cabeçalho."""

    title: str
    criticality_label: str
    source_module_label: str
    tone: str
    icon: str
    created_at: datetime
    is_unread: bool
    url: str

    @classmethod
    def from_model(cls, notification: Any) -> 'NotificationPreview':
        criticality = getattr(notification, 'criticality', '')
        presentations = {
            'low': ('Baixa', 'secondary', 'feather-info'),
            'medium': ('Média', 'primary', 'feather-bell'),
            'high': ('Alta', 'warning', 'feather-alert-triangle'),
            'critical': ('Crítica', 'danger', 'feather-alert-octagon'),
        }
        presentation = presentations.get(criticality)
        if presentation is None:
            label = str(notification.get_criticality_display())
            tone, icon = 'secondary', 'feather-bell'
        else:
            label, tone, icon = presentation
        return cls(
            title=notification.title,
            criticality_label=label,
            source_module_label=str(notification.get_source_module_display())
            or 'Origem não informada',
            tone=tone,
            icon=icon,
            created_at=notification.created_at,
            is_unread=notification.status == 'unread',
            url=reverse('app:resource_detail', args=('workflow', 'notifications', notification.pk)),
        )
