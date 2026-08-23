import hashlib

import environ
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle, UserRateThrottle

env = environ.Env()


class CaptchaAnonRateThrottle(AnonRateThrottle):
    rate = env('NORMAL_THROTTLE_NOT_LOGIN', default='30/minute')


class CaptchaUserRateThrottle(UserRateThrottle):
    rate = env('NORMAL_THROTTLE_LOGIN', default='30/minute')


class EmailAnonRateThrottle(AnonRateThrottle):
    rate = env('EMAIL_THROTTLE_NOT_LOGIN', default='2/minute')


class EmailUserRateThrottle(UserRateThrottle):
    rate = env('EMAIL_THROTTLE_LOGIN', default='2/minute')


class EmailAddressRateThrottle(SimpleRateThrottle):
    """Limit email-triggering actions by destination address."""

    scope = 'email_address'
    rate = env('EMAIL_THROTTLE_ADDRESS', default='2/minute')

    def get_cache_key(self, request, view):
        email = str(
            request.data.get('email') or request.data.get('college_email') or ''
        ).strip().casefold()
        if not email:
            return None
        email_digest = hashlib.sha256(email.encode('utf-8')).hexdigest()
        return self.cache_format % {
            'scope': self.scope,
            'ident': email_digest,
        }


class LoginIPRateThrottle(AnonRateThrottle):
    """Limit credential attempts from one client address."""

    rate = env('LOGIN_THROTTLE_IP', default='10/minute')


class LoginUsernameRateThrottle(SimpleRateThrottle):
    """Limit credential attempts for one account, even across client addresses."""

    scope = 'login_username'
    rate = env('LOGIN_THROTTLE_USERNAME', default='5/minute')

    def get_cache_key(self, request, view):
        username = str(request.data.get('username', '')).strip().casefold()
        if not username:
            return None
        username_digest = hashlib.sha256(username.encode('utf-8')).hexdigest()
        return self.cache_format % {
            'scope': self.scope,
            'ident': username_digest,
        }
