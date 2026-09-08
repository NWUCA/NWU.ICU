from django.contrib import admin
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.cache import never_cache

from utils.throttle import LoginIPRateThrottle, LoginUsernameRateThrottle


@never_cache
@csrf_protect
def throttled_admin_login(request):
    """Apply the public login buckets to Django Admin credential attempts."""
    if request.method == 'POST':
        request.data = request.POST
        waits = []
        for throttle_class in (LoginIPRateThrottle, LoginUsernameRateThrottle):
            throttle = throttle_class()
            if not throttle.allow_request(request, None):
                waits.append(throttle.wait())
        if waits:
            response = JsonResponse({
                'message': '请求过于频繁，请稍后重试',
                'errors': {'login': {'err_code': 'throttled', 'err_msg': '登录尝试次数过多'}},
            }, status=429)
            valid_waits = [wait for wait in waits if wait is not None]
            if valid_waits:
                response['Retry-After'] = str(max(1, int(max(valid_waits))))
            return response
    return admin.site.login(request)
