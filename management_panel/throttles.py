from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


class AdminPasskeyUserThrottle(UserRateThrottle):
    scope = 'admin_passkey_user'

    def get_rate(self):
        config = settings.API_RATE_LIMITS['admin_passkey']
        return config['user'] if config['enabled'] else None


class AdminPasskeyIPThrottle(SimpleRateThrottle):
    scope = 'admin_passkey_ip'

    def get_rate(self):
        config = settings.API_RATE_LIMITS['admin_passkey']
        return config['ip'] if config['enabled'] else None

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}
