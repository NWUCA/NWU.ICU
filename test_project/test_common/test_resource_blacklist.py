import time
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APITestCase

from common.file.models import ResourceUploadDirectoryBlacklist, ResourceUploadFile, ResourceUploadRequest
from common.file.resource_directories import write_resource_directory_cache
from management_panel.models import AdminPasskeyCredential, AdminPasskeyState
from management_panel.security import ELEVATED_CREDENTIAL_KEY, ELEVATED_REVISION_KEY, ELEVATED_UNTIL_KEY
from test_project.common import create_user


class ResourceUploadBlacklistTests(APITestCase):
    blacklist_url = '/api/management/uploads/blacklist/'
    directories_url = '/api/management/uploads/directories/'

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        config = override_settings(
            MEDIA_ROOT=temporary.name,
            RESOURCE_DIRECTORY_CACHE_FILE=Path(temporary.name) / 'directories.json',
        )
        config.enable()
        self.addCleanup(config.disable)
        write_resource_directory_cache(['/', '/course', '/course/private', '/course/private/sub', '/course/private-other'])
        ResourceUploadDirectoryBlacklist.objects.create(path='/course/private')
        self.user = create_user(is_active=True)
        self.client.force_login(self.user)

    def elevate(self, permission=True):
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        if permission:
            self.user.user_permissions.add(Permission.objects.get(codename='review_resource_uploads'))
        credential = AdminPasskeyCredential.objects.create(user=self.user, credential_id=b'blacklist-key', public_key=b'key')
        state, _ = AdminPasskeyState.objects.get_or_create(user=self.user)
        session = self.client.session
        session[ELEVATED_UNTIL_KEY] = time.time() + 600
        session[ELEVATED_CREDENTIAL_KEY] = credential.pk
        session[ELEVATED_REVISION_KEY] = state.revision
        session.save()

    def post_upload(self, target_path, relative_path='notes.txt', **extra):
        return self.client.post('/api/upload/request/', {
            'target_path': target_path,
            'files': [SimpleUploadedFile('notes.txt', b'notes')],
            'relative_paths': [relative_path],
            **extra,
        }, format='multipart')

    def test_user_directory_listing_hides_blacklisted_children_only(self):
        response = self.client.get('/api/upload/directories/', {'path': '/course'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([entry['path'] for entry in response.data['contents']['directories']], ['/course/private-other'])
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_direct_navigation_to_blocked_folder_and_descendants_is_hidden(self):
        for path in ['/course/private', '/course/private/sub', '//course/private', '/course//private/.']:
            with self.subTest(path=path):
                response = self.client.get('/api/upload/directories/', {'path': path})
                self.assertEqual(response.status_code, 400 if '//' in path or '/.' in path else 404)
                self.assertNotIn('directories', response.data.get('contents', {}))

    def test_upload_rejects_blocked_targets_and_folder_upload_bypasses(self):
        for target, relative, extra in [
            ('/course/private', 'notes.txt', {}),
            ('/course/private/sub', 'notes.txt', {}),
            ('//course/private', 'notes.txt', {}),
            ('/course\\private', 'notes.txt', {}),
            ('/course', 'private/sub/notes.txt', {}),
            ('/course', 'notes.txt', {'new_folder_name': 'private'}),
            ('/course/private', 'notes.txt', {'new_folder_name': 'new'}),
        ]:
            with self.subTest(target=target, relative=relative, extra=extra):
                self.assertEqual(self.post_upload(target, relative, **extra).status_code, 400)
        self.assertFalse(ResourceUploadRequest.objects.exists())
        self.assertFalse(ResourceUploadFile.objects.exists())

    def test_similarly_named_sibling_is_still_allowed(self):
        self.assertEqual(self.post_upload('/course/private-other').status_code, 201)

    def test_update_checks_retained_files_and_leaves_request_unchanged(self):
        upload = ResourceUploadRequest.objects.create(uploaded_by=self.user, target_path='/other', total_size=5)
        upload_file = ResourceUploadFile.objects.create(
            upload_request=upload, file=SimpleUploadedFile('notes.txt', b'notes'),
            original_name='notes.txt', relative_path='private/notes.txt', size=5,
        )
        response = self.client.put(f'/api/upload/request/{upload.pk}/', {
            'target_path': '/course', 'expected_revision': upload.revision,
        }, format='multipart')
        self.assertEqual(response.status_code, 400)
        upload.refresh_from_db()
        self.assertEqual(upload.target_path, '/other')
        self.assertTrue(upload.files.filter(pk=upload_file.pk).exists())

    def test_update_rejects_new_file_in_blocked_child(self):
        upload = ResourceUploadRequest.objects.create(uploaded_by=self.user, target_path='/other', total_size=0)
        response = self.client.put(f'/api/upload/request/{upload.pk}/', {
            'target_path': '/course', 'expected_revision': upload.revision,
            'files': [SimpleUploadedFile('notes.txt', b'notes')],
            'relative_paths': ['private/notes.txt'],
        }, format='multipart')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(upload.files.exists())

    def test_management_requires_staff_elevation_and_review_permission(self):
        for url in [self.blacklist_url, self.directories_url]:
            self.assertEqual(self.client.get(url).status_code, 404)
        self.assertEqual(self.client.post(self.blacklist_url, {'path': '/course', 'action': 'add'}).status_code, 404)
        self.user.is_staff = True
        self.user.save(update_fields=['is_staff'])
        self.assertEqual(self.client.get(self.blacklist_url).status_code, 403)
        self.elevate(permission=False)
        for url in [self.blacklist_url, self.directories_url]:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.assertEqual(self.client.post(self.blacklist_url, {'path': '/course', 'action': 'add'}).status_code, 403)

    def test_admin_can_browse_add_and_remove_blacklist(self):
        self.elevate()
        response = self.client.get(self.directories_url, {'path': '/course'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['contents']['directories']), 2)
        response = self.client.post(
            self.blacklist_url, {'path': '//course/private/sub/', 'action': 'add'}, format='json'
        )
        self.assertEqual(response.status_code, 400)
        for _ in range(2):
            response = self.client.post(self.blacklist_url, {'path': '/course/private/sub', 'action': 'add'}, format='json')
            self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['contents']['paths'], ['/course/private', '/course/private/sub'])
        response = self.client.post(self.blacklist_url, {'path': '/course/private', 'action': 'remove'}, format='json')
        self.assertEqual(response.data['contents']['paths'], ['/course/private/sub'])
        self.assertEqual(self.post_upload('/course/private').status_code, 201)
        self.assertEqual(self.post_upload('/course/private/sub').status_code, 400)

    def test_blacklist_survives_directory_cache_refresh(self):
        write_resource_directory_cache(['/', '/course', '/course/private', '/course/private/new'])
        response = self.client.get('/api/upload/directories/', {'path': '/course'})
        self.assertEqual(response.data['contents']['directories'], [])

    def test_admin_invalid_path_or_action_does_not_change_blacklist(self):
        self.elevate()
        for data in [
            {'path': '/', 'action': 'add'}, {'path': 'relative', 'action': 'add'},
            {'path': '/course/../other', 'action': 'add'}, {'path': '/course', 'action': 'bad'},
            {'action': 'add'}, {'path': '/course'},
        ]:
            with self.subTest(data=data):
                self.assertEqual(self.client.post(self.blacklist_url, data, format='json').status_code, 400)
        self.assertEqual(list(ResourceUploadDirectoryBlacklist.objects.values_list('path', flat=True)), ['/course/private'])
