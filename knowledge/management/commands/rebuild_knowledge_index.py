import time

from django.core.management.base import BaseCommand, CommandError

from knowledge.indexing import build_index_generation
from knowledge.models import KnowledgeIndexGeneration
from knowledge.redis_client import knowledge_redis_health


class Command(BaseCommand):
    help = (
        'Constrói a geração do índice de conhecimento no Redis (embeddings OpenAI + '
        'RediSearch) e a ativa, tornando-a a fonte do chat RAG.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--generation-id', type=str, default='')
        parser.add_argument('--no-health-check', action='store_true', help='Pula o ping ao Redis.')

    def handle(self, *args, **options):
        if not options['no_health_check']:
            try:
                health = knowledge_redis_health()
            except Exception:
                raise CommandError('Redis de conhecimento indisponível.') from None
            if not health['available']:
                raise CommandError(
                    'Redis de conhecimento indisponível; verifique a configuração do serviço.'
                )
            self.stdout.write(self.style.SUCCESS('Redis de conhecimento acessível.'))

        started = time.monotonic()
        generation = build_index_generation(generation_id=options['generation_id'] or None)
        elapsed = time.monotonic() - started
        if generation.status != KnowledgeIndexGeneration.Status.ACTIVE:
            raise CommandError(
                f'Geração {generation.generation_id} não foi ativada (status={generation.status}).'
            )
        self.stdout.write(
            self.style.SUCCESS(
                'Índice publicado. '
                f'generation_id={generation.generation_id} '
                f'redis_index={generation.redis_index_name} '
                f'chunks={generation.chunk_count} '
                f'embedding_model={generation.embedding_model} '
                f'elapsed={elapsed:.1f}s'
            )
        )
