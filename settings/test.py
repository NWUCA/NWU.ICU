from .settings import *

CAPTCHA_TEST_MODE = True

# Tests still use the configured PostgreSQL database, but must not depend on the
# manually-created production database cache table.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'nwuicu-tests',
    },
}

PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]
