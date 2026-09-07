"""Count accepted attachment requests, never previews or completed transfers."""
import logging
from ipaddress import ip_address
from django.db import DatabaseError, transaction
from django.utils import timezone
from django.utils.crypto import salted_hmac
from common.models import ResourceDownloadEvent


def parse_ip(value):
    try:
        address = ip_address(value.strip())
        return getattr(address, 'ipv4_mapped', None) or address
    except ValueError:
        return None


def client_ip(request):
    candidates = [request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0],
                  request.META.get('HTTP_X_REAL_IP', ''), request.META.get('REMOTE_ADDR', '')]
    for candidate in candidates:
        address = parse_ip(candidate)
        if address is not None:
            return str(address)
    return None


def record_download(request, path):
    authenticated = bool(request.user.is_authenticated)
    address = client_ip(request)
    user_agent = ''.join(char for char in request.META.get('HTTP_USER_AGENT', '')[:2048]
                         if ord(char) >= 32 and ord(char) != 127)
    actor = f'user:{request.user.pk}' if authenticated else (
        (address or '') + ':' + user_agent)
    bucket = int(timezone.now().timestamp()) // 300
    key = salted_hmac('resource-download', f'{actor}\n{path}\n{bucket}', algorithm='sha256').hexdigest()
    try:
        with transaction.atomic():
            ResourceDownloadEvent.objects.get_or_create(dedupe_key=key, defaults={
                'path': path, 'authenticated': authenticated,
                'ip_address': address, 'user_agent': user_agent,
                'user_id': request.user.pk if authenticated else None,
                'username': request.user.get_username() if authenticated else '',
            })
    except DatabaseError:
        logging.getLogger(__name__).exception('Could not record resource download')
