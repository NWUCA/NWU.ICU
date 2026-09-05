from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from common.file.models import ResourceUploadFile, ResourceUploadRequest
from common.file.view import (
    enqueue_resource_upload_telegram_notification,
    resource_upload_notification_executor,
    send_resource_upload_telegram_notification,
)
from test_project.common import create_user


class ResourceUploadNotificationTests(SimpleTestCase):
    @patch.object(resource_upload_notification_executor, 'submit')
    def test_notification_is_submitted_to_background_executor(self, submit):
        upload_request = SimpleNamespace(
            pk=7,
            uploaded_by=SimpleNamespace(username='test-user'),
            uploaded_by_id=2,
            target_path='/course',
            total_size=13,
            files=SimpleNamespace(
                all=lambda: [
                    SimpleNamespace(relative_path='notes.txt', size=13),
                ],
            ),
        )

        enqueue_resource_upload_telegram_notification(upload_request)

        submit.assert_called_once()
        args = submit.call_args.args
        self.assertIs(args[0], send_resource_upload_telegram_notification)
        self.assertEqual(args[1], 7)
        self.assertIn('notes.txt', args[2])

    @override_settings(TELEGRAM_BOT_API_TOKEN='', TELEGRAM_CHAT_ID='')
    @patch('common.file.view.TelegramBotHandler')
    def test_missing_telegram_config_skips_notification(self, telegram_handler):
        send_resource_upload_telegram_notification(7, 'test message')

        telegram_handler.assert_not_called()


class ResourceUploadRequestTests(APITestCase):
    def setUp(self):
        self.media_directory = TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        self.media_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.user = create_user(is_active=True)
        self.client.force_login(self.user)
        self.url = reverse('api:resource-upload-request')

    def create_upload_request(self, status=ResourceUploadRequest.STATUS_PENDING):
        upload_request = ResourceUploadRequest.objects.create(
            uploaded_by=self.user,
            target_path='/course',
            status=status,
            total_size=7,
        )
        upload_file = ResourceUploadFile.objects.create(
            upload_request=upload_request,
            file=SimpleUploadedFile('old.txt', b'old-one'),
            original_name='old.txt',
            relative_path='old.txt',
            size=7,
        )
        return upload_request, upload_file

    @patch('common.file.view.queue_resource_upload_notifications')
    def test_upload_response_queues_telegram_notification(self, queue_notification):
        uploaded_file = SimpleUploadedFile(
            'notes.txt',
            b'test resource',
            content_type='text/plain',
        )

        response = self.client.post(
            self.url,
            {
                'target_path': '/course',
                'files': [uploaded_file],
                'relative_paths': ['notes.txt'],
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            response.data['contents']['upload_request']['files'][0]['relative_path'],
            'notes.txt',
        )
        self.assertEqual(
            response.data['contents']['upload_request']['files'][0]['size_display'],
            '13 B',
        )
        self.assertEqual(
            response.data['contents']['upload_request']['total_size_display'],
            '13 B',
        )
        queue_notification.assert_called_once()

    def test_only_admin_can_download_submitted_file(self):
        upload_request = ResourceUploadRequest.objects.create(
            uploaded_by=self.user,
            target_path='/',
            total_size=13,
        )
        upload_file = ResourceUploadFile.objects.create(
            upload_request=upload_request,
            file=SimpleUploadedFile('notes.txt', b'test resource'),
            original_name='notes.txt',
            relative_path='notes.txt',
            size=13,
        )
        url = reverse('api:resource-upload-file-download', args=[upload_file.pk])

        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        self.user.is_staff = True
        self.user.save(update_fields=('is_staff',))
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response['Content-Disposition'],
            'attachment; filename="notes.txt"',
        )
        for closer in response._resource_closers:
            closer()
        response._resource_closers.clear()

    @patch('common.file.view.queue_resource_upload_notifications')
    def test_rejected_request_can_remove_add_and_move_files(self, queue_notification):
        upload_request, removed_file = self.create_upload_request(
            status=ResourceUploadRequest.STATUS_REJECTED,
        )
        kept_file = ResourceUploadFile.objects.create(
            upload_request=upload_request,
            file=SimpleUploadedFile('keep.pdf', b'keep'),
            original_name='keep.pdf',
            relative_path='keep.pdf',
            size=4,
        )
        upload_request.total_size = 11
        upload_request.rejection_reason = '请调整目录'
        upload_request.reviewed_by = self.user
        upload_request.save(update_fields=('total_size', 'rejection_reason', 'reviewed_by'))

        response = self.client.put(
            reverse('api:resource-upload-request-detail', args=[upload_request.pk]),
            {
                'target_path': '/documents',
                'expected_revision': str(upload_request.revision),
                'new_folder_name': 'new-course',
                'remove_file_ids': [str(removed_file.pk)],
                'files': [SimpleUploadedFile('new.txt', b'new')],
                'relative_paths': ['new.txt'],
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        upload_request.refresh_from_db()
        self.assertEqual(upload_request.status, ResourceUploadRequest.STATUS_PENDING)
        self.assertEqual(upload_request.target_path, '/documents/new-course')
        self.assertTrue(upload_request.creates_new_folder)
        self.assertEqual(upload_request.total_size, 7)
        self.assertEqual(upload_request.rejection_reason, '')
        self.assertIsNone(upload_request.reviewed_by)
        self.assertFalse(ResourceUploadFile.objects.filter(pk=removed_file.pk).exists())
        self.assertEqual(
            set(upload_request.files.values_list('relative_path', flat=True)),
            {kept_file.relative_path, 'new.txt'},
        )
        queue_notification.assert_called_once()
        self.assertEqual(queue_notification.call_args.kwargs, {'event': 'updated'})

    def test_approved_request_cannot_be_edited(self):
        upload_request, _ = self.create_upload_request(
            status=ResourceUploadRequest.STATUS_APPROVED,
        )

        response = self.client.put(
            reverse('api:resource-upload-request-detail', args=[upload_request.pk]),
            {'target_path': '/documents', 'expected_revision': str(upload_request.revision)},
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        upload_request.refresh_from_db()
        self.assertEqual(upload_request.target_path, '/course')

    def test_edit_must_keep_at_least_one_file(self):
        upload_request, upload_file = self.create_upload_request()

        response = self.client.put(
            reverse('api:resource-upload-request-detail', args=[upload_request.pk]),
            {
                'target_path': '/documents',
                'expected_revision': str(upload_request.revision),
                'remove_file_ids': [str(upload_file.pk)],
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(ResourceUploadFile.objects.filter(pk=upload_file.pk).exists())

    def test_upload_history_is_ordered_by_review_priority(self):
        approved, _ = self.create_upload_request(ResourceUploadRequest.STATUS_APPROVED)
        pending, _ = self.create_upload_request(ResourceUploadRequest.STATUS_PENDING)
        rejected, _ = self.create_upload_request(ResourceUploadRequest.STATUS_REJECTED)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        request_ids = [
            upload_request['id']
            for upload_request in response.data['contents']['upload_requests']
        ]
        self.assertEqual(request_ids, [rejected.pk, pending.pk, approved.pk])
