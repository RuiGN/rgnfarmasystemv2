import hashlib
import math
import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from base.models import SingleInstanceModel
from base.sequences import AutoCodeMixin


TOKEN_PATTERN = re.compile(r'[\wÀ-ÿ]+', re.IGNORECASE)


def _tokens(value):
    return [token.lower() for token in TOKEN_PATTERN.findall(value or '') if len(token) > 2]


def content_hash(value):
    return hashlib.sha256((value or '').encode('utf-8')).hexdigest()


def deterministic_embedding(value, dimensions=64):
    vector = [0.0] * dimensions
    for token in _tokens(value):
        digest = hashlib.sha256(token.encode('utf-8')).digest()
        index = int.from_bytes(digest[:2], 'big') % dimensions
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(item * item for item in vector)) or 1.0
    return [round(item / norm, 6) for item in vector]


class KnowledgeSource(AutoCodeMixin, SingleInstanceModel):
    CODE_PREFIX = 'KSR'

    class SourceType(models.TextChoices):
        REGULATION = 'regulation', 'Legislação'
        TECHNICAL_REFERENCE = 'technical_reference', 'Referência técnica'
        GUIDELINE = 'guideline', 'Guia'
        STANDARD = 'standard', 'Norma'
        BOOK_REFERENCE = 'book_reference', 'Referência bibliográfica'
        WEB = 'web', 'Página web'
        SYSTEM_MANUAL = 'system_manual', 'Manual do sistema'
        OTHER = 'other', 'Outra'

    code = models.CharField('código', max_length=100, blank=True)
    title = models.CharField('título', max_length=255)
    source_type = models.CharField('tipo', max_length=32, choices=SourceType.choices)
    publisher = models.CharField('publicador', max_length=160)
    jurisdiction = models.CharField('jurisdição', max_length=80, blank=True)
    version = models.CharField('versão', max_length=120, blank=True)
    url = models.URLField('URL', max_length=1000, blank=True)
    license_note = models.TextField('nota de licença', blank=True)
    is_official = models.BooleanField('fonte oficial', default=False)
    is_active = models.BooleanField('ativo', default=True)
    chat_eligible = models.BooleanField('elegível para o manual do ERP', default=False)
    metadata = models.JSONField('metadados', default=dict, blank=True)

    class Meta:
        ordering = ['publisher', 'code']
        constraints = [
            models.UniqueConstraint(fields=['code'], name='unique_knowledge_source_code'),
        ]
        indexes = [
            models.Index(fields=['source_type', 'is_active']),
            models.Index(
                fields=['source_type', 'chat_eligible', 'is_active'],
                name='knowledge_source_manual_idx',
            ),
            models.Index(fields=['publisher']),
            models.Index(fields=['code']),
        ]
        verbose_name = 'fonte de conhecimento'
        verbose_name_plural = 'fontes de conhecimento'

    def save(self, *args, **kwargs):
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if not self.code.strip():
            errors['code'] = 'Informe o código da fonte.'
        if not self.title.strip():
            errors['title'] = 'Informe o título da fonte.'
        if self.source_type == self.SourceType.BOOK_REFERENCE and not self.license_note:
            errors['license_note'] = 'Referências bibliográficas protegidas exigem nota de licença.'
        if not isinstance(self.metadata or {}, dict):
            errors['metadata'] = 'Metadados devem ser um objeto chave/valor.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.code} - {self.title}'

    @property
    def is_manual_source(self):
        return self.source_type == self.SourceType.SYSTEM_MANUAL and self.chat_eligible


class KnowledgeDocument(SingleInstanceModel):
    class DocumentType(models.TextChoices):
        HTML = 'html', 'HTML'
        PDF = 'pdf', 'PDF'
        TEXT = 'text', 'Texto'
        REFERENCE = 'reference', 'Referência'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pendente'
        INGESTED = 'ingested', 'Ingerido'
        FAILED = 'failed', 'Falhou'

    source = models.ForeignKey(
        KnowledgeSource,
        on_delete=models.PROTECT,
        related_name='documents',
        verbose_name='fonte',
    )
    title = models.CharField('título', max_length=255)
    document_type = models.CharField(
        'tipo de documento', max_length=24, choices=DocumentType.choices
    )
    source_url = models.URLField('URL de origem', max_length=1000, blank=True)
    version_label = models.CharField('versão', max_length=120, blank=True)
    published_on = models.DateField('publicado em', null=True, blank=True)
    retrieved_at = models.DateTimeField('coletado em', null=True, blank=True)
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.PENDING
    )
    content_hash = models.CharField('hash do conteúdo', max_length=64)
    extracted_text = models.TextField('texto extraído', blank=True)
    error_message = models.TextField('erro', blank=True)
    metadata = models.JSONField('metadados', default=dict, blank=True)

    class Meta:
        ordering = ['source__publisher', 'title']
        constraints = [
            models.UniqueConstraint(
                fields=['source', 'content_hash'],
                name='unique_knowledge_document_hash',
            ),
        ]
        indexes = [
            models.Index(fields=['source', 'status']),
            models.Index(fields=['document_type']),
            models.Index(fields=['content_hash']),
            models.Index(fields=['retrieved_at']),
        ]
        verbose_name = 'documento de conhecimento'
        verbose_name_plural = 'documentos de conhecimento'

    def save(self, *args, **kwargs):
        if not self.content_hash:
            self.content_hash = content_hash(self.extracted_text or self.source_url or self.title)
        if not getattr(self, '_skip_clean', False):
            self.full_clean()
        super().save(*args, **kwargs)

    def clean(self):
        super().clean()
        errors = {}
        if not self.title.strip():
            errors['title'] = 'Informe o título do documento.'
        if not isinstance(self.metadata or {}, dict):
            errors['metadata'] = 'Metadados devem ser um objeto chave/valor.'
        if self.status == self.Status.FAILED and not self.error_message:
            errors['error_message'] = 'Documento com falha exige mensagem de erro.'
        if errors:
            raise ValidationError(errors)

    @transaction.atomic
    def replace_chunks(self, chunks):
        self.chunks.all().delete()
        objects = []
        for index, chunk in enumerate(chunks):
            text = ' '.join(str(chunk.get('content', '')).split())
            if not text:
                continue
            objects.append(
                KnowledgeChunk(
                    source=self.source,
                    document=self,
                    chunk_index=index,
                    title=chunk.get('title') or self.title,
                    section_reference=chunk.get('section_reference', ''),
                    page_number=chunk.get('page_number'),
                    content=text,
                    content_hash=content_hash(f'{self.pk}:{index}:{text}'),
                    token_count=len(_tokens(text)),
                    embedding_vector=deterministic_embedding(text),
                    metadata=chunk.get('metadata') or {},
                )
            )
        KnowledgeChunk.objects.bulk_create(objects)
        self.status = self.Status.INGESTED
        self.error_message = ''
        self.save(update_fields=['status', 'error_message', 'updated_at'])
        return objects

    def __str__(self):
        return self.title


class KnowledgeChunk(SingleInstanceModel):
    source = models.ForeignKey(
        KnowledgeSource,
        on_delete=models.PROTECT,
        related_name='chunks',
        verbose_name='fonte',
    )
    document = models.ForeignKey(
        KnowledgeDocument,
        on_delete=models.CASCADE,
        related_name='chunks',
        verbose_name='documento',
    )
    chunk_index = models.PositiveIntegerField('índice')
    title = models.CharField('título', max_length=255)
    section_reference = models.CharField('seção', max_length=180, blank=True)
    page_number = models.PositiveIntegerField('página', null=True, blank=True)
    content = models.TextField('conteúdo')
    content_hash = models.CharField('hash do conteúdo', max_length=64)
    token_count = models.PositiveIntegerField('tokens', default=0)
    embedding_vector = models.JSONField('vetor', default=list, blank=True)
    metadata = models.JSONField('metadados', default=dict, blank=True)

    class Meta:
        ordering = ['document', 'chunk_index']
        constraints = [
            models.UniqueConstraint(
                fields=['document', 'chunk_index'],
                name='unique_document_chunk_index',
            ),
        ]
        indexes = [
            models.Index(fields=['source']),
            models.Index(fields=['document']),
            models.Index(fields=['content_hash']),
        ]
        verbose_name = 'chunk de conhecimento'
        verbose_name_plural = 'chunks de conhecimento'

    def clean(self):
        super().clean()
        errors = {}
        if self.document_id and self.source_id and self.document.source_id != self.source_id:
            errors['source'] = 'A fonte deve ser a mesma do documento.'
        if not self.content.strip():
            errors['content'] = 'Informe o conteúdo do chunk.'
        if not isinstance(self.embedding_vector or [], list):
            errors['embedding_vector'] = 'O vetor deve ser uma lista.'
        if not isinstance(self.metadata or {}, dict):
            errors['metadata'] = 'Metadados devem ser um objeto chave/valor.'
        if errors:
            raise ValidationError(errors)

    def match_score(self, query):
        query_tokens = set(_tokens(query))
        if not query_tokens:
            return 0.0
        content_tokens = set(_tokens(f'{self.title} {self.section_reference} {self.content}'))
        overlap = query_tokens & content_tokens
        return len(overlap) / max(len(query_tokens), 1)

    def __str__(self):
        return f'{self.document} #{self.chunk_index}'


class KnowledgeIndexGeneration(SingleInstanceModel):
    class Status(models.TextChoices):
        BUILDING = 'building', 'Em construção'
        READY = 'ready', 'Pronta'
        ACTIVE = 'active', 'Ativa'
        FAILED = 'failed', 'Falhou'
        RETIRED = 'retired', 'Desativada'

    generation_id = models.CharField('geração', max_length=64, unique=True)
    redis_index_name = models.CharField('índice Redis', max_length=180, unique=True)
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.BUILDING
    )
    embedding_model = models.CharField('modelo de embedding', max_length=160, blank=True)
    embedding_dimensions = models.PositiveIntegerField('dimensões do embedding', default=0)
    chunk_count = models.PositiveIntegerField('quantidade de chunks', default=0)
    manifest_hash = models.CharField('hash do manifesto', max_length=64, blank=True)
    activated_at = models.DateTimeField('ativada em', null=True, blank=True)
    error_message = models.TextField('erro', blank=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['status'],
                condition=models.Q(status='active'),
                name='unique_active_knowledge_generation',
            ),
        ]
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['activated_at']),
        ]
        verbose_name = 'geração do índice de conhecimento'
        verbose_name_plural = 'gerações do índice de conhecimento'

    @transaction.atomic
    def activate(self):
        locked = type(self).objects.select_for_update().get(pk=self.pk)
        if locked.status != self.Status.READY:
            raise ValidationError({'status': 'Somente uma geração pronta pode ser ativada.'})
        type(self).objects.select_for_update().filter(status=self.Status.ACTIVE).exclude(
            pk=locked.pk
        ).update(status=self.Status.RETIRED)
        locked.status = self.Status.ACTIVE
        locked.activated_at = timezone.now()
        locked.save(update_fields=['status', 'activated_at', 'updated_at'])
        self.status = locked.status
        self.activated_at = locked.activated_at
        return self

    def __str__(self):
        return f'{self.generation_id} - {self.get_status_display()}'


class RAGChatSession(SingleInstanceModel):
    class Status(models.TextChoices):
        OPEN = 'open', 'Aberta'
        CLOSED = 'closed', 'Encerrada'

    title = models.CharField('título', max_length=180)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='rag_chat_sessions',
        verbose_name='criada por',
    )
    status = models.CharField('status', max_length=24, choices=Status.choices, default=Status.OPEN)
    last_question_at = models.DateTimeField('última pergunta em', null=True, blank=True)

    class Meta:
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['created_by', 'status']),
            models.Index(fields=['last_question_at']),
        ]
        verbose_name = 'sessão de chat RAG'
        verbose_name_plural = 'sessões de chat RAG'

    def clean(self):
        super().clean()
        errors = {}
        if not self.title.strip():
            errors['title'] = 'Informe o título da sessão.'
        if errors:
            raise ValidationError(errors)

    def add_user_message(self, text):
        message = RAGChatMessage.objects.create(
            session=self,
            role=RAGChatMessage.Role.USER,
            content=text,
            created_by=self.created_by,
        )
        self.last_question_at = timezone.now()
        self.save(update_fields=['last_question_at', 'updated_at'])
        return message

    def __str__(self):
        return self.title


class RAGChatMessage(SingleInstanceModel):
    class Role(models.TextChoices):
        USER = 'user', 'Usuário'
        ASSISTANT = 'assistant', 'Assistente'
        SYSTEM = 'system', 'Sistema'

    class Status(models.TextChoices):
        SUCCEEDED = 'succeeded', 'Concluída'
        FAILED = 'failed', 'Falhou'

    session = models.ForeignKey(
        RAGChatSession,
        on_delete=models.CASCADE,
        related_name='messages',
        verbose_name='sessão',
    )
    role = models.CharField('papel', max_length=24, choices=Role.choices)
    content = models.TextField('conteúdo')
    model_name = models.CharField('modelo', max_length=160, blank=True)
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.SUCCEEDED
    )
    latency_ms = models.PositiveIntegerField('latência ms', null=True, blank=True)
    retrieved_context = models.JSONField('contexto recuperado', default=list, blank=True)
    error_message = models.TextField('erro', blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='rag_chat_messages',
        null=True,
        blank=True,
        verbose_name='criada por',
    )

    class Meta:
        ordering = ['created_at']
        indexes = [
            models.Index(fields=['session', 'created_at']),
            models.Index(fields=['role', 'status']),
            models.Index(fields=['created_by']),
        ]
        verbose_name = 'mensagem de chat RAG'
        verbose_name_plural = 'mensagens de chat RAG'

    def clean(self):
        super().clean()
        errors = {}
        if not self.content.strip():
            errors['content'] = 'Informe o conteúdo da mensagem.'
        if self.status == self.Status.FAILED and not self.error_message:
            errors['error_message'] = 'Mensagem com falha exige erro.'
        if not isinstance(self.retrieved_context or [], list):
            errors['retrieved_context'] = 'O contexto recuperado deve ser uma lista.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.get_role_display()} - {self.created_at:%Y-%m-%d %H:%M}'


class RAGCitation(SingleInstanceModel):
    message = models.ForeignKey(
        RAGChatMessage,
        on_delete=models.CASCADE,
        related_name='citations',
        verbose_name='mensagem',
    )
    source = models.ForeignKey(
        KnowledgeSource,
        on_delete=models.PROTECT,
        related_name='citations',
        verbose_name='fonte',
    )
    document = models.ForeignKey(
        KnowledgeDocument,
        on_delete=models.PROTECT,
        related_name='citations',
        verbose_name='documento',
    )
    chunk = models.ForeignKey(
        KnowledgeChunk,
        on_delete=models.SET_NULL,
        related_name='citations',
        null=True,
        blank=True,
        verbose_name='chunk',
    )
    title = models.CharField('título', max_length=255)
    source_url = models.URLField('URL', max_length=1000, blank=True)
    section_reference = models.CharField('seção', max_length=180, blank=True)
    excerpt = models.TextField('trecho')
    relevance_score = models.DecimalField('relevância', max_digits=6, decimal_places=4, default=0)

    class Meta:
        ordering = ['-relevance_score', 'title']
        indexes = [
            models.Index(fields=['message']),
            models.Index(fields=['source']),
            models.Index(fields=['document']),
        ]
        verbose_name = 'citação RAG'
        verbose_name_plural = 'citações RAG'

    def clean(self):
        super().clean()
        errors = {}
        if self.chunk_id and self.chunk.document_id != self.document_id:
            errors['chunk'] = 'O chunk deve pertencer ao documento citado.'
        if not self.excerpt.strip():
            errors['excerpt'] = 'Informe o trecho citado.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return self.title


class KnowledgeIngestionLog(SingleInstanceModel):
    class Status(models.TextChoices):
        STARTED = 'started', 'Iniciada'
        SUCCEEDED = 'succeeded', 'Concluída'
        FAILED = 'failed', 'Falhou'
        SKIPPED = 'skipped', 'Ignorada'

    source = models.ForeignKey(
        KnowledgeSource,
        on_delete=models.PROTECT,
        related_name='ingestion_logs',
        verbose_name='fonte',
    )
    document = models.ForeignKey(
        KnowledgeDocument,
        on_delete=models.SET_NULL,
        related_name='ingestion_logs',
        null=True,
        blank=True,
        verbose_name='documento',
    )
    status = models.CharField(
        'status', max_length=24, choices=Status.choices, default=Status.STARTED
    )
    started_at = models.DateTimeField('iniciada em', default=timezone.now)
    completed_at = models.DateTimeField('concluída em', null=True, blank=True)
    chunks_created = models.PositiveIntegerField('chunks criados', default=0)
    error_message = models.TextField('erro', blank=True)
    details = models.JSONField('detalhes', default=dict, blank=True)

    class Meta:
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['source', 'status']),
            models.Index(fields=['started_at']),
        ]
        verbose_name = 'log de ingestão RAG'
        verbose_name_plural = 'logs de ingestão RAG'

    def clean(self):
        super().clean()
        errors = {}
        if self.status == self.Status.FAILED and not self.error_message:
            errors['error_message'] = 'Ingestão com falha exige mensagem de erro.'
        if not isinstance(self.details or {}, dict):
            errors['details'] = 'Detalhes devem ser um objeto chave/valor.'
        if errors:
            raise ValidationError(errors)

    def finish(self, status, *, document=None, chunks_created=0, error_message='', details=None):
        self.status = status
        self.document = document or self.document
        self.chunks_created = chunks_created
        self.error_message = error_message
        self.details = details or self.details
        self.completed_at = timezone.now()
        self.full_clean()
        self.save(
            update_fields=[
                'status',
                'document',
                'chunks_created',
                'error_message',
                'details',
                'completed_at',
                'updated_at',
            ]
        )
        return self

    def __str__(self):
        return f'{self.source} - {self.status}'
