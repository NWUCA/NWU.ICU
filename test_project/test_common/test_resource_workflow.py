from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from common.file.models import (
    ResourceNotificationOutbox,
    ResourcePublishJob,
    ResourceUploadFile,
    ResourceUploadRequest,
)
from common.file.resource_directories import write_resource_directory_cache
from common.file.resource_tasks import process_one_notification, process_one_publish_job
from common.file.resource_workflow import (
    ResourceReviewError,
    approve_resource_upload,
    reject_resource_upload,
    retry_resource_publish,
)
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

    def test_rejection_enqueues_user_notifications(self):
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
