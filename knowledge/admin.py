from django.contrib import admin

from base.admin_mixins import ImmutableAuditAdminMixin
from knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeIndexGeneration,
    KnowledgeIngestionLog,
    KnowledgeSource,
    RAGChatMessage,
    RAGChatSession,
    RAGCitation,
)


@admin.register(KnowledgeSource)
class KnowledgeSourceAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'title',
        'source_type',
        'publisher',
        'jurisdiction',
        'chat_eligible',
        'is_active',
    )
    list_filter = ('source_type', 'publisher', 'chat_eligible', 'is_active')
    search_fields = ('code', 'title', 'publisher', 'url')


@admin.register(KnowledgeDocument)
class KnowledgeDocumentAdmin(admin.ModelAdmin):
    list_display = ('title', 'source', 'document_type', 'status', 'retrieved_at')
    list_filter = ('document_type', 'status', 'source')
    search_fields = ('title', 'source__code', 'source__title', 'source_url', 'content_hash')
    autocomplete_fields = ('source',)
    readonly_fields = ('content_hash', 'retrieved_at')


@admin.register(KnowledgeChunk)
class KnowledgeChunkAdmin(ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = ('document', 'chunk_index', 'section_reference', 'page_number', 'token_count')
    list_filter = ('source', 'document')
    search_fields = ('title', 'section_reference', 'content', 'document__title', 'source__title')
    autocomplete_fields = ('source', 'document')


class ChatOwnerAdminMixin(admin.ModelAdmin):
    owner_lookup = 'created_by'

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if not request.user.is_authenticated or not request.user.is_active:
            return queryset.none()
        return queryset.filter(**{self.owner_lookup: request.user})


@admin.register(RAGChatSession)
class RAGChatSessionAdmin(ChatOwnerAdminMixin, ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = ('title', 'created_by', 'status', 'last_question_at')
    list_filter = ('status', 'last_question_at')
    search_fields = ('title', 'created_by__email')
    autocomplete_fields = ('created_by',)


@admin.register(RAGChatMessage)
class RAGChatMessageAdmin(ChatOwnerAdminMixin, ImmutableAuditAdminMixin, admin.ModelAdmin):
    owner_lookup = 'session__created_by'
    list_display = ('session', 'role', 'status', 'model_name', 'latency_ms', 'created_by')
    list_filter = ('role', 'status', 'model_name')
    search_fields = ('content', 'error_message', 'created_by__email')
    autocomplete_fields = ('session', 'created_by')


@admin.register(RAGCitation)
class RAGCitationAdmin(ChatOwnerAdminMixin, ImmutableAuditAdminMixin, admin.ModelAdmin):
    owner_lookup = 'message__session__created_by'
    list_display = ('message', 'title', 'section_reference', 'relevance_score')
    list_filter = ('source', 'document')
    search_fields = ('title', 'excerpt', 'source_url')
    autocomplete_fields = ('message', 'source', 'document', 'chunk')


@admin.register(KnowledgeIngestionLog)
class KnowledgeIngestionLogAdmin(ImmutableAuditAdminMixin, admin.ModelAdmin):
    list_display = ('source', 'document', 'status', 'chunks_created', 'started_at', 'completed_at')
    list_filter = ('status', 'source')
    search_fields = ('source__code', 'source__title', 'error_message')
    autocomplete_fields = ('source', 'document')


@admin.register(KnowledgeIndexGeneration)
class KnowledgeIndexGenerationAdmin(admin.ModelAdmin):
    list_display = (
        'generation_id',
        'status',
        'embedding_model',
        'embedding_dimensions',
        'chunk_count',
        'activated_at',
    )
    list_filter = ('status', 'embedding_model')
    search_fields = ('generation_id', 'redis_index_name', 'error_message')
    readonly_fields = (
        'generation_id',
        'redis_index_name',
        'embedding_model',
        'embedding_dimensions',
        'chunk_count',
        'manifest_hash',
        'activated_at',
        'error_message',
    )
    actions = None
