import time
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from rest_framework.test import APIClient, APITestCase

from common.file.resource_directories import read_resource_directory_cache, write_resource_directory_cache
from management_panel.models import AdminPasskeyCredential, AdminPasskeyState
from management_panel.resource_files import PRIVATE_DIRECTORY, version
from management_panel.security import ELEVATED_CREDENTIAL_KEY, ELEVATED_REVISION_KEY, ELEVATED_UNTIL_KEY
from scripts.export_resource_tree import build_resource_tree
from test_project.common import create_user


class ResourceFileManagementTests(APITestCase):
    base = '/api/management/resources/'

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'storage'
        self.root.mkdir()
        (self.root / '目标目录').mkdir()
        (self.root / '试卷 #1%.pdf').write_bytes(b'original')
        (self.root / 'readme.md').write_text('# 说明', encoding='utf-8')
        self.override = override_settings(RESOURCE_STORAGE_ROOT=self.root,
            RESOURCE_DIRECTORY_CACHE_FILE=Path(self.temp.name) / 'index.json')
        self.override.enable()
        self.addCleanup(self.override.disable)
        write_resource_directory_cache(['/', '/目标目录'], entries=build_resource_tree(self.root)['entries'])
        self.staff = create_user(username='file-admin', email='file-admin@example.com', is_staff=True)
        self.staff.user_permissions.add(Permission.objects.get(codename='manage_resource_files'))
        self.elevate()

    def elevate(self):
        credential, _ = AdminPasskeyCredential.objects.get_or_create(user=self.staff,
            credential_id=b'file-manager-test', defaults={'name': 'test', 'public_key': b'test-key'})
        state, _ = AdminPasskeyState.objects.get_or_create(user=self.staff)
        self.client.force_login(self.staff)
        session = self.client.session
        session[ELEVATED_UNTIL_KEY] = time.time() + 600
        session[ELEVATED_CREDENTIAL_KEY] = credential.pk
        session[ELEVATED_REVISION_KEY] = state.revision
        session.save()

    def action(self, action, path='/试卷 #1%.pdf', **extra):
        data = {'action': action, 'path': path, **extra}
        if action != 'restore' and 'version' not in data:
            data['version'] = version(self.root / path.lstrip('/'))
        return self.client.post(self.base + 'action/', data, format='json')

    def cached_paths(self):
        return {entry['path'] for entry in read_resource_directory_cache()['entries']}

    def test_requires_admin_passkey_and_separate_file_permission(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.base).status_code, 404)
        self.client.force_login(create_user(username='student', email='student@example.com'))
        self.assertEqual(self.client.get(self.base).status_code, 404)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.base).status_code, 403)
        self.elevate()
        self.staff.user_permissions.clear()
        self.staff.user_permissions.add(Permission.objects.get(codename='review_resource_uploads'))
        for endpoint in ['', 'trash/']:
            self.assertEqual(self.client.get(self.base + endpoint).status_code, 403)
        self.assertEqual(self.action('delete').status_code, 403)
        self.assertTrue((self.root / '试卷 #1%.pdf').exists())

    def test_post_requires_csrf_even_when_elevated(self):
        client = APIClient(enforce_csrf_checks=True)
        client.cookies = self.client.cookies
        response = client.post(self.base + 'action/', {'action': 'delete', 'path': '/readme.md',
            'version': version(self.root / 'readme.md')}, format='json')
        self.assertEqual(response.status_code, 403)
        self.assertTrue((self.root / 'readme.md').exists())

    def test_admin_sees_readme_but_private_browser_does_not(self):
        data = self.client.get(self.base).data['contents']
        self.assertIn('readme.md', [entry['name'] for entry in data['entries']])
        self.assertTrue(all(entry['version'] for entry in data['entries']))
        public = self.client.get('/api/resources/browse/').data['contents']
        self.assertNotIn('readme.md', [entry['name'] for entry in public['entries']])

    def test_upload_publishes_complete_files_and_updates_index(self):
        response = self.client.post(self.base + 'upload/', {'path': '/目标目录',
            'files': [SimpleUploadedFile('讲义 #2%.pdf', b'new'), SimpleUploadedFile('empty.txt', b'')]}, format='multipart')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((self.root / '目标目录' / '讲义 #2%.pdf').read_bytes(), b'new')
        self.assertIn('/目标目录/讲义 #2%.pdf', self.cached_paths())
        self.assertEqual(list((self.root / PRIVATE_DIRECTORY).glob('upload-*')), [])

    def test_upload_never_overwrites_case_insensitive_collisions(self):
        response = self.client.post(self.base + 'upload/', {'path': '/', 'files': [
            SimpleUploadedFile('new.txt', b'new'), SimpleUploadedFile('README.MD', b'changed')]}, format='multipart')
        self.assertEqual(response.status_code, 409)
        self.assertFalse((self.root / 'new.txt').exists())
        self.assertEqual((self.root / 'readme.md').read_text(encoding='utf-8'), '# 说明')

    def test_upload_rejects_limits_and_unsafe_destination(self):
        with patch('management_panel.resource_files.MAX_FILE_SIZE', 2):
            response = self.client.post(self.base + 'upload/', {'path': '/',
                'files': [SimpleUploadedFile('too-big.txt', b'123')]}, format='multipart')
            self.assertEqual(response.status_code, 400)
        for path in ['/../outside', '/目标目录/../../outside']:
            response = self.client.post(self.base + 'upload/', {'path': path,
                'files': [SimpleUploadedFile('test.txt', b'ok')]}, format='multipart')
            self.assertEqual(response.status_code, 400)

    def test_upload_rolls_back_on_index_write_failure(self):
        with patch('management_panel.resource_files.write_index', side_effect=OSError('disk full')):
            response = self.client.post(self.base + 'upload/', {'path': '/',
                'files': [SimpleUploadedFile('new.txt', b'new')]}, format='multipart')
        self.assertEqual(response.status_code, 503)
        self.assertFalse((self.root / 'new.txt').exists())

    def test_move_preserves_content_and_updates_search_index(self):
        response = self.action('move', destination='/目标目录')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertFalse((self.root / '试卷 #1%.pdf').exists())
        self.assertEqual((self.root / '目标目录' / '试卷 #1%.pdf').read_bytes(), b'original')
        self.assertNotIn('/试卷 #1%.pdf', self.cached_paths())
        self.assertIn('/目标目录/试卷 #1%.pdf', self.cached_paths())

    def test_move_collision_and_stale_file_leave_source_untouched(self):
        (self.root / '目标目录' / '试卷 #1%.pdf').write_bytes(b'other')
        self.assertEqual(self.action('move', destination='/目标目录').status_code, 409)
        self.assertEqual(self.action('delete', version='old').status_code, 409)
        self.assertEqual((self.root / '试卷 #1%.pdf').read_bytes(), b'original')

    def test_delete_and_restore_keep_original_bytes_and_hide_trash(self):
        self.assertEqual(self.action('delete').status_code, 200)
        self.assertFalse((self.root / '试卷 #1%.pdf').exists())
        self.assertNotIn('/试卷 #1%.pdf', self.cached_paths())
        trash = self.client.get(self.base + 'trash/').data['contents']['entries']
        self.assertEqual(len(trash), 1)
        self.assertEqual(trash[0]['path'], '/试卷 #1%.pdf')
        self.assertFalse(any(PRIVATE_DIRECTORY in path for path in build_resource_tree(self.root)['paths']))
        self.assertEqual(self.client.get('/api/resources/browse/', {'path': '/' + PRIVATE_DIRECTORY}).status_code, 404)
        self.assertEqual(self.action('restore', trash_id=trash[0]['id']).status_code, 200)
        self.assertEqual((self.root / '试卷 #1%.pdf').read_bytes(), b'original')
        self.assertIn('/试卷 #1%.pdf', self.cached_paths())
        self.assertEqual(self.client.get(self.base + 'trash/').data['contents']['entries'], [])

    def test_restore_collision_keeps_both_versions(self):
        self.action('delete')
        record = self.client.get(self.base + 'trash/').data['contents']['entries'][0]
        (self.root / '试卷 #1%.pdf').write_bytes(b'replacement')
        self.assertEqual(self.action('restore', trash_id=record['id']).status_code, 409)
        self.assertEqual((self.root / '试卷 #1%.pdf').read_bytes(), b'replacement')
        self.assertEqual(len(self.client.get(self.base + 'trash/').data['contents']['entries']), 1)

    def test_delete_rolls_back_on_index_error(self):
        with patch('management_panel.resource_files.write_index', side_effect=OSError('disk full')):
            self.assertEqual(self.action('delete').status_code, 503)
        self.assertEqual((self.root / '试卷 #1%.pdf').read_bytes(), b'original')
        self.assertIn('/试卷 #1%.pdf', self.cached_paths())

    def test_directories_and_symlink_targets_are_rejected(self):
        self.assertEqual(self.action('delete', '/目标目录').status_code, 400)
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (self.root / 'alias').symlink_to(outside, target_is_directory=True)
        self.assertEqual(self.action('move', destination='/alias').status_code, 404)
        self.assertEqual(list(outside.iterdir()), [])
