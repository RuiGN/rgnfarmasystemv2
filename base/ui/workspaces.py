from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from django.urls import reverse

from inventory.models import StockLot
from production.models import ProductionOrder
from quality.models import LaboratoryInvestigation, QualityAnalysis, QualitySample
from workflow.models import ApprovalTask, AsyncJobStatus, WorkflowNotification

from .presentation import ProgressMetric
from .registry import get_module


class WorkspaceMetric(ProgressMetric):
    """Adapta a assinatura legada dos workspaces ao contrato compartilhado."""

    def __init__(
        self,
        label: str,
        value: int | float,
        icon: str,
        tone: str,
        badge: str,
        url: str,
        required_permission: str = '',
        target: int | float | None = None,
        helper: str = '',
    ):
        super().__init__(
            label,
            value,
            icon,
            tone,
            badge,
            url,
            target,
            helper,
            required_permission,
        )


@dataclass(frozen=True)
class WorkspaceLink:
    label: str
    icon: str
    url: str
    required_module_slug: str = ''

    def can_view(self, user: Any) -> bool:
        if not self.required_module_slug:
            return True
        module = get_module(self.required_module_slug)
        return module is not None and module.can_view(user)


@dataclass(frozen=True)
class WorkspaceContent:
    metrics: tuple[WorkspaceMetric, ...]
    quick_links: tuple[WorkspaceLink, ...]

    def visible_to(self, user: Any) -> 'WorkspaceContent':
        return WorkspaceContent(
            metrics=tuple(metric for metric in self.metrics if metric.can_view(user)),
            quick_links=tuple(link for link in self.quick_links if link.can_view(user)),
        )


@dataclass(frozen=True)
class WorkspaceConfig:
    slug: str
    title: str
    description: str
    breadcrumb_label: str
    module_slug: str
    quick_links_title: str
    route_name: str
    navigation_label: str
    icon: str
    order: int
    builder: Callable[[Any], WorkspaceContent]

    @property
    def navigation_url(self) -> str:
        return reverse(self.route_name)

    def build_content(self, request: Any) -> WorkspaceContent:
        return self.builder(request).visible_to(request.user)

    def build_deadlines(self, request: Any, limit: int = 5):
        from .deadlines import build_workspace_deadlines

        return build_workspace_deadlines(request, self.slug, limit=limit)


def _resource_url(module_slug: str, resource_slug: str) -> str:
    return reverse('app:resource_list', args=(module_slug, resource_slug))


def _module_url(module_slug: str) -> str:
    return reverse('app:module', args=(module_slug,))


def build_operations_content(request: Any) -> WorkspaceContent:
    metrics = []
    if request.user.has_perm('production.view_productionorder'):
        metrics.append(
            WorkspaceMetric(
                label='Ordens em execução',
                value=ProductionOrder.objects.filter(
                    status=ProductionOrder.Status.IN_PROGRESS
                ).count(),
                icon='feather-play-circle',
                tone='primary',
                badge='Produção',
                url=_resource_url('production', 'orders'),
                target=ProductionOrder.objects.exclude(
                    status__in=(
                        ProductionOrder.Status.COMPLETED,
                        ProductionOrder.Status.CANCELLED,
                        ProductionOrder.Status.CLOSED,
                    )
                ).count(),
                required_permission='production.view_productionorder',
            )
        )
    if request.user.has_perm('inventory.view_stocklot'):
        metrics.append(
            WorkspaceMetric(
                label='Lotes em estoque',
                value=StockLot.objects.count(),
                icon='feather-archive',
                tone='success',
                badge='Estoque',
                url=_resource_url('inventory', 'lots'),
                required_permission='inventory.view_stocklot',
            )
        )
    if request.user.has_perm('quality.view_qualitysample'):
        metrics.append(
            WorkspaceMetric(
                label='Amostras pendentes',
                value=QualitySample.objects.exclude(
                    status__in=(
                        QualitySample.Status.APPROVED,
                        QualitySample.Status.REJECTED,
                        QualitySample.Status.CANCELLED,
                    )
                ).count(),
                icon='feather-check-square',
                tone='warning',
                badge='Qualidade',
                url=_resource_url('quality', 'samples'),
                required_permission='quality.view_qualitysample',
            )
        )
    return WorkspaceContent(
        metrics=tuple(metrics),
        quick_links=(
            WorkspaceLink(
                label='Planejamento',
                icon='feather-calendar',
                url=_module_url('planning'),
                required_module_slug='planning',
            ),
            WorkspaceLink(
                label='Compras',
                icon='feather-shopping-cart',
                url=_module_url('procurement'),
                required_module_slug='procurement',
            ),
            WorkspaceLink(
                label='Qualidade',
                icon='feather-check-square',
                url=_module_url('quality'),
                required_module_slug='quality',
            ),
        ),
    )


def build_quality_content(request: Any) -> WorkspaceContent:
    metrics = []
    if request.user.has_perm('quality.view_qualitysample'):
        metrics.append(
            WorkspaceMetric(
                label='Amostras em análise',
                value=QualitySample.objects.filter(status=QualitySample.Status.IN_ANALYSIS).count(),
                icon='feather-droplet',
                tone='warning',
                badge='Amostragem',
                url=_resource_url('quality', 'samples'),
                target=QualitySample.objects.exclude(
                    status__in=(
                        QualitySample.Status.APPROVED,
                        QualitySample.Status.REJECTED,
                        QualitySample.Status.CANCELLED,
                    )
                ).count(),
                required_permission='quality.view_qualitysample',
            )
        )
    if request.user.has_perm('quality.view_qualityanalysis'):
        metrics.append(
            WorkspaceMetric(
                label='Análises pendentes',
                value=QualityAnalysis.objects.filter(status=QualityAnalysis.Status.PENDING).count(),
                icon='feather-activity',
                tone='primary',
                badge='Laboratório',
                url=_resource_url('quality', 'analyses'),
                required_permission='quality.view_qualityanalysis',
            )
        )
    if request.user.has_perm('quality.view_laboratoryinvestigation'):
        metrics.append(
            WorkspaceMetric(
                label='Investigações abertas',
                value=LaboratoryInvestigation.objects.exclude(
                    status__in=(
                        LaboratoryInvestigation.Status.CONCLUDED,
                        LaboratoryInvestigation.Status.CANCELLED,
                    )
                ).count(),
                icon='feather-alert-triangle',
                tone='danger',
                badge='Investigação',
                url=_resource_url('quality', 'investigations'),
                required_permission='quality.view_laboratoryinvestigation',
            )
        )
    return WorkspaceContent(
        metrics=tuple(metrics),
        quick_links=(
            WorkspaceLink(
                label='Garantia da qualidade',
                icon='feather-shield',
                url=_module_url('qa'),
                required_module_slug='qa',
            ),
            WorkspaceLink(
                label='Desvios',
                icon='feather-alert-circle',
                url=_module_url('deviations'),
                required_module_slug='deviations',
            ),
            WorkspaceLink(
                label='CAPA',
                icon='feather-target',
                url=_module_url('capa'),
                required_module_slug='capa',
            ),
            WorkspaceLink(
                label='Documentos',
                icon='feather-file-text',
                url=_module_url('documents'),
                required_module_slug='documents',
            ),
        ),
    )


def build_workflow_content(request: Any) -> WorkspaceContent:
    metrics = []
    if request.user.has_perm('workflow.view_approvaltask'):
        metrics.append(
            WorkspaceMetric(
                label='Aprovações pendentes',
                value=ApprovalTask.objects.filter(status=ApprovalTask.Status.PENDING).count(),
                icon='feather-check-square',
                tone='warning',
                badge='Aprovações',
                url=_resource_url('workflow', 'tasks'),
                required_permission='workflow.view_approvaltask',
            )
        )
    if request.user.has_perm('workflow.view_workflownotification'):
        metrics.append(
            WorkspaceMetric(
                label='Notificações não lidas',
                value=WorkflowNotification.objects.filter(
                    recipient=request.user,
                    status=WorkflowNotification.Status.UNREAD,
                ).count(),
                icon='feather-bell',
                tone='primary',
                badge='Avisos',
                url=_resource_url('workflow', 'notifications'),
                target=WorkflowNotification.objects.filter(recipient=request.user)
                .exclude(status=WorkflowNotification.Status.ARCHIVED)
                .count(),
                required_permission='workflow.view_workflownotification',
            )
        )
    if request.user.has_perm('workflow.view_asyncjobstatus'):
        metrics.append(
            WorkspaceMetric(
                label='Jobs em execução',
                value=AsyncJobStatus.objects.filter(
                    status__in=(AsyncJobStatus.Status.PENDING, AsyncJobStatus.Status.RUNNING)
                ).count(),
                icon='feather-loader',
                tone='info',
                badge='Processamento',
                url=_resource_url('workflow', 'async-jobs'),
                required_permission='workflow.view_asyncjobstatus',
            )
        )
    return WorkspaceContent(
        metrics=tuple(metrics),
        quick_links=(
            WorkspaceLink(
                label='Todos os recursos',
                icon='feather-git-pull-request',
                url=_module_url('workflow'),
                required_module_slug='workflow',
            ),
            WorkspaceLink(
                label='Compliance',
                icon='feather-shield',
                url=_module_url('compliance'),
                required_module_slug='compliance',
            ),
            WorkspaceLink(
                label='Governança',
                icon='feather-settings',
                url=_module_url('governance'),
                required_module_slug='governance',
            ),
        ),
    )


WORKSPACES = {
    'operations': WorkspaceConfig(
        slug='operations',
        title='Cockpit operacional',
        description='Produção, estoque e qualidade em um único contexto.',
        breadcrumb_label='Operação',
        module_slug='production',
        quick_links_title='Acessos rápidos',
        route_name='app:operations_workspace',
        navigation_label='Cockpit operacional',
        icon='feather-activity',
        order=10,
        builder=build_operations_content,
    ),
    'quality': WorkspaceConfig(
        slug='quality',
        title='Cockpit de qualidade',
        description='Amostragem, análises e investigações sob controle.',
        breadcrumb_label='Qualidade',
        module_slug='quality',
        quick_links_title='Fluxos de qualidade',
        route_name='app:quality_workspace',
        navigation_label='Cockpit de qualidade',
        icon='feather-check-square',
        order=20,
        builder=build_quality_content,
    ),
    'workflow': WorkspaceConfig(
        slug='workflow',
        title='Fluxo de trabalho',
        description='Aprovações, notificações e processamento assíncrono.',
        breadcrumb_label='Fluxo de trabalho',
        module_slug='workflow',
        quick_links_title='Governança operacional',
        route_name='app:workflow_workspace',
        navigation_label='Central de workflow',
        icon='feather-git-pull-request',
        order=30,
        builder=build_workflow_content,
    ),
}


def get_workspace(slug: str) -> WorkspaceConfig | None:
    return WORKSPACES.get(slug)
