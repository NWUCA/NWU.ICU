import json
import os
import posixpath
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import requests
from django.conf import settings

from utils.utils import format_file_size


class ResourceDirectoryCacheError(Exception):
    pass


def normalize_directory_path(path):
    untrimmed_path = str(path)
    raw_path = untrimmed_path.strip()
    if (
        raw_path != untrimmed_path
        or not raw_path.startswith('/')
        or raw_path.startswith('//')
        or '\\' in raw_path
        or any(ord(char) < 32 or ord(char) == 127 for char in raw_path)
    ):
        raise ValueError('目录路径不合法')
    if raw_path == '/':
        return '/'
    parts = raw_path[1:].split('/')
    if any(part in {'', '.', '..'} for part in parts):
        raise ValueError('目录路径不合法')
    normalized_path = posixpath.normpath(raw_path)
    if normalized_path != raw_path or not normalized_path.startswith('/'):
        raise ValueError('目录路径不合法')
    return normalized_path


def get_resource_directory_cache_file():
    return Path(settings.RESOURCE_DIRECTORY_CACHE_FILE)


@contextmanager
def resource_directory_cache_lock(timeout=10):
    cache_file = get_resource_directory_cache_file()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file = cache_file.with_suffix(cache_file.suffix + '.lock')
    deadline = time.monotonic() + timeout
    descriptor = None
    while descriptor is None:
        try:
            descriptor = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                if time.time() - lock_file.stat().st_mtime > 60:
                    lock_file.unlink()
                    continue
            except FileNotFoundError:
                continue
            if time.monotonic() >= deadline:
                raise ResourceDirectoryCacheError('等待目录缓存写入锁超时')
            time.sleep(0.1)
    try:
        yield
    finally:
        os.close(descriptor)
        try:
            lock_file.unlink()
        except FileNotFoundError:
            pass


def read_resource_directory_cache():
    cache_file = get_resource_directory_cache_file()
    try:
        with cache_file.open(encoding='utf-8') as file:
            payload = json.load(file)
    except (FileNotFoundError, json.JSONDecodeError, OSError) as error:
        raise ResourceDirectoryCacheError('资料目录缓存不存在或无法读取') from error

    paths = payload.get('paths')
    if not isinstance(paths, list):
        raise ResourceDirectoryCacheError('资料目录缓存格式错误')
    try:
        normalized_paths = sorted({normalize_directory_path(path) for path in paths})
    except (TypeError, ValueError) as error:
        raise ResourceDirectoryCacheError('资料目录缓存包含非法路径') from error
    if '/' not in normalized_paths:
        normalized_paths.insert(0, '/')
    entries = payload.get('entries', [])
    if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
        raise ResourceDirectoryCacheError('资料目录缓存的文件树格式错误')
    return {
        'version': payload.get('version', 1),
        'updated_at': payload.get('updated_at'),
        'source': payload.get('source'),
        'storage_root': payload.get('storage_root'),
        'summary': payload.get('summary'),
        'paths': normalized_paths,
        'entries': entries,
    }


def write_resource_directory_cache(paths, source=None, entries=None, storage_root=None):
    normalized_paths = sorted({normalize_directory_path(path) for path in paths})
    if '/' not in normalized_paths:
        normalized_paths.insert(0, '/')
    if entries is None:
        entries = [
            {
                'path': path,
                'name': '/' if path == '/' else posixpath.basename(path),
                'type': 'directory',
                'size': None,
                'size_display': None,
                'modified_at': None,
            }
            for path in normalized_paths
        ]
    payload = {
        'version': 1,
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'source': source,
        'storage_root': storage_root,
        'paths': normalized_paths,
        'entries': entries,
    }
    total_file_size = sum(
        entry.get('size') or 0
        for entry in payload['entries']
        if entry.get('type') == 'file'
    )
    payload['summary'] = {
        'directory_count': len(normalized_paths),
        'file_count': sum(entry.get('type') == 'file' for entry in payload['entries']),
        'total_file_size': total_file_size,
        'total_file_size_display': format_file_size(total_file_size),
    }
    cache_file = get_resource_directory_cache_file()
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    temporary_file = None
    try:
        with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=cache_file.parent,
                prefix=cache_file.name + '.',
                suffix='.tmp',
                delete=False,
        ) as file:
            temporary_file = Path(file.name)
            json.dump(payload, file, ensure_ascii=False, indent=2)
            file.write('\n')
        os.replace(temporary_file, cache_file)
    finally:
        if temporary_file and temporary_file.exists():
            temporary_file.unlink()
    return payload


def add_resource_directory_paths(paths):
    requested_paths = {normalize_directory_path(path) for path in paths}
    if not requested_paths:
        return None
    with resource_directory_cache_lock():
        try:
            payload = read_resource_directory_cache()
            cached_paths = set(payload['paths'])
            source = payload.get('source')
            entries = list(payload.get('entries') or [])
            storage_root = payload.get('storage_root')
        except ResourceDirectoryCacheError:
            cached_paths = {'/'}
            source = settings.RESOURCES_WEBSITE_URL.rstrip('/')
            entries = []
            storage_root = None

        existing_entry_paths = {
            entry.get('path')
            for entry in entries
            if isinstance(entry, dict)
        }
        for requested_path in requested_paths:
            current_path = requested_path
            while current_path != '/':
                cached_paths.add(current_path)
                parent_path = posixpath.dirname(current_path) or '/'
                if parent_path == current_path:
                    raise ResourceDirectoryCacheError('目录路径无法安全遍历')
                current_path = parent_path
        for directory_path in sorted(cached_paths):
            if directory_path in existing_entry_paths:
                continue
            entries.append({
                'path': directory_path,
                'name': '/' if directory_path == '/' else posixpath.basename(directory_path),
                'type': 'directory',
                'size': None,
                'size_display': None,
                'modified_at': None,
            })
            existing_entry_paths.add(directory_path)
        return write_resource_directory_cache(
            cached_paths,
            source=source,
            entries=entries,
            storage_root=storage_root,
        )


def add_resource_file_entries(file_entries, directory_paths=(), storage_root=None):
    """Atomically merge newly published files and their parent directories into the cache."""
    normalized_files = []
    requested_directories = {
        normalize_directory_path(path)
        for path in directory_paths
    }
    for entry in file_entries:
        if not isinstance(entry, dict):
            raise ValueError('文件树条目格式错误')
        file_path = normalize_directory_path(entry.get('path', ''))
        if file_path == '/' or entry.get('type') != 'file':
            raise ValueError('文件树条目路径或类型不合法')
        normalized_entry = dict(entry)
        normalized_entry['path'] = file_path
        normalized_entry['name'] = posixpath.basename(file_path)
        normalized_files.append(normalized_entry)
        requested_directories.add(posixpath.dirname(file_path) or '/')

    if not normalized_files:
        return None

    with resource_directory_cache_lock():
        try:
            payload = read_resource_directory_cache()
            cached_paths = set(payload['paths'])
            source = payload.get('source')
            cached_entries = list(payload.get('entries') or [])
            cached_storage_root = payload.get('storage_root')
        except ResourceDirectoryCacheError:
            cached_paths = {'/'}
            source = settings.RESOURCES_WEBSITE_URL.rstrip('/')
            cached_entries = []
            cached_storage_root = None

        for requested_path in requested_directories:
            current_path = requested_path
            while current_path != '/':
                cached_paths.add(current_path)
                parent_path = posixpath.dirname(current_path) or '/'
                if parent_path == current_path:
                    raise ResourceDirectoryCacheError('目录路径无法安全遍历')
                current_path = parent_path
        cached_paths.add('/')

        entries_by_path = {
            entry.get('path'): entry
            for entry in cached_entries
            if isinstance(entry, dict) and entry.get('path')
        }
        for directory_path in sorted(cached_paths):
            existing_entry = entries_by_path.get(directory_path)
            if existing_entry and existing_entry.get('type') != 'directory':
                raise ResourceDirectoryCacheError(
                    f'资源树路径与已有文件冲突：{directory_path}'
                )
            entries_by_path[directory_path] = existing_entry or {
                'path': directory_path,
                'name': '/' if directory_path == '/' else posixpath.basename(directory_path),
                'type': 'directory',
                'size': None,
                'size_display': None,
                'modified_at': None,
            }

        for entry in normalized_files:
            existing_entry = entries_by_path.get(entry['path'])
            if existing_entry and existing_entry.get('type') == 'directory':
                raise ResourceDirectoryCacheError(
                    f'资源树路径与已有目录冲突：{entry["path"]}'
                )
            entries_by_path[entry['path']] = entry

        entries = sorted(
            entries_by_path.values(),
            key=lambda entry: (entry.get('path', '').casefold(), entry.get('type') != 'directory'),
        )
        return write_resource_directory_cache(
            cached_paths,
            source=source,
            entries=entries,
            storage_root=str(storage_root) if storage_root else cached_storage_root,
        )


def get_cached_child_directories(parent_path):
    parent_path = normalize_directory_path(parent_path)
    payload = read_resource_directory_cache()
    prefix = '/' if parent_path == '/' else parent_path + '/'
    directories = []
    for path in payload['paths']:
        if not path.startswith(prefix) or path == parent_path:
            continue
        remainder = path[len(prefix):]
        if remainder and '/' not in remainder:
            directories.append({
                'name': remainder,
                'path': path,
                'modified': None,
            })
    return {
        'path': parent_path,
        'directories': directories,
        'updated_at': payload.get('updated_at'),
    }


def fetch_all_resource_directory_paths(base_url, session=None, page_size=200, timeout=15):
    session = session or requests.Session()
    base_url = base_url.rstrip('/')
    visited = {'/'}
    stack = ['/']

    while stack:
        current_path = stack.pop()
        page = 1
        while True:
            try:
                response = session.post(
                    base_url + '/api/fs/list',
                    json={
                        'path': current_path,
                        'password': '',
                        'page': page,
                        'per_page': page_size,
                        'refresh': False,
                    },
                    timeout=timeout,
                )
                response.raise_for_status()
                result = response.json()
            except (requests.RequestException, ValueError) as error:
                raise ResourceDirectoryCacheError(
                    f'资料服务读取目录失败：{current_path}'
                ) from error
            data = result.get('data') or {}
            content = data.get('content')
            if result.get('code') == 200 and content is None:
                content = []
            if result.get('code') != 200 or not isinstance(content, list):
                raise ResourceDirectoryCacheError(
                    f'资料服务读取目录失败：{current_path}（{result.get("message", "未知错误")}）'
                )

            for item in content:
                name = item.get('name')
                if not item.get('is_dir') or not name or '/' in name or '\\' in name or name in {'.', '..'}:
                    continue
                child_path = normalize_directory_path(posixpath.join(current_path, name))
                if child_path not in visited:
                    visited.add(child_path)
                    stack.append(child_path)

            total = data.get('total')
            if not content or not isinstance(total, int) or page * page_size >= total:
                break
            page += 1

    return visited
