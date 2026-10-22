"""Explicit maintenance planning for the training installation (never startup)."""

import hashlib
import json
from pathlib import Path
import re
from uuid import uuid4

from django.conf import settings
from django.core.management.base import CommandError
from django.db import connections, transaction
from psycopg import sql

from reference_data.services import seed_production_reference_data
from reports.catalog import sync_curated_report_catalog
from reports.models import ReportDefinition


MANIFEST_PATH = Path(__file__).with_name('training_reset_manifest.json')
PRESERVED_TABLES = frozenset(
    {
        'accounts_user',
        'accounts_user_groups',
        'accounts_user_user_permissions',
        'auth_group',
        'auth_group_permissions',
        'auth_permission',
        'django_content_type',
        'django_migrations',
        'base_identifiersequence',
    }
)


def _load_manifest():
    raw = MANIFEST_PATH.read_bytes()
    manifest = json.loads(raw)
    groups = ['preserved_tables', 'clear_tables', 'reload_tables']
    for group in groups:
        names = manifest[group]
        if (
            not isinstance(names, list)
            or len(names) != len(set(names))
            or not all(
                isinstance(name, str) and re.fullmatch(r'[a-z][a-z0-9_]*', name) for name in names
            )
        ):
            raise CommandError('Manifesto de manutenção inválido.')
    preserved, cleared, reloaded = (set(manifest[group]) for group in groups)
    if (
        manifest['schema'] != 'training-reset/v1'
        or manifest['database_schema'] != 'public'
        or manifest['sequence_policy'] != 'CONTINUE IDENTITY'
        or preserved != PRESERVED_TABLES
        or not cleared
        or preserved & cleared
        or not reloaded <= cleared
    ):
        raise CommandError('Manifesto de manutenção fora do escopo autorizado.')
    return manifest, hashlib.sha256(raw).hexdigest()


def _validate_schema(cursor, manifest):
    cursor.execute(
        "SELECT nspname FROM pg_namespace WHERE left(nspname, 3) <> 'pg_' AND nspname <> 'information_schema'"
    )
    if {row[0] for row in cursor.fetchall()} != {'public'}:
        raise CommandError('Schema desconhecido; manutenção recusada.')
    cursor.execute('SELECT current_schema()')
    if cursor.fetchone()[0] != 'public':
        raise CommandError('Schema de escrita não autorizado.')
    cursor.execute("""
        SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')
    """)
    actual = {row[0] for row in cursor.fetchall()}
    expected = set(manifest['preserved_tables']) | set(manifest['clear_tables'])
    if actual != expected:
        raise CommandError('Tabela desconhecida ou ausente; manifesto não corresponde ao banco.')
    cursor.execute("""
        SELECT child.relname, parent.relname FROM pg_constraint c
        JOIN pg_class child ON child.oid=c.conrelid
        JOIN pg_class parent ON parent.oid=c.confrelid
        WHERE c.contype='f'
    """)
    for child, parent in cursor.fetchall():
        if child in manifest['preserved_tables'] and parent in manifest['clear_tables']:
            raise CommandError(
                'FK de tabela preservada aponta para tabela limpa; manutenção recusada.'
            )


def training_reset_plan(*, using='default') -> dict:
    # Existing reference loaders are intentionally single-database services.
    if using != 'default':
        raise CommandError('A manutenção suporta somente o alias default.')
    connection = connections[using]
    if connection.vendor != 'postgresql':
        raise CommandError('A manutenção exige PostgreSQL.')
    manifest, manifest_hash = _load_manifest()
    with connection.cursor() as cursor:
        cursor.execute('SELECT current_database()')
        database = cursor.fetchone()[0]
        _validate_schema(cursor, manifest)
    return {
        **manifest,
        'mode': 'inspect',
        'database': database,
        'manifest_sha256': manifest_hash,
        'backup_validation': 'O orquestrador deve conferir backup e restore isolado antes de executar.',
    }


def reset_training_data(
    *, expected_database: str, backup_receipt_sha256: str, using='default'
) -> dict:
    if not settings.TRAINING_RESET_ENABLED:
        raise CommandError('A manutenção exige TRAINING_RESET_ENABLED explicitamente ativo.')
    if using != 'default':
        raise CommandError('A manutenção suporta somente o alias default.')
    if not isinstance(backup_receipt_sha256, str) or not re.fullmatch(
        r'[0-9a-f]{64}', backup_receipt_sha256
    ):
        raise CommandError('O SHA-256 do recibo de backup é obrigatório e deve ser válido.')
    plan = training_reset_plan(using=using)
    if not expected_database or expected_database != plan['database']:
        raise CommandError('O banco conectado não corresponde ao banco explicitamente autorizado.')
    connection = connections[using]
    if connection.in_atomic_block or not connection.get_autocommit():
        raise CommandError('A manutenção não pode executar dentro de uma transação externa.')

    def table(name):
        return sql.Identifier('public', name)

    all_tables = sorted(plan['preserved_tables'] + plan['clear_tables'])
    with transaction.atomic(using=using):
        with connection.cursor() as cursor:
            cursor.execute(
                'SELECT pg_try_advisory_xact_lock(hashtext(%s))', ['rgn:training-reset:v1']
            )
            if not cursor.fetchone()[0]:
                raise CommandError('Outra manutenção está em execução.')
            cursor.execute("SELECT set_config('lock_timeout', '5s', true)")
            cursor.execute("SELECT set_config('statement_timeout', '120s', true)")
            cursor.execute(
                sql.SQL('LOCK TABLE {} IN ACCESS EXCLUSIVE MODE NOWAIT').format(
                    sql.SQL(', ').join(table(name) for name in all_tables)
                )
            )
            _validate_schema(cursor, plan)
            snapshots = {}
            for index, name in enumerate(plan['preserved_tables']):
                snapshot = sql.Identifier(f'rgn_training_preserve_{uuid4().hex}_{index}')
                cursor.execute(
                    sql.SQL('CREATE TEMP TABLE {} ON COMMIT DROP AS TABLE {}').format(
                        snapshot, table(name)
                    )
                )
                snapshots[name] = snapshot
            # All names come from the closed, validated release manifest, never CLI input.
            cursor.execute(
                sql.SQL('TRUNCATE TABLE {} CONTINUE IDENTITY RESTRICT').format(
                    sql.SQL(', ').join(table(name) for name in plan['clear_tables'])
                )
            )

        references = seed_production_reference_data()
        sync_curated_report_catalog(ReportDefinition)

        with connection.cursor() as cursor:
            for name, snapshot in snapshots.items():
                if name == 'base_identifiersequence':
                    cursor.execute(
                        sql.SQL(
                            'SELECT EXISTS (SELECT 1 FROM {} old LEFT JOIN {} current USING (namespace) WHERE current.namespace IS NULL OR current.value < old.value)'
                        ).format(snapshot, table(name))
                    )
                else:
                    cursor.execute(
                        sql.SQL(
                            'SELECT EXISTS ((SELECT * FROM {old} EXCEPT SELECT * FROM {current}) UNION ALL (SELECT * FROM {current} EXCEPT SELECT * FROM {old}))'
                        ).format(old=snapshot, current=table(name))
                    )
                if cursor.fetchone()[0]:
                    raise CommandError('Verificação de preservação falhou; reset revertido.')
            counts = {}
            for name in all_tables:
                cursor.execute(sql.SQL('SELECT count(*) FROM {}').format(table(name)))
                counts[name] = cursor.fetchone()[0]
            if any(counts[name] for name in set(plan['clear_tables']) - set(plan['reload_tables'])):
                raise CommandError(
                    'Carga criou dados fora dos catálogos autorizados; reset revertido.'
                )
            if any(not counts[name] for name in plan['reload_tables']):
                raise CommandError('Catálogo obrigatório vazio; reset revertido.')
            for snapshot in snapshots.values():
                cursor.execute(sql.SQL('DROP TABLE {}').format(snapshot))
    return {
        **plan,
        'mode': 'reset',
        'preserved_equal': True,
        'counts': counts,
        'reference_manifests': references.manifest_hashes,
        'backup_receipt_sha256': backup_receipt_sha256,
    }
