import os
from pathlib import Path

import environ


BASE_DIR = Path(__file__).resolve().parents[2]


def resolve_runtime_path(value, *, docker_root=Path('/app')):
    path = Path(value)
    if path.is_absolute():
        try:
            relative_to_docker_root = path.relative_to(docker_root)
        except ValueError:
            return path
        if BASE_DIR != docker_root and docker_root not in BASE_DIR.parents:
            return BASE_DIR / relative_to_docker_root
        return path
    return BASE_DIR / path


def _nearest_existing_parent(path):
    candidate = path if path.exists() else path.parent
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def resolve_media_root(value):
    path = resolve_runtime_path(value)
    if DEBUG:
        writable_probe = path if path.exists() else _nearest_existing_parent(path)
        if writable_probe.exists() and not os.access(writable_probe, os.W_OK):
            return BASE_DIR / 'var' / 'media'
    return path


env = environ.Env(
    DEBUG=(bool, True),
    SECURE_SSL_REDIRECT=(bool, False),
    SESSION_COOKIE_SECURE=(bool, False),
    CSRF_COOKIE_SECURE=(bool, False),
)
env.read_env(BASE_DIR / '.env')

# Bandit B105: explicit local-only default rejected by the production profile.
DEVELOPMENT_SECRET_KEY_DEFAULT = 'django-insecure-local-rgn-farma-system'  # nosec B105
SECRET_KEY = env('SECRET_KEY', default=DEVELOPMENT_SECRET_KEY_DEFAULT)
DEBUG = env.bool('DEBUG', default=True)
ALLOWED_HOSTS = env.list('ALLOWED_HOSTS', default=['localhost', '127.0.0.1'])
CSRF_TRUSTED_ORIGINS = env.list('CSRF_TRUSTED_ORIGINS', default=[])
CUSTOMER_APP_BASE_URL = env('CUSTOMER_APP_BASE_URL', default='http://localhost:8000')
LOGIN_MAX_ATTEMPTS = env.int('LOGIN_MAX_ATTEMPTS', default=5)
LOGIN_WINDOW_SECONDS = env.int('LOGIN_WINDOW_SECONDS', default=900)
DEMO_USER_PASSWORD = env('DEMO_USER_PASSWORD', default='')

DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'django_filters',
    'drf_spectacular',
    'django_celery_beat',
    'dj_celery_panel',
]

LOCAL_APPS = [
    'base',
    'auxiliary',
    'accounts',
    'masters',
    'formulations',
    'production',
    'planning',
    'procurement',
    'inventory',
    'costing',
    'finance',
    'fiscal',
    'crm',
    'quality',
    'qa',
    'documents',
    'deviations',
    'capa',
    'changes',
    'audits',
    'risks',
    'recalls',
    'training',
    'files',
    'reports',
    'workflow',
    'integrations',
    'ai_agents',
    'governance',
    'compliance',
    'knowledge',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'integrations.middleware.ApiCallLoggingMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'base.ui.context_processors.sidebar_menu',
            ],
        },
    },
]

WSGI_APPLICATION = 'core.wsgi.application'
ASGI_APPLICATION = 'core.asgi.application'

DATABASES = {'default': env.db('DATABASE_URL')}
DATABASES['default']['CONN_MAX_AGE'] = env.int(
    'DATABASE_CONN_MAX_AGE',
    default=60,
)

AUTH_USER_MODEL = 'accounts.User'
TRAINING_RESET_ENABLED = env.bool('TRAINING_RESET_ENABLED', default=False)
LOGIN_URL = 'accounts:login'
LOGIN_REDIRECT_URL = '/app/'
LOGOUT_REDIRECT_URL = LOGIN_URL

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': ('django.contrib.auth.password_validation.UserAttributeSimilarityValidator'),
    },
    {
        'NAME': ('django.contrib.auth.password_validation.MinimumLengthValidator'),
    },
    {
        'NAME': ('django.contrib.auth.password_validation.CommonPasswordValidator'),
    },
    {
        'NAME': ('django.contrib.auth.password_validation.NumericPasswordValidator'),
    },
]


LANGUAGE_CODE = 'pt-br'
TIME_ZONE = 'America/Recife'

USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static'] if (BASE_DIR / 'static').exists() else []
STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': (
            'django.contrib.staticfiles.storage.StaticFilesStorage'
            if DEBUG
            else 'whitenoise.storage.CompressedStaticFilesStorage'
        ),
    },
}

MEDIA_URL = 'media/'
MEDIA_ROOT = resolve_media_root(env('MEDIA_ROOT', default='media'))

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_FILTER_BACKENDS': [
        'django_filters.rest_framework.DjangoFilterBackend',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': ('rest_framework.pagination.PageNumberPagination'),
    'PAGE_SIZE': 50,
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'RGN Farma System API',
    'DESCRIPTION': ('APIs REST do ERP single-instance para a indústria de cosméticos.'),
    'VERSION': '1.0.0',
    'ENUM_NAME_OVERRIDES': {
        'OperationalRoleEnum': 'base.roles.OperationalRole',
        'AgentSourceModuleEnum': ('ai_agents.models.AIAgentProfile.SourceModule'),
        'AgentRunStatusEnum': 'ai_agents.models.AIAgentRun.Status',
        'ActionStatusEnum': 'capa.models.CapaAction.Status',
        'AssessmentStatusEnum': 'changes.models.ChangeAssessment.Status',
        'StandardCostStatusEnum': 'costing.models.StandardCost.Status',
        'MonthlyClosingStatusEnum': 'costing.models.MonthlyCostClosing.Status',
        'ApprovalDecisionEnum': 'documents.models.DocumentApproval.Decision',
        'AnalyticalSpecificationStatusEnum': ('fiscal.models.TaxRule.Status'),
        'GovernanceModuleEnum': 'base.modules.OperationalModule',
        'StockQualityStatusEnum': 'inventory.models.StockQualityStatus',
        'InvestigationStatusEnum': ('quality.models.LaboratoryInvestigation.Status'),
        'PlanningSourceEnum': 'planning.models.PlanningPolicy.Source',
        'ReportModuleEnum': 'reports.models.ReportDefinition.Module',
        'ReportExecutionStatusEnum': 'reports.models.ReportExecution.Status',
        'ReportNotificationStatusEnum': ('reports.models.ReportNotification.Status'),
        'RecallEffectivenessStatusEnum': ('recalls.models.RecallEffectivenessReport.Status'),
        'NotificationChannelEnum': 'reports.models.ReportNotification.Channel',
        'RiskLevelEnum': 'risks.models.RiskRecord.RiskLevel',
        'AlertStatusEnum': 'risks.models.RiskAlert.Status',
        'GxpCriticalityEnum': ('deviations.models.QualityEvent.Criticality'),
        'GxpSeverityEnum': 'crm.models.CustomerComplaint.Severity',
        'FileSourceModuleEnum': 'files.models.ProtectedFile.SourceModule',
        'WorkflowSourceModuleEnum': ('workflow.models.WorkflowNotification.SourceModule'),
    },
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': env('REDIS_URL', default='redis://localhost:6379/1'),
    }
}

CELERY_BROKER_URL = env(
    'CELERY_BROKER_URL',
    default='amqp://guest:guest@localhost:5672//',
)
CELERY_RESULT_BACKEND = env(
    'CELERY_RESULT_BACKEND',
    default='redis://localhost:6379/0',
)
CELERY_TIMEZONE = TIME_ZONE
CELERY_TASK_TRACK_STARTED = True
CELERY_BEAT_SCHEDULER = 'django_celery_beat.schedulers:DatabaseScheduler'

EMAIL_BACKEND = env(
    'EMAIL_BACKEND',
    default='django.core.mail.backends.console.EmailBackend',
)
EMAIL_HOST = env('EMAIL_HOST', default='')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD', default='')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
DEFAULT_FROM_EMAIL = env(
    'DEFAULT_FROM_EMAIL',
    default='no-reply@rgnfarmasystem.rgnsystems.com.br',
)

# Configuracao de e-mail exclusiva para notificacao de erros.
# Permite usar uma conta Gmail (ou outro SMTP) separada da conta de nota
# fiscal.
ERROR_EMAIL_BACKEND_PATH = 'core.email_backends.ErrorEmailBackend'
ERROR_EMAIL_HOST = env('ERROR_EMAIL_HOST', default='smtp.gmail.com')
ERROR_EMAIL_PORT = env.int('ERROR_EMAIL_PORT', default=587)
ERROR_EMAIL_HOST_USER = env('ERROR_EMAIL_HOST_USER', default='')
ERROR_EMAIL_HOST_PASSWORD = env('ERROR_EMAIL_HOST_PASSWORD', default='')
ERROR_EMAIL_USE_TLS = env.bool('ERROR_EMAIL_USE_TLS', default=True)
ERROR_EMAIL_USE_SSL = env.bool('ERROR_EMAIL_USE_SSL', default=False)
ERROR_EMAIL_FROM = env('ERROR_EMAIL_FROM', default='')
ERROR_EMAIL_RECIPIENTS = env.list('ERROR_EMAIL_RECIPIENTS', default=[])

SERVER_EMAIL = ERROR_EMAIL_FROM or DEFAULT_FROM_EMAIL
ADMINS = (
    [
        (name or email, email)
        for recipient in ERROR_EMAIL_RECIPIENTS
        for (name, email) in [recipient.split(':', 1) if ':' in recipient else (None, recipient)]
    ]
    if ERROR_EMAIL_RECIPIENTS
    else []
)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'mail_admins': {
            'level': 'ERROR',
            'class': 'django.utils.log.AdminEmailHandler',
            'email_backend': ERROR_EMAIL_BACKEND_PATH,
            'include_html': False,
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'INFO',
    },
    'loggers': {
        'django': {
            'handlers': ['console', 'mail_admins'],
            'level': 'INFO',
            'propagate': False,
        },
        'django.request': {
            'handlers': ['mail_admins'],
            'level': 'ERROR',
            'propagate': False,
        },
    },
}

FISCAL_PROVIDER = env('FISCAL_PROVIDER', default='generic')
FISCAL_ENVIRONMENT = env('FISCAL_ENVIRONMENT', default='homologation')
FISCAL_PROVIDER_BASE_URL = env('FISCAL_PROVIDER_BASE_URL', default='')
FISCAL_PROVIDER_SECRET_REFERENCE = env('FISCAL_PROVIDER_SECRET_REFERENCE', default='')
# Exact HTTPS base URLs mapped to the only environment names usable at each destination.
FISCAL_PROVIDER_ALLOWED_DESTINATIONS = env.json('FISCAL_PROVIDER_ALLOWED_DESTINATIONS', default={})
FISCAL_PROVIDER_TIMEOUT_SECONDS = env.int('FISCAL_PROVIDER_TIMEOUT_SECONDS', default=30)
FISCAL_EMAIL_AUTO_SEND = env.bool('FISCAL_EMAIL_AUTO_SEND', default=True)
FISCAL_EMAIL_SEND_DELAY_SECONDS = env.int('FISCAL_EMAIL_SEND_DELAY_SECONDS', default=300)
FISCAL_EMAIL_MAX_ATTACHMENT_MB = env.int('FISCAL_EMAIL_MAX_ATTACHMENT_MB', default=10)
FISCAL_EMAIL_USE_SECURE_LINKS_WHEN_TOO_LARGE = env.bool(
    'FISCAL_EMAIL_USE_SECURE_LINKS_WHEN_TOO_LARGE', default=True
)

OPENAI_API_KEY = env('OPENAI_API_KEY', default='')
OPENAI_MODEL = env('OPENAI_MODEL', default='gpt-5.5-mini')
OPENAI_TIMEOUT_SECONDS = env.int('OPENAI_TIMEOUT_SECONDS', default=120)
OPENAI_EMBEDDING_MODEL = env('OPENAI_EMBEDDING_MODEL', default='text-embedding-3-small')
OPENAI_EMBEDDING_DIMENSIONS = env.int('OPENAI_EMBEDDING_DIMENSIONS', default=1536)
KNOWLEDGE_REDIS_URL = env('KNOWLEDGE_REDIS_URL', default='redis://localhost:6379/0')
KNOWLEDGE_REDIS_PREFIX = env('KNOWLEDGE_REDIS_PREFIX', default='rgn:knowledge')
KNOWLEDGE_REDIS_MAX_CONNECTIONS = env.int('KNOWLEDGE_REDIS_MAX_CONNECTIONS', default=20)
RAG_CHAT_LOCAL_ONLY = env.bool('RAG_CHAT_LOCAL_ONLY', default=False)
DATA_ENCRYPTION_KEY_ID = env('DATA_ENCRYPTION_KEY_ID', default='primary')
DATA_ENCRYPTION_KEYS = env('DATA_ENCRYPTION_KEYS', default='')
DATA_ENCRYPTION_KEY = env('DATA_ENCRYPTION_KEY', default='')

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# Confiar em X-Forwarded-For (último salto) apenas atrás do nginx do deploy.
USE_X_FORWARDED_FOR = env.bool('USE_X_FORWARDED_FOR', default=False)
SECURE_REDIRECT_EXEMPT = [r'^health/$', r'^ready/$']
SECURE_SSL_REDIRECT = env.bool('SECURE_SSL_REDIRECT', default=not DEBUG)
# Security Settings
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

SESSION_COOKIE_SECURE = env.bool('SESSION_COOKIE_SECURE', default=not DEBUG)
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
CSRF_COOKIE_SECURE = env.bool('CSRF_COOKIE_SECURE', default=not DEBUG)
X_FRAME_OPTIONS = 'DENY'

SITE_NAME = 'RGN Farma System'
