from django.conf import settings
from rest_framework.throttling import SimpleRateThrottle, UserRateThrottle


class AdminPasskeyUserThrottle(UserRateThrottle):
    scope = 'admin_passkey_user'
    rate = getattr(settings, 'ADMIN_PASSKEY_USER_THROTTLE', '10/minute')


class AdminPasskeyIPThrottle(SimpleRateThrottle):
    scope = 'admin_passkey_ip'
    rate = getattr(settings, 'ADMIN_PASSKEY_IP_THROTTLE', '30/minute')

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}

