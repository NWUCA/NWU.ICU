"""Public, read-only browsing of the configured resource tree on Windows/Linux."""
import mimetypes
import posixpath
import re
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.utils.http import content_disposition_header, http_date
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from utils.utils import return_response
from .resource_directories import ResourceDirectoryCacheError, read_resource_directory_cache
from .resource_access import ResourceAccess
from .resource_statistics import record_download


class ResourceUnavailable(APIException):
    status_code = 503
    default_detail = '资料目录暂时无法访问，请稍后重试。'


def resource_root():
    configured = getattr(settings, 'RESOURCE_STORAGE_ROOT', None)
    if not configured:
        raise ResourceUnavailable()
    try:
        root = Path(configured).resolve(strict=True)
        if not root.is_dir():
            raise ResourceUnavailable()
        return root
    except (OSError, RuntimeError) as error:
        raise ResourceUnavailable() from error


def visible_name(name):
    return not name.startswith('.') and name.casefold() != 'readme.md'


def resolve_resource(raw_path, *, allow_readme=False):
    # URL paths always use POSIX separators, regardless of the host filesystem.
    raw = str(raw_path).replace('\\', '/')
    parts = raw.split('/')
    if not raw.startswith('/') or raw.startswith('//') or any(
        part in {'.', '..'} or ':' in part or any(ord(char) < 32 for char in part)
        or part.endswith((' ', '.')) for part in parts if part
    ):
        raise ValidationError({'path': '资料路径不合法。'})
    if any(part.startswith('.') or (not allow_readme and part.casefold() == 'readme.md')
           for part in parts if part):
        raise Http404
    root = resource_root()
    path = '/' + '/'.join(part for part in parts if part)
    target = root
    try:
        # Reject aliases (including Windows junctions), even when they point inside
        # the tree: an alias must never expose a hidden README or private folder.
        for part in parts:
            if not part:
                continue
            target = target / part
            if target.is_symlink() or getattr(target, 'is_junction', lambda: False)():
                raise Http404
        target = target.resolve(strict=True)
        target.relative_to(root)
        if any(part.startswith('.') for part in target.relative_to(root).parts):
            raise Http404
        if not allow_readme and target.name.casefold() == 'readme.md':
            raise Http404
    except (OSError, RuntimeError, ValueError) as error:
        raise Http404 from error
    return target, path


def entry_metadata(target, path):
    stat = target.stat()
    return {
        'name': target.name,
        'path': path,
        'type': 'directory' if target.is_dir() else 'file',
        'size': None if target.is_dir() else stat.st_size,
        'modified_at': datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
    }


def read_directory_readme(directory):
    candidates = sorted((p for p in directory.iterdir() if p.name.casefold() == 'readme.md'),
                        key=lambda p: (p.name != 'readme.md', p.name))
    for candidate in candidates:
        if candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            with candidate.open('rb') as source:
                raw = source.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                return '', '目录说明超过 1 MB，暂时无法显示。'
            for encoding in ('utf-8-sig', 'gb18030'):
                try:
                    return raw.decode(encoding), ''
                except UnicodeDecodeError:
                    pass
            return raw.decode('utf-8', errors='replace'), ''
        except OSError:
            return '', '目录说明暂时无法读取。'
    return '', ''


class ResourceBrowseView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        target, path = resolve_resource(request.query_params.get('path', '/'))
        access = ResourceAccess(request.user)
        access.require(path)
        try:
            contents = entry_metadata(target, path)
            directory = target if target.is_dir() else target.parent
            contents['readme'], contents['readme_warning'] = read_directory_readme(directory)
            if target.is_dir():
                entries = []
                for child in target.iterdir():
                    if not visible_name(child.name):
                        continue
                    child_path = posixpath.join(path, child.name)
                    if not access.allowed(child_path):
                        continue
                    try:
                        resolved, _ = resolve_resource(child_path)
                        if resolved.is_dir() or resolved.is_file():
                            entries.append(entry_metadata(resolved, child_path))
                    except (Http404, ValidationError, OSError):
                        continue
                contents['entries'] = sorted(entries, key=lambda item: (
                    item['type'] != 'directory', item['name'].casefold(), item['name']))
            elif not target.is_file():
                raise Http404
        except OSError as error:
            raise ResourceUnavailable() from error
        response = return_response(contents=contents)
        response['Cache-Control'] = 'no-store'
        return response


def search_resources(keyword, page, page_size, user=None):
    """Use the local tree index; revalidate matches against the actual storage."""
    resource_root()
    try:
        entries = read_resource_directory_cache()['entries']
    except ResourceDirectoryCacheError as error:
        raise ResourceUnavailable('资料搜索索引暂时不可用，请先按目录浏览。') from error
    matches = []
    access = ResourceAccess(user)
    for entry in entries:
        name = entry.get('name', '')
        path = entry.get('path', '')
        if not access.allowed(path):
            continue
        if path == '/' or not visible_name(name) or keyword.casefold() not in name.casefold():
            continue
        try:
            target, path = resolve_resource(path)
            if not (target.is_file() or target.is_dir()):
                continue
            metadata = entry_metadata(target, path)
        except (Http404, ValidationError, OSError):
            continue
        matches.append({
            'name': name, 'size': metadata['size'] or 0,
            'path': posixpath.dirname(path),
            'type': 'dir' if metadata['type'] == 'directory' else 'file',
            'url': '/disk',
        })
    matches.sort(key=lambda item: (item['type'] != 'dir', item['path'], item['name'].casefold()))
    total = len(matches)
    return {
        'total_pages': (total + page_size - 1) // page_size,
        'current_page': page, 'has_next': total > page * page_size,
        'has_previous': page > 1, 'total_count': total,
    }, matches[(page - 1) * page_size:page * page_size]


# Never serve uploaded HTML/SVG as a same-origin active document.
INLINE_TYPES = {
    '.pdf': 'application/pdf', '.png': 'image/png', '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg', '.gif': 'image/gif', '.webp': 'image/webp',
    '.avif': 'image/avif', '.txt': 'text/plain; charset=utf-8',
}


def stream_range(source, start, length):
    try:
        source.seek(start)
        while length > 0:
            chunk = source.read(min(length, 64 * 1024))
            if not chunk:
                break
            length -= len(chunk)
            yield chunk
    finally:
        source.close()


class ResourceFileView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        target, path = resolve_resource(request.query_params.get('path', '/'))
        ResourceAccess(request.user).require(path)
        if not target.is_file():
            raise Http404
        try:
            source = target.open('rb')
            stat = target.stat()
        except OSError as error:
            raise Http404 from error
        size = stat.st_size
        inline = request.query_params.get('inline') == '1' and target.suffix.lower() in INLINE_TYPES
        content_type = INLINE_TYPES[target.suffix.lower()] if inline else (
            mimetypes.guess_type(target.name)[0] or 'application/octet-stream')
        modified = http_date(stat.st_mtime)
        etag = f'"{stat.st_mtime_ns:x}-{size:x}"'
        range_header = request.headers.get('Range', '')
        if request.headers.get('If-Range', etag) not in {etag, modified}:
            range_header = ''
        if range_header:
            match = re.fullmatch(r'bytes=(\d*)-(\d*)', range_header)
            try:
                if not match or not any(match.groups()):
                    raise ValueError
                first, last = match.groups()
                start = int(first) if first else max(0, size - int(last))
                end = min(int(last), size - 1) if first and last else size - 1
                if start > end or start >= size or (not first and int(last) == 0):
                    raise ValueError
            except ValueError:
                source.close()
                response = HttpResponse(status=416)
                response['Content-Range'] = f'bytes */{size}'
                return response
            response = StreamingHttpResponse(stream_range(source, start, end - start + 1),
                                             status=206, content_type=content_type)
            response['Content-Length'] = str(end - start + 1)
            response['Content-Range'] = f'bytes {start}-{end}/{size}'
            # Register close on the response even if its iterator is never consumed.
            response._resource_closers.append(source.close)
        else:
            response = FileResponse(source, content_type=content_type)
        response['Content-Disposition'] = content_disposition_header(not inline, target.name)
        response['Accept-Ranges'] = 'bytes'
        response['Last-Modified'] = modified
        response['ETag'] = etag
        response['X-Content-Type-Options'] = 'nosniff'
        response['Content-Security-Policy'] = "sandbox; default-src 'none'"
        response['Cache-Control'] = 'private, no-store'
        if request.method == 'GET' and request.query_params.get('inline') != '1' and (not range_header or start == 0):
            record_download(request, path)
        return response
