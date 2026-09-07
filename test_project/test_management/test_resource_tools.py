from unittest.mock import patch
from rest_framework.test import APIClient, APITestCase
from common.models import ResourceAccessRule, ResourceAuditEvent, ResourceDownloadEvent
from common.file.resource_browser import search_resources
from common.file.resource_directories import read_resource_directory_cache
from test_project.test_management import test_resource_files


class ResourceToolsTests(APITestCase):
    base = test_resource_files.ResourceFileManagementTests.base
    setUp = test_resource_files.ResourceFileManagementTests.setUp
    elevate = test_resource_files.ResourceFileManagementTests.elevate
    action = test_resource_files.ResourceFileManagementTests.action
    cached_paths = test_resource_files.ResourceFileManagementTests.cached_paths
    def test_rename_mkdir_and_audit(self):
        response = self.action('rename', name='新名称.pdf')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((self.root / '新名称.pdf').read_bytes(), b'original')
        self.assertNotIn('/试卷 #1%.pdf', self.cached_paths())
        response = self.client.post(self.base + 'operations/', {'action': 'mkdir', 'path': '/', 'name': '新目录'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('/新目录', read_resource_directory_cache()['paths'])
        response = self.client.get(self.base + 'audit/', {'search': '新名称'})
        self.assertEqual(response.data['contents']['count'], 1)
        self.assertEqual(response.data['contents']['results'][0]['actor'], 'file-admin')

    def test_readme_edit_version_and_rollback(self):
        original = self.client.get(self.base + 'readme/', {'path': '/'}).data['contents']
        response = self.client.post(self.base + 'readme/', {**original, 'content': '# 更新\n\n**文字**'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual((self.root / 'readme.md').read_text(), '# 更新\n\n**文字**')
        self.assertEqual(self.client.post(self.base + 'readme/', {**original, 'content': 'stale'}, format='json').status_code, 409)
        latest = response.data['contents']
        with patch('management_panel.resource_tools.write_index', side_effect=OSError('disk full')):
            response = self.client.post(self.base + 'readme/', {**latest, 'content': 'rollback'}, format='json')
        self.assertEqual(response.status_code, 503)
        self.assertEqual((self.root / 'readme.md').read_text(), latest['content'])
        self.assertEqual(ResourceAuditEvent.objects.filter(action='readme').count(), 1)

    def test_create_readme_and_block_alias(self):
        response = self.client.post(self.base + 'readme/', {'path': '/目标目录', 'content': '# hello', 'version': ''}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self.client.get('/api/resources/file/', {'path': '/目标目录/readme.md'}).status_code, 404)
        (self.root / '目标目录' / 'readme.md').unlink()
        (self.root / '目标目录' / 'readme.md').symlink_to(self.root / 'readme.md')
        self.assertEqual(self.client.get(self.base + 'readme/', {'path': '/目标目录'}).status_code, 404)

    def test_purge_requires_confirmation_and_only_removes_snapshot(self):
        self.action('delete')
        first = self.client.get(self.base + 'trash/').data['contents']['entries'][0]
        self.action('delete', '/readme.md')
        query = {'action': 'purge', 'trash_ids': [first['id']]}
        self.assertEqual(self.client.post(self.base + 'operations/', query, format='json').status_code, 400)
        response = self.client.post(self.base + 'operations/', {**query, 'confirmation': '永久删除'}, format='json')
        self.assertEqual(response.data['contents'], {'completed': 1, 'failed': []})
        remaining = self.client.get(self.base + 'trash/').data['contents']['entries']
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]['name'], 'readme.md')
        self.assertEqual(ResourceAuditEvent.objects.filter(action='purge').count(), 1)

    def test_reindex_discovers_external_changes(self):
        (self.root / '目标目录' / '外部.txt').write_text('external')
        response = self.client.post(self.base + 'index/', {}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.assertIn('/目标目录/外部.txt', self.cached_paths())
        self.assertTrue(response.data['contents']['updated_at'])

    def test_access_filters_browse_search_direct_download_and_inherits(self):
        response = self.client.post(self.base + 'access/', {'path': '/', 'mode': 'login'}, format='json')
        self.assertEqual(response.status_code, 200, response.data)
        self.client.post(self.base + 'access/', {'path': '/目标目录', 'mode': 'public'}, format='json')
        self.assertEqual(self.client.get(self.base + 'access/', {'path': '/目标目录'}).data['contents']['effective'], 'login')
        guest = APIClient()
        self.assertEqual(guest.get('/api/resources/browse/').status_code, 401)
        self.assertEqual(guest.get('/api/resources/file/', {'path': '/试卷 #1%.pdf'}).status_code, 401)
        self.assertEqual(search_resources('试卷', 1, 20)[0]['total_count'], 0)
        self.assertEqual(ResourceDownloadEvent.objects.count(), 0)
        self.assertEqual(self.client.get('/api/resources/browse/').status_code, 200)
        ResourceAccessRule.objects.all().delete()
        self.client.post(self.base + 'access/', {'path': '/目标目录', 'mode': 'admin'}, format='json')
        self.assertNotIn('目标目录', [item['name'] for item in guest.get('/api/resources/browse/').data['contents']['entries']])
        self.assertEqual(guest.get('/api/resources/browse/', {'path': '/目标目录'}).status_code, 404)

    def test_download_counts_deduplicate_and_exclude_preview_head_ranges_errors(self):
        guest = APIClient()
        path = {'path': '/试卷 #1%.pdf'}
        def request(method='get', **kwargs):
            response = getattr(guest, method)('/api/resources/file/', kwargs.pop('query', path), **kwargs)
            with patch('django.http.response.signals.request_finished.send'):
                response.close()
            return response
        request(query={**path, 'inline': '1'})
        request('head')
        request(HTTP_RANGE='bytes=2-4')
        request(HTTP_RANGE='bytes=100-200')
        self.assertEqual(ResourceDownloadEvent.objects.count(), 0)
        request()
        request(HTTP_RANGE='bytes=0-2')
        self.assertEqual(ResourceDownloadEvent.objects.count(), 1)
        response = self.client.get('/api/resources/file/', path)
        with patch('django.http.response.signals.request_finished.send'):
            response.close()
        report = self.client.get(self.base + 'statistics/', {'days': 7}).data['contents']
        self.assertEqual((report['total'], report['guest'], report['authenticated']), (2, 1, 1))
        self.assertEqual(report['files'][0]['path'], path['path'])

    def test_tools_require_passkey_and_file_permission(self):
        self.client.logout()
        for endpoint in ['readme/', 'access/', 'index/', 'audit/', 'statistics/']:
            self.assertEqual(self.client.get(self.base + endpoint).status_code, 404)
        self.assertEqual(self.client.post(self.base + 'operations/', {'action': 'mkdir', 'path': '/', 'name': 'blocked'}, format='json').status_code, 404)
