import os
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import unquote

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.core.management import call_command
from django.db import close_old_connections
from django.http import Http404
from django.test import TransactionTestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError, NotAuthenticated
from rest_framework.test import APIClient, APIRequestFactory

from common.file import resource_archives as s
from common.file.archive_views import ArchiveAuthorizeView, ArchiveDownloadView, ArchiveListView
from common.archive_models import ResourceArchive as Archive, ResourceArchiveReceipt as Receipt, ResourceArchiveNotice as Notice
from common.models import ResourceAccessRule
from user.models import User
from utils.throttle import CaptchaRequired, InvalidCaptchaProof, issue_captcha_proof


class ArchiveSetup:
    def setUp(self):
        super().setUp()
        cache.clear()
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / 'source'
        self.source.mkdir()
        self.cfg = {**settings.RESOURCE_ARCHIVE, 'cache_root': str(Path(self.temp.name) / 'cache'),
                    'min_free': 0, 'ip_captcha': 1000, 'telegram': True}
        self.override = override_settings(RESOURCE_STORAGE_ROOT=self.source, RESOURCE_ARCHIVE=self.cfg)
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.user = User.objects.create_user(username='archive-user', password='password')
        for name in ['a.pdf', 'b.pdf', 'c.pdf', 'd.pdf', 'e.pdf']:
            (self.source / name).write_bytes((name * 20).encode())
        self.a = self.request('a')
        self.b = self.request('b')

    def request(self, browser, user=None):
        return SimpleNamespace(user=user or AnonymousUser(), nwu_browser_id=browser,
            headers={}, META={'REMOTE_ADDR': '192.0.2.1'})

    def submit(self, request=None, paths=None, key=None):
        return s.submit(request or self.a, paths or ['/a.pdf', '/b.pdf'], key or uuid.uuid4())[0]

    def finish(self, request=None, paths=None):
        receipt = self.submit(request, paths)
        self.assertTrue(s.process_one())
        receipt.refresh_from_db()
        self.assertEqual(receipt.archive.status, 'ready', receipt.archive.message)
        return receipt

    def view(self, view, receipt, method='get', browser='a', url='/', **headers):
        factory = APIRequestFactory()
        request = getattr(factory, method)(url, {}, format='json', **headers)
        request.nwu_browser_id = browser
        return view.as_view()(request, receipt_id=receipt.pk)


class ResourceArchiveTests(ArchiveSetup, TransactionTestCase):
    def test_zip_name_uses_folder_in_task_and_actual_download_header(self):
        folder = self.source / '计算机网络'
        folder.mkdir()
        (folder / 'a.pdf').write_bytes(b'PDF A')
        (folder / 'b.pdf').write_bytes(b'PDF B')
        receipt = self.finish(paths=['/计算机网络/a.pdf', '/计算机网络/b.pdf'])
        self.assertEqual(s.serialize(receipt)['filename'], '计算机网络.zip')
        url = self.view(ArchiveAuthorizeView, receipt, 'post').data['contents']['url']
        response = self.view(ArchiveDownloadView, receipt, url=url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(unquote(response['Content-Disposition']), "attachment; filename*=utf-8''计算机网络.zip")
        response.close()

    def test_zip_names_handle_common_parent_root_and_unsafe_names(self):
        cases = [
            (['/课程/甲/a.pdf', '/课程/乙/b.pdf'], '课程.zip'),
            (['/a.pdf', '/b.pdf'], '学习资料-20260928.zip'),
            (['/课程:课件?/a.pdf'], '课程_课件_.zip'),
            (['/CON/a.pdf'], '_CON.zip'),
        ]
        for paths, name in cases:
            with self.subTest(paths=paths):
                a = SimpleNamespace(manifest=[{'path': p} for p in paths],
                    created_at=timezone.datetime(2026, 9, 28))
                self.assertEqual(s.archive_filename(a), name)

    def test_stored_zip_has_all_files_and_no_source_changes(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        receipt = self.finish(paths=['/b.pdf', '/a.pdf', '/a.pdf'])
        with zipfile.ZipFile(s.archive_path(receipt.archive)) as archive:
            self.assertEqual(archive.namelist(), ['a.pdf', 'b.pdf'])
            self.assertEqual(archive.read('a.pdf'), before['a.pdf'])
            self.assertTrue(all(e.compress_type == zipfile.ZIP_STORED for e in archive.infolist()))
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})
        self.assertEqual(receipt.archive.reserved_bytes, 0)

    def test_shared_cache_renews_on_claim_not_polling(self):
        first = self.finish()
        old_expiry = first.archive.expires_at
        with patch.object(s.timezone, 'now', return_value=timezone.now() + timedelta(minutes=10)):
            second = self.submit(self.b, ['/b.pdf', '/a.pdf'])
        self.assertEqual(first.archive_id, second.archive_id)
        self.assertEqual(Archive.objects.count(), 1)
        second.archive.refresh_from_db()
        self.assertGreater(second.archive.expires_at, old_expiry)
        expiry = second.archive.expires_at
        s.serialize(second)
        second.archive.refresh_from_db()
        self.assertEqual(second.archive.expires_at, expiry)

    def test_version_change_requires_new_artifact(self):
        first = self.finish()
        (self.source / 'a.pdf').write_bytes(b'new')
        second = self.submit(self.b)
        self.assertNotEqual(first.archive_id, second.archive_id)

    def test_one_active_and_idempotency(self):
        key = uuid.uuid4()
        first = self.submit(key=key)
        second, result = s.submit(self.a, ['/c.pdf'], uuid.uuid4())
        self.assertEqual(second.pk, first.pk)
        self.assertEqual(result, 'active')
        s.cancel(self.a, first.pk)
        self.assertEqual(self.submit(key=key).pk, first.pk)
        self.assertEqual(Archive.objects.count(), 1)

    def test_shared_pending_job_one_cancellation_does_not_cancel_others(self):
        first, second = self.submit(), self.submit(self.b)
        self.assertEqual(first.archive_id, second.archive_id)
        s.cancel(self.a, first.pk)
        self.assertTrue(s.process_one())
        second.refresh_from_db()
        first.refresh_from_db()
        self.assertEqual(second.archive.status, 'ready')
        self.assertEqual(s.serialize(first)['status'], 'cancelled')

    def test_cancelling_worker_still_occupies_identity_slot(self):
        first = self.submit()
        s.claim()
        result = s.cancel(self.a, first.pk)
        self.assertEqual(s.serialize(result)['status'], 'cancelling')
        self.assertEqual(self.submit(paths=['/c.pdf']).pk, first.pk)

    def test_anon_fifth_user_eighth_and_one_use_context_bound_captcha(self):
        for request, limit in [(self.a, 4), (self.request('member', self.user), 7)]:
            for _ in range(limit):
                receipt = self.submit(request)
                s.cancel(request, receipt.pk)
            with self.assertRaises(CaptchaRequired):
                self.submit(request)
            proof, _ = issue_captcha_proof(request, 'resource_archive')
            request.headers = {'X-Captcha-Proof': proof}
            with self.assertRaises(InvalidCaptchaProof):
                self.submit(request, ['/c.pdf'])
            receipt = self.submit(request)
            s.cancel(request, receipt.pk)
            with self.assertRaises(InvalidCaptchaProof):
                self.submit(request)
            request.headers = {}
            with self.assertRaises(CaptchaRequired):
                self.submit(request)

    def test_sliding_window_not_calendar_hour(self):
        for _ in range(4):
            receipt = self.submit()
            s.cancel(self.a, receipt.pk)
        Archive.objects.update(created_at=timezone.now() - timedelta(seconds=3601))
        self.submit()

    def test_cache_hits_dont_spend_creation_allowance(self):
        self.finish(self.b)
        self.cfg['anon_free'] = 0
        receipt = self.submit()
        self.assertEqual(receipt.archive.status, 'ready')
        self.assertEqual(Archive.objects.count(), 1)

    def test_login_adopts_guest_receipts_logout_cannot_access(self):
        receipt = self.submit()
        logged = self.request('a', self.user)
        self.assertEqual(self.submit(logged, ['/c.pdf']).pk, receipt.pk)
        with s.gate():
            self.assertEqual(s.owned(self.a).count(), 0)
            self.assertEqual(s.owned(self.request('other-device', self.user)).count(), 1)

    def test_queue_limit_and_position(self):
        self.cfg['queue_limit'] = 2
        first = self.submit()
        s.claim()
        second = self.submit(self.b, ['/c.pdf'])
        third = self.submit(self.request('c'), ['/d.pdf'])
        self.assertEqual(s.serialize(second)['ahead'], 1)
        self.assertEqual(s.serialize(third)['ahead'], 2)
        with self.assertRaises(s.ArchiveError):
            self.submit(self.request('d'), ['/e.pdf'])
        self.assertEqual(Archive.objects.count(), 3)

    def test_unsafe_paths_directories_symlinks_limits(self):
        (self.source / 'readme.md').write_text('private metadata')
        (self.source / '.hidden').write_text('private')
        (self.source / 'alias.pdf').symlink_to(self.source / 'a.pdf')
        for path in ['/readme.md', '/.hidden', '/../secret', '/alias.pdf', '/']:
            with self.assertRaises((ValidationError, Http404)):
                self.submit(paths=[path])
        self.cfg['max_bytes'] = 1
        with self.assertRaises(ValidationError):
            self.submit()
        self.assertFalse(Archive.objects.exists())

    def test_acl_rechecked_on_cache_hit_worker_and_download(self):
        receipt = self.finish()
        ResourceAccessRule.objects.create(path='/a.pdf', mode='login')
        with self.assertRaises(NotAuthenticated):
            self.submit(self.b)
        response = self.view(ArchiveAuthorizeView, receipt, 'post')
        self.assertEqual(response.status_code, 401)
        ResourceAccessRule.objects.all().delete()
        pending = self.submit(self.b, ['/c.pdf'])
        ResourceAccessRule.objects.create(path='/c.pdf', mode='admin')
        s.process_one()
        pending.archive.refresh_from_db()
        self.assertEqual(pending.archive.status, 'failed')

    def test_changed_file_worker_failure_cleans_partial(self):
        receipt = self.submit()
        (self.source / 'a.pdf').write_bytes(b'changed')
        s.process_one()
        receipt.archive.refresh_from_db()
        self.assertEqual(receipt.archive.status, 'failed')
        self.assertFalse(list(s.root().glob('*.part')))
        self.assertEqual(s.used_bytes(), 0)

    def test_changed_file_failure_is_only_visible_to_current_owner_panel(self):
        receipt = self.submit()
        (self.source / 'a.pdf').write_bytes(b'changed')
        s.process_one()

        def tasks(browser='a', current=''):
            request = APIRequestFactory().get('/', {'current': current})
            request.nwu_browser_id = browser
            return ArchiveListView.as_view()(request).data['contents']['tasks']

        self.assertEqual(tasks(), [])
        current = tasks(current=str(receipt.pk))
        self.assertEqual(len(current), 1)
        self.assertTrue(current[0]['transient'])
        self.assertEqual(tasks('b', str(receipt.pk)), [])
        self.assertEqual(tasks(), [])
        # Hiding failed jobs must not reset rate-limit or idempotency accounting.
        self.assertEqual(Archive.objects.count(), 1)
        self.assertEqual(self.submit(key=receipt.request_key).pk, receipt.pk)
        Archive.objects.filter(pk=receipt.archive_id).update(message='打包超时，请分批选择。')
        self.assertEqual(len(tasks()), 1)

    def test_metadata_change_during_read_does_not_fail_or_invalidate_cache(self):
        receipt = self.submit()
        target = self.source / 'a.pdf'
        before = target.stat()
        write = zipfile._ZipWriteFile.write
        changed = False

        def write_with_metadata_change(dest, data):
            nonlocal changed
            if not changed:
                changed = True
                # Like cloud-file hydration, chmod changes ctime without
                # changing content, size, inode or mtime.
                target.chmod(before.st_mode ^ 0o100)
            return write(dest, data)

        with patch.object(zipfile._ZipWriteFile, 'write', write_with_metadata_change):
            s.process_one()
        self.assertNotEqual(before.st_ctime_ns, target.stat().st_ctime_ns)
        self.assertEqual(before.st_mtime_ns, target.stat().st_mtime_ns)
        receipt.archive.refresh_from_db()
        self.assertEqual(receipt.archive.status, 'ready', receipt.archive.message)
        self.assertEqual(self.submit(self.b).archive_id, receipt.archive_id)
        url = self.view(ArchiveAuthorizeView, receipt, 'post').data['contents']['url']
        response = self.view(ArchiveDownloadView, receipt, url=url)
        self.assertEqual(response.status_code, 200)
        response.close()
        with zipfile.ZipFile(s.archive_path(receipt.archive)) as archive:
            self.assertEqual(archive.read('a.pdf'), target.read_bytes())

    def test_legacy_ctime_manifest_can_finish_and_download(self):
        receipt = self.submit()
        for entry in receipt.archive.manifest:
            entry['version'].append(1)  # Old, stale ctime must not invalidate it.
        receipt.archive.save(update_fields=['manifest'])
        s.process_one()
        receipt.archive.refresh_from_db()
        self.assertEqual(receipt.archive.status, 'ready', receipt.archive.message)
        url = self.view(ArchiveAuthorizeView, receipt, 'post').data['contents']['url']
        response = self.view(ArchiveDownloadView, receipt, url=url)
        self.assertEqual(response.status_code, 200)
        response.close()

    def test_same_size_content_change_during_read_still_fails(self):
        receipt = self.submit()
        target = self.source / 'a.pdf'
        before = target.stat()
        write = zipfile._ZipWriteFile.write

        def write_with_content_change(dest, data):
            target.write_bytes(b'x' * before.st_size)
            os.utime(target, ns=(before.st_atime_ns, before.st_mtime_ns + 1000000000))
            return write(dest, data)

        with patch.object(zipfile._ZipWriteFile, 'write', write_with_content_change):
            s.process_one()
        receipt.archive.refresh_from_db()
        self.assertEqual(receipt.archive.status, 'failed')
        self.assertIn('文件发生变化', receipt.archive.message)
        self.assertFalse(list(s.root().glob('*.part')))
        self.assertEqual(s.used_bytes(), 0)

    def test_replacement_with_same_size_and_mtime_during_read_still_fails(self):
        receipt = self.submit()
        target = self.source / 'a.pdf'
        before = target.stat()
        replacement = self.source / 'replacement.pdf'
        replacement.write_bytes(target.read_bytes())
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        write = zipfile._ZipWriteFile.write

        def write_with_replacement(dest, data):
            if replacement.exists():
                os.replace(replacement, target)
            return write(dest, data)

        with patch.object(zipfile._ZipWriteFile, 'write', write_with_replacement):
            s.process_one()
        receipt.archive.refresh_from_db()
        self.assertEqual(receipt.archive.status, 'failed')
        self.assertIn('文件发生变化', receipt.archive.message)
        self.assertFalse(list(s.root().glob('*.part')))
        self.assertEqual(s.used_bytes(), 0)

    def test_lru_not_creation_order_and_telegram_batch(self):
        oldest = self.finish(paths=['/a.pdf'])
        cold = self.finish(self.b, ['/b.pdf'])
        with s.gate():
            s.touch(oldest.archive)
            self.cfg['cache_max'] = s.used_bytes() + 99
            self.assertTrue(s.reserve_space(100))
        oldest.archive.refresh_from_db(); cold.archive.refresh_from_db()
        self.assertEqual(oldest.archive.status, 'ready')
        self.assertEqual(cold.archive.status, 'evicted')
        self.assertEqual(Notice.objects.get().count, 1)

    def test_expiration_does_not_interrupt_download_and_range_is_valid(self):
        receipt = self.finish()
        authorization = self.view(ArchiveAuthorizeView, receipt, 'post')
        url = authorization.data['contents']['url']
        response = self.view(ArchiveDownloadView, receipt, url=url, HTTP_RANGE='bytes=0-9')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response['Content-Length'], '10')
        Archive.objects.filter(pk=receipt.archive_id).update(expires_at=timezone.now() - timedelta(seconds=1))
        s.maintenance()
        self.assertTrue(s.archive_path(receipt.archive).exists())
        self.assertEqual(self.view(ArchiveDownloadView, receipt, url=url).status_code, 410)
        self.assertEqual(len(b''.join(response.streaming_content)), 10)
        response.close()
        s.maintenance()
        self.assertFalse(s.archive_path(receipt.archive).exists())

    def test_signed_url_is_owner_bound_invalid_range_does_not_pin_file(self):
        receipt = self.finish()
        url = self.view(ArchiveAuthorizeView, receipt, 'post').data['contents']['url']
        self.assertEqual(self.view(ArchiveDownloadView, receipt, browser='b', url=url).status_code, 404)
        self.assertEqual(self.view(ArchiveDownloadView, receipt, url=url, HTTP_RANGE='bytes=9999999-').status_code, 416)
        with s.gate():
            self.assertTrue(s.remove_artifact(receipt.archive))

    def test_download_does_not_renew_poll_or_range(self):
        receipt = self.finish()
        url = self.view(ArchiveAuthorizeView, receipt, 'post').data['contents']['url']
        receipt.archive.refresh_from_db(); expiry = receipt.archive.expires_at
        response = self.view(ArchiveDownloadView, receipt, url=url)
        response.close()
        receipt.archive.refresh_from_db()
        self.assertEqual(expiry, receipt.archive.expires_at)

    def test_timeout_and_stale_restart_release_budget(self):
        receipt = self.submit()
        claimed = s.claim()
        part = s.archive_path(claimed, '.part')
        part.write_bytes(b'partial')
        Archive.objects.filter(pk=claimed.pk).update(heartbeat_at=timezone.now() - timedelta(hours=1))
        s.maintenance()
        receipt.archive.refresh_from_db()
        self.assertEqual(receipt.archive.status, 'failed')
        self.assertFalse(part.exists())
        self.assertEqual(s.used_bytes(), 0)

    def test_execution_deadline_cleans_part_and_releases_slot(self):
        receipt = self.submit()
        # A deadline inside the read loop must be handled like an ordinary failure.
        ticks = iter([0, 121])
        with patch.object(s, 'time', SimpleNamespace(monotonic=lambda: next(ticks))):
            s.process_one()
        receipt.archive.refresh_from_db()
        self.assertEqual(receipt.archive.status, 'failed')
        self.assertIn('超时', receipt.archive.message)
        self.assertEqual(s.used_bytes(), 0)
        self.assertFalse(list(s.root().glob('*.part')))

    def test_low_disk_space_pauses_not_overruns(self):
        self.submit()
        with patch.object(s.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
            self.assertIsNone(s.claim())
        self.assertEqual(Archive.objects.get().status, 'queued')
        self.assertTrue(Notice.objects.exists())

    def test_cleanup_failure_keeps_budget_and_queues_notice(self):
        receipt = self.finish()
        size = s.used_bytes()
        with s.gate(), patch.object(Path, 'unlink', side_effect=PermissionError('denied')):
            self.assertFalse(s.remove_artifact(receipt.archive, 'evicted'))
        self.assertEqual(s.used_bytes(), size)
        self.assertTrue(Notice.objects.filter(reason__contains='清理失败').exists())

    def test_concurrent_reservations_preserve_physical_disk_headroom(self):
        receipt = self.submit()
        s.claim()
        receipt.archive.refresh_from_db()
        reserved = receipt.archive.reserved_bytes
        with s.gate(), patch.object(s.shutil, 'disk_usage', return_value=SimpleNamespace(free=reserved + 99)):
            self.assertFalse(s.reserve_space(100))

    def test_no_absolute_lifetime_hot_archive_can_renew(self):
        receipt = self.finish()
        Archive.objects.filter(pk=receipt.archive_id).update(created_at=timezone.now() - timedelta(days=30))
        again = self.submit(self.b)
        self.assertEqual(again.archive_id, receipt.archive_id)

    def test_telegram_failure_retries_and_success_removes_notice(self):
        with s.gate():
            s.notice('test space pressure', 2, 1024)
        Notice.objects.update(available_at=timezone.now() - timedelta(seconds=1))
        with override_settings(TELEGRAM_BOT_API_TOKEN='test', TELEGRAM_CHAT_ID='test'):
            with patch('settings.log.TelegramBotHandler') as handler:
                handler.return_value.emit.side_effect = RuntimeError('offline')
                s.deliver_notices()
                self.assertEqual(Notice.objects.get().attempts, 1)
                handler.return_value.emit.side_effect = None
                Notice.objects.update(available_at=timezone.now() - timedelta(seconds=1))
                s.deliver_notices()
        self.assertFalse(Notice.objects.exists())

    def test_api_csrf_cookie_recovery_and_cancel(self):
        client = APIClient(enforce_csrf_checks=True)
        response = client.get('/api/resources/archives/config/')
        self.assertEqual(response.status_code, 200)
        data = {'paths': ['/a.pdf'], 'request_key': str(uuid.uuid4())}
        self.assertEqual(client.post('/api/resources/archives/', data, format='json').status_code, 403)
        client.get('/api/user/csrf/')
        response = client.post('/api/resources/archives/', data, format='json',
            HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 200, response.data)
        recovered = client.get('/api/resources/archives/').data['contents']['tasks']
        self.assertEqual(recovered[0]['id'], response.data['contents']['task']['id'])
        other = APIClient()
        self.assertEqual(other.get('/api/resources/archives/').data['contents']['tasks'], [])


class ResourceArchiveConcurrencyTests(ArchiveSetup, TransactionTestCase):
    def test_parallel_submissions_create_one_job_and_one_receipt(self):
        def submit_one(_):
            close_old_connections()
            try:
                return self.submit().pk
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(submit_one, range(4)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(Archive.objects.count(), 1)
        self.assertEqual(Receipt.objects.count(), 1)

    def test_parallel_users_share_identical_pending_artifact(self):
        def submit_one(number):
            close_old_connections()
            try:
                return self.submit(self.request(str(number))).archive_id
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=4) as pool:
            ids = list(pool.map(submit_one, range(4)))
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(Receipt.objects.count(), 4)


class ResourceArchiveDatabaseCacheTests(ArchiveSetup, TransactionTestCase):
    def test_http_captcha_challenge_survives_transaction_and_proof_is_bound_and_single_use(self):
        # Production uses a DB cache. LocMemCache cannot reproduce a cache write
        # being rolled back when CaptchaRequired escapes the archive transaction.
        database_caches = {**settings.CACHES, 'archive_captcha_test': {
            'BACKEND': 'django.core.cache.backends.db.DatabaseCache',
            'LOCATION': 'test_archive_captcha_cache',
        }}
        limits = {**settings.API_RATE_LIMITS, 'cache_alias': 'archive_captcha_test'}
        with override_settings(CACHES=database_caches, API_RATE_LIMITS=limits):
            call_command('createcachetable', 'test_archive_captcha_cache', verbosity=0)
            try:
                for user in (None, self.user):
                    with self.subTest(authenticated=user is not None):
                        s.throttle_cache().clear()
                        self.cfg.update(anon_free=0, user_free=0)
                        client = APIClient(enforce_csrf_checks=True)
                        if user:
                            client.force_authenticate(user)
                        client.get('/api/user/csrf/')
                        csrf = client.cookies['csrftoken'].value
                        data = {'paths': ['/a.pdf'], 'request_key': str(uuid.uuid4())}

                        def submit(body, proof=None):
                            headers = {'HTTP_X_CSRFTOKEN': csrf}
                            if proof:
                                headers['HTTP_X_CAPTCHA_PROOF'] = proof
                            return client.post('/api/resources/archives/', body, format='json', **headers)

                        challenge = submit(data)
                        self.assertEqual(challenge.status_code, 429)
                        self.assertEqual(challenge.data['contents']['captcha_scope'], 'resource_archive')
                        verified = client.post('/api/captcha/', {
                            'captcha_key': 'test-key', 'captcha_value': 'PASSED', 'scope': 'resource_archive',
                        }, format='json', HTTP_X_CSRFTOKEN=csrf)
                        self.assertEqual(verified.status_code, 200, verified.data)
                        proof = verified.data['contents']['captcha_proof']
                        # A different selection must not consume this proof.
                        wrong = submit({**data, 'paths': ['/b.pdf']}, proof)
                        self.assertEqual(wrong.status_code, 400)
                        accepted = submit(data, proof)
                        self.assertEqual(accepted.status_code, 200, accepted.data)
                        task_id = accepted.data['contents']['task']['id']
                        cancelled = client.post(f'/api/resources/archives/{task_id}/cancel/', {},
                            format='json', HTTP_X_CSRFTOKEN=csrf)
                        self.assertEqual(cancelled.status_code, 200)
                        replay = submit({**data, 'request_key': str(uuid.uuid4())}, proof)
                        self.assertEqual(replay.status_code, 400)
                        self.assertEqual(submit({**data, 'request_key': str(uuid.uuid4())}).status_code, 429)
            finally:
                s.throttle_cache().clear()
