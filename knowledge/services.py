import io
import logging
from pathlib import Path
import time
from decimal import Decimal

import httpx
from bs4 import BeautifulSoup
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from pypdf import PdfReader

from knowledge.models import (
    KnowledgeDocument,
    KnowledgeIngestionLog,
    KnowledgeSource,
    RAGChatMessage,
    RAGChatSession,
    RAGCitation,
    content_hash,
    deterministic_embedding,
)
from knowledge.openai_gateway import OpenAIGateway
from knowledge.redis_client import knowledge_redis_health


logger = logging.getLogger(__name__)


def normalize_text(value):
    return ' '.join(str(value or '').replace('\x00', ' ').split())


def chunk_text(text, *, max_words=240, overlap=40):
    words = normalize_text(text).split()
    if not words:
        return []
    chunks = []
    step = max(max_words - overlap, 1)
    for start in range(0, len(words), step):
        part = words[start : start + max_words]
        if not part:
            continue
        chunks.append({'content': ' '.join(part), 'section_reference': f'chunk {len(chunks) + 1}'})
        if start + max_words >= len(words):
            break
    return chunks


def source_from_entry(entry):
    metadata = dict(entry.get('metadata') or {})
    metadata.pop('manual_content', None)
    values = {
        'title': entry['title'],
        'source_type': entry['source_type'],
        'publisher': entry['publisher'],
        'jurisdiction': entry.get('jurisdiction', ''),
        'version': entry.get('version', ''),
        'url': entry.get('url', ''),
        'license_note': entry.get('license_note', ''),
        'is_official': bool(entry.get('is_official', False)),
        'is_active': True,
        'chat_eligible': bool(entry.get('chat_eligible', False)),
        'metadata': metadata,
    }
    source, _created = KnowledgeSource.objects.update_or_create(
        code=entry['code'],
        defaults=values,
    )
    return source


def ingest_source(entry, *, max_chunks=None, timeout=30):
    entry_manual_content = entry.get('manual_content')
    source = source_from_entry(entry)
    log = KnowledgeIngestionLog.objects.create(source=source)
    if source.source_type == KnowledgeSource.SourceType.BOOK_REFERENCE or (
        source.metadata or {}
    ).get('metadata_only'):
        log.finish(
            KnowledgeIngestionLog.Status.SKIPPED,
            details={'reason': 'metadata_only', 'url': source.url},
        )
        return {'source': source, 'document': None, 'chunks_created': 0, 'status': log.status}

    try:
        local_path = (source.metadata or {}).get('local_path')
        manual_content = entry_manual_content
        if manual_content:
            fetched = {
                'text': manual_content,
                'document_type': KnowledgeDocument.DocumentType.TEXT,
                'content_type': 'text/markdown; charset=utf-8',
            }
            selected_url = source.url
        elif local_path:
            fetched = fetch_local_source_text(local_path)
            selected_url = source.url
        else:
            urls = [source.url, *((source.metadata or {}).get('alternate_urls') or [])]
            fetched, selected_url = fetch_source_text_candidates(urls, timeout=timeout)
        text = normalize_text(fetched['text'])
        if not text:
            raise ValueError('A fonte não retornou texto extraível.')
        document_hash = content_hash(text)
        document, _created = KnowledgeDocument.objects.update_or_create(
            source=source,
            content_hash=document_hash,
            defaults={
                'title': source.title,
                'document_type': fetched['document_type'],
                'source_url': selected_url,
                'version_label': source.version,
                'retrieved_at': timezone.now(),
                'status': KnowledgeDocument.Status.PENDING,
                'extracted_text': text,
                'metadata': {'content_type': fetched.get('content_type', '')},
            },
        )
        chunks = chunk_text(text)
        if max_chunks is not None:
            chunks = chunks[:max_chunks]
        created_chunks = document.replace_chunks(chunks)
        log.finish(
            KnowledgeIngestionLog.Status.SUCCEEDED,
            document=document,
            chunks_created=len(created_chunks),
            details={'url': selected_url, 'content_type': fetched.get('content_type', '')},
        )
        return {
            'source': source,
            'document': document,
            'chunks_created': len(created_chunks),
            'status': log.status,
        }
    except Exception as error:
        log.finish(
            KnowledgeIngestionLog.Status.FAILED,
            error_message=str(error),
            details={'url': source.url},
        )
        raise


def fetch_source_text(url, *, timeout=30):
    response = httpx.get(
        url,
        timeout=timeout,
        follow_redirects=True,
        headers={
            'User-Agent': (
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
                '(KHTML, like Gecko) Chrome/131.0 Safari/537.36'
            ),
            'Accept': 'text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.8',
            'Accept-Language': 'pt-BR,pt;q=0.9,en;q=0.8',
        },
    )
    response.raise_for_status()
    content_type = response.headers.get('content-type', '').lower()
    if 'application/pdf' in content_type or url.lower().endswith('.pdf'):
        return {
            'text': extract_pdf_text(response.content),
            'document_type': KnowledgeDocument.DocumentType.PDF,
            'content_type': content_type,
        }
    return {
        'text': extract_html_text(response.text),
        'document_type': KnowledgeDocument.DocumentType.HTML,
        'content_type': content_type,
    }


def fetch_source_text_candidates(urls, *, timeout=30):
    candidates = [str(url).strip() for url in urls if str(url).strip()]
    if not candidates:
        raise ValueError('A fonte não possui URL para ingestão.')
    errors = []
    for url in candidates:
        try:
            return fetch_source_text(url, timeout=timeout), url
        except Exception as error:
            errors.append(f'{url}: {error}')
    raise RuntimeError('Nenhuma URL da fonte pôde ser ingerida. ' + ' | '.join(errors))


def fetch_local_source_text(local_path):
    root = Path(settings.BASE_DIR).resolve()
    candidate = (root / str(local_path)).resolve()
    if root not in candidate.parents or not candidate.is_file():
        raise ValueError('O caminho local da fonte não é permitido ou não existe.')
    return {
        'text': candidate.read_text(encoding='utf-8'),
        'document_type': KnowledgeDocument.DocumentType.TEXT,
        'content_type': 'text/plain; charset=utf-8',
    }


def extract_pdf_text(content):
    reader = PdfReader(io.BytesIO(content))
    return '\n'.join(page.extract_text() or '' for page in reader.pages)


def extract_html_text(html):
    soup = BeautifulSoup(html or '', 'html.parser')
    for tag in soup(['script', 'style', 'noscript', 'svg']):
        tag.decompose()
    main = soup.find('main') or soup.find('article') or soup.body or soup
    return main.get_text(' ', strip=True)


class InvalidChatSession(ValueError):
    pass


def retrieve_context(question, limit=5):
    # The privacy policy applies to retrieval, not just answer generation.
    if getattr(settings, 'RAG_CHAT_LOCAL_ONLY', False):
        return _postgres_retrieve_context(question, limit=limit)
    redis_context = _redis_retrieve_context(question, limit=limit)
    if redis_context is not None:
        return redis_context
    return _postgres_retrieve_context(question, limit=limit)


def _postgres_retrieve_context(question, *, limit=5):
    query_vector = deterministic_embedding(question)
    scored = []
    queryset = (
        KnowledgeDocument.objects.filter(
            status=KnowledgeDocument.Status.INGESTED,
            source__is_active=True,
            source__chat_eligible=True,
            source__source_type=KnowledgeSource.SourceType.SYSTEM_MANUAL,
        )
        .select_related('source')
        .prefetch_related('chunks')
    )
    for document in queryset:
        for chunk in document.chunks.all():
            lexical = chunk.match_score(question)
            if lexical <= 0:
                continue
            vector = _cosine_similarity(query_vector, chunk.embedding_vector or [])
            score = (lexical * 0.75) + (vector * 0.25)
            if score <= 0:
                continue
            scored.append(_context_payload(chunk, score))
    scored.sort(key=lambda item: item['score'], reverse=True)
    return scored[:limit]


def _redis_retrieve_context(question, *, limit=5):
    from knowledge.models import KnowledgeIndexGeneration

    if not KnowledgeIndexGeneration.objects.filter(
        status=KnowledgeIndexGeneration.Status.ACTIVE
    ).exists():
        return None

    try:
        if not knowledge_redis_health().get('available', False):
            logger.warning('Redis de conhecimento indisponível; usando PostgreSQL.')
            return None
    except Exception as error:
        logger.warning(
            'Falha ao verificar Redis de conhecimento; usando PostgreSQL. %s',
            type(error).__name__,
        )
        return None

    from knowledge.retrieval import retrieve_context as redis_retrieve

    try:
        chunks = redis_retrieve(question, limit=limit)
    except Exception as error:
        logger.warning(
            'Falha ao recuperar contexto via Redis; usando PostgreSQL. %s',
            type(error).__name__,
        )
        return None
    return [_redis_chunk_payload(chunk) for chunk in chunks]


def _redis_chunk_payload(chunk):
    return {
        'chunk_id': chunk.chunk_id,
        'document_id': chunk.document_id,
        'source_id': chunk.source_id,
        'title': chunk.title or '',
        'source_title': chunk.source_title,
        'source_url': chunk.source_url,
        'section_reference': chunk.section_reference,
        'page_number': chunk.page_number,
        'content': chunk.content,
        'score': round(chunk.score, 6),
    }


@transaction.atomic
def answer_question(user, question, *, session_id=None, limit=5):
    started = time.monotonic()
    session = _get_or_create_session(user, question, session_id=session_id)
    session.add_user_message(question)
    context = retrieve_context(question, limit=limit)

    if getattr(settings, 'RAG_CHAT_LOCAL_ONLY', False):
        answer = local_answer(question, context)
        model_name = 'local'
    else:
        try:
            answer, provider = invoke_openai(question, context)
            model_name = provider['model']
        except Exception as error:
            logger.warning(
                'Provedor externo indisponível; usando resposta local. %s',
                type(error).__name__,
            )
            answer = local_answer(question, context, provider_fallback=True)
            model_name = 'local'
    latency_ms = int((time.monotonic() - started) * 1000)

    assistant_message = RAGChatMessage.objects.create(
        session=session,
        role=RAGChatMessage.Role.ASSISTANT,
        content=answer,
        model_name=model_name,
        status=RAGChatMessage.Status.SUCCEEDED,
        latency_ms=latency_ms,
        retrieved_context=context,
        error_message='',
        created_by=user,
    )
    citations = create_citations(assistant_message, context)
    return {
        'session_id': session.id,
        'message_id': assistant_message.id,
        'answer': answer,
        'citations': citations,
    }


def invoke_openai(question, context):
    generation = OpenAIGateway().generate_text(
        instructions=build_system_prompt(),
        input=build_prompt(question, context),
    )
    return generation.text, {
        'provider': 'openai',
        'response_id': generation.response_id,
        'model': generation.model,
    }


def build_system_prompt():
    return (
        'Você é o assistente do manual de utilização do RGN Farma System, um ERP '
        'para a indústria de cosméticos. Responda sempre em português do Brasil, com tom cordial, claro e '
        'profissional. Responda exclusivamente sobre funcionalidades, telas, permissões, '
        'campos, fluxos e estados do sistema. Use somente as fontes do manual fornecidas como '
        'contexto. Quando a pergunta for sobre como fazer algo no sistema, forneça instruções '
        'passo a passo numeradas, incluindo caminho do menu, campos e botões. Não execute '
        'ações, não crie propostas e não consulte legislação ou qualquer fonte '
        'regulatória externa. Quando o manual não cobrir a pergunta, informe a limitação sem '
        'inventar procedimentos.'
    )


def build_prompt(question, context):
    sources = []
    for index, item in enumerate(context, start=1):
        sources.append(
            f'[{index}] {item["title"]} | {item["section_reference"]} | '
            f'{item["source_url"]}\n{item["content"]}'
        )
    context_text = '\n\n'.join(sources)
    if not context_text:
        return (
            f'Pergunta do usuário:\n{question}\n\n'
            'Fontes recuperadas:\nNenhuma fonte recuperada.\n\n'
            'Informe que não há instrução validada no manual do ERP para responder com '
            'segurança. Não invente passos, permissões ou comportamentos do sistema.'
        )
    return (
        f'Pergunta do usuário:\n{question}\n\n'
        f'Contexto do manual:\n{context_text}\n\n'
        'Responda somente com base no contexto. Forneça passos numerados quando aplicável e '
        'não proponha nem confirme alteração de dados.'
    )


def local_answer(question, context, provider_fallback=False):
    if not context:
        lines = [
            'Não encontrei uma instrução validada no manual do ERP para essa pergunta.',
            'Refine a pergunta informando o módulo e a operação desejada ou procure o '
            'responsável pelo processo.',
        ]
    else:
        lines = ['Com base no manual do ERP, estes são os pontos relevantes:']
        for index, item in enumerate(context[:3], start=1):
            excerpt = item['content']
            if len(excerpt) > 360:
                excerpt = f'{excerpt[:357]}...'
            lines.append(f'{index}. {excerpt}')
        lines.append('Confira abaixo as citações usadas para fundamentar esta orientação.')
    if provider_fallback:
        lines.append('A resposta foi produzida em modo local porque o provedor está indisponível.')
    return '\n'.join(lines)


def create_citations(message, context):
    citations = []
    for item in context:
        citation = RAGCitation.objects.create(
            message=message,
            source_id=item['source_id'],
            document_id=item['document_id'],
            chunk_id=item['chunk_id'],
            title=item['title'],
            source_url=item['source_url'],
            section_reference=item['section_reference'],
            excerpt=item['content'][:1000],
            relevance_score=Decimal(str(round(item['score'], 4))),
        )
        citations.append(
            {
                'title': citation.title,
                'section_reference': citation.section_reference,
                'url': citation.source_url,
                'excerpt': citation.excerpt,
            }
        )
    return citations


def _get_or_create_session(user, question, *, session_id=None):
    if session_id:
        session = RAGChatSession.objects.filter(
            created_by=user,
            pk=session_id,
            status=RAGChatSession.Status.OPEN,
        ).first()
        if session is None:
            raise InvalidChatSession('A conversa informada não existe ou não está disponível.')
        return session
    title = normalize_text(question)[:120] or 'Pergunta RAG'
    return RAGChatSession.objects.create(created_by=user, title=title)


def _context_payload(chunk, score):
    document = chunk.document
    source = chunk.source
    return {
        'chunk_id': chunk.id,
        'document_id': document.id,
        'source_id': source.id,
        'title': document.title,
        'source_title': source.title,
        'source_url': document.source_url or source.url,
        'section_reference': chunk.section_reference,
        'page_number': chunk.page_number,
        'content': chunk.content,
        'score': round(float(score), 6),
    }


def _cosine_similarity(left, right):
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(float(a) * float(b) for a, b in zip(left, right))
