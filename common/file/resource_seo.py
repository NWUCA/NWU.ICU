"""Public resource documents and discovery endpoints, sharing browser ACLs."""
import math
import posixpath
from urllib.parse import quote, urlencode
from xml.etree.ElementTree import Element, SubElement, tostring

from django.http import Http404, HttpResponse, HttpResponsePermanentRedirect
from django.shortcuts import render
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_safe
from rest_framework.exceptions import NotAuthenticated, ValidationError

from .resource_access import ResourceAccess
from .resource_browser import (
    ResourceUnavailable, browse_resource, normalize_resource_path, resource_root,
)
from .resource_directories import ResourceDirectoryCacheError, read_resource_directory_cache

SITE_ORIGIN = 'https://nwu.icu'
SITEMAP_PAGE_SIZE = 10000
XMLNS = 'http://www.sitemaps.org/schemas/sitemap/0.9'


def resource_page_url(path):
    # Match encodeURIComponent in the frontend; never decode an already decoded path.
    return '/disk' if path == '/' else '/disk' + quote(path, safe="/!~*'()")


def resource_metadata(contents):
    parent = posixpath.basename(posixpath.dirname(contents['path']))
    name = contents['name']
    if contents['path'] == '/':
        title = '资料下载'
        description = '浏览和下载 NWU.ICU 公开学习资料。'
    elif contents['type'] == 'file':
        title = f"{name} - {parent or '资料下载'}"
        description = f"{name}，所属目录：{parent or '全部资料'}。查看文件信息与下载入口。"
    else:
        title = f'{name} - 资料下载'
        description = f'{name}，浏览目录中的学习资料和文件。'
    return {'title': title + ' - NWU.ICU', 'description': description,
            'canonical': SITE_ORIGIN + resource_page_url(contents['path'])}


@require_safe
def resource_page(request, path=''):
    raw_path = '/' + path
    # Direct directory URLs use no trailing slash. Validate access before redirecting.
    requested_path = raw_path[:-1] if raw_path.endswith('/') and raw_path != '/' else raw_path
    context = {'title': '资料暂不可用 - NWU.ICU', 'noindex': True}
    status = 200
    try:
        contents = browse_resource(requested_path, request.user)
        canonical_path = resource_page_url(contents['path'])
        if raw_path != requested_path or request.path == '/disk/':
            return HttpResponsePermanentRedirect(canonical_path)
        context.update(resource_metadata(contents))
        context.update(contents=contents, noindex=not contents['indexable'])
        context['breadcrumbs'] = [{'name': '全部资料', 'url': '/disk'}]
        parts = contents['path'].split('/')[1:]
        for index, name in enumerate(parts):
            if name:
                context['breadcrumbs'].append({'name': name, 'url': resource_page_url('/' + '/'.join(parts[:index + 1]))})
        context['entries'] = [{**entry, 'url': resource_page_url(entry['path'])} for entry in contents.get('entries', [])]
        context['download_url'] = '/api/resources/file/?' + urlencode({'path': contents['path']})
    except NotAuthenticated:
        status = 401
        context.update(title='资料需要登录 - NWU.ICU', error='此目录需要登录后访问。')
    except (Http404, ValidationError):
        status = 404
        context.update(title='资料未找到 - NWU.ICU', error='这个资料不存在、已移动或无权访问。')
    except ResourceUnavailable:
        status = 503
        context.update(noindex=False, error='资料暂时无法读取，请稍后重试。')
    context['status'] = status
    response = render(request, 'resources/page.html', context, status=status)
    # HTML and bootstrap can contain session-specific listings; never share-cache them.
    response['Cache-Control'] = 'private, no-store'
    if context['noindex']:
        response['X-Robots-Tag'] = 'noindex, follow'
    if status == 503:
        response['Retry-After'] = '300'
    return response


@require_safe
def robots_txt(request):
    response = HttpResponse(
        f'User-agent: *\nAllow: /\nDisallow: /admin/\nDisallow: /manage\n'
        f'Sitemap: {SITE_ORIGIN}/sitemap.xml\n', content_type='text/plain; charset=utf-8')
    response['Cache-Control'] = 'public, max-age=300'
    return response


def public_sitemap_entries():
    # Use the existing event-updated index, not a full storage scan per crawler request.
    resource_root()  # Fail with 503 when storage is unavailable, not an empty sitemap.
    entries = read_resource_directory_cache()['entries']
    access = ResourceAccess()  # Always anonymous, even for a logged-in administrator.
    public = {}
    if access.allowed('/'):
        public['/'] = None
    for entry in entries:
        if entry.get('type') not in {'file', 'directory'}:
            continue
        try:
            path = normalize_resource_path(entry['path'])
        except (KeyError, Http404, ValidationError, TypeError):
            continue
        if not access.allowed(path):
            continue
        modified = entry.get('modified_at')
        try:
            timestamp = parse_datetime(modified) if isinstance(modified, str) else None
        except ValueError:
            timestamp = None
        public[path] = timestamp.isoformat() if timestamp else None
    return sorted(public.items())


@require_safe
def sitemap(request):
    try:
        entries = public_sitemap_entries()
    except (ResourceUnavailable, ResourceDirectoryCacheError):
        response = HttpResponse('资料索引暂时不可用', status=503, content_type='text/plain; charset=utf-8')
        response['Retry-After'] = '300'
        response['Cache-Control'] = 'no-store'
        return response
    page_count = max(1, math.ceil(len(entries) / SITEMAP_PAGE_SIZE))
    page = request.GET.get('page')
    if page is None:
        root = Element('sitemapindex', xmlns=XMLNS)
        for number in range(1, page_count + 1):
            SubElement(SubElement(root, 'sitemap'), 'loc').text = f'{SITE_ORIGIN}/sitemap.xml?page={number}'
    else:
        if not page.isascii() or not page.isdecimal() or len(page) > 8 or not 1 <= int(page) <= page_count:
            return HttpResponse(status=404)
        start = (int(page) - 1) * SITEMAP_PAGE_SIZE
        root = Element('urlset', xmlns=XMLNS)
        for path, modified in entries[start:start + SITEMAP_PAGE_SIZE]:
            item = SubElement(root, 'url')
            SubElement(item, 'loc').text = SITE_ORIGIN + resource_page_url(path)
            if modified:
                SubElement(item, 'lastmod').text = modified
    response = HttpResponse(tostring(root, encoding='utf-8', xml_declaration=True), content_type='application/xml; charset=utf-8')
    # Reapply current permissions and index changes on every request.
    response['Cache-Control'] = 'no-store'
    return response
