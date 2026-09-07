"""README editing, index maintenance, directory rules and management reports."""
import os
import posixpath
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path

from django.db import transaction
from django.db.models import Count, Max, Q
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from common.models import ResourceAccessRule, ResourceAuditEvent, ResourceDownloadEvent
from common.file.resource_access import ResourceAccess
from common.file.resource_browser import read_directory_readme, resolve_resource
from common.file.resource_directories import (resource_directory_cache_lock, read_resource_directory_cache,
                                              ResourceDirectoryCacheError)
from scripts.export_resource_tree import build_resource_tree
from utils.utils import return_response
from .resource_files import (ResourceManagementView, audit, directory, destination, version,
                             read_index, write_index, private_directory, trash_record, FileConflict)


class OperationSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=['mkdir', 'purge'])
    path = serializers.CharField(max_length=4096, default='/', trim_whitespace=False)
    name = serializers.CharField(max_length=255, required=False, trim_whitespace=False)
    trash_ids = serializers.ListField(child=serializers.UUIDField(), max_length=10000, allow_empty=False, required=False)
    confirmation = serializers.CharField(required=False)

    def validate(self, attrs):
        if attrs['action'] == 'mkdir' and not attrs.get('name'):
            raise serializers.ValidationError('请填写目录名称。')
        if attrs['action'] == 'purge' and (not attrs.get('trash_ids') or attrs.get('confirmation') != '永久删除'):
            raise serializers.ValidationError('请输入“永久删除”确认，并指定要删除的回收站文件。')
        return attrs


class ManagementResourceOperationsView(ResourceManagementView):
    def post(self, request):
        serializer = OperationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        with resource_directory_cache_lock():
            if data['action'] == 'mkdir':
                with transaction.atomic():
                    folder, path = directory(data['path'])
                    if data['name'].casefold() == 'readme.md':
                        raise ValidationError('readme.md 专用于目录说明，不能作为文件夹名。')
                    target = destination(folder, data['name'])
                    payload = read_index()
                    target.mkdir()
                    try:
                        audit(request, 'mkdir', posixpath.join(path, data['name']))
                        write_index(payload, additions=[(target, posixpath.join(path, data['name']))])
                    except Exception:
                        target.rmdir()
                        raise
                return return_response(contents={'completed': 1, 'failed': []})
            hidden = private_directory()
            completed, failed = 0, []
            # Snapshot IDs avoid deleting files added to the trash after confirmation.
            for trash_id in dict.fromkeys(map(str, data['trash_ids'])):
                try:
                    record, manifest, content = trash_record(hidden, trash_id)
                    # Persist intent first, so even process interruption leaves a trace.
                    audit(request, 'purge_requested', record['path'], trash_id=trash_id)
                    content.unlink()
                    completed += 1
                    manifest.unlink(missing_ok=True)
                    audit(request, 'purge', record['path'], trash_id=trash_id)
                except Exception:
                    failed.append(trash_id)
            return return_response(contents={'completed': completed, 'failed': failed})


def readme_file(folder, path):
    matches = sorted((p for p in folder.iterdir() if p.name.casefold() == 'readme.md'), key=lambda p: (p.name != 'readme.md', p.name))
    if len(matches) > 1:
        raise FileConflict('此目录存在多个大小写不同的 README，请先整理为一个文件。')
    if matches:
        target, _ = resolve_resource(posixpath.join(path, matches[0].name), allow_readme=True)
        if not target.is_file():
            raise FileConflict('README 路径不是文件。')
        return target
    return folder / 'readme.md'


class ReadmeSerializer(serializers.Serializer):
    path = serializers.CharField(max_length=4096, trim_whitespace=False)
    version = serializers.CharField(max_length=64, allow_blank=True)
    content = serializers.CharField(allow_blank=True, trim_whitespace=False, max_length=1024 * 1024)


class ManagementResourceReadmeView(ResourceManagementView):
    def get(self, request):
        folder, path = directory(request.query_params.get('path', '/'))
        target = readme_file(folder, path)
        content, warning = read_directory_readme(folder)
        return return_response(contents={'path': path, 'content': content, 'warning': warning,
                                         'version': version(target) if target.exists() else ''})

    @transaction.atomic
    def post(self, request):
        serializer = ReadmeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        raw = data['content'].encode('utf-8')
        if len(raw) > 1024 * 1024:
            raise ValidationError('目录说明不能超过 1 MiB。')
        with resource_directory_cache_lock():
            folder, path = directory(data['path'])
            target = readme_file(folder, path)
            if (version(target) if target.exists() else '') != data['version']:
                raise FileConflict('目录说明已被修改，请重新加载后编辑。')
            if target.exists() and target.stat().st_size > 1024 * 1024:
                raise ValidationError('原目录说明超过 1 MiB，请通过文件管理整理后再编辑。')
            original = target.read_bytes() if target.exists() else None
            file_mode = target.stat().st_mode & 0o777 if original is not None else 0o644
            payload = read_index()
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=private_directory(), prefix='readme-', delete=False) as output:
                    temporary = Path(output.name)
                    output.write(raw)
                    output.flush()
                    os.fsync(output.fileno())
                os.chmod(temporary, file_mode)
                audit(request, 'readme', posixpath.join(path, target.name))
                os.replace(temporary, target)
                try:
                    write_index(payload, additions=[(target, posixpath.join(path, target.name))])
                except Exception:
                    if original is None:
                        target.unlink()
                    else:
                        temporary.write_bytes(original)
                        os.chmod(temporary, file_mode)
                        os.replace(temporary, target)
                    raise
            finally:
                if temporary:
                    temporary.unlink(missing_ok=True)
        return return_response(contents={'path': path, 'content': data['content'], 'warning': '', 'version': version(target)})


class AccessSerializer(serializers.Serializer):
    path = serializers.CharField(max_length=2048, trim_whitespace=False)
    mode = serializers.ChoiceField(choices=['public', 'login', 'admin'])


class ManagementResourceAccessView(ResourceManagementView):
    def get(self, request):
        _, path = directory(request.query_params.get('path', '/'))
        rule = ResourceAccessRule.objects.filter(path=path).first()
        return return_response(contents={'path': path, 'mode': rule.mode if rule else 'public',
                                         'effective': ResourceAccess(request.user).mode(path),
                                         'rules': list(ResourceAccessRule.objects.order_by('path').values('path', 'mode'))})

    @transaction.atomic
    def post(self, request):
        serializer = AccessSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        _, path = directory(data['path'])
        if data['mode'] == 'public':
            ResourceAccessRule.objects.filter(path=path).delete()
        else:
            ResourceAccessRule.objects.update_or_create(path=path, defaults={'mode': data['mode']})
        audit(request, 'access', path, mode=data['mode'])
        return return_response(contents={'effective': ResourceAccess(request.user).mode(path)})


class ManagementResourceIndexView(ResourceManagementView):
    def get(self, request):
        try:
            payload = read_resource_directory_cache()
        except ResourceDirectoryCacheError:
            payload = {}
        return return_response(contents={'updated_at': payload.get('updated_at'), 'summary': payload.get('summary')})

    @transaction.atomic
    def post(self, request):
        with resource_directory_cache_lock():
            root, _ = directory('/')
            payload = build_resource_tree(root)
            audit(request, 'reindex', '/', **payload['summary'])
            write_index(payload)
        return self.get(request)


class ReportQuerySerializer(serializers.Serializer):
    page = serializers.IntegerField(default=1, min_value=1)
    action = serializers.CharField(default='', allow_blank=True, max_length=32)
    search = serializers.CharField(default='', allow_blank=True, max_length=200)
    days = serializers.ChoiceField(choices=[7, 30, 90], default=30)


class ManagementResourceAuditView(ResourceManagementView):
    def get(self, request):
        serializer = ReportQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        events = ResourceAuditEvent.objects.all()
        if data['action']:
            events = events.filter(action=data['action'])
        if data['search']:
            events = events.filter(Q(path__icontains=data['search']) | Q(destination__icontains=data['search']) | Q(actor__icontains=data['search']))
        count = events.count()
        start = (data['page'] - 1) * 50
        return return_response(contents={'count': count, 'page': data['page'], 'results': list(events.order_by('-id').values()[start:start + 50])})


class StatisticsQuerySerializer(serializers.Serializer):
    days = serializers.ChoiceField(choices=[7, 30, 90], default=30)
    page = serializers.IntegerField(default=1, min_value=1)
    ip = serializers.IPAddressField(required=False)
    user_id = serializers.IntegerField(required=False, min_value=1)
    ua = serializers.CharField(default='', allow_blank=True, max_length=2048)
    search = serializers.CharField(default='', allow_blank=True, max_length=200)


class ManagementResourceStatisticsView(ResourceManagementView):
    def get(self, request):
        serializer = StatisticsQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        days = int(data['days'])
        now = timezone.now()
        today = timezone.localtime(now).date() if timezone.is_aware(now) else now.date()
        start = today - timedelta(days=days - 1)
        lower = datetime.combine(start, time.min)
        upper = datetime.combine(today + timedelta(days=1), time.min)
        if timezone.is_aware(now):
            lower, upper = timezone.make_aware(lower), timezone.make_aware(upper)
        events = ResourceDownloadEvent.objects.filter(created_at__gte=lower, created_at__lt=upper)
        if data.get('ip'):
            events = events.filter(ip_address=data['ip'])
        if data.get('user_id'):
            events = events.filter(user_id=data['user_id'])
        if data['ua']:
            events = events.filter(user_agent__icontains=data['ua'])
        if data['search']:
            events = events.filter(path__icontains=data['search'])
        totals = events.aggregate(total=Count('id'), authenticated_total=Count('id', filter=Q(authenticated=True)),
            unique_ips=Count('ip_address', distinct=True), unique_users=Count('user_id', distinct=True),
            unique_uas=Count('user_agent', distinct=True, filter=~Q(user_agent='')),
            unknown_ip=Count('id', filter=Q(ip_address__isnull=True)),
            unknown_ua=Count('id', filter=Q(user_agent='')),
            unknown_user=Count('id', filter=Q(authenticated=True, user_id__isnull=True)))
        totals['authenticated'] = totals.pop('authenticated_total')
        totals['guest'] = totals['total'] - totals['authenticated']
        daily = {row['date']: row['count'] for row in events.annotate(date=TruncDate('created_at')).values('date').annotate(count=Count('id'))}
        users = list(events.filter(user_id__isnull=False).values('user_id').annotate(count=Count('id'), latest_id=Max('id')).order_by('-count', 'user_id')[:50])
        names = dict(ResourceDownloadEvent.objects.filter(id__in=[row['latest_id'] for row in users]).values_list('id', 'username'))
        for row in users:
            row['username'] = names[row.pop('latest_id')]
        page = data['page']
        records = list(events.order_by('-id').values('id', 'path', 'created_at', 'ip_address', 'user_id', 'username',
                                                    'user_agent', 'authenticated')[(page - 1) * 50:page * 50])
        return return_response(contents={**totals, 'days': days,
            'ips': list(events.filter(ip_address__isnull=False).values('ip_address').annotate(count=Count('id')).order_by('-count', 'ip_address')[:50]),
            'users': users,
            'uas': list(events.exclude(user_agent='').values('user_agent').annotate(count=Count('id')).order_by('-count', 'user_agent')[:50]),
            'events': {'count': totals['total'], 'page': page, 'page_size': 50, 'results': records},
            'daily': [{'date': start + timedelta(days=offset), 'count': daily.get(start + timedelta(days=offset), 0)} for offset in range(days)],
            'files': list(events.values('path').annotate(count=Count('id')).order_by('-count', 'path')[:50])})
