from urllib.parse import urlencode

from django.conf import settings
from django.core import signing

from utils.throttle import (
    CaptchaRequired,
    _inspect_window,
    _parse_rate,
    _record_window,
    actor_identity,
    consume_captcha_proof,
    digest,
    throttle_cache,
)


TICKET_SALT = 'nwuicu.resource-ticket.v1'


def download_gate_enabled():
    return bool(settings.API_RATE_LIMITS['resource_download']['enabled'])


def _ticket(request, path, inline):
    config = settings.API_RATE_LIMITS['resource_download']
    return signing.dumps({
        'actor': actor_identity(request),
        'path': path,
        'inline': bool(inline),
    }, salt=TICKET_SALT, compress=True), config['ticket_ttl']


def authorize_resource(request, path, inline=False):
    config = settings.API_RATE_LIMITS['resource_download']
    query = {'path': path}
    if inline:
        query['inline'] = '1'
    if not config['enabled']:
        return f"/api/resources/file/?{urlencode(query)}", None

    actor = actor_identity(request)
    # Opening a preview and then downloading the same path is one authorization
    # event for quota purposes, although each signed ticket remains mode-bound.
    dedupe_key = f"resource-download:dedupe:{digest(f'{actor}:{path}')}"
    if not throttle_cache().get(dedupe_key):
        rate = config['user'] if request.user.is_authenticated else config['anonymous']
        window = _inspect_window('resource_download', 'actor', actor, rate)
        if not window[0]:
            if not consume_captcha_proof(request, 'resource_download'):
                raise CaptchaRequired('resource_download', window[1])
            # A solved challenge grants one fresh allowance of the configured size.
            throttle_cache().delete(window[2])
            window = _inspect_window('resource_download', 'actor', actor, rate)
        parsed = _parse_rate(rate)
        if parsed:
            _record_window(window[2], window[3], parsed[1])
        throttle_cache().set(dedupe_key, True, config['dedupe_ttl'])

    ticket, ttl = _ticket(request, path, inline)
    query['access'] = ticket
    return f"/api/resources/file/?{urlencode(query)}", ttl


def require_resource_ticket(request, path, inline=False):
    config = settings.API_RATE_LIMITS['resource_download']
    if not config['enabled']:
        return
    try:
        payload = signing.loads(
            request.query_params.get('access', ''),
            salt=TICKET_SALT,
            max_age=config['ticket_ttl'],
        )
    except signing.BadSignature as error:
        raise CaptchaRequired('resource_download') from error
    if (
        payload.get('actor') != actor_identity(request)
        or payload.get('path') != path
        or payload.get('inline') != bool(inline)
    ):
        raise CaptchaRequired('resource_download')
