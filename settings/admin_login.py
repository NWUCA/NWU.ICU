from django.contrib import admin
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from rest_framework.exceptions import Throttled

from utils.throttle import (
    CaptchaRequired,
    InvalidCaptchaProof,
    LoginIPRateThrottle,
    check_login_attempt,
    clear_login_failures,
    record_login_failure,
)


def _limited_response(code, message, wait=None, scope=None):
    response = JsonResponse({
        'message': message,
        'errors': {'login': {'err_code': code, 'err_msg': message}},
        'contents': {'captcha_scope': scope} if scope else {},
    }, status=429 if code != 'invalid_captcha_proof' else 400)
    if wait is not None:
        response['Retry-After'] = str(max(1, int(wait)))
    return response


@never_cache
@csrf_protect
def throttled_admin_login(request):
    """Share progressive credential-failure state with the public API login."""
    username = ''
    if request.method == 'POST':
        request.data = request.POST
        username = str(request.POST.get('username', ''))
        ip_throttle = LoginIPRateThrottle()
        if not ip_throttle.allow_request(request, None):
            return _limited_response('too_many_requests', '登录尝试次数过多', ip_throttle.wait())
        try:
            check_login_attempt(request, username)
        except CaptchaRequired as error:
            return _limited_response('captcha_required', str(error.detail), error.wait, error.scope)
        except InvalidCaptchaProof as error:
            return _limited_response('invalid_captcha_proof', str(error.detail))
        except Throttled as error:
            return _limited_response('too_many_requests', '登录尝试次数过多', error.wait)

    response = admin.site.login(request)
    if request.method == 'POST':
        if 300 <= response.status_code < 400:
            clear_login_failures(request, username)
        else:
            record_login_failure(request, username)
    return response
