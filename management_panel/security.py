import base64
import logging
import time
from datetime import timedelta

from django.http import Http404
from django.utils import timezone

from .exceptions import AdminPasskeyRequired, AdminPermissionDenied
from .models import AdminPasskeyCredential, AdminPasskeyState


logger = logging.getLogger('management.security')
ELEVATED_UNTIL_KEY = 'admin_elevated_until'
ELEVATED_CREDENTIAL_KEY = 'admin_elevated_credential_id'
ELEVATED_REVISION_KEY = 'admin_passkey_revision'
CEREMONY_KEY = 'admin_passkey_ceremony'


def encode_bytes(value):
    return base64.urlsafe_b64encode(value).rstrip(b'=').decode('ascii')


def decode_bytes(value):
    encoded = str(value).encode('ascii')
    return base64.urlsafe_b64decode(encoded + b'=' * (-len(encoded) % 4))


def is_management_admin(user):
    return bool(user and user.is_authenticated and user.is_active and user.is_staff)


def clear_admin_elevation(request):
    for key in (ELEVATED_UNTIL_KEY, ELEVATED_CREDENTIAL_KEY, ELEVATED_REVISION_KEY, CEREMONY_KEY):
        request.session.pop(key, None)
    request.session.modified = True


def current_passkey_revision(user):
    state, _ = AdminPasskeyState.objects.get_or_create(user=user)
    return state.revision


def elevate_admin_session(request, credential):
    request.session.cycle_key()
    until = time.time() + timedelta(minutes=10).total_seconds()
    request.session[ELEVATED_UNTIL_KEY] = until
    request.session[ELEVATED_CREDENTIAL_KEY] = credential.pk
    request.session[ELEVATED_REVISION_KEY] = current_passkey_revision(request.user)
    request.session.modified = True
    return timezone.now() + timedelta(minutes=10)


def is_admin_elevated(request):
    if not is_management_admin(request.user):
        return False
    try:
        until = float(request.session.get(ELEVATED_UNTIL_KEY, 0))
        credential_id = int(request.session.get(ELEVATED_CREDENTIAL_KEY, 0))
        revision = int(request.session.get(ELEVATED_REVISION_KEY, 0))
    except (TypeError, ValueError):
        clear_admin_elevation(request)
        return False
    if until <= time.time():
        clear_admin_elevation(request)
        return False
    credential_exists = AdminPasskeyCredential.objects.filter(
        pk=credential_id,
        user=request.user,
        revoked_at__isnull=True,
    ).exists()
    state_revision = AdminPasskeyState.objects.filter(user=request.user).values_list('revision', flat=True).first()
    if not credential_exists or state_revision != revision:
        clear_admin_elevation(request)
        return False
    return True


def require_management_access(request, permission=None, require_elevation=True):
    if not is_management_admin(request.user):
        logger.warning(
            'management endpoint hidden from ineligible user user_id=%s',
            getattr(request.user, 'pk', None),
        )
        raise Http404
    if require_elevation and not is_admin_elevated(request):
        logger.warning('management elevation required user_id=%s', request.user.pk)
        raise AdminPasskeyRequired()
    if permission and not request.user.has_perm(permission):
        logger.warning('management permission denied user_id=%s permission=%s', request.user.pk, permission)
        raise AdminPermissionDenied()
