"""Bounded, disk-backed shared archives. All lifecycle changes take the DB gate.

Linux flock protects active downloads/worker files across web/cron containers.
Source bytes never enter the database or a whole-file in-memory buffer.
"""
import hashlib
import ipaddress
import json
import logging
import os
import posixpath
import re
import shutil
import signal
import threading
import time
import zipfile
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404
from django.utils import timezone
from django.utils.crypto import salted_hmac
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.throttling import BaseThrottle

from common.archive_models import ResourceArchive as Archive, ResourceArchiveReceipt as Receipt
from common.archive_models import ResourceArchiveState, ResourceArchiveNotice as Notice
from utils.throttle import actor_identity, browser_identity, consume_captcha_proof, CaptchaRequired, throttle_cache, digest
from .resource_access import ResourceAccess
from .resource_browser import resolve_resource

logger = logging.getLogger(__name__)
LIVE = ('queued', 'running', 'cancelling')
SOURCE_CHANGED_MESSAGES = (
    '部分资料已经变化，请重新选择并打包。',
    '源文件大小发生变化，请重新选择。',
    '打包期间文件发生变化，请重新选择。',
)


def config():
    return settings.RESOURCE_ARCHIVE


class ArchiveError(APIException):
    def __init__(self, message, code='archive_unavailable', status=409):
        self.status_code = status
        self.err_code = code
        self.err_msg = message
        self.field = 'archive'
        super().__init__(message)


@contextmanager
def gate():
    with transaction.atomic():
        ResourceArchiveState.objects.get_or_create(pk=1)
        ResourceArchiveState.objects.select_for_update().get(pk=1)
        yield


def identity_hash(value):
    return salted_hmac('resource-archive-identity', value, algorithm='sha256').hexdigest()


def identities(request):
    if browser_identity(request) == 'missing-browser-id':
        raise ArchiveError('请允许本站 Cookie 后重试。', status=400)
    return identity_hash(actor_identity(request)), identity_hash('browser:' + browser_identity(request))


def client_ip(request):
    # DRF NUM_PROXIES must match the trusted proxy chain; never trust leftmost XFF.
    raw = BaseThrottle().get_ident(request)
    try:
        raw = str(ipaddress.ip_address(raw))
    except ValueError:
        raw = request.META.get('REMOTE_ADDR', '')
    return identity_hash('ip:' + raw)


def owned(request):
    actor, browser = identities(request)
    if request.user.is_authenticated:
        # Attach only anonymous receipts. Logging out cannot expose account receipts.
        Receipt.objects.filter(user__isnull=True, actor=browser).update(actor=actor, user=request.user)
        return Receipt.objects.filter(user=request.user)
    return Receipt.objects.filter(user__isnull=True, actor=actor)


def version(stat):
    # ctime describes metadata, not content. Windows cloud-file hydration via
    # WSL/DrvFS can change it on a read without changing the file's contents.
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]


def manifest_for(paths, user):
    if not isinstance(paths, list) or not paths or len(paths) > config()['max_files']:
        raise ValidationError({'paths': f"每次请选择 1–{config()['max_files']} 个文件。"})
    access = ResourceAccess(user)
    entries = {}
    for raw in paths:
        if not isinstance(raw, str) or len(raw) > 4096:
            raise ValidationError({'paths': '文件路径不合法。'})
        target, path = resolve_resource(raw)
        access.require(path)
        if not target.is_file():
            raise ValidationError({'paths': '只能选择文件，不能选择文件夹。'})
        stat = target.stat()
        entries[path] = {'path': path, 'size': stat.st_size, 'version': version(stat)}
    manifest = [entries[key] for key in sorted(entries)]
    if sum(e['size'] for e in manifest) > config()['max_bytes']:
        raise ValidationError({'paths': f"文件总大小超过 {config()['max_bytes'] // 1024**2} MiB，请分批选择。"})
    return manifest


def fingerprint(manifest):
    # Accept existing five-field manifests as well, so completed ZIPs and queued
    # jobs remain usable after upgrading from the ctime-based version scheme.
    canonical = [{**entry, 'version': entry['version'][:4]} for entry in manifest]
    return hashlib.sha256(json.dumps(['stored-v2-root-paths', canonical], ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def check_manifest(archive, user):
    current = manifest_for([e['path'] for e in archive.manifest], user)
    if fingerprint(current) != fingerprint(archive.manifest):
        raise ArchiveError('部分资料已经变化，请重新选择并打包。', 'archive_changed')


def root():
    directory = Path(config()['cache_root'])
    directory.mkdir(parents=True, exist_ok=True)
    directory = directory.resolve()
    source = settings.RESOURCE_STORAGE_ROOT
    if source and (directory == source.resolve() or source.resolve() in directory.parents):
        raise ArchiveError('资料包缓存目录必须独立于资料目录。', status=503)
    return directory


def archive_path(archive, suffix='.zip'):
    return root() / (str(archive.pk) + suffix)


def file_lock(stream, exclusive=False):
    import fcntl
    try:
        fcntl.flock(stream.fileno(), (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


def touch(archive):
    archive.last_used_at = timezone.now()
    archive.expires_at = archive.last_used_at + timedelta(seconds=config()['idle_ttl'])
    archive.save(update_fields=['last_used_at', 'expires_at'])


def archive_filename(archive):
    parents = [posixpath.dirname(entry['path']) for entry in archive.manifest]
    folder = posixpath.basename(posixpath.commonpath(parents)) if parents else ''
    # A safe download basename on Windows, Android and iOS; keep Chinese names.
    folder = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', '_', folder).strip().rstrip('.')
    folder = folder.encode('utf-8')[:200].decode('utf-8', errors='ignore').rstrip(' .')
    if folder and re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', folder):
        folder = '_' + folder
    return (folder or '学习资料-' + archive.created_at.strftime('%Y%m%d')) + '.zip'


def serialize(receipt):
    a = receipt.archive
    status = 'cancelled' if receipt.cancelled and a.status != 'cancelling' else a.status
    if status == 'ready' and a.expires_at <= timezone.now():
        status = 'expired'
    ahead = 0
    if status == 'queued':
        ahead = Archive.objects.filter(Q(status__in=['running', 'cancelling']) |
                                       Q(status='queued', created_at__lt=a.created_at)).count()
    return {
        'id': str(receipt.pk), 'status': status, 'file_count': len(a.manifest),
        'paths': [e['path'] for e in a.manifest], 'source_bytes': a.source_bytes,
        'zip_bytes': a.zip_bytes, 'processed_files': a.processed_files,
        'processed_bytes': a.processed_bytes, 'ahead': ahead,
        'expires_at': a.expires_at, 'created_at': receipt.created_at,
        'filename': archive_filename(a),
        'message': a.message,
        'transient': status == 'failed' and a.message in SOURCE_CHANGED_MESSAGES,
    }


def submit(request, paths, request_key):
    actor, browser = identities(request)
    manifest = manifest_for(paths, request.user)
    key = fingerprint(manifest)
    captcha_required = False
    with gate():
        mine = owned(request)
        previous = mine.filter(request_key=request_key).select_related('archive').first()
        if previous:
            return previous, 'existing'
        active = mine.filter(Q(cancelled=False, archive__status__in=LIVE) |
                             Q(archive__status='cancelling')).select_related('archive').first()
        if active:
            return active, 'active'
        now = timezone.now()
        archive = Archive.objects.filter(cache_key=key, status__in=['queued', 'running', 'ready']).first()
        if archive and archive.status == 'ready':
            if archive.expires_at <= now or not archive_path(archive).is_file():
                # Do not revive an expired artifact; a downloading expired file can stay
                # on disk until its lock releases, but no longer occupies the cache key.
                archive.status = 'expired'
                archive.save(update_fields=['status'])
                archive = None
        if archive:
            if archive.status == 'ready':
                touch(archive)
            receipt = mine.filter(archive=archive, cancelled=False).first()
            if receipt:
                return receipt, 'reused'
        else:
            if Archive.objects.filter(status='queued').count() >= config()['queue_limit']:
                raise ArchiveError('打包队列已满，请稍后重试。已选文件会保留。', 'archive_queue_full', 429)
            cutoff = now - timedelta(seconds=config()['window'])
            history = Archive.objects.filter(created_at__gt=cutoff)
            free = config()['user_free'] if request.user.is_authenticated else config()['anon_free']
            need_captcha = (history.filter(creator__in={actor, browser}).count() >= free or
                            history.filter(ip_digest=client_ip(request)).count() >= config()['ip_captcha'])
            if need_captcha and not consume_captcha_proof(request, 'resource_archive', context=key):
                captcha_required = True
            else:
                archive = Archive.objects.create(cache_key=key, manifest=manifest,
                    source_bytes=sum(e['size'] for e in manifest), creator=actor, ip_digest=client_ip(request))
        if not captcha_required:
            receipt = Receipt.objects.create(archive=archive, actor=actor, browser=browser,
                user=request.user if request.user.is_authenticated else None, request_key=request_key)
            return receipt, 'reused' if archive.status != 'queued' or archive.creator != actor else 'created'
    # DatabaseCache shares the DB transaction: raising inside gate() would roll
    # back the context and issue an unusable proof even after a valid CAPTCHA.
    # Admission is checked again under the gate when the request is retried.
    throttle_cache().set('archive-context:' + digest(actor_identity(request)), key,
                         settings.API_RATE_LIMITS['captcha_proof']['ttl'])
    raise CaptchaRequired('resource_archive')


def cancel(request, receipt_id):
    with gate():
        receipt = owned(request).select_related('archive').filter(pk=receipt_id).first()
        if not receipt:
            raise Http404
        archive = receipt.archive
        if archive.status in LIVE:
            receipt.cancelled = True
            receipt.save(update_fields=['cancelled'])
            if not archive.receipts.filter(cancelled=False).exists():
                archive.status = 'cancelling' if archive.status != 'queued' else 'cancelled'
                archive.save(update_fields=['status'])
        return receipt


def usage():
    return Archive.objects.aggregate(z=Sum('zip_bytes'), r=Sum('reserved_bytes'))


def used_bytes():
    value = usage()
    return (value['z'] or 0) + (value['r'] or 0)


def notice(reason, count=0, freed=0):
    if not config()['telegram']:
        return
    # Merge pending events, including failed deliveries, to keep an outage bounded.
    pending = Notice.objects.filter(reason=reason).first()
    if pending:
        pending.count += count
        pending.freed_bytes += freed
        pending.save(update_fields=['count', 'freed_bytes'])
    else:
        Notice.objects.create(reason=reason, count=count, freed_bytes=freed,
            available_at=timezone.now() + timedelta(seconds=config()['notice_interval']))


def remove_artifact(archive, status='expired'):
    """Gate held; never unlink files pinned by a worker or a download."""
    streams = []
    try:
        for suffix in ('.zip', '.part'):
            path = archive_path(archive, suffix)
            try:
                stream = path.open('rb')
            except FileNotFoundError:
                continue
            streams.append((stream, path))
            if not file_lock(stream, exclusive=True):
                return False
        for _, path in streams:
            path.unlink(missing_ok=True)
        archive.status = status
        archive.zip_bytes = archive.reserved_bytes = 0
        archive.save(update_fields=['status', 'zip_bytes', 'reserved_bytes'])
        return True
    except OSError:
        logger.warning('Archive cache deletion failed for %s', archive.pk)
        notice('缓存文件清理失败，已保留空间占用记录，请检查缓存目录权限和磁盘状态。')
        return False
    finally:
        for stream, _ in streams:
            stream.close()


def cleanup_locked():
    now = timezone.now()
    for a in Archive.objects.filter(status='queued', created_at__lt=now - timedelta(seconds=config()['max_wait'])):
        a.status, a.message = 'failed', '排队超时，请重新提交。'
        a.save(update_fields=['status', 'message'])
    for a in Archive.objects.filter(status__in=['running', 'cancelling'],
                                     heartbeat_at__lt=now - timedelta(seconds=config()['timeout'] + 30)):
        if remove_artifact(a, 'cancelled' if a.status == 'cancelling' else 'failed'):
            a.message = '任务已中断，请重新提交。'
            a.save(update_fields=['message'])
    candidates = Archive.objects.filter(Q(status='ready', expires_at__lte=now) |
        Q(status__in=['expired', 'evicted', 'failed', 'cancelled']))
    for a in candidates:
        if a.zip_bytes or a.reserved_bytes or a.status == 'ready':
            remove_artifact(a, 'expired' if a.status == 'ready' else a.status)
    # Receipts remain long enough for retries and the full rolling CAPTCHA window.
    retention = max(config()['history_ttl'], config()['window'])
    Archive.objects.filter(status__in=['expired', 'evicted', 'failed', 'cancelled'],
        zip_bytes=0, reserved_bytes=0, created_at__lt=now - timedelta(seconds=retention)).delete()


def reserve_space(required):
    """Gate held. Evict LRU only as needed, preserving all active file locks."""
    removed = freed = 0
    def fits():
        # Other in-flight reservations also need physical disk headroom. Subtract
        # their remaining bytes conservatively (they may already be partly written).
        reserved = usage()['r'] or 0
        return (used_bytes() + required <= config()['cache_max'] and
                shutil.disk_usage(root()).free - required - reserved >= config()['min_free'])
    for a in Archive.objects.filter(status='ready').order_by('last_used_at', 'created_at'):
        if fits():
            break
        old_size = a.zip_bytes
        if remove_artifact(a, 'evicted'):
            removed += 1
            freed += old_size
    if removed:
        notice('新任务所需空间超过缓存预算或磁盘剩余空间门槛，已按最久未使用清理。', removed, freed)
    if not fits():
        notice('缓存空间暂时不足，活动下载或其他磁盘占用阻止清理，打包任务正在等待。')
        return False
    return True


def claim():
    with gate():
        cleanup_locked()
        if not config()['enabled'] or Archive.objects.filter(status__in=['running', 'cancelling']).count() >= config()['concurrency']:
            return None
        archive = Archive.objects.filter(status='queued').order_by('created_at', 'id').first()
        if not archive:
            return None
        reserve = archive.source_bytes + sum(2 * len(e['path'].encode()) + 4096 for e in archive.manifest) + 1024
        if reserve > config()['cache_max']:
            archive.status, archive.message = 'failed', '资料包超过当前缓存容量，请分批选择。'
            archive.save(update_fields=['status', 'message'])
            return None
        if not reserve_space(reserve):
            archive.message = '等待可用缓存空间。'
            archive.save(update_fields=['message'])
            return None
        archive.status = 'running'
        archive.reserved_bytes = reserve
        archive.started_at = archive.heartbeat_at = timezone.now()
        archive.message = ''
        archive.save()
        return archive


def has_authorized_receipt(archive):
    for receipt in archive.receipts.filter(cancelled=False).select_related('user'):
        user = receipt.user or AnonymousUser()
        if receipt.user and not receipt.user.is_active:
            continue
        access = ResourceAccess(user)
        if all(access.allowed(e['path']) for e in archive.manifest):
            return True
    return False


def process_one():
    archive = claim()
    if not archive:
        return False
    part = archive_path(archive, '.part')
    started = last_check = time.monotonic()
    processed = completed = 0
    previous_alarm = None
    alarm_enabled = hasattr(signal, 'setitimer') and threading.current_thread() is threading.main_thread()
    if alarm_enabled:
        def deadline(signum, frame):
            raise ArchiveError('打包超时，请分批选择。')
        previous_alarm = signal.signal(signal.SIGALRM, deadline)
        signal.setitimer(signal.ITIMER_REAL, config()['timeout'])
    try:
        if not has_authorized_receipt(archive):
            raise ArchiveError('资料访问权限已变化，请重新选择。')
        with part.open('xb') as output:
            if not file_lock(output, exclusive=True):
                raise ArchiveError('资料包正在处理，请稍后重试。')
            with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as z:
                for entry in archive.manifest:
                    target, _ = resolve_resource(entry['path'])
                    # O_NOFOLLOW guards replacement of the final component after resolve.
                    fd = os.open(target, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
                    with os.fdopen(fd, 'rb') as source:
                        if version(os.fstat(source.fileno())) != entry['version'][:4]:
                            raise ArchiveError('部分资料已经变化，请重新选择并打包。')
                        with z.open(entry['path'].lstrip('/'), 'w', force_zip64=True) as dest:
                            while True:
                                if time.monotonic() - started > config()['timeout']:
                                    raise ArchiveError('打包超时，请分批选择。')
                                if time.monotonic() - last_check >= 0.25:
                                    state = Archive.objects.get(pk=archive.pk)
                                    if state.status != 'running':
                                        raise ArchiveError('打包已取消。')
                                    Archive.objects.filter(pk=archive.pk).update(processed_bytes=processed,
                                        processed_files=completed, heartbeat_at=timezone.now())
                                    last_check = time.monotonic()
                                chunk = source.read(256 * 1024)
                                if not chunk:
                                    break
                                processed += len(chunk)
                                if processed > archive.source_bytes or output.tell() + len(chunk) > archive.reserved_bytes:
                                    raise ArchiveError('源文件大小发生变化，请重新选择。')
                                dest.write(chunk)
                        if version(os.fstat(source.fileno())) != entry['version'][:4]:
                            raise ArchiveError('打包期间文件发生变化，请重新选择。')
                    completed += 1
            output.flush()
            os.fsync(output.fileno())
            # Verify all paths again, catching replacement of an already-read file.
            for entry in archive.manifest:
                if version(resolve_resource(entry['path'])[0].stat()) != entry['version'][:4]:
                    raise ArchiveError('打包期间文件发生变化，请重新选择。')
            with gate():
                current = Archive.objects.get(pk=archive.pk)
                if current.status != 'running' or not has_authorized_receipt(current):
                    raise ArchiveError('任务已取消或访问权限发生变化。')
                if time.monotonic() - started > config()['timeout'] or output.tell() > current.reserved_bytes:
                    raise ArchiveError('打包超时或大小超限，请分批选择。')
                os.replace(part, archive_path(archive))
                current.status = 'ready'
                current.zip_bytes = output.tell()
                current.reserved_bytes = 0
                current.processed_files, current.processed_bytes = completed, processed
                current.completed_at = timezone.now()
                current.save()
                touch(current)
    except Exception as error:
        if alarm_enabled:
            signal.setitimer(signal.ITIMER_REAL, 0)
        logger.warning('Archive %s failed: %s', archive.pk, type(error).__name__)
        with gate():
            current = Archive.objects.get(pk=archive.pk)
            status = 'cancelled' if current.status == 'cancelling' else 'failed'
            current.message = error.err_msg if isinstance(error, ArchiveError) else '资料包生成失败，请稍后重试。'
            current.save(update_fields=['message'])
            remove_artifact(current, status)
            if isinstance(error, OSError):
                notice('打包发生文件系统错误，请检查缓存目录权限和磁盘剩余空间。')
    finally:
        if alarm_enabled:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_alarm)
    return True


def maintenance():
    # One janitor per shared cache volume; sends notifications outside the DB gate.
    with (root() / '.maintenance.lock').open('a+b') as lock:
        if not file_lock(lock, exclusive=True):
            return
        with gate():
            cleanup_locked()
            # Orphan files from a crash before DB commit stay budget-visible via the
            # corresponding reservation; truly unknown files are removed only when idle.
            for pattern in ('*.part', '*.zip'):
                for path in root().glob(pattern):
                    import uuid
                    try:
                        archive_id = uuid.UUID(path.stem)
                    except ValueError:
                        continue
                    if Archive.objects.filter(pk=archive_id).exists():
                        continue
                    with path.open('rb') as stream:
                        if file_lock(stream, exclusive=True):
                            path.unlink(missing_ok=True)
        deliver_notices()


def deliver_notices():
    if not config()['telegram'] or not settings.TELEGRAM_BOT_API_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    pending = list(Notice.objects.filter(available_at__lte=timezone.now()).order_by('pk')[:100])
    if not pending:
        return
    message = '\n'.join([
        '📦 资料包缓存清理通知',
        *sorted({n.reason for n in pending}),
        f'缓存上限：{config()["cache_max"] / 1024**3:.2f} GiB',
        f'清理数量：{sum(n.count for n in pending)} 个',
        f'释放空间：{sum(n.freed_bytes for n in pending) / 1024**2:.2f} MiB',
        f'当前占用（含预留）：{used_bytes() / 1024**3:.2f} GiB',
        '清理策略：优先过期，其次最久未使用；活动下载不淘汰。',
    ])
    try:
        from settings.log import TelegramBotHandler
        handler = TelegramBotHandler(send_timeout=10)
        handler.setFormatter(logging.Formatter('%(message)s'))
        handler.emit(logging.LogRecord(__name__, logging.INFO, '', 0, message, (), None))
    except Exception:
        logger.warning('Archive Telegram notification failed; queued for retry')
        with gate():
            for n in pending:
                Notice.objects.filter(pk=n.pk).update(attempts=n.attempts + 1,
                    available_at=timezone.now() + timedelta(seconds=min(3600, 60 * 2**min(n.attempts, 6))))
    else:
        with gate():
            for n in pending:
                current = Notice.objects.filter(pk=n.pk).first()
                if current and (current.count, current.freed_bytes) == (n.count, n.freed_bytes):
                    current.delete()
                elif current:
                    current.count -= n.count
                    current.freed_bytes -= n.freed_bytes
                    current.save(update_fields=['count', 'freed_bytes'])
