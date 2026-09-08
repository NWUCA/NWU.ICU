import posixpath
import shutil
import hashlib
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from django.conf import settings

from common.file.resource_directories import (
    add_resource_file_entries,
    normalize_directory_path,
)
from utils.utils import format_file_size


logger = logging.getLogger(__name__)


class ResourcePublishError(Exception):
    pass


def _sha256_file(file_path):
    digest = hashlib.sha256()
    with file_path.open('rb') as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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
    raw_path = str(path).strip()
    normalized_path = posixpath.normpath(raw_path)
    if (
        '\\' in raw_path
        or '//' in raw_path
        or any(ord(char) < 32 or ord(char) == 127 for char in raw_path)
        or normalized_path.startswith('/')
        or normalized_path in {'', '.', '..'}
        or any(part in {'', '.', '..'} for part in raw_path.split('/'))
        or normalized_path != raw_path
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
    """Publish staged files safely and idempotently into AList's local storage."""
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
        # Check every requested destination before creating any visible file.
        for upload_file in upload_files:
            relative_path = _normalize_relative_file_path(upload_file.relative_path)
            virtual_path = normalize_directory_path(posixpath.join(target_path, relative_path))
            destination = storage_root.joinpath(*virtual_path.lstrip('/').split('/'))
            if destination.exists() or destination.is_symlink():
                if not (
                    getattr(upload_file, 'published_path', '') == virtual_path
                    and getattr(upload_file, 'content_hash', '')
                    and destination.is_file()
                    and _sha256_file(destination) == upload_file.content_hash
                ):
                    raise ResourcePublishError(f'目标文件已存在，未覆盖：{virtual_path}')
        for upload_file in upload_files:
            relative_path = _normalize_relative_file_path(upload_file.relative_path)
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
                if (
                    getattr(upload_file, 'published_path', '') == virtual_path
                    and getattr(upload_file, 'content_hash', '')
                    and destination.is_file()
                    and _sha256_file(destination) == upload_file.content_hash
                ):
                    stat_result = destination.stat()
                    if not getattr(upload_file, 'published_at', None):
                        upload_file.published_at = datetime.now(timezone.utc)
                        if hasattr(upload_file, 'save'):
                            upload_file.save(update_fields=('published_at',))
                else:
                    raise ResourcePublishError(f'目标文件已存在，未覆盖：{virtual_path}')
            else:
                try:
                    source_path = Path(upload_file.file.path).resolve(strict=True)
                except (OSError, ValueError) as error:
                    raise ResourcePublishError(f'投稿原文件不存在：{relative_path}') from error
                if not source_path.is_file():
                    raise ResourcePublishError(f'投稿原路径不是文件：{relative_path}')
                temporary_destination = destination.with_name(
                    f'.{destination.name}.nwuicu-{getattr(upload_request, "pk", "upload")}.part'
                )
                if temporary_destination.exists() or temporary_destination.is_symlink():
                    temporary_destination.unlink()
                digest = hashlib.sha256()
                try:
                    with source_path.open('rb') as source, temporary_destination.open('xb') as output:
                        while chunk := source.read(1024 * 1024):
                            digest.update(chunk)
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    if temporary_destination.stat().st_size != getattr(upload_file, 'size', source_path.stat().st_size):
                        raise ResourcePublishError(f'发布后的文件大小不匹配：{relative_path}')
                    shutil.copystat(source_path, temporary_destination, follow_symlinks=False)
                    # Persist the recovery marker before the visible rename.  A worker
                    # restarted after os.replace can then verify and reuse this file.
                    upload_file.content_hash = digest.hexdigest()
                    upload_file.published_path = virtual_path
                    if hasattr(upload_file, 'save'):
                        upload_file.save(update_fields=('content_hash', 'published_path'))
                    # A hard link publishes the completed file atomically and, unlike
                    # os.replace(), fails if another writer created the final path.
                    os.link(temporary_destination, destination)
                    temporary_destination.unlink()
                    created_files.append(destination)
                except FileExistsError as error:
                    raise ResourcePublishError(f'目标文件已存在，未覆盖：{virtual_path}') from error
                finally:
                    if temporary_destination.exists():
                        temporary_destination.unlink()
                upload_file.published_at = datetime.now(timezone.utc)
                if hasattr(upload_file, 'save'):
                    upload_file.save(update_fields=('content_hash', 'published_path', 'published_at'))
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


def delete_resource_upload_staging_files(upload_request):
    """Best-effort cleanup after publishing; never rolls back published files."""
    all_deleted = True
    for upload_file in upload_request.files.all():
        if not upload_file.file or not hasattr(upload_file.file, 'delete'):
            continue
        try:
            upload_file.file.delete(save=False)
            upload_file.file = None
            if hasattr(upload_file, 'save'):
                upload_file.save(update_fields=('file',))
        except Exception:
            all_deleted = False
            logger.exception('Failed to delete staging file for resource upload file %s', upload_file.pk)
    return all_deleted
