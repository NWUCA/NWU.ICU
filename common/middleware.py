from django.contrib import messages
from django.shortcuts import redirect


def ensure_nickname_middleware(get_response):
    # One-time configuration and initialization.

    def middleware(request):
        # Code to be executed for each request before
        # the view (and later middleware) are called.
        if (
            request.path != "/settings/"
            and request.user.is_authenticated
            and not request.user.nickname
        ):
            messages.error(request, "请设置昵称")
            return redirect('/settings/')

        response = get_response(request)

        return response

    return middleware
