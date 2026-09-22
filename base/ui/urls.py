from django.urls import path

from base.ui import views
from base.ui.actions import views as action_views
from crm.ui_views import SalesOrderCockpitView
from deviations.ui_views import QualityEventCockpitView
from formulations.ui_views import MasterFormulaCockpitView, MasterFormulaReuseView
from production.ui_views import ProductionOrderCockpitView
from qa.ui_views import LotReleaseCockpitView, StockLotDossierView


app_name = 'app'

urlpatterns = [
    path('', views.AppIndexView.as_view(), name='index'),
    path('minha-area/', views.PersonalAreaView.as_view(), name='personal_area'),
    path('busca-global/', views.GlobalSearchView.as_view(), name='global_search'),
    path('cep-lookup/', views.CepLookupView.as_view(), name='cep_lookup'),
    path(
        'dashboards/<slug:dashboard_slug>/', views.DashboardHubView.as_view(), name='dashboard_hub'
    ),
    path(
        'workspaces/operations/',
        views.WorkspaceView.as_view(workspace_slug='operations'),
        name='operations_workspace',
    ),
    path(
        'workspaces/quality/',
        views.WorkspaceView.as_view(workspace_slug='quality'),
        name='quality_workspace',
    ),
    path(
        'workspaces/workflow/',
        views.WorkspaceView.as_view(workspace_slug='workflow'),
        name='workflow_workspace',
    ),
    # Explicit operational maps must precede the generic resource detail route.
    path(
        'production/orders/<int:pk>/control-map/',
        views.ProductionControlMapView.as_view(),
        name='production_control_map',
    ),
    path(
        'production/orders/<int:pk>/results-map/',
        views.ProductionResultsMapView.as_view(),
        name='production_results_map',
    ),
    path('reports/catalog/', views.ReportCatalogView.as_view(), name='report_catalog'),
    path(
        'reports/catalog/<int:pk>/run/',
        views.ReportRunView.as_view(),
        name='report_run',
    ),
    path('<slug:module_slug>/', views.ModuleView.as_view(), name='module'),
    path(
        '<slug:module_slug>/<slug:resource_slug>/',
        views.ResourceListView.as_view(),
        name='resource_list',
    ),
    path(
        '<slug:module_slug>/<slug:resource_slug>/export/',
        views.ResourceExportView.as_view(),
        name='resource_export',
    ),
    path(
        '<slug:module_slug>/<slug:resource_slug>/new/',
        views.ResourceCreateView.as_view(),
        name='resource_create',
    ),
    path(
        '<slug:module_slug>/<slug:resource_slug>/actions/<slug:action_name>/',
        action_views.CollectionResourceActionView.as_view(),
        name='collection_action',
    ),
    path(
        'formulations/formulas/<int:pk>/reuse/',
        MasterFormulaReuseView.as_view(),
        {'module_slug': 'formulations', 'resource_slug': 'formulas'},
        name='master_formula_reuse',
    ),
    path(
        'formulations/formulas/<int:pk>/cockpit/',
        MasterFormulaCockpitView.as_view(),
        {'module_slug': 'formulations', 'resource_slug': 'formulas'},
        name='master_formula_cockpit',
    ),
    path(
        'production/orders/<int:pk>/cockpit/',
        ProductionOrderCockpitView.as_view(),
        {'module_slug': 'production', 'resource_slug': 'orders'},
        name='production_order_cockpit',
    ),
    path(
        'qa/lot-releases/<int:pk>/cockpit/',
        LotReleaseCockpitView.as_view(),
        {'module_slug': 'qa', 'resource_slug': 'lot-releases'},
        name='qa_lot_release_cockpit',
    ),
    path(
        'inventory/lots/<int:pk>/dossier/',
        StockLotDossierView.as_view(),
        {'module_slug': 'inventory', 'resource_slug': 'lots'},
        name='stock_lot_dossier',
    ),
    path(
        'deviations/events/<int:pk>/cockpit/',
        QualityEventCockpitView.as_view(),
        {'module_slug': 'deviations', 'resource_slug': 'events'},
        name='quality_event_cockpit',
    ),
    path(
        'crm/orders/<int:pk>/cockpit/',
        SalesOrderCockpitView.as_view(),
        {'module_slug': 'crm', 'resource_slug': 'orders'},
        name='sales_order_cockpit',
    ),
    path(
        '<slug:module_slug>/<slug:resource_slug>/<int:pk>/actions/<slug:action_name>/',
        action_views.ResourceActionView.as_view(),
        name='resource_action',
    ),
    path(
        '<slug:module_slug>/<slug:resource_slug>/<int:pk>/',
        views.ResourceDetailView.as_view(),
        name='resource_detail',
    ),
    path(
        '<slug:module_slug>/<slug:resource_slug>/kanban/',
        views.ResourceKanbanView.as_view(),
        name='resource_kanban',
    ),
    path(
        '<slug:module_slug>/<slug:resource_slug>/gantt/',
        views.ResourceGanttView.as_view(),
        name='resource_gantt',
    ),
    path(
        '<slug:module_slug>/<slug:resource_slug>/<int:pk>/viewer/',
        views.ResourceDocumentView.as_view(),
        name='resource_viewer',
    ),
    path(
        '<slug:module_slug>/<slug:resource_slug>/<int:pk>/chat/',
        views.ResourceChatView.as_view(),
        name='resource_chat',
    ),
    path(
        '<slug:module_slug>/<slug:resource_slug>/<int:pk>/tree/',
        views.ResourceTreeView.as_view(),
        name='resource_tree',
    ),
    path(
        '<slug:module_slug>/<slug:resource_slug>/<int:pk>/edit/',
        views.ResourceUpdateView.as_view(),
        name='resource_edit',
    ),
    path(
        '<slug:module_slug>/<slug:resource_slug>/<int:pk>/execute/',
        views.ResourceExecutionView.as_view(),
        name='resource_execute',
    ),
    path(
        '<slug:module_slug>/<slug:resource_slug>/<int:pk>/delete/',
        views.ResourceDeleteView.as_view(),
        name='resource_delete',
    ),
]
