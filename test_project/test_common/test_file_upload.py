import tempfile
from unittest.mock import patch
from io import BytesIO

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient, APITestCase

from common.file.models import ResourceUploadRequest, UploadedFile
from test_project.common import create_user, login_user


class FileUploadSecurityTests(APITestCase):
    def setUp(self):
        self.media_directory = tempfile.TemporaryDirectory()
        self.settings_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.settings_override.enable()
        self.user = create_user(is_active=True)
        login_user(self.client)
        self.upload_url = reverse('api:file-upload')

    def tearDown(self):
        self.settings_override.disable()
        self.media_directory.cleanup()

    @staticmethod
    def png_file(name='avatar.png'):
        contents = BytesIO()
        Image.new('RGB', (2, 2), color='blue').save(contents, format='PNG')
        return SimpleUploadedFile(name, contents.getvalue(), content_type='image/png')

    def test_generic_file_is_not_parsed_as_an_image(self):
        response = self.client.post(
            self.upload_url,
            {
                'file': SimpleUploadedFile(
                    'notes.txt', b'plain text', content_type='text/plain'
                ),
                'file_type': 'file',
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        uploaded_file = UploadedFile.objects.get(pk=response.data['contents']['uuid'])
        self.assertEqual(uploaded_file.file_type, 'file')
        self.assertEqual(uploaded_file.file_size, len(b'plain text'))

    def test_spoofed_image_content_type_is_rejected(self):
        response = self.client.post(
            self.upload_url,
            {
                'file': SimpleUploadedFile(
                    'avatar.png', b'not an image', content_type='image/png'
                ),
                'file_type': 'avatar',
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(UploadedFile.objects.count(), 0)

    def test_non_image_mime_is_rejected_for_avatar(self):
        response = self.client.post(
            self.upload_url,
            {
                'file': SimpleUploadedFile(
                    'avatar.png', b'not an image', content_type='text/plain'
                ),
                'file_type': 'avatar',
            },
            format='multipart',
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(UploadedFile.objects.count(), 0)

    def test_file_size_limit_is_enforced_at_exact_boundary(self):
        limits = {'file': 3, 'avatar': 66 * 1024, 'img': 5 * 1024 * 1024}
        with override_settings(FILE_UPLOAD_SIZE_LIMIT=limits):
            accepted = self.client.post(
                self.upload_url,
                {
                    'file': SimpleUploadedFile('three.txt', b'123'),
                    'file_type': 'file',
                },
                format='multipart',
            )
            rejected = self.client.post(
                self.upload_url,
                {
                    'file': SimpleUploadedFile('four.txt', b'1234'),
                    'file_type': 'file',
                },
                format='multipart',
            )

        self.assertEqual(accepted.status_code, status.HTTP_201_CREATED)
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(USER_UPLOAD_QUOTA_BYTES=10)
    @patch('common.file.view.resource_upload_notification_executor.submit')
    def test_ordinary_and_resource_uploads_share_quota(self, submit_notification):
        ResourceUploadRequest.objects.create(
            uploaded_by=self.user,
            target_path='/course',
            status=ResourceUploadRequest.STATUS_PENDING,
            total_size=7,
        )

        accepted = self.client.post(
            self.upload_url,
            {'file': SimpleUploadedFile('three.txt', b'123'), 'file_type': 'file'},
            format='multipart',
        )
        with self.assertLogs('common.file.view', level='WARNING') as logs:
            rejected = self.client.post(
                self.upload_url,
                {'file': SimpleUploadedFile('one.txt', b'1'), 'file_type': 'file'},
                format='multipart',
            )

        self.assertEqual(accepted.status_code, status.HTTP_201_CREATED)
        self.assertEqual(rejected.status_code, status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        self.assertEqual(
            rejected.data['errors'][0]['err_code'],
            'upload_quota_exceeded',
        )
        self.assertIn('upload_quota_exceeded', logs.output[0])
        submit_notification.assert_called_once()

    def test_deleting_last_deduplicated_reference_removes_physical_file(self):
        first = self.client.post(
            self.upload_url,
            {'file': SimpleUploadedFile('first.txt', b'same'), 'file_type': 'file'},
            format='multipart',
        )
        second = self.client.post(
            self.upload_url,
            {'file': SimpleUploadedFile('second.txt', b'same'), 'file_type': 'file'},
            format='multipart',
        )
        first_file = UploadedFile.objects.get(pk=first.data['contents']['uuid'])
        second_file = UploadedFile.objects.get(pk=second.data['contents']['uuid'])
        self.assertEqual(first_file.file.name, second_file.file.name)

        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(reverse('api:file-delete', args=[first_file.pk]))
        self.assertTrue(second_file.file.storage.exists(second_file.file.name))
        with self.captureOnCommitCallbacks(execute=True):
            self.client.delete(reverse('api:file-delete', args=[second_file.pk]))
        self.assertFalse(second_file.file.storage.exists(second_file.file.name))

    def test_only_owner_can_select_uploaded_avatar(self):
        own_upload = self.client.post(
            self.upload_url,
            {'file': self.png_file('own.png'), 'file_type': 'avatar'},
            format='multipart',
        )
        own_uuid = own_upload.data['contents']['uuid']
        accepted = self.client.post(
            reverse('api:my_profile'), {'avatar_uuid': own_uuid}, format='json'
        )

        second_client = APIClient()
        create_user(
            username='second_user', email='second@example.com', is_active=True
        )
        login_user(
            second_client,
            {'username': 'second_user', 'password': 'test_password'},
        )
        other_upload = second_client.post(
            self.upload_url,
            {'file': self.png_file('other.png'), 'file_type': 'avatar'},
            format='multipart',
        )
        rejected = self.client.post(
            reverse('api:my_profile'),
            {'avatar_uuid': other_upload.data['contents']['uuid']},
            format='json',
        )

        self.assertEqual(accepted.status_code, status.HTTP_200_OK)
        self.assertEqual(accepted.data['contents']['avatar'], own_uuid)
        self.assertTrue(accepted.data['contents']['has_avatar'])
        self.assertEqual(rejected.status_code, status.HTTP_400_BAD_REQUEST)
