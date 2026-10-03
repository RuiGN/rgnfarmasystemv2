import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class BackupRunRemovalMigrationTests(TransactionTestCase):
    migrate_from = [('auxiliary', '0001_initial')]
    migrate_to = [('auxiliary', '0002_remove_backup_run')]

    def setUp(self):
        super().setUp()
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old_apps = executor.loader.project_state(self.migrate_from).apps

        BackupRun = old_apps.get_model('auxiliary', 'BackupRun')
        ContentType = old_apps.get_model('contenttypes', 'ContentType')
        Permission = old_apps.get_model('auth', 'Permission')

        BackupRun.objects.create(
            run_number='legacy-backup-run',
            kind='postgres',
            source_path='/var/backups/legacy.sql.gz',
        )
        content_type, _ = ContentType.objects.get_or_create(
            app_label='auxiliary', model='backuprun'
        )
        Permission.objects.get_or_create(
            content_type=content_type,
            codename='view_backuprun',
            defaults={'name': 'Can view backup run'},
        )

        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.apps = executor.loader.project_state(self.migrate_to).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())
        super().tearDown()

    def test_upgrade_removes_model_table_content_type_and_permissions(self):
        with pytest.raises(LookupError):
            self.apps.get_model('auxiliary', 'BackupRun')

        tables = set(connection.introspection.table_names())
        ContentType = self.apps.get_model('contenttypes', 'ContentType')
        Permission = self.apps.get_model('auth', 'Permission')

        assert 'auxiliary_backuprun' not in tables
        assert not ContentType.objects.filter(app_label='auxiliary', model='backuprun').exists()
        assert not Permission.objects.filter(
            content_type__app_label='auxiliary',
            content_type__model='backuprun',
        ).exists()
