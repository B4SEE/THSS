"""
Test-only settings that override the main config for fast, infrastructure-free test runs.

Use with: python manage.py test --settings=config.test_settings
"""
from config.settings import *  # noqa: F401, F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Disable the scheduler so it doesn't start a background thread during tests
SCHEDULER_ENABLED = False

# Use in-memory channel layer so Redis is not required
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels.layers.InMemoryChannelLayer',
    }
}

# Speed up password hashing in tests
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# Silence logging noise during test runs
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'null': {'class': 'logging.NullHandler'},
    },
    'root': {
        'handlers': ['null'],
        'level': 'CRITICAL',
    },
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
    }
}

RESEND_API_KEY = 'test-key'
PLATFORM_BASE_URL = 'https://test.example.com'
EMAIL_SEND_DELAY = 0
EMAIL_BATCH_SIZE = 0
