from django.contrib import admin
from base.admin_mixins import AutomaticGeneratedFieldsAdminMixin, ImmutableAuditAdminMixin
from integrations.models import (
    ApiCallLog,
    ApiClientApplication,
    IntegrationConnector,
    IntegrationEvent,
    LabelPrinterSettings,
)


@admin.register(LabelPrinterSettings)
class LabelPrinterSettingsAdmin(admin.ModelAdmin):
    list_display = ('name', 'host', 'port', 'protocol', 'width_mm', 'height_mm', 'is_active')
    list_filter = ('protocol', 'is_active')
    search_fields = ('name', 'host')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(IntegrationConnector)
class IntegrationConnectorAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = (
        'code',
        'name',
        'provider_type',
        'auth_type',
        'status',
        'responsible',
        'last_tested_at',
    )
    list_filter = ('provider_type', 'auth_type', 'status', 'is_active', 'last_tested_at')
    search_fields = ('code', 'name', 'base_url', 'secret_reference', 'responsible__email')
    autocomplete_fields = ('responsible',)
    readonly_fields = ('last_tested_at', 'last_error', 'created_at', 'updated_at')


@admin.register(ApiClientApplication)
class ApiClientApplicationAdmin(AutomaticGeneratedFieldsAdminMixin, admin.ModelAdmin):
    list_display = (
        'code',
        'name',
        'client_id',
        'status',
        'created_by',
        'expires_at',
        'last_used_at',
    )
    list_filter = ('status', 'expires_at', 'last_used_at')
    search_fields = ('code', 'name', 'client_id', 'created_by__email')
    autocomplete_fields = ('created_by',)
    readonly_fields = ('secret_hash', 'last_used_at', 'created_at', 'updated_at')


@admin.register(ApiCallLog)
class ApiCallLogAdmin(ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = (
        'method',
        'path',
        'api_version',
        'status_code',
        'outcome',
        'user',
        'duration_ms',
        'created_at',
    )
    list_filter = ('api_version', 'method', 'status_code', 'outcome', 'created_at')
    search_fields = ('request_id', 'path', 'endpoint_name', 'user__email', 'error_message')
    autocomplete_fields = ('user', 'client_application')
    readonly_fields = (
        'request_id',
        'api_version',
        'method',
        'path',
        'endpoint_name',
        'status_code',
        'outcome',
        'user',
        'client_application',
        'remote_addr',
        'user_agent',
        'duration_ms',
        'safe_context',
        'error_message',
        'created_at',
        'updated_at',
    )


@admin.register(IntegrationEvent)
class IntegrationEventAdmin(ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = ('event_type', 'connector', 'api_client_application', 'actor', 'occurred_at')
    list_filter = ('event_type', 'occurred_at')
    search_fields = (
        'connector__code',
        'connector__name',
        'api_client_application__code',
        'actor__email',
        'message',
    )
    autocomplete_fields = ('connector', 'api_client_application', 'actor')
    readonly_fields = (
        'event_type',
        'occurred_at',
        'message',
        'safe_context',
        'created_at',
        'updated_at',
    )
