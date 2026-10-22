from knowledge.models import KnowledgeDocument


def is_document_eligible(document, *, as_of=None):
    if document.status != KnowledgeDocument.Status.INGESTED or not document.source.is_active:
        return False
    source_metadata = document.source.metadata or {}
    current_hash = source_metadata.get('current_content_hash')
    if current_hash and document.content_hash != current_hash:
        return False
    if source_metadata.get('content_kind') == 'system_help':
        expected = source_metadata.get('registry_generator')
        actual = (document.metadata or {}).get('registry_generator')
        return bool(expected and actual and expected == actual)
    return True
