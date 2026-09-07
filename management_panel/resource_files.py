"""Management of published files. No operation overwrites an existing path."""
import hashlib
import json
import logging
import os
import posixpath
import re
import tempfile
import uuid
from pathlib import Path

from django.http import Http404
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework import serializers

from common.file.resource_browser import entry_metadata, resolve_resource, resource_root
from common.file.resource_directories import (
    ResourceDirectoryCacheError, read_resource_directory_cache,
    resource_directory_cache_lock, write_resource_directory_cache,
)
from scripts.export_resource_tree import build_resource_tree
from utils.utils import format_file_size, return_response
from .views import ManagementAPIView
from common.models import ResourceAuditEvent

logger = logging.getLogger('management.security')
MAX_FILE_SIZE = 100 * 1024 * 1024
MAX_FILES = 20
PRIVATE_DIRECTORY = '.nwuicu-management'


def audit(request, action, path='', destination='', **detail):
    ResourceAuditEvent.objects.create(actor=request.user.get_username(), action=action,
                                     path=path, destination=destination, detail=detail)


class FileConflict(APIException):
    status_code = 409
    default_detail = '文件已变化或目标存在同名文件，请刷新后重试。'


class FileOperationUnavailable(APIException):
    status_code = 503
    default_detail = '文件操作失败，请检查目录写入权限后重试。'


def version(path):
    stat = path.stat()
    return hashlib.sha256(f'{stat.st_dev}:{stat.st_ino}:{stat.st_size}:{stat.st_mtime_ns}'.encode()).hexdigest()


def file_metadata(target, path):
    return {**entry_metadata(target, path), 'version': version(target)}


def directory(path):
    physical, path = resolve_resource(path, allow_readme=True)
    if not physical.is_dir():
        raise ValidationError({'path': '请选择文件夹。'})
    return physical, path


def checked_file(path, expected_version):
    physical, path = resolve_resource(path, allow_readme=True)
    if not physical.is_file():
        raise ValidationError({'path': '此操作仅支持文件。'})
    if version(physical) != expected_version:
        raise FileConflict('文件已被修改，请刷新列表后重试。')
    return physical, path


def destination(folder, name):
    if (not name or name.startswith('.') or name.endswith((' ', '.'))
            or any(char in name for char in '/\\<>:"|?*')
            or any(ord(char) < 32 for char in name)
            or re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', name, re.I)):
        raise ValidationError({'files': '文件名不合法或无法在 Windows 与 Linux 间通用。'})
    # Consistent no-overwrite behavior even on case-sensitive Linux storage.
    if any(child.name.casefold() == name.casefold() for child in folder.iterdir()):
        raise FileConflict(f'目标已有同名文件或目录：{name}')
    return folder / name


def private_directory():
    root = resource_root()
    hidden = root / PRIVATE_DIRECTORY
    hidden.mkdir(exist_ok=True)
    if hidden.is_symlink() or getattr(hidden, 'is_junction', lambda: False)() or hidden.resolve() != hidden:
        raise FileOperationUnavailable()
    return hidden


def read_index():
    try:
        return read_resource_directory_cache()
    except ResourceDirectoryCacheError:
        return build_resource_tree(resource_root())


def write_index(payload, *, removed=(), additions=()):
    entries = {item['path']: item for item in payload['entries'] if item['path'] not in removed}
    paths = set(payload['paths'])
    for target, path in additions:
        metadata = entry_metadata(target, path)
        metadata['size_display'] = format_file_size(metadata['size'] or 0)
        if target.is_dir():
            paths.add(path)
        entries[path] = metadata
        parent = posixpath.dirname(path)
        while parent:
            paths.add(parent)
            if parent not in entries:
                actual, _ = directory(parent)
                entries[parent] = entry_metadata(actual, parent)
            if parent == '/':
                break
            parent = posixpath.dirname(parent)
    write_resource_directory_cache(paths, source=payload.get('source'), entries=list(entries.values()),
                                   storage_root=str(resource_root()))


def move_without_overwrite(source, target):
    # Hard links work on both NTFS and Linux filesystems and fail atomically on
    # collisions. The source remains intact if link creation is unsupported.
    try:
        os.link(source, target, follow_symlinks=False)
    except FileExistsError as error:
        raise FileConflict() from error
    try:
        source.unlink()
    except OSError:
        target.unlink()
        raise


class FileActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['move', 'delete', 'restore', 'rename'])
    name = serializers.CharField(max_length=255, required=False, trim_whitespace=False)
    path = serializers.CharField(max_length=4096, required=False, trim_whitespace=False)
    version = serializers.CharField(max_length=64, required=False)
    destination = serializers.CharField(max_length=4096, required=False, trim_whitespace=False)
    trash_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        required = ['trash_id'] if attrs['action'] == 'restore' else ['path', 'version']
        if attrs['action'] == 'move':
            required.append('destination')
        if attrs['action'] == 'rename':
            required.append('name')
        for field in required:
            if not attrs.get(field):
                raise serializers.ValidationError({field: '此项必填。'})
        return attrs


class ResourceManagementView(ManagementAPIView):
    required_permission = 'common.manage_resource_files'

    def handle_exception(self, error):
        if isinstance(error, (OSError, ResourceDirectoryCacheError)):
            logger.exception('Resource file operation failed user_id=%s', getattr(self.request.user, 'pk', None))
            error = FileOperationUnavailable()
        response = super().handle_exception(error)
        if isinstance(error, (FileConflict, FileOperationUnavailable, ValidationError, Http404)):
            detail = getattr(error, 'detail', '文件或目录不存在，请刷新后重试。')
            while isinstance(detail, (dict, list)):
                detail = next(iter(detail.values())) if isinstance(detail, dict) else detail[0]
            return return_response(errors={'files': {'err_code': 'resource_file_operation', 'err_msg': str(detail)}},
                                   status_code=response.status_code)
        return response


class ManagementFileListView(ResourceManagementView):
    def get(self, request):
        parent, path = directory(request.query_params.get('path', '/'))
        entries = []
        for child in parent.iterdir():
            if child.name.startswith('.'):
                continue
            virtual = posixpath.join(path, child.name)
            try:
                physical, _ = resolve_resource(virtual, allow_readme=True)
                if physical.is_file() or physical.is_dir():
                    entries.append(file_metadata(physical, virtual))
            except (Http404, ValidationError, FileNotFoundError):
                continue
        return return_response(contents={
            'path': path,
            'entries': sorted(entries, key=lambda item: (item['type'] != 'directory', item['name'].casefold())),
            'max_file_size': MAX_FILE_SIZE, 'max_files': MAX_FILES,
        })


class ManagementFileUploadView(ResourceManagementView):
    parser_classes = [MultiPartParser, FormParser]

    @transaction.atomic
    def post(self, request):
        files = request.FILES.getlist('files')
        if not files or len(files) > MAX_FILES or any(file.size > MAX_FILE_SIZE for file in files):
            raise ValidationError({'files': '每次上传 1–20 个文件，单个文件不能超过 100 MiB。'})
        folder, virtual = directory(request.data.get('path', '/'))
        names = [file.name.casefold() for file in files]
        if len(names) != len(set(names)):
            raise FileConflict('本次上传包含同名文件。')
        for file in files:
            destination(folder, file.name)
        staged, created = [], []
        try:
            for file in files:
                with tempfile.NamedTemporaryFile(dir=private_directory(), prefix='upload-', delete=False) as output:
                    staged.append((Path(output.name), file.name))
                    for chunk in file.chunks():
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if staged[-1][0].stat().st_size != file.size:
                    raise ValidationError({'files': '上传文件大小不完整，请重试。'})
                os.chmod(staged[-1][0], 0o644)
            with resource_directory_cache_lock():
                payload = read_index()
                folder, virtual = directory(virtual)
                try:
                    for temporary, name in staged:
                        final = destination(folder, name)
                        os.link(temporary, final, follow_symlinks=False)
                        created.append((final, posixpath.join(virtual, name)))
                    for _, path in created:
                        audit(request, 'upload', path)
                    write_index(payload, additions=created)
                except Exception:
                    for final, _ in reversed(created):
                        final.unlink()
                    raise
            logger.info('resource upload user_id=%s paths=%r', request.user.pk, [path for _, path in created])
            return return_response(contents={'uploaded': len(created)}, status_code=201)
        finally:
            for temporary, _ in staged:
                temporary.unlink(missing_ok=True)


def trash_record(hidden, trash_id):
    manifest, content = hidden / f'{trash_id}.json', hidden / f'{trash_id}.data'
    if manifest.is_symlink() or content.is_symlink() or not content.is_file():
        raise Http404
    try:
        record = json.loads(manifest.read_text(encoding='utf-8'))
        return record, manifest, content
    except (OSError, ValueError) as error:
        raise Http404 from error


class ManagementTrashView(ResourceManagementView):
    def get(self, request):
        hidden = private_directory()
        entries = []
        for manifest in hidden.glob('*.json'):
            try:
                trash_id = str(uuid.UUID(manifest.stem))
                record, _, content = trash_record(hidden, trash_id)
                entries.append({**record, 'id': trash_id, 'size': content.stat().st_size})
            except (Http404, ValueError, OSError):
                continue
        return return_response(contents={'entries': sorted(entries, key=lambda item: item['deleted_at'], reverse=True)})


class ManagementFileActionView(ResourceManagementView):
    @transaction.atomic
    def post(self, request):
        serializer = FileActionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with resource_directory_cache_lock():
            payload = read_index()
            if data['action'] == 'restore':
                record, manifest, source = trash_record(private_directory(), str(data['trash_id']))
                parent, _ = directory(posixpath.dirname(record['path']) or '/')
                target = destination(parent, posixpath.basename(record['path']))
                removed, additions = (), [(target, record['path'])]
            else:
                source, path = checked_file(data['path'], data['version'])
                removed = (path,)
                if data['action'] in ('move', 'rename'):
                    parent, virtual = directory(data['destination'] if data['action'] == 'move' else posixpath.dirname(path))
                    name = data['name'] if data['action'] == 'rename' else source.name
                    target = destination(parent, name)
                    additions = [(target, posixpath.join(virtual, name))]
                    manifest = None
                else:
                    hidden = private_directory()
                    trash_id = str(uuid.uuid4())
                    manifest, target = hidden / f'{trash_id}.json', hidden / f'{trash_id}.data'
                    record = {'path': path, 'name': source.name, 'deleted_at': timezone.now().isoformat(),
                              'deleted_by': request.user.pk}
                    with manifest.open('x', encoding='utf-8') as output:
                        json.dump(record, output, ensure_ascii=False)
                        output.flush()
                        os.fsync(output.fileno())
                    additions = []
            try:
                move_without_overwrite(source, target)
            except Exception:
                if data['action'] == 'delete':
                    manifest.unlink(missing_ok=True)
                raise
            try:
                audit(request, data['action'], data.get('path') or record['path'],
                      additions[0][1] if additions else '')
                write_index(payload, removed=removed, additions=additions)
            except Exception:
                move_without_overwrite(target, source)
                if data['action'] == 'delete':
                    manifest.unlink(missing_ok=True)
                raise
            if data['action'] == 'restore':
                # An orphaned manifest is harmless and is excluded from trash listings.
                try:
                    manifest.unlink()
                except OSError:
                    logger.warning('Restored resource manifest cleanup failed: %s', manifest)
            logger.info('resource %s user_id=%s path=%r destination=%r', data['action'], request.user.pk,
                        data.get('path') or record['path'], additions[0][1] if additions else 'trash')
        return return_response(contents={'action': data['action']})
