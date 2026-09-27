"""Stable, one-hop destinations for historical AList URLs."""
import json
from pathlib import Path
from urllib.parse import unquote, urlencode

from django.http import HttpResponse, HttpResponsePermanentRedirect
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from .resource_browser import ResourceFileView, normalize_resource_path
from .resource_limits import authorize_resource
from .resource_seo import SITE_ORIGIN, resource_page_url


# Versioned alongside code, loaded once per worker rather than per request.
with Path(__file__).with_name('resource_legacy_aliases.json').open(encoding='utf-8') as source:
    COLLEGE_ALIASES = json.load(source)
RETIRED_ROUTES = {'api', 'assets', 'static'}
OLD_CREDENTIALS = {'sign', 'signature', 'token', 'access', 'password'}


def legacy_destination(raw_uri):
    raw_path, _, query = raw_uri.partition('?')
    try:
        # Decode exactly once: a literal filename "%23" must not become "#".
        path = unquote(raw_path, errors='strict')
    except UnicodeError as error:
        raise ValidationError('旧资料地址编码不合法。') from error
    if not path.startswith('/') or path.startswith('//'):
        raise ValidationError('旧资料地址不合法。')
    if path.split('/')[1] in RETIRED_ROUTES:
        return None
    kind = 'page'
    if path.startswith(('/d/', '/p/')):
        kind, path = path[1], path[2:]
    if path == '/local' or path.startswith('/local/'):
        path = path[6:] or '/'
    if path != '/' and path.endswith('/'):
        path = path[:-1]
    path = normalize_resource_path(path)
    parts = path.split('/')
    if len(parts) >= 3 and parts[1] == '【3】学院课程':
        parts[2] = COLLEGE_ALIASES.get(parts[2], parts[2])
    path = '/'.join(parts)
    if kind != 'page':
        params = {'path': path}
        if kind == 'p':
            params['inline'] = '1'
        return SITE_ORIGIN + '/api/resources/file/legacy/?' + urlencode(params)
    # Retain ordinary page parameters without copying obsolete credentials.
    query = '&'.join(item for item in query.split('&') if item and
                     unquote(item.partition('=')[0]).casefold() not in OLD_CREDENTIALS)
    return SITE_ORIGIN + resource_page_url(path) + ('?' + query if query else '')


class LegacyResourceRedirectView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        destination = legacy_destination(request.headers.get('X-Legacy-URI', ''))
        response = HttpResponsePermanentRedirect(destination) if destination else HttpResponse(status=410)
        response['Cache-Control'] = 'no-store'
        return response


class LegacyResourceFileView(ResourceFileView):
    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response

    def check_download_access(self, request, path, inline):
        # Old clients cannot POST to authorize first. Apply the same quota/captcha
        # policy here, after inherited disk and ACL checks, on every request.
        # Never permanently redirect to an expiring, actor-bound ticket URL.
        authorize_resource(request, path, inline)
