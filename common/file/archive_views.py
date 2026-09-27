import re
from urllib.parse import urlencode

from django.core import signing
from django.db.models import Q
from django.http import FileResponse, Http404, HttpResponse, StreamingHttpResponse
from django.utils import timezone
from django.utils.http import content_disposition_header, http_date
from rest_framework import serializers
from rest_framework.permissions import AllowAny
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from utils.utils import return_response
from . import resource_archives as service
from .resource_browser import stream_range
from .resource_statistics import record_download

TICKET_SALT = 'resource-archive-download-v1'


class ArchiveThrottle(SimpleRateThrottle):
    scope = 'resource_archive_requests'

    def __init__(self, ip=False):
        self.ip = ip
        super().__init__()

    def get_rate(self):
        return service.config()['ip_request_rate' if self.ip else 'request_rate']

    def get_cache_key(self, request, view):
        identity = service.client_ip(request) if self.ip else service.identities(request)[0]
        return f'archive-requests:{self.ip}:{identity}'


class ArchiveView(APIView):
    permission_classes = [AllowAny]

    def get_throttles(self):
        return [ArchiveThrottle(), ArchiveThrottle(ip=True)] if self.request.method == 'POST' else []

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not service.config()['enabled']:
            raise service.ArchiveError('批量打包暂时不可用。', status=503)

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response['Cache-Control'] = 'private, no-store'
        return response


class ArchiveConfigView(ArchiveView):
    def get(self, request):
        c = service.config()
        return return_response(contents={
            'max_files': c['max_files'], 'max_bytes': c['max_bytes'],
            'idle_ttl': c['idle_ttl'], 'queue_limit': c['queue_limit'],
            'anonymous': not request.user.is_authenticated,
        })


class CreateSerializer(serializers.Serializer):
    paths = serializers.ListField(child=serializers.CharField(max_length=4096, trim_whitespace=False),
                                  allow_empty=False, max_length=1000)
    request_key = serializers.UUIDField()


class ArchiveListView(ArchiveView):
    def get(self, request):
        # Only the current open panel may watch these failures. They are not
        # history; short-lived job rows still enforce admission and idempotency.
        raw = request.query_params.get('current', '')
        current = serializers.ListField(child=serializers.UUIDField(), max_length=30).run_validation(
            raw.split(',') if raw else [])
        with service.gate():
            transient = Q(archive__status='failed', archive__message__in=service.SOURCE_CHANGED_MESSAGES)
            receipts = service.owned(request).filter(~transient | Q(pk__in=current))
            receipts = receipts.select_related('archive').order_by('-created_at')[:30]
            return return_response(contents={'tasks': [service.serialize(r) for r in receipts]})

    def post(self, request):
        query = CreateSerializer(data=request.data)
        query.is_valid(raise_exception=True)
        receipt, result = service.submit(request, **query.validated_data)
        return return_response(contents={'task': service.serialize(receipt), 'result': result})


class ArchiveDetailView(ArchiveView):
    def get(self, request, receipt_id):
        with service.gate():
            receipt = service.owned(request).select_related('archive').filter(pk=receipt_id).first()
            if not receipt:
                raise Http404
            return return_response(contents={'task': service.serialize(receipt)})


class ArchiveCancelView(ArchiveView):
    def post(self, request, receipt_id):
        return return_response(contents={'task': service.serialize(service.cancel(request, receipt_id))})


def ready_receipt(request, receipt_id):
    receipt = service.owned(request).select_related('archive').filter(pk=receipt_id, cancelled=False).first()
    if not receipt:
        raise Http404
    a = receipt.archive
    if a.status != 'ready' or a.expires_at <= timezone.now():
        raise service.ArchiveError('资料包已过期或尚未准备好，请查看任务或重新打包。', 'archive_expired', 410)
    service.check_manifest(a, request.user)
    return receipt


class ArchiveAuthorizeView(ArchiveView):
    def post(self, request, receipt_id):
        with service.gate():
            receipt = ready_receipt(request, receipt_id)
            if not service.archive_path(receipt.archive).is_file():
                raise service.ArchiveError('资料包已被清理，请重新打包。', 'archive_expired', 410)
            service.touch(receipt.archive)
            token = signing.dumps({'receipt': str(receipt.pk), 'actor': service.identities(request)[0]},
                                  salt=TICKET_SALT)
            # Reuse the unbuffered, uncached file-download proxy location. The
            # generic API proxy may otherwise strip Range when caching is enabled.
            url = f'/api/resources/file/archives/{receipt.pk}/?' + urlencode({'access': token})
            return return_response(contents={'url': url, 'task': service.serialize(receipt)})


class ArchiveDownloadView(ArchiveView):
    def get(self, request, receipt_id):
        try:
            payload = signing.loads(request.query_params.get('access', ''), salt=TICKET_SALT,
                                    max_age=service.config()['ticket_ttl'])
        except signing.BadSignature as error:
            raise service.ArchiveError('下载链接已失效，请重新选择文件并点击打包下载。', status=403) from error
        if payload != {'receipt': str(receipt_id), 'actor': service.identities(request)[0]}:
            raise Http404
        with service.gate():
            receipt = ready_receipt(request, receipt_id)
            a = receipt.archive
            try:
                source = service.archive_path(a).open('rb')
            except FileNotFoundError as error:
                raise service.ArchiveError('资料包已被清理，请重新打包。', status=410) from error
            if not service.file_lock(source):
                source.close()
                raise service.ArchiveError('资料包正在清理，请重新打包。', status=410)
        try:
            size = a.zip_bytes
            etag = f'"{a.pk}"'
            modified = http_date(a.completed_at.timestamp())
            range_header = request.headers.get('Range', '')
            if request.headers.get('If-Range', etag) not in (etag, modified):
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
                                                 status=206, content_type='application/zip')
                response['Content-Length'] = str(end - start + 1)
                response['Content-Range'] = f'bytes {start}-{end}/{size}'
                response._resource_closers.append(source.close)
            else:
                response = FileResponse(source, content_type='application/zip')
            # TTL renewal happens only on explicit authorize/submit, never on HEAD,
            # Range chunks, retries, polling, or replaying a signed download URL.
            response['Content-Disposition'] = content_disposition_header(True, service.serialize(receipt)['filename'])
            response['Accept-Ranges'] = 'bytes'
            response['ETag'] = etag
            response['Last-Modified'] = modified
            response['X-Content-Type-Options'] = 'nosniff'
            if request.method == 'GET' and (not range_header or start == 0):
                for entry in a.manifest:
                    record_download(request, entry['path'])
            return response
        except Exception:
            source.close()
            raise
