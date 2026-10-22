import json

from django.core.management.base import BaseCommand

from governance.training_reset import reset_training_data, training_reset_plan


class Command(BaseCommand):
    help = 'Inspeciona a manutenção seletiva de treinamento; não executa reset por padrão.'

    def add_arguments(self, parser):
        parser.add_argument('--execute', action='store_true')
        parser.add_argument('--database', default='default')
        parser.add_argument('--expected-database')
        parser.add_argument('--backup-receipt-sha256')

    def handle(self, *args, **options):
        if options['execute']:
            result = reset_training_data(
                expected_database=options['expected_database'],
                backup_receipt_sha256=options['backup_receipt_sha256'],
                using=options['database'],
            )
        else:
            result = training_reset_plan(using=options['database'])
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
