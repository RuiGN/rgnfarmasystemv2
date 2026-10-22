"""Synthetic, versioned manual regression probes; no fixtures or business writes."""

import json
from pathlib import Path
import re
import time
import unicodedata

from knowledge.services import invoke_openai, retrieve_context


CASE_PATH = Path(__file__).parent / 'evals' / 'pt-br-manual-v2.json'


def load_cases():
    return json.loads(CASE_PATH.read_text(encoding='utf-8'))


def _normalized(text):
    return ''.join(
        c for c in unicodedata.normalize('NFKD', text.casefold()) if not unicodedata.combining(c)
    )


def _has_forbidden(text, case):
    negatable = {_normalized(term) for term in case.get('forbidden_unless_negated', [])}
    for term in case['forbidden']:
        term = _normalized(term)
        for match in re.finditer(re.escape(term), text):
            # Opt-in per term and occurrence: "não apenas" is not a direct negation.
            if term in negatable and re.search(r'(?<!\w)nao[ \t]+$', text[: match.start()]):
                continue
            return True
    return False


def evaluate_case(case, *, mode, require_redis=False):
    started = time.monotonic()
    result = {
        'id': case['id'],
        'retrieval_ok': False,
        'generation_ok': False if mode == 'generation' else None,
        'model': None,
        'answer': None,
        'sources': [],
        'error': None,
        'tokens': None,
        'cost': None,
    }
    try:
        if require_redis:
            from knowledge.retrieval import retrieve_context as redis_retrieve
            from knowledge.services import _redis_chunk_payload

            context = [_redis_chunk_payload(chunk) for chunk in redis_retrieve(case['question'])]
        else:
            context = retrieve_context(case['question'], limit=8)
        result['sources'] = [
            {
                key: item.get(key)
                for key in (
                    'chunk_id',
                    'document_id',
                    'source_code',
                    'section_reference',
                    'corpus_hash',
                    'version_label',
                )
            }
            for item in context
        ]
        expected = case['expected_sources']
        result['retrieval_ok'] = not expected or any(
            item.get('source_code') in expected
            and _normalized(case['section']) in _normalized(item['section_reference'])
            for item in context
        )
        if mode == 'generation' and result['retrieval_ok']:
            answer, provider = invoke_openai(case['question'], context)
            result.update(answer=answer, model=provider['model'])
            text = _normalized(answer)
            result['used_source_numbers'] = provider['source_numbers']
            used_evidence = [
                context[n - 1]
                for n in provider['source_numbers']
                if context[n - 1].get('source_code') in expected
                and _normalized(case['section']) in _normalized(context[n - 1]['section_reference'])
            ]
            evidence_text = _normalized('\n'.join(item['content'] for item in used_evidence))
            result['generation_ok'] = (
                all(
                    any(_normalized(term) in text for term in alternatives)
                    for alternatives in case['required_any']
                )
                and not _has_forbidden(text, case)
                and (
                    not expected
                    or (
                        bool(used_evidence)
                        and all(
                            any(_normalized(term) in evidence_text for term in alternatives)
                            for alternatives in case['required_any']
                        )
                    )
                )
            )
    except Exception as error:
        # Artifacts may be shared; exception messages can contain credentials/URLs.
        result['error'] = type(error).__name__
    result['latency_ms'] = int((time.monotonic() - started) * 1000)
    return result
