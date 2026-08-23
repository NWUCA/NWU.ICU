from rest_framework.authentication import SessionAuthentication


class CSRFSafeSessionAuthentication(SessionAuthentication):
    """Enforce CSRF for unsafe requests, including anonymous auth endpoints."""

    def authenticate(self, request):
        self.enforce_csrf(request)
        return super().authenticate(request)
