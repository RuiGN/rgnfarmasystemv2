import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from knowledge.evaluation import CASE_PATH, evaluate_case, load_cases
from knowledge.models import KnowledgeIndexGeneration, content_hash
from knowledge.services import PROMPT_VERSION, build_system_prompt


class Command(BaseCommand):
    help = 'Avalia recuperação e geração reais do manual com sondas sintéticas PT-BR.'

    def add_arguments(self, parser):
        parser.add_argument('--mode', choices=('retrieval', 'generation'), default='retrieval')
        parser.add_argument('--require-redis', action='store_true')
        parser.add_argument('--output', default='')

    def handle(self, *args, **options):
        mode = options['mode']
        local = getattr(settings, 'RAG_CHAT_LOCAL_ONLY', False)
        if mode == 'generation' and local:
            raise CommandError(
                'Geração real não é permitida em modo local; configuração preservada.'
            )
        require_redis = options['require_redis'] or mode == 'generation'
        if require_redis:
            if local:
                raise CommandError('Redis externo não é permitido em modo local.')
            from knowledge.redis_client import knowledge_redis_health

            try:
                healthy = knowledge_redis_health().get('available', False)
            except Exception as error:
                raise CommandError('Índice indisponível; avaliação não executada.') from error
            if not healthy:
                raise CommandError('Índice indisponível; avaliação não executada.')
        active = KnowledgeIndexGeneration.objects.filter(status='active').first()
        if require_redis and active is None:
            raise CommandError('Não há geração ativa para a avaliação real.')
        suite = load_cases()
        cases = suite['cases']
        # Duplicate questions skew aggregate scores and must fail, not disappear.
        if len({case['question'].strip().casefold() for case in cases}) != len(cases):
            raise CommandError('A avaliação contém perguntas duplicadas.')
        results = [evaluate_case(case, mode=mode, require_redis=require_redis) for case in cases]
        passed = all(
            result['retrieval_ok']
            and not result['error']
            and (mode != 'generation' or result['generation_ok'])
            for result in results
        )
        report = {
            'suite': suite['version'],
            'suite_hash': content_hash(CASE_PATH.read_text()),
            'mode': mode,
            'local_only': local,
            'redis_required': require_redis,
            'prompt_version': PROMPT_VERSION,
            'prompt_hash': content_hash(build_system_prompt()),
            'configured_model': settings.OPENAI_MODEL if mode == 'generation' else None,
            'generation_id': active.generation_id if active else None,
            'index_manifest_hash': active.manifest_hash if active else None,
            'provenance': suite['provenance'],
            'split': suite['split'],
            'semantic_review_required': True,
            'tokens': None,
            'cost': None,
            'case_count': len(results),
            'passed': passed,
            'results': results,
        }
        encoded = json.dumps(report, ensure_ascii=False, indent=2)
        if options['output']:
            # Never overwrite another run's evidence.
            with Path(options['output']).open('x', encoding='utf-8') as target:
                target.write(encoded + '\n')
        self.stdout.write(encoded)
        if not passed:
            raise CommandError('Avaliação reprovada; veja os resultados por caso.')
