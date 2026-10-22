from dataclasses import dataclass
from datetime import date

from django.conf import settings

from knowledge.eligibility import is_document_eligible
from knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeIndexGeneration,
    KnowledgeSource,
)
from knowledge.openai_gateway import OpenAIGateway
from knowledge.redis_client import get_knowledge_redis
from knowledge.redis_index import RedisKnowledgeIndex


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    chunk_id: int
    document_id: int
    source_id: int
    title: str
    section_reference: str
    page_number: int | None
    content: str
    source_url: str
    score: float
    source_type: str = ''
    source_title: str = ''
    source_code: str = ''
    corpus_hash: str = ''
    jurisdiction: str = ''
    version_label: str = ''
    effective_from: date | None = None
    effective_to: date | None = None


def search_index(question, *, vector, filters, limit, offset=0):
    index = RedisKnowledgeIndex(get_knowledge_redis(), prefix=settings.KNOWLEDGE_REDIS_PREFIX)
    return index.search(
        f'idx:{settings.KNOWLEDGE_REDIS_PREFIX}:active',
        query=question,
        vector=vector,
        filters=filters,
        limit=limit,
        offset=offset,
    )


def retrieve_context(question, *, filters=None, limit=8, as_of=None):
    limit = max(1, min(int(limit), 20))
    if not KnowledgeIndexGeneration.objects.filter(
        status=KnowledgeIndexGeneration.Status.ACTIVE
    ).exists():
        return []
    embedding = OpenAIGateway().embed_texts([question])
    results = []
    page_size = min(max(limit * 2, 4), 50)
    offset = 0
    seen_pages = set()
    while len(results) < limit:
        hits = search_index(
            question,
            vector=embedding.vectors[0],
            filters=filters or {},
            limit=page_size,
            offset=offset,
        )
        if not hits:
            break
        page_fingerprint = tuple(
            (str(hit.get('chunk_id', '')), str(hit.get('score', ''))) for hit in hits
        )
        if page_fingerprint in seen_pages:
            break
        seen_pages.add(page_fingerprint)
        hit_ids = []
        for hit in hits:
            try:
                hit_ids.append(int(hit['chunk_id']))
            except KeyError, TypeError, ValueError:
                continue
        chunks = {
            chunk.pk: chunk
            for chunk in KnowledgeChunk.objects.filter(
                pk__in=hit_ids,
                document__status=KnowledgeDocument.Status.INGESTED,
                source__is_active=True,
                source__chat_eligible=True,
                source__source_type=KnowledgeSource.SourceType.SYSTEM_MANUAL,
            ).select_related('source', 'document')
            if is_document_eligible(chunk.document, as_of=as_of)
        }
        for hit in hits:
            try:
                chunk = chunks[int(hit['chunk_id'])]
            except KeyError, TypeError, ValueError:
                continue
            results.append(
                RetrievedChunk(
                    chunk_id=chunk.pk,
                    document_id=chunk.document_id,
                    source_id=chunk.source_id,
                    title=chunk.title,
                    section_reference=chunk.section_reference,
                    page_number=chunk.page_number,
                    content=chunk.content,
                    source_url=chunk.document.source_url or chunk.source.url,
                    score=float(hit.get('score', 0.0)),
                    source_type=chunk.source.source_type,
                    source_title=chunk.source.title,
                    source_code=chunk.source.code,
                    corpus_hash=chunk.document.content_hash,
                    jurisdiction=chunk.source.jurisdiction,
                    version_label=chunk.document.version_label,
                    effective_from=None,
                    effective_to=None,
                )
            )
            if len(results) >= limit:
                break
        next_offset = offset + len(hits)
        if next_offset <= offset:
            break
        offset = next_offset
        if len(hits) < page_size:
            break
    return results
