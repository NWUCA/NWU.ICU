import uuid

from django.conf import settings
from django.core import signing
from django.core.exceptions import RequestDataTooBig


BROWSER_ID_SALT = 'nwuicu.browser-identity.v1'


class RequestBodySizeLimitMiddleware:
    """Reject oversized non-file bodies before DRF validation and throttles."""

    limited_content_types = {'application/json', 'application/x-www-form-urlencoded'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        content_type = request.content_type.split(';', 1)[0].lower()
        try:
            content_length = int(request.META.get('CONTENT_LENGTH') or 0)
        except (TypeError, ValueError):
            content_length = 0
        limit = settings.DATA_UPLOAD_MAX_MEMORY_SIZE
        if limit is not None and content_type in self.limited_content_types and content_length > limit:
            raise RequestDataTooBig('Request body exceeded DATA_UPLOAD_MAX_MEMORY_SIZE.')
        return self.get_response(request)


def _decode_browser_id(value):
    if not value:
        return None
    try:
        browser_id = signing.loads(value, salt=BROWSER_ID_SALT)
        return str(uuid.UUID(browser_id))
    except (signing.BadSignature, TypeError, ValueError, AttributeError):
        return None


class BrowserIdentityMiddleware:
    """Give anonymous throttles a stable identity without relying on NAT IPs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        config = settings.API_RATE_LIMITS['browser_cookie']
        cookie_name = config['name']
        browser_id = _decode_browser_id(request.COOKIES.get(cookie_name))
        should_set_cookie = browser_id is None
        if browser_id is None:
            browser_id = str(uuid.uuid4())
        request.nwu_browser_id = browser_id

        response = self.get_response(request)
        if should_set_cookie:
            response.set_cookie(
                cookie_name,
                signing.dumps(browser_id, salt=BROWSER_ID_SALT, compress=True),
                max_age=config['max_age'],
                secure=settings.SESSION_COOKIE_SECURE,
                httponly=True,
                samesite='Lax',
            )
        return response
