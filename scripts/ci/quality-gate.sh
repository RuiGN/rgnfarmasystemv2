#!/usr/bin/env bash
set -euo pipefail

: "${TEST_DATABASE_URL:?TEST_DATABASE_URL is required}"

export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-core.settings.test}"
STATIC_ANALYSIS_PACKAGES=(
  core
  accounts
  ai_agents
  audits
  auxiliary
  base
  capa
  changes
  compliance
  costing
  crm
  deviations
  documents
  files
  finance
  fiscal
  formulations
  governance
  integrations
  inventory
  knowledge
  masters
  planning
  procurement
  production
  qa
  quality
  recalls
  reports
  risks
  training
  workflow
)

node --version
for script in static/js/*.js; do
  node --check "$script"
done
node --test tests/js/*.test.cjs

python manage.py check
python manage.py makemigrations --check --dry-run
python -m ruff check .
python -m ruff format --check .
python -m mypy "${STATIC_ANALYSIS_PACKAGES[@]}"
python -m bandit -r "${STATIC_ANALYSIS_PACKAGES[@]}" -q
python -m pip_audit --strict
python -m pytest --create-db --cov=. --cov-report=term-missing --cov-report=xml --cov-fail-under=80
python manage.py spectacular --file openapi-schema.yml --validate --fail-on-warn
python manage.py check_operational_readiness --fail-on-error
python manage.py check_backup_restore_readiness --fail-on-error
python manage.py check_product_acceptance --fail-on-error
python manage.py check_release_readiness --fail-on-error

DJANGO_SETTINGS_MODULE=core.settings.production python manage.py check --deploy --fail-level WARNING
