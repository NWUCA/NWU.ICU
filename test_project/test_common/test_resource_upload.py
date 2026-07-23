from types import SimpleNamespace
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
        self.user = create_user(is_active=True)
        self.client.force_login(self.user)
        self.url = reverse('api:resource-upload-request')

    @patch('common.file.view.enqueue_resource_upload_telegram_notification')
    def test_upload_response_does_not_wait_for_telegram(self, enqueue_notification):
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
        enqueue_notification.assert_called_once()

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
