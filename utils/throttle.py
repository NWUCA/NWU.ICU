import hashlib
import math
import time
import uuid

from django.conf import settings
from django.core import signing
from django.core.cache import caches
from rest_framework.exceptions import APIException, Throttled
from rest_framework.throttling import SimpleRateThrottle


PROOF_SALT = 'nwuicu.captcha-proof.v1'


def throttle_config(name):
    return settings.API_RATE_LIMITS[name]


def throttle_cache():
    return caches[settings.API_RATE_LIMITS['cache_alias']]


def digest(value):
    return hashlib.sha256(str(value).strip().casefold().encode('utf-8')).hexdigest()


def browser_identity(request):
    return str(getattr(request, 'nwu_browser_id', '') or 'missing-browser-id')


def actor_identity(request):
    user = getattr(request, 'user', None)
    if user is not None and user.is_authenticated:
        return f'user:{user.pk}'
    return f'browser:{browser_identity(request)}'


def _parse_rate(rate):
    if not rate:
        return None
    count, period = str(rate).split('/', 1)
    duration = {'s': 1, 'm': 60, 'h': 3600, 'd': 86400}[period.strip()[0].lower()]
    return int(count), duration


def _history_key(policy, dimension, identity, period):
    return f'rl:{policy}:{dimension}:{digest(identity)}:{period}'


def _inspect_window(policy, dimension, identity, rate, now=None):
    parsed = _parse_rate(rate)
    if parsed is None:
        return True, None, None, []
    limit, duration = parsed
    now = time.time() if now is None else now
    key = _history_key(policy, dimension, identity, duration)
    history = list(throttle_cache().get(key, []))
    cutoff = now - duration
    history = [timestamp for timestamp in history if timestamp > cutoff]
    if len(history) >= limit:
        wait = max(1, math.ceil(duration - (now - history[-1])))
        return False, wait, key, history
    return True, None, key, history


def _record_window(key, history, duration, now=None):
    if key is None:
        return
    now = time.time() if now is None else now
    history.insert(0, now)
    throttle_cache().set(key, history, duration)


class CaptchaRequired(APIException):
    status_code = 429
    default_code = 'captcha_required'

    def __init__(self, scope, wait=None):
        self.scope = scope
        self.wait = wait
        super().__init__('操作过于频繁，请完成验证码后继续', code=self.default_code)


class InvalidCaptchaProof(APIException):
    status_code = 400
    default_code = 'invalid_captcha_proof'
    default_detail = '验证码凭证无效或已失效'


def issue_captcha_proof(request, scope):
    proof_config = throttle_config('captcha_proof')
    if scope not in proof_config['allowed_scopes']:
        raise InvalidCaptchaProof('不支持的验证码使用场景')
    nonce = uuid.uuid4().hex
    payload = {
        'nonce': nonce,
        'scope': scope,
        'actor': actor_identity(request),
        'issued_at': int(time.time()),
    }
    ttl = proof_config['ttl']
    throttle_cache().set(f'captcha-proof:{digest(nonce)}', True, ttl)
    return signing.dumps(payload, salt=PROOF_SALT, compress=True), ttl


def consume_captcha_proof(request, scope, proof=None):
    proof = proof or request.headers.get('X-Captcha-Proof', '')
    if not proof:
        return False
    try:
        payload = signing.loads(
            proof,
            salt=PROOF_SALT,
            max_age=throttle_config('captcha_proof')['ttl'],
        )
    except signing.BadSignature as error:
        raise InvalidCaptchaProof() from error
    if payload.get('scope') != scope or payload.get('actor') != actor_identity(request):
        raise InvalidCaptchaProof()
    if not throttle_cache().delete(f"captcha-proof:{digest(payload.get('nonce', ''))}"):
        raise InvalidCaptchaProof()
    return True


class ConfiguredSimpleRateThrottle(SimpleRateThrottle):
    policy_name = None
    dimension = None
    config_key = None
    rate = None

    def get_rate(self):
        # Preserve explicit test/debug overrides of the public class attribute.
        if self.rate is not None:
            return self.rate
        config = throttle_config(self.policy_name)
        if not config.get('enabled', True):
            return None
        return config.get(self.config_key)

    def identity(self, request):
        if self.dimension == 'ip':
            return self.get_ident(request)
        if self.dimension == 'browser':
            return browser_identity(request)
        if self.dimension == 'user':
            return str(request.user.pk) if request.user.is_authenticated else None
        if self.dimension == 'email':
            value = (
                getattr(request, '_throttle_email', None)
                or request.data.get('email')
                or request.data.get('college_email')
            )
            return digest(value) if value else None
        if self.dimension == 'username':
            value = request.data.get('username')
            return digest(value) if value else None
        return None

    def get_cache_key(self, request, view):
        identity = self.identity(request)
        if not identity:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': identity}


class CaptchaAnonRateThrottle(ConfiguredSimpleRateThrottle):
    scope = 'captcha_anon'
    policy_name = 'captcha_validation'
    config_key = 'anonymous'
    dimension = 'browser'

    def get_cache_key(self, request, view):
        if request.user.is_authenticated:
            return None
        return super().get_cache_key(request, view)


class CaptchaUserRateThrottle(ConfiguredSimpleRateThrottle):
    scope = 'captcha_user'
    policy_name = 'captcha_validation'
    config_key = 'user'
    dimension = 'user'


class EmailAnonRateThrottle(CaptchaAnonRateThrottle):
    scope = 'email_anon'
    policy_name = 'email'
    config_key = 'anonymous'


class EmailUserRateThrottle(CaptchaUserRateThrottle):
    scope = 'email_user'
    policy_name = 'email'
    config_key = 'user'


class EmailAddressRateThrottle(ConfiguredSimpleRateThrottle):
    scope = 'email_address'
    policy_name = 'email'
    config_key = 'address'
    dimension = 'email'


class MessageWriteRateThrottle(ConfiguredSimpleRateThrottle):
    scope = 'message_write'
    policy_name = 'message_write'
    config_key = 'user'
    dimension = 'user'


class SearchAnonRateThrottle(CaptchaAnonRateThrottle):
    scope = 'search_anon'
    policy_name = 'search'


class SearchUserRateThrottle(CaptchaUserRateThrottle):
    scope = 'search_user'
    policy_name = 'search'


class InteractionAnonRateThrottle(CaptchaAnonRateThrottle):
    scope = 'interaction_anon'
    policy_name = 'interaction'


class InteractionUserRateThrottle(CaptchaUserRateThrottle):
    scope = 'interaction_user'
    policy_name = 'interaction'


class LoginIPRateThrottle(ConfiguredSimpleRateThrottle):
    scope = 'login_ip'
    policy_name = 'login'
    config_key = 'emergency_ip'
    dimension = 'ip'


class LoginUsernameRateThrottle(ConfiguredSimpleRateThrottle):
    scope = 'login_username'
    policy_name = 'login'
    config_key = 'legacy_username'
    dimension = 'username'


class PolicyThrottle(SimpleRateThrottle):
    """Two-window actor throttle with an optional one-use CAPTCHA bypass."""

    policy_name = None
    scope = None
    rate = None

    def get_rate(self):
        # This throttle owns multiple configured windows instead of DRF's
        # single THROTTLE_RATES entry.
        return None

    def get_cache_key(self, request, view):  # pragma: no cover
        return None

    def allow_request(self, request, view):
        config = throttle_config(self.policy_name)
        if not config.get('enabled', True):
            return True
        identity = actor_identity(request)
        now = time.time()

        sustained_rate = config.get('sustained')
        sustained = _inspect_window(self.policy_name, 'actor-sustained', identity, sustained_rate, now)
        if not sustained[0]:
            self._wait = sustained[1]
            return False

        burst_rate = config.get('burst')
        burst = _inspect_window(self.policy_name, 'actor-burst', identity, burst_rate, now)
        if not burst[0]:
            if config.get('captcha_on_burst'):
                if not consume_captcha_proof(request, self.policy_name):
                    raise CaptchaRequired(self.policy_name, burst[1])
            else:
                self._wait = burst[1]
                return False

        burst_parsed = _parse_rate(burst_rate)
        sustained_parsed = _parse_rate(sustained_rate)
        if burst_parsed:
            _record_window(burst[2], burst[3], burst_parsed[1], now)
        if sustained_parsed:
            _record_window(sustained[2], sustained[3], sustained_parsed[1], now)
        return True

    def wait(self):
        return getattr(self, '_wait', None)


class ReviewWriteRateThrottle(PolicyThrottle):
    policy_name = scope = 'review_write'


class GuestbookWriteRateThrottle(PolicyThrottle):
    policy_name = scope = 'guestbook_write'


class ReplyWriteRateThrottle(PolicyThrottle):
    policy_name = scope = 'reply_write'


class CatalogWriteRateThrottle(PolicyThrottle):
    policy_name = scope = 'catalog_write'


class RegisterAttemptRateThrottle(PolicyThrottle):
    policy_name = scope = 'register_attempt'


def enforce_email_delivery(request, email):
    """Apply caller and destination email limits after CAPTCHA validation."""
    request._throttle_email = email
    for throttle in (EmailAnonRateThrottle(), EmailUserRateThrottle(), EmailAddressRateThrottle()):
        if not throttle.allow_request(request, None):
            raise Throttled(wait=throttle.wait())


def enforce_policy(policy_name, identity, dimension='actor'):
    config = throttle_config(policy_name)
    if not config.get('enabled', True):
        return
    rate = config.get('burst')
    allowed, wait, key, history = _inspect_window(policy_name, dimension, identity, rate)
    if not allowed:
        raise Throttled(wait=wait)
    parsed = _parse_rate(rate)
    if parsed:
        _record_window(key, history, parsed[1])


def enforce_policies(policy_name, identities, dimension='target'):
    config = throttle_config(policy_name)
    if not config.get('enabled', True):
        return
    rate = config.get('burst')
    inspected = [_inspect_window(policy_name, dimension, identity, rate) for identity in identities if identity]
    denied = [item for item in inspected if not item[0]]
    if denied:
        raise Throttled(wait=max(item[1] for item in denied))
    parsed = _parse_rate(rate)
    if parsed:
        for _, _, key, history in inspected:
            _record_window(key, history, parsed[1])


def _login_key(kind, identity):
    return f'login:{kind}:{digest(identity)}'


def _cache_increment(key, ttl):
    cache = throttle_cache()
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 1, ttl)
        return 1


def check_login_attempt(request, username):
    config = throttle_config('login')
    if not config.get('enabled', True):
        request._login_challenge_attempt = False
        return
    browser = browser_identity(request)
    blocked_until = throttle_cache().get(_login_key('blocked', browser))
    if blocked_until:
        raise Throttled(wait=max(1, math.ceil(float(blocked_until) - time.time())))

    browser_failures = throttle_cache().get(_login_key('browser-failures', browser), 0)
    username_failures = throttle_cache().get(_login_key('username-failures', username), 0)
    threshold = config['captcha_after_failures']
    request._login_challenge_attempt = False
    if max(browser_failures, username_failures) < threshold:
        return

    grant_key = _login_key('grant', browser)
    remaining = throttle_cache().get(grant_key, 0)
    if remaining:
        throttle_cache().set(grant_key, remaining - 1, config['captcha_ttl'])
        request._login_challenge_attempt = True
        request._login_grant_remaining = remaining - 1
        return
    if not consume_captcha_proof(request, 'login'):
        raise CaptchaRequired('login')
    remaining = max(0, config['captcha_attempts'] - 1)
    throttle_cache().set(grant_key, remaining, config['captcha_ttl'])
    request._login_challenge_attempt = True
    request._login_grant_remaining = remaining


def record_login_failure(request, username):
    config = throttle_config('login')
    if not config.get('enabled', True):
        return
    browser = browser_identity(request)
    ttl = config['failure_ttl']
    _cache_increment(_login_key('browser-failures', browser), ttl)
    _cache_increment(_login_key('username-failures', username), ttl)
    if getattr(request, '_login_challenge_attempt', False) and not getattr(request, '_login_grant_remaining', 0):
        level_key = _login_key('backoff-level', browser)
        level = throttle_cache().get(level_key, 0)
        backoffs = config['backoff_seconds']
        delay = backoffs[min(level, len(backoffs) - 1)]
        throttle_cache().set(level_key, level + 1, ttl)
        throttle_cache().set(_login_key('blocked', browser), time.time() + delay, delay)


def clear_login_failures(request, username):
    browser = browser_identity(request)
    throttle_cache().delete_many([
        _login_key('browser-failures', browser),
        _login_key('username-failures', username),
        _login_key('grant', browser),
        _login_key('backoff-level', browser),
        _login_key('blocked', browser),
    ])
