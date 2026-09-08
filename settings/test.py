from copy import deepcopy

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

# Keep the general test suite independent of production anti-abuse thresholds.
# Rate-limit tests override individual policies with deliberately small values.
API_RATE_LIMITS = deepcopy(API_RATE_LIMITS)
API_RATE_LIMITS['login'].update({
    'captcha_after_failures': 5_000,
    'emergency_ip': '10000/minute',
    'legacy_username': '10000/minute',
})
for policy in ('register_attempt', 'register_success', 'register_target'):
    API_RATE_LIMITS[policy]['burst'] = '10000/day'
for policy in ('review_write', 'guestbook_write', 'reply_write', 'catalog_write'):
    API_RATE_LIMITS[policy].update({'burst': '10000/minute', 'sustained': '10000/day'})
for policy in ('captcha_validation', 'search', 'interaction'):
    API_RATE_LIMITS[policy].update({'anonymous': '10000/minute', 'user': '10000/minute'})
API_RATE_LIMITS['message_write']['user'] = '10000/minute'
API_RATE_LIMITS['email'].update({
    'anonymous': '10000/minute',
    'user': '10000/minute',
    'address': '10000/minute',
})
API_RATE_LIMITS['admin_passkey'].update({'user': '10000/minute', 'ip': '10000/minute'})
API_RATE_LIMITS['resource_download']['enabled'] = False
