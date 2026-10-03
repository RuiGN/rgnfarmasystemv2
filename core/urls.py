from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from accounts.views import admin_login_redirect
from core.views import health_check, home, readiness_check

urlpatterns = [
    path('', home, name='home'),
    path('health/', health_check, name='health'),
    path('ready/', readiness_check, name='readiness'),
    path('accounts/', include('accounts.urls')),
    path('app/', include('base.ui.urls')),
    path('api/v1/', include('core.api_v1_urls')),
    path('api/accounts/', include('accounts.api_urls')),
    path('api/ai-agents/', include('ai_agents.urls')),
    path('api/audits/', include('audits.urls')),
    path('api/capa/', include('capa.urls')),
    path('api/changes/', include('changes.urls')),
    path('api/compliance/', include('compliance.urls')),
    path('api/costing/', include('costing.urls')),
    path('api/crm/', include('crm.urls')),
    path('api/deviations/', include('deviations.urls')),
    path('api/documents/', include('documents.urls')),
    path('api/files/', include('files.urls')),
    path('api/finance/', include('finance.urls')),
    path('api/fiscal/', include('fiscal.urls')),
    path('api/formulations/', include('formulations.urls')),
    path('api/governance/', include('governance.urls')),
    path('api/integrations/', include('integrations.urls')),
    path('api/knowledge/', include('knowledge.urls')),
    path('api/inventory/', include('inventory.urls')),
    path('api/masters/', include('masters.urls')),
    path('api/planning/', include('planning.urls')),
    path('api/procurement/', include('procurement.urls')),
    path('api/production/', include('production.urls')),
    path('api/qa/', include('qa.urls')),
    path('api/quality/', include('quality.urls')),
    path('api/recalls/', include('recalls.urls')),
    path('api/reports/', include('reports.urls')),
    path('api/risks/', include('risks.urls')),
    path('api/training/', include('training.urls')),
    path('api/workflow/', include('workflow.urls')),
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path(
        'api/docs/',
        SpectacularSwaggerView.as_view(url_name='schema'),
        name='swagger-ui',
    ),
    path('admin/login/', admin_login_redirect, name='admin-login-redirect'),
    path('admin/', admin.site.urls),
]

handler403 = 'core.views.permission_denied'
