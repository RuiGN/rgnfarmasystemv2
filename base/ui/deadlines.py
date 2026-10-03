"""Prazos operacionais autorizados exibidos nos workspaces."""

from datetime import date, datetime, time

from django.urls import reverse
from django.utils import timezone

from production.models import ProductionOrder
from qa.models import BatchRecordChecklistItem
from workflow.models import ApprovalTask, WorkflowNotification

from .presentation import DeadlineItem, _deadline_local_date


def _deadline_tone(due_at: date | datetime) -> tuple[str, str]:
    due_date = _deadline_local_date(due_at)
    if due_date < timezone.localdate():
        return 'danger', 'feather-alert-triangle'
    if due_date == timezone.localdate():
        return 'warning', 'feather-clock'
    return 'primary', 'feather-calendar'


def _sort_due_at(value: date | datetime) -> datetime:
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            return timezone.make_aware(value, timezone.get_current_timezone())
        return timezone.localtime(value, timezone.get_current_timezone())
    return timezone.make_aware(datetime.combine(value, time.min), timezone.get_current_timezone())


def _production_deadlines() -> list[DeadlineItem]:
    orders = ProductionOrder.objects.filter(scheduled_end__isnull=False).exclude(
        status__in=(
            ProductionOrder.Status.COMPLETED,
            ProductionOrder.Status.CANCELLED,
            ProductionOrder.Status.CLOSED,
        )
    )
    return [
        DeadlineItem(
            title=order.order_number,
            description='Fim previsto da ordem de produção.',
            due_at=order.scheduled_end,
            tone=_deadline_tone(order.scheduled_end)[0],
            icon=_deadline_tone(order.scheduled_end)[1],
            url=reverse('app:resource_detail', args=('production', 'orders', order.pk)),
        )
        for order in orders
    ]


def _quality_deadlines() -> list[DeadlineItem]:
    items = (
        BatchRecordChecklistItem.objects.select_related('review')
        .filter(due_date__isnull=False)
        .exclude(
            status__in=(
                BatchRecordChecklistItem.Status.COMPLETED,
                BatchRecordChecklistItem.Status.NOT_APPLICABLE,
            )
        )
    )
    return [
        DeadlineItem(
            title=item.title,
            description=f'Item do checklist da revisão {item.review.review_number}.',
            due_at=item.due_date,
            tone=_deadline_tone(item.due_date)[0],
            icon=_deadline_tone(item.due_date)[1],
            url=reverse('app:resource_detail', args=('qa', 'checklist-items', item.pk)),
        )
        for item in items
    ]


def _workflow_deadlines(user) -> list[DeadlineItem]:
    deadlines: list[DeadlineItem] = []
    if user.has_perm('workflow.view_approvaltask'):
        tasks = ApprovalTask.objects.filter(assigned_to=user, due_at__isnull=False).exclude(
            status__in=(
                ApprovalTask.Status.APPROVED,
                ApprovalTask.Status.REJECTED,
                ApprovalTask.Status.CANCELLED,
            )
        )
        deadlines.extend(
            DeadlineItem(
                title=task.title,
                description=task.description or 'Tarefa de aprovação pendente.',
                due_at=task.due_at,
                tone=_deadline_tone(task.due_at)[0],
                icon=_deadline_tone(task.due_at)[1],
                url=reverse('app:resource_detail', args=('workflow', 'tasks', task.pk)),
            )
            for task in tasks
        )
    if user.has_perm('workflow.view_workflownotification'):
        notifications = WorkflowNotification.objects.filter(
            recipient=user,
            due_at__isnull=False,
        ).exclude(status=WorkflowNotification.Status.ARCHIVED)
        deadlines.extend(
            DeadlineItem(
                title=notification.title,
                description=notification.message,
                due_at=notification.due_at,
                tone=_deadline_tone(notification.due_at)[0],
                icon=_deadline_tone(notification.due_at)[1],
                url=reverse(
                    'app:resource_detail', args=('workflow', 'notifications', notification.pk)
                ),
            )
            for notification in notifications
        )
    return deadlines


def build_workspace_deadlines(
    request, workspace_slug: str, limit: int = 5
) -> tuple[DeadlineItem, ...]:
    """Retorna prazos do workspace apenas para fontes que o usuário pode consultar."""

    user = request.user
    deadlines: list[DeadlineItem] = []
    if workspace_slug == 'operations' and user.has_perm('production.view_productionorder'):
        deadlines.extend(_production_deadlines())
    elif workspace_slug == 'quality' and user.has_perm('qa.view_batchrecordchecklistitem'):
        deadlines.extend(_quality_deadlines())
    elif workspace_slug == 'workflow':
        deadlines.extend(_workflow_deadlines(user))

    normalized_limit = max(0, limit)
    ordered = sorted(
        deadlines,
        key=lambda item: (_sort_due_at(item.due_at), item.title, item.description, item.url),
    )
    return tuple(ordered[:normalized_limit])
