import posixpath
import shutil
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

from common.file.resource_directories import (
    add_resource_file_entries,
    normalize_directory_path,
)
from utils.utils import format_file_size


class ResourcePublishError(Exception):
    pass


def _get_storage_root():
    configured_root = getattr(settings, 'RESOURCE_STORAGE_ROOT', None)
    if not configured_root:
        raise ResourcePublishError('尚未配置 RESOURCE_STORAGE_ROOT')
    try:
        storage_root = Path(configured_root).resolve(strict=True)
    except OSError as error:
        raise ResourcePublishError('资料存储根目录不存在或无法访问') from error
    if not storage_root.is_dir():
        raise ResourcePublishError('资料存储根路径不是目录')
    return storage_root


def _normalize_relative_file_path(path):
    raw_path = str(path).strip().replace('\\', '/')
    normalized_path = posixpath.normpath(raw_path)
    if (
        normalized_path.startswith('/')
        or normalized_path in {'', '.', '..'}
        or any(part == '..' for part in normalized_path.split('/'))
    ):
        raise ResourcePublishError(f'投稿文件路径不合法：{path}')
    return normalized_path


def _ensure_directory(storage_root, directory, created_directories):
    try:
        relative_directory = directory.relative_to(storage_root)
    except ValueError as error:
        raise ResourcePublishError('目标目录超出资料存储根目录') from error

    current_directory = storage_root
    for part in relative_directory.parts:
        current_directory = current_directory / part
        try:
            current_directory.mkdir()
            created_directories.append(current_directory)
        except FileExistsError:
            if not current_directory.is_dir():
                raise ResourcePublishError(f'目标路径不是目录：{current_directory}')

    try:
        resolved_directory = directory.resolve(strict=True)
        resolved_directory.relative_to(storage_root)
    except (OSError, ValueError) as error:
        raise ResourcePublishError('目标目录通过符号链接超出资料存储根目录') from error
    return resolved_directory


def _rollback(created_files, created_directories):
    for file_path in reversed(created_files):
        try:
            file_path.unlink(missing_ok=True)
        except OSError:
            pass
    for directory in reversed(created_directories):
        try:
            directory.rmdir()
        except OSError:
            pass


def publish_resource_upload(upload_request):
    """Copy one staged upload into AList's local storage and update the local tree cache."""
    storage_root = _get_storage_root()
    try:
        target_path = normalize_directory_path(upload_request.target_path)
    except ValueError as error:
        raise ResourcePublishError('投稿目标目录不合法') from error
    if target_path == '/':
        raise ResourcePublishError('禁止发布到资料根目录')

    upload_files = list(upload_request.files.all())
    if not upload_files:
        raise ResourcePublishError('投稿中没有可发布的文件')

    created_files = []
    created_directories = []
    published_entries = []
    published_directories = {target_path}
    try:
        for upload_file in upload_files:
            relative_path = _normalize_relative_file_path(upload_file.relative_path)
            try:
                source_path = Path(upload_file.file.path).resolve(strict=True)
            except (OSError, ValueError) as error:
                raise ResourcePublishError(f'投稿原文件不存在：{relative_path}') from error
            if not source_path.is_file():
                raise ResourcePublishError(f'投稿原路径不是文件：{relative_path}')

            virtual_path = normalize_directory_path(posixpath.join(target_path, relative_path))
            virtual_parent = posixpath.dirname(virtual_path) or '/'
            published_directories.add(virtual_parent)
            destination = storage_root.joinpath(*virtual_path.lstrip('/').split('/'))
            resolved_parent = _ensure_directory(
                storage_root,
                destination.parent,
                created_directories,
            )
            destination = resolved_parent / destination.name
            if destination.exists() or destination.is_symlink():
                raise ResourcePublishError(f'目标文件已存在，未覆盖：{virtual_path}')

            try:
                with source_path.open('rb') as source, destination.open('xb') as output:
                    created_files.append(destination)
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                shutil.copystat(source_path, destination, follow_symlinks=False)
            except FileExistsError as error:
                raise ResourcePublishError(f'目标文件已存在，未覆盖：{virtual_path}') from error

            stat_result = destination.stat()
            published_entries.append({
                'path': virtual_path,
                'name': posixpath.basename(virtual_path),
                'type': 'file',
                'size': stat_result.st_size,
                'size_display': format_file_size(stat_result.st_size),
                'modified_at': datetime.fromtimestamp(
                    stat_result.st_mtime,
                    tz=timezone.utc,
                ).isoformat(),
            })

        add_resource_file_entries(
            published_entries,
            directory_paths=published_directories,
            storage_root=storage_root,
        )
    except Exception as error:
        _rollback(created_files, created_directories)
        if isinstance(error, ResourcePublishError):
            raise
        raise ResourcePublishError(f'发布失败：{error}') from error

    return published_entries
