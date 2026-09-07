from urllib.parse import urlencode

from django.shortcuts import redirect

from .security import is_admin_elevated


class AdminPasskeyElevationMiddleware:
    EXEMPT_PATHS = {'/admin/login/', '/admin/logout/'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            request.path.startswith('/admin/')
            and request.path not in self.EXEMPT_PATHS
            and request.user.is_authenticated
            and request.user.is_active
            and request.user.is_staff
            and not is_admin_elevated(request)
        ):
            query = urlencode({'next': request.get_full_path()})
            return redirect(f'/manage?{query}')
        return self.get_response(request)

