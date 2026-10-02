from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from common.file.models import (
    ResourceNotificationOutbox,
    ResourcePublishJob,
    ResourceUploadFile,
    ResourceUploadRequest,
)
from common.file.resource_directories import write_resource_directory_cache
from common.file.resource_notifications import queue_resource_upload_notifications
from common.file.resource_tasks import _mark_notifications_sent, process_one_notification, process_one_publish_job
from common.file.resource_workflow import (
    ResourceReviewError,
    approve_resource_upload,
    reject_resource_upload,
    retry_resource_publish,
)
from common.models import Conversation, DirectMessage, Notification
from test_project.common import create_user


class ResourceUploadWorkflowTests(TestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.storage_root = root / 'storage'
        self.media_root = root / 'media'
        self.cache_file = root / 'resource-tree.json'
        self.storage_root.mkdir()
        self.media_root.mkdir()
        self.settings_override = override_settings(
            RESOURCE_STORAGE_ROOT=self.storage_root,
            RESOURCE_DIRECTORY_CACHE_FILE=self.cache_file,
            MEDIA_ROOT=self.media_root,
            ADMIN_PUBLIC_URL='https://nwu.icu',
            FRONTEND_URL='https://nwu.icu',
            RESOURCES_WEBSITE_URL='https://resour.nwu.icu',
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        write_resource_directory_cache(['/'])
        self.user = create_user(is_active=True)
        self.reviewer = create_user(username='reviewer', email='reviewer@example.com', is_active=True, is_staff=True)

    def create_request(self):
        request = ResourceUploadRequest.objects.create(
            uploaded_by=self.user,
            target_path='/suggested',
            total_size=7,
        )
        ResourceUploadFile.objects.create(
            upload_request=request,
            file=SimpleUploadedFile('notes.txt', b'content'),
            original_name='notes.txt',
            relative_path='notes.txt',
            size=7,
        )
        return request

    def test_created_telegram_notification_has_readable_size_without_review_link(self):
        request = self.create_request()
        request.total_size = 116761
        request.save(update_fields=('total_size', 'updated_at'))

        queue_resource_upload_notifications(request, event='created')

        notification = ResourceNotificationOutbox.objects.get(upload_request=request)
        self.assertEqual(
            notification.body,
            f'收到新的资料上传请求 #{request.pk}\n'
            f'用户: {self.user.username} (ID: {self.user.pk})\n'
            '目标路径: /suggested\n'
            '总大小: 114.02 KB',
        )
        self.assertNotIn('审核链接', notification.body)

    def test_publish_failed_telegram_notification_has_no_review_link(self):
        request = self.create_request()
        request.publish_error = '目标文件已存在'
        request.save(update_fields=('publish_error', 'updated_at'))

        queue_resource_upload_notifications(request, event='publish_failed')

        notification = ResourceNotificationOutbox.objects.get(upload_request=request)
        self.assertEqual(
            notification.body,
            f'资料投稿 #{request.pk} 发布失败，请在后台处理。\n错误：目标文件已存在',
        )
        self.assertNotIn('审核链接', notification.body)

    def test_approval_queues_and_worker_publishes_then_removes_staging_file(self):
        request = self.create_request()

        approve_resource_upload(
            upload_request_id=request.pk,
            reviewer=self.reviewer,
            expected_revision=request.revision,
            target_path='/courses/new-course',
        )
        request.refresh_from_db()
        self.assertEqual(request.status, ResourceUploadRequest.STATUS_PUBLISHING)
        self.assertTrue(ResourcePublishJob.objects.filter(upload_request=request).exists())

        self.assertTrue(process_one_publish_job())
        request.refresh_from_db()
        upload_file = request.files.get()
        self.assertEqual(request.status, ResourceUploadRequest.STATUS_APPROVED)
        self.assertIsNotNone(request.files_deleted_at)
        self.assertFalse(bool(upload_file.file))
        self.assertEqual(upload_file.published_path, '/courses/new-course/notes.txt')
        self.assertEqual((self.storage_root / 'courses' / 'new-course' / 'notes.txt').read_bytes(), b'content')

        notifications = ResourceNotificationOutbox.objects.filter(upload_request=request)
        self.assertEqual(notifications.count(), 2)
        self.assertTrue(all(notification.available_at > timezone.now() for notification in notifications))
        self.assertFalse(process_one_notification())

    @patch('common.file.resource_tasks.send_mail')
    def test_review_results_for_same_user_are_batched_per_channel(self, send_mail):
        rejected = [self.create_request() for _ in range(2)]
        approved = [self.create_request() for _ in range(10)]
        for index, upload_request in enumerate(rejected, start=1):
            upload_request.rejection_reason = f'拒绝理由 {index}'
            upload_request.save(update_fields=('rejection_reason', 'updated_at'))
            queue_resource_upload_notifications(upload_request, event='rejected', reviewer=self.reviewer)
        for index, upload_request in enumerate(approved, start=1):
            upload_request.target_path = f'/courses/approved-{index}'
            upload_request.save(update_fields=('target_path', 'updated_at'))
            queue_resource_upload_notifications(upload_request, event='approved', reviewer=self.reviewer)
        ResourceNotificationOutbox.objects.update(available_at=timezone.now() - timedelta(seconds=1))

        self.assertTrue(process_one_notification())
        self.assertTrue(process_one_notification())
        self.assertFalse(process_one_notification())
        notice = Notification.objects.get()
        self.assertEqual(notice.recipient, self.user)
        self.assertEqual(notice.kind, Notification.KIND_SYSTEM)
        self.assertIsNone(notice.actor_id)
        self.assertIsNone(notice.read_at)
        self.assertFalse(Conversation.objects.exists())
        self.assertFalse(DirectMessage.objects.exists())
        self.assertEqual(send_mail.call_count, 1)
        site_message = notice.payload['content']
        email_subject, email_body = send_mail.call_args.args[:2]
        html_body = send_mail.call_args.kwargs['html_message']
        self.assertTrue(site_message.startswith('[审核拒绝]\n'))
        self.assertIn('可在https://nwu.icu/upload修改/撤回投稿', site_message)
        self.assertLess(site_message.index('[审核拒绝]'), site_message.index('[审核通过]'))
        self.assertEqual(site_message.count('未通过审核'), 2)
        self.assertEqual(site_message.count('已审核通过'), 10)
        self.assertIn(f'投稿 #{rejected[0].pk}', site_message)
        self.assertIn(f'投稿 #{approved[-1].pk}', site_message)
        self.assertIn('资料投稿审核结果', email_subject)
        self.assertEqual(site_message, email_body)
        self.assertIn('font-size: 20px', html_body)
        self.assertIn('>[审核拒绝]</h2>', html_body)
        self.assertIn('>[审核通过]</h2>', html_body)
        self.assertIn('>https://nwu.icu/upload</a>修改/撤回投稿', html_body)
        self.assertLess(html_body.index('审核拒绝'), html_body.index('审核通过'))
        self.assertIn('<a href="', html_body)
        self.assertIn('/disk/', html_body)
        self.assertNotIn('查看资料', html_body)
        self.assertIn('>/courses/approved-1</a>。', html_body)
        self.assertEqual(
            ResourceNotificationOutbox.objects.filter(status=ResourceNotificationOutbox.STATUS_SENT).count(),
            24,
        )

    def test_approval_and_rejection_share_existing_ten_minute_window(self):
        first = self.create_request()
        second = self.create_request()
        initial_time = timezone.now()
        later_time = initial_time + timedelta(minutes=5)

        with patch('common.file.resource_notifications.timezone.now', return_value=initial_time):
            queue_resource_upload_notifications(first, event='approved', reviewer=self.reviewer)
        with patch('common.file.resource_notifications.timezone.now', return_value=later_time):
            queue_resource_upload_notifications(second, event='rejected', reviewer=self.reviewer)

        notifications = ResourceNotificationOutbox.objects.order_by('pk')
        self.assertEqual(notifications.count(), 4)
        self.assertTrue(all(
            notification.available_at == initial_time + timedelta(minutes=10)
            for notification in notifications
        ))

    @patch('common.file.resource_tasks.send_mail')
    def test_result_snapshots_survive_resubmission_and_preserve_revision_order(self, send_mail):
        request = self.create_request()
        reject_resource_upload(
            upload_request_id=request.pk, reviewer=self.reviewer,
            expected_revision=1, reason='补充 <script>课程</script> 信息',
        )
        request.refresh_from_db()
        request.revision = 2
        request.rejection_reason = ''
        request.target_path = '/courses/approved & original'
        request.save()
        queue_resource_upload_notifications(request, event='approved', reviewer=self.reviewer)
        request.revision = 3
        request.target_path = '/changed-after-review'
        request.rejection_reason = '新的拒绝理由'
        request.save()
        queue_resource_upload_notifications(request, event='rejected', reviewer=self.reviewer)
        ResourceNotificationOutbox.objects.update(available_at=timezone.now() - timedelta(seconds=1))

        self.assertTrue(process_one_notification())
        self.assertTrue(process_one_notification())
        body = Notification.objects.get().payload['content']
        html = send_mail.call_args.kwargs['html_message']
        self.assertIn('补充 <script>课程</script> 信息', body)
        self.assertIn('/courses/approved & original', body)
        self.assertLess(body.index('第 1 版'), body.index('第 2 版'))
        self.assertLess(body.index('第 2 版'), body.index('第 3 版'))
        self.assertIn('补充 &lt;script&gt;课程&lt;/script&gt; 信息', html)
        self.assertNotIn('<script>', html)
        self.assertIn('/disk/courses/approved%20%26%20original', html)
        self.assertEqual(ResourceNotificationOutbox.objects.filter(status='sent').count(), 6)

    @patch('common.file.resource_tasks.send_mail')
    def test_legacy_pending_results_use_saved_body_after_request_changes(self, send_mail):
        request = self.create_request()
        request.rejection_reason = '旧理由 <课程>'
        queue_resource_upload_notifications(request, event='rejected', reviewer=self.reviewer)
        ResourceNotificationOutbox.objects.update(
            result_snapshot={}, available_at=timezone.now() - timedelta(seconds=1),
        )
        request.rejection_reason = ''
        request.revision += 1
        request.save()

        self.assertTrue(process_one_notification())
        self.assertTrue(process_one_notification())
        self.assertIn('旧理由 <课程>', Notification.objects.get().payload['content'])
        self.assertIn('旧理由 &lt;课程&gt;', send_mail.call_args.kwargs['html_message'])

    def test_site_results_support_self_review_and_missing_sender(self):
        approved = self.create_request()
        rejected = self.create_request()
        rejected.rejection_reason = '请补充课程信息'
        rejected.save(update_fields=('rejection_reason', 'updated_at'))
        queue_resource_upload_notifications(approved, event='approved', reviewer=self.user)
        queue_resource_upload_notifications(rejected, event='rejected')
        ResourceNotificationOutbox.objects.filter(
            channel=ResourceNotificationOutbox.CHANNEL_SITE_MESSAGE,
        ).update(available_at=timezone.now() - timedelta(seconds=1))

        self.assertTrue(process_one_notification())
        notice = Notification.objects.get()
        self.assertEqual(notice.recipient, self.user)
        self.assertEqual(notice.kind, Notification.KIND_SYSTEM)
        self.assertIsNone(notice.actor_id)
        self.assertIsNone(notice.read_at)
        self.assertIn('已审核通过', notice.payload['content'])
        self.assertIn('未通过审核', notice.payload['content'])
        self.assertFalse(Conversation.objects.exists())
        self.assertFalse(DirectMessage.objects.exists())
        self.assertEqual(ResourceNotificationOutbox.objects.filter(status='sent').count(), 2)

    def test_reclaimed_site_batch_does_not_duplicate_or_reset_read_notice(self):
        request = self.create_request()
        queue_resource_upload_notifications(request, event='approved', reviewer=self.reviewer)
        site_batch = ResourceNotificationOutbox.objects.filter(
            channel=ResourceNotificationOutbox.CHANNEL_SITE_MESSAGE,
        )
        site_batch.update(available_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(process_one_notification())
        notice = Notification.objects.get()
        read_at = timezone.now()
        notice.read_at = read_at
        notice.save(update_fields=('read_at',))

        site_batch.update(
            status=ResourceNotificationOutbox.STATUS_PROCESSING,
            locked_at=timezone.now() - timedelta(minutes=16),
        )
        self.assertTrue(process_one_notification())

        notice.refresh_from_db()
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(notice.read_at, read_at)
        self.assertEqual(site_batch.get().status, ResourceNotificationOutbox.STATUS_SENT)

    def test_stale_claim_for_sent_subset_does_not_redeliver_completed_batch(self):
        first = self.create_request()
        second = self.create_request()
        queue_resource_upload_notifications(first, event='approved', reviewer=self.reviewer)
        queue_resource_upload_notifications(second, event='rejected', reviewer=self.reviewer)
        site_batch = ResourceNotificationOutbox.objects.filter(
            channel=ResourceNotificationOutbox.CHANNEL_SITE_MESSAGE,
        ).order_by('pk')
        site_batch.update(available_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(process_one_notification())
        notice = Notification.objects.get()
        read_at = timezone.now()
        notice.read_at = read_at
        notice.save(update_fields=('read_at',))
        completed_rows = list(site_batch.values('pk', 'status', 'sent_at', 'attempts'))

        with (
            patch('common.file.resource_tasks.claim_notification', return_value=(completed_rows[0]['pk'],)),
            patch('common.file.resource_tasks._deliver') as deliver,
        ):
            self.assertTrue(process_one_notification())

        deliver.assert_not_called()
        notice.refresh_from_db()
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(notice.read_at, read_at)
        self.assertEqual(list(site_batch.values('pk', 'status', 'sent_at', 'attempts')), completed_rows)

    def test_partially_completed_claim_delivers_only_still_processing_rows(self):
        first = self.create_request()
        second = self.create_request()
        queue_resource_upload_notifications(first, event='approved', reviewer=self.reviewer)
        queue_resource_upload_notifications(second, event='rejected', reviewer=self.reviewer)
        first_row = ResourceNotificationOutbox.objects.get(
            upload_request=first, channel=ResourceNotificationOutbox.CHANNEL_SITE_MESSAGE,
        )
        second_row = ResourceNotificationOutbox.objects.get(
            upload_request=second, channel=ResourceNotificationOutbox.CHANNEL_SITE_MESSAGE,
        )
        ResourceNotificationOutbox.objects.filter(pk=first_row.pk).update(
            available_at=timezone.now() - timedelta(seconds=1),
        )
        self.assertTrue(process_one_notification())
        first_row.refresh_from_db()
        first_sent_at = first_row.sent_at
        first_notice = Notification.objects.get()
        first_notice.read_at = timezone.now()
        first_notice.save(update_fields=('read_at',))
        ResourceNotificationOutbox.objects.filter(pk=second_row.pk).update(
            status=ResourceNotificationOutbox.STATUS_PROCESSING, locked_at=timezone.now(),
        )

        with patch('common.file.resource_tasks.claim_notification', return_value=(first_row.pk, second_row.pk)):
            self.assertTrue(process_one_notification())

        self.assertEqual(Notification.objects.count(), 2)
        second_notice = Notification.objects.exclude(pk=first_notice.pk).get()
        self.assertIn(f'投稿 #{second.pk}（', second_notice.payload['content'])
        self.assertNotIn(f'投稿 #{first.pk}（', second_notice.payload['content'])
        first_row.refresh_from_db()
        second_row.refresh_from_db()
        self.assertEqual(first_row.sent_at, first_sent_at)
        self.assertEqual(second_row.status, ResourceNotificationOutbox.STATUS_SENT)

    def test_site_retry_does_not_reset_rows_completed_after_delivery_error(self):
        request = self.create_request()
        queue_resource_upload_notifications(request, event='approved', reviewer=self.reviewer)
        site_row = ResourceNotificationOutbox.objects.get(
            channel=ResourceNotificationOutbox.CHANNEL_SITE_MESSAGE,
        )
        ResourceNotificationOutbox.objects.filter(pk=site_row.pk).update(
            status=ResourceNotificationOutbox.STATUS_PROCESSING, locked_at=timezone.now(),
        )
        select_for_update = ResourceNotificationOutbox.objects.select_for_update
        lock_calls = 0

        def complete_before_retry_lock(*args, **kwargs):
            nonlocal lock_calls
            lock_calls += 1
            if lock_calls == 2:
                _mark_notifications_sent((site_row.pk,))
            return select_for_update(*args, **kwargs)

        with (
            patch('common.file.resource_tasks.claim_notification', return_value=(site_row.pk,)),
            patch('common.file.resource_tasks._deliver', side_effect=RuntimeError('delivery failed')),
            patch.object(ResourceNotificationOutbox.objects, 'select_for_update', side_effect=complete_before_retry_lock),
        ):
            self.assertTrue(process_one_notification())

        site_row.refresh_from_db()
        self.assertEqual(site_row.status, ResourceNotificationOutbox.STATUS_SENT)
        self.assertEqual(site_row.attempts, 0)
        self.assertEqual(site_row.last_error, '')

    def test_removed_claimed_outbox_rows_are_ignored(self):
        with patch('common.file.resource_tasks.claim_notification', return_value=(987654321,)):
            self.assertTrue(process_one_notification())
        self.assertFalse(Notification.objects.exists())

    def test_site_notice_and_sent_status_roll_back_together_then_retry(self):
        request = self.create_request()
        queue_resource_upload_notifications(request, event='rejected', reviewer=self.reviewer)
        site_batch = ResourceNotificationOutbox.objects.filter(
            channel=ResourceNotificationOutbox.CHANNEL_SITE_MESSAGE,
        )
        site_batch.update(available_at=timezone.now() - timedelta(seconds=1))

        def fail_after_acknowledgement(notification_ids):
            self.assertTrue(Notification.objects.exists())
            _mark_notifications_sent(notification_ids)
            raise RuntimeError('acknowledgement failed')

        with patch('common.file.resource_tasks._mark_notifications_sent', side_effect=fail_after_acknowledgement):
            self.assertTrue(process_one_notification())

        self.assertFalse(Notification.objects.exists())
        outbox = site_batch.get()
        self.assertEqual(outbox.status, ResourceNotificationOutbox.STATUS_RETRY)
        self.assertEqual(outbox.attempts, 1)
        self.assertEqual(outbox.last_error, 'acknowledgement failed')
        self.assertIsNone(outbox.sent_at)
        self.assertIsNone(outbox.locked_at)

        site_batch.update(available_at=timezone.now() - timedelta(seconds=1))
        self.assertTrue(process_one_notification())
        self.assertEqual(Notification.objects.count(), 1)
        self.assertEqual(site_batch.get().status, ResourceNotificationOutbox.STATUS_SENT)

    def test_stale_review_version_is_rejected(self):
        request = self.create_request()
        request.revision += 1
        request.save(update_fields=('revision', 'updated_at'))

        with self.assertRaisesRegex(ResourceReviewError, '已被用户更新'):
            approve_resource_upload(
                upload_request_id=request.pk,
                reviewer=self.reviewer,
                expected_revision=1,
                target_path='/courses/new-course',
            )

    def test_rejection_enqueues_delayed_user_notifications(self):
        request = self.create_request()

        reject_resource_upload(
            upload_request_id=request.pk,
            reviewer=self.reviewer,
            expected_revision=request.revision,
            reason='请补充课程信息',
        )
        request.refresh_from_db()
        self.assertEqual(request.status, ResourceUploadRequest.STATUS_REJECTED)
        self.assertEqual(request.rejection_reason, '请补充课程信息')
        self.assertEqual(
            ResourceNotificationOutbox.objects.filter(upload_request=request).count(),
            2,
        )
        self.assertTrue(all(
            notification.available_at > timezone.now()
            for notification in ResourceNotificationOutbox.objects.filter(upload_request=request)
        ))
        self.assertFalse(process_one_notification())

    def test_publish_failed_can_change_target_and_retry(self):
        request = self.create_request()
        request.status = ResourceUploadRequest.STATUS_PUBLISH_FAILED
        request.publish_error = '目标文件已存在'
        request.save(update_fields=('status', 'publish_error', 'updated_at'))
        job = ResourcePublishJob.objects.create(
            upload_request=request,
            revision=request.revision,
            target_path=request.target_path,
            status=ResourcePublishJob.STATUS_FAILED,
            attempts=5,
            available_at=request.updated_at,
        )

        retry_resource_publish(
            upload_request_id=request.pk,
            reviewer=self.reviewer,
            expected_revision=request.revision,
            target_path='/courses/corrected',
        )

        request.refresh_from_db()
        job.refresh_from_db()
        self.assertEqual(request.status, ResourceUploadRequest.STATUS_PUBLISHING)
        self.assertEqual(request.target_path, '/courses/corrected')
        self.assertEqual(job.status, ResourcePublishJob.STATUS_PENDING)
        self.assertEqual(job.target_path, '/courses/corrected')
        self.assertEqual(job.attempts, 0)

    def test_publish_failed_can_be_rejected_with_reason(self):
        request = self.create_request()
        request.status = ResourceUploadRequest.STATUS_PUBLISH_FAILED
        request.save(update_fields=('status', 'updated_at'))

        reject_resource_upload(
            upload_request_id=request.pk,
            reviewer=self.reviewer,
            expected_revision=request.revision,
            reason='目录冲突，请重新投稿',
        )

        request.refresh_from_db()
        self.assertEqual(request.status, ResourceUploadRequest.STATUS_REJECTED)
        self.assertEqual(request.rejection_reason, '目录冲突，请重新投稿')

    @override_settings(TELEGRAM_BOT_API_TOKEN='', TELEGRAM_CHAT_ID='')
    def test_unconfigured_telegram_notification_is_retried_not_marked_sent(self):
        request = self.create_request()
        notification = ResourceNotificationOutbox.objects.create(
            event_key=f'test-telegram-{request.pk}',
            upload_request=request,
            channel=ResourceNotificationOutbox.CHANNEL_TELEGRAM,
            body='test',
            available_at=request.created_at,
        )

        self.assertTrue(process_one_notification())

        notification.refresh_from_db()
        self.assertEqual(notification.status, ResourceNotificationOutbox.STATUS_RETRY)
        self.assertEqual(notification.attempts, 1)

    def test_staging_cleanup_failure_does_not_remove_published_file(self):
        request = self.create_request()
        approve_resource_upload(
            upload_request_id=request.pk,
            reviewer=self.reviewer,
            expected_revision=request.revision,
            target_path='/courses/new-course',
        )

        with patch('django.db.models.fields.files.FieldFile.delete', side_effect=OSError('busy')):
            self.assertTrue(process_one_publish_job())

        request.refresh_from_db()
        self.assertEqual(request.status, ResourceUploadRequest.STATUS_APPROVED)
        self.assertIsNone(request.files_deleted_at)
        self.assertEqual((self.storage_root / 'courses' / 'new-course' / 'notes.txt').read_bytes(), b'content')
