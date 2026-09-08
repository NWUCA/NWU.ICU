from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from io import StringIO

from django.core.management import call_command, CommandError
from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory

from common.file.resource_browser import ResourceBrowseView, ResourceFileView, ResourceSearchView, search_resources
from common.models import ResourceAccessRule
from scripts.export_resource_tree import build_resource_tree
from common.file.resource_directories import write_resource_directory_cache


class ResourceBrowserTests(TestCase):
    def test_search_uses_only_index_and_refreshes_metadata_after_reindex(self):
        for number in range(30):
            (self.root / '课程.2026' / f'试卷{number}.txt').write_text('old')
        payload = build_resource_tree(self.root)
        write_resource_directory_cache(payload['paths'], entries=payload['entries'])
        with patch('common.file.resource_browser.resource_root', side_effect=AssertionError('search must not access storage')):
            response = ResourceSearchView.as_view()(self.factory.get('/api/resources/search/', {'q': '试卷', 'path': '/课程.2026'}))
        self.assertEqual(response.data['contents']['total_count'], 31)
        (self.root / '课程.2026' / '试卷0.txt').unlink()
        (self.root / '课程.2026' / '试卷1.txt').write_bytes(b'updated')
        pagination, results = search_resources('试卷', 1, 100)
        self.assertEqual(pagination['total_count'], 31)
        self.assertEqual(next(item['size'] for item in results if item['name'] == '试卷1.txt'), 3)
        self.assertEqual(self.download('/课程.2026/试卷0.txt').status_code, 404)
        call_command('reindex_resources', stdout=StringIO())
        pagination, results = search_resources('试卷', 1, 100)
        self.assertEqual(pagination['total_count'], 30)
        self.assertEqual(next(item['size'] for item in results if item['name'] == '试卷1.txt'), 7)
        ResourceAccessRule.objects.create(path='/课程.2026', mode='admin')
        self.assertEqual(search_resources('试卷', 1, 100)[1], [])

    def test_search_index_excludes_aliases_and_hidden_paths(self):
        outside = Path(self.temp.name) / 'outside'
        outside.mkdir()
        (outside / '试卷.txt').write_text('private')
        (self.root / '.hidden').mkdir()
        (self.root / '.hidden' / '试卷.txt').write_text('private')
        try:
            (self.root / 'alias').symlink_to(outside, target_is_directory=True)
            (self.root / '试卷链接.txt').symlink_to(outside / '试卷.txt')
        except OSError:
            self.skipTest('Host does not permit creating symbolic links')
        payload = build_resource_tree(self.root)
        write_resource_directory_cache(payload['paths'], entries=payload['entries'] + [
            {'name': '试卷.txt', 'path': '/.hidden/试卷.txt', 'type': 'file'},
            {'name': '试卷.txt', 'path': '/../outside/试卷.txt', 'type': 'file'},
        ])
        self.assertEqual([item['name'] for item in search_resources('试卷', 1, 100)[1]], ['试卷 #1%.pdf'])

    def test_failed_reindex_preserves_previous_search_index(self):
        call_command('reindex_resources', stdout=StringIO())
        before = search_resources('试卷', 1, 100)
        with patch('common.management.commands.reindex_resources.build_resource_tree', side_effect=OSError('storage unavailable')):
            with self.assertRaises(CommandError):
                call_command('reindex_resources', stdout=StringIO())
        self.assertEqual(search_resources('试卷', 1, 100), before)

    def test_global_search_prioritizes_current_folder_before_pagination(self):
        elsewhere = self.root / '其他目录'
        elsewhere.mkdir()
        for number in range(101):
            (elsewhere / f'试卷{number:03}').mkdir()
        payload = build_resource_tree(self.root)
        write_resource_directory_cache(payload['paths'], entries=payload['entries'])
        request = self.factory.get('/api/resources/search/', {'q': '试卷', 'path': '/课程.2026', 'sort': 'name'})
        response = ResourceSearchView.as_view()(request)
        data = response.data['contents']
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data['total_count'], 102)
        self.assertEqual(len(data['entries']), 100)
        self.assertEqual(data['entries'][0]['path'], '/课程.2026/试卷 #1%.pdf')
        second = ResourceSearchView.as_view()(self.factory.get('/api/resources/search/', {'q': '试卷', 'path': '/课程.2026', 'page': 2})).data['contents']
        self.assertEqual(len(second['entries']), 2)
        self.assertFalse({item['path'] for item in data['entries']} & {item['path'] for item in second['entries']})
        file_context = ResourceSearchView.as_view()(self.factory.get('/api/resources/search/', {'q': '试卷', 'path': '/课程.2026/试卷 #1%.pdf'}))
        self.assertEqual(file_context.status_code, 200)
        self.assertEqual(file_context.data['contents']['entries'][0]['path'], '/课程.2026/试卷 #1%.pdf')
        files = ResourceSearchView.as_view()(self.factory.get('/api/resources/search/', {'q': '试卷', 'type': 'file'})).data['contents']
        self.assertEqual(files['total_count'], 1)
        self.assertEqual(files['entries'][0]['type'], 'file')
        directories = ResourceSearchView.as_view()(self.factory.get('/api/resources/search/', {'q': '试卷', 'type': 'directory', 'page': 2})).data['contents']
        self.assertEqual(directories['total_count'], 101)
        self.assertEqual(len(directories['entries']), 1)
        self.assertEqual(directories['entries'][0]['type'], 'directory')

    def test_global_search_obeys_visibility_rules_and_rejects_invalid_queries(self):
        payload = build_resource_tree(self.root)
        write_resource_directory_cache(payload['paths'], entries=payload['entries'])
        ResourceAccessRule.objects.create(path='/课程.2026', mode='admin')
        for keyword in ('试卷', 'readme'):
            response = ResourceSearchView.as_view()(self.factory.get('/api/resources/search/', {'q': keyword}))
            self.assertEqual(response.data['contents']['total_count'], 0)
        self.assertEqual(ResourceSearchView.as_view()(self.factory.get('/api/resources/search/', {'q': '试卷', 'path': '/课程.2026'})).status_code, 404)
        for query in ({'q': ''}, {'q': '试卷', 'page': 0}, {'q': '试卷', 'path': '/../秘密'}, {'q': '试卷', 'type': 'invalid'}):
            self.assertEqual(ResourceSearchView.as_view()(self.factory.get('/api/resources/search/', query)).status_code, 400)

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'resources'
        self.root.mkdir()
        self.override = override_settings(
            RESOURCE_STORAGE_ROOT=self.root,
            RESOURCE_DIRECTORY_CACHE_FILE=Path(self.temp.name) / 'index.json',
        )
        self.override.enable()
        self.addCleanup(self.override.disable)
        self.factory = APIRequestFactory()
        (self.root / 'readme.md').write_text('# 学习资料\n\n**请勿商用**', encoding='utf-8-sig')
        (self.root / '课程.2026').mkdir()
        (self.root / '课程.2026' / 'README.md').write_bytes('# 子目录'.encode('gb18030'))
        (self.root / '课程.2026' / '试卷 #1%.pdf').write_bytes(b'0123456789')
        (self.root / '无扩展名').write_bytes(b'data')

    def browse(self, path='/'):
        return ResourceBrowseView.as_view()(self.factory.get('/api/resources/browse/', {'path': path}))

    def download(self, path='/课程.2026/试卷 #1%.pdf', **headers):
        query = {'path': path, 'inline': headers.pop('inline', '0')}
        response = ResourceFileView.as_view()(self.factory.get('/api/resources/file/', query, **headers))
        self.addCleanup(self.close_response, response)
        return response

    @staticmethod
    def close_response(response):
        # These filesystem-only unit requests do not own a database connection.
        with patch('django.http.response.signals.request_finished.send'):
            response.close()

    def test_public_listing_hides_readme_and_renders_source_separately(self):
        response = self.browse()
        self.assertEqual(response.status_code, 200)
        data = response.data['contents']
        self.assertEqual(data['readme'], '# 学习资料\n\n**请勿商用**')
        self.assertEqual([entry['name'] for entry in data['entries']], ['课程.2026', '无扩展名'])
        self.assertNotIn(str(self.root), str(data))

    def test_subdirectory_readme_is_case_insensitive_and_supports_legacy_encoding(self):
        data = self.browse('/课程.2026').data['contents']
        self.assertEqual(data['readme'], '# 子目录')
        self.assertEqual(len(data['entries']), 1)
        self.assertEqual(data['type'], 'directory')

    def test_extensionless_file_is_not_a_directory(self):
        self.assertEqual(self.browse('/无扩展名').data['contents']['type'], 'file')

    def test_readme_cannot_be_opened_or_downloaded(self):
        for path in ['/readme.md', '/课程.2026/README.md']:
            with self.subTest(path=path):
                self.assertEqual(self.browse(path).status_code, 404)
                self.assertEqual(self.download(path).status_code, 404)

    def test_path_traversal_windows_drive_and_invalid_paths_are_rejected(self):
        for path in ['/../secret', '/课程.2026/../readme.md', '/C:/Windows',
                     '//server/share', '/课程.2026\\..\\readme.md', '/file:stream',
                     '/readme.md.', '/readme.md ', '/bad\x00name', 'relative']:
            with self.subTest(path=path):
                self.assertEqual(self.browse(path).status_code, 400)
                self.assertEqual(self.download(path).status_code, 400)

    def test_hidden_files_and_symlinks_are_not_exposed(self):
        (self.root / '.secret').write_text('secret')
        outside = Path(self.temp.name) / 'outside.txt'
        outside.write_text('private')
        try:
            (self.root / 'escape.txt').symlink_to(outside)
            (self.root / 'alias.txt').symlink_to(self.root / 'readme.md')
        except OSError:
            self.skipTest('Host does not permit creating symbolic links')
        names = [entry['name'] for entry in self.browse().data['contents']['entries']]
        for name in ['.secret', 'escape.txt', 'alias.txt']:
            self.assertNotIn(name, names)
            self.assertEqual(self.download('/' + name).status_code, 404)

    def test_directory_contents_are_live(self):
        self.browse()
        (self.root / '新资料.txt').write_text('new')
        self.assertIn('新资料.txt', [entry['name'] for entry in self.browse().data['contents']['entries']])

    def test_missing_root_returns_service_unavailable(self):
        with override_settings(RESOURCE_STORAGE_ROOT=self.root / 'missing'):
            self.assertEqual(self.browse().status_code, 503)

    def test_missing_path_returns_not_found(self):
        self.assertEqual(self.browse('/missing').status_code, 404)

    def test_download_has_utf8_filename_and_streams_original_bytes(self):
        response = self.download()
        self.assertEqual(response.status_code, 200)
        self.assertIn("filename*=utf-8''", response['Content-Disposition'])
        self.assertTrue(response['Content-Disposition'].startswith('attachment'))
        self.assertEqual(b''.join(response.streaming_content), b'0123456789')

    def test_range_downloads(self):
        for requested, expected, content_range in [
            ('bytes=2-5', b'2345', 'bytes 2-5/10'),
            ('bytes=8-', b'89', 'bytes 8-9/10'),
            ('bytes=-3', b'789', 'bytes 7-9/10'),
            ('bytes=0-999', b'0123456789', 'bytes 0-9/10'),
        ]:
            with self.subTest(range=requested):
                response = self.download(HTTP_RANGE=requested)
                self.assertEqual(response.status_code, 206)
                self.assertEqual(response['Content-Range'], content_range)
                self.assertEqual(b''.join(response.streaming_content), expected)
                self.assertEqual(int(response['Content-Length']), len(expected))

    def test_invalid_ranges(self):
        for requested in ['bytes=100-', 'bytes=-0', 'bytes=7-2', 'bytes=1-2,4-5', 'bad', 'bytes=-']:
            with self.subTest(range=requested):
                response = self.download(HTTP_RANGE=requested)
                self.assertEqual(response.status_code, 416)
                self.assertEqual(response['Content-Range'], 'bytes */10')

    def test_changed_if_range_falls_back_to_full_file(self):
        self.assertEqual(self.download(HTTP_RANGE='bytes=1-2', HTTP_IF_RANGE='"old"').status_code, 200)

    def test_preview_is_allowlisted(self):
        self.assertTrue(self.download(inline='1')['Content-Disposition'].startswith('inline'))
        (self.root / 'unsafe.html').write_text('<script>alert(1)</script>')
        response = self.download('/unsafe.html', inline='1')
        self.assertTrue(response['Content-Disposition'].startswith('attachment'))
        self.assertIn('sandbox', response['Content-Security-Policy'])

    def test_search_uses_local_index_hides_readme_and_rejects_inconsistent_entries(self):
        write_resource_directory_cache(['/', '/课程.2026'], entries=[
            {'name': 'readme.md', 'path': '/readme.md', 'type': 'file'},
            {'name': '试卷 #1%.pdf', 'path': '/课程.2026/试卷 #1%.pdf', 'type': 'file'},
            {'name': '试卷旧.pdf', 'path': '/missing.pdf', 'type': 'file'},
        ])
        pagination, results = search_resources('试卷', 1, 10)
        self.assertEqual(pagination['total_count'], 1)
        self.assertEqual(results[0]['path'], '/课程.2026')
        self.assertEqual(results[0]['url'], '/disk')
        self.assertEqual(search_resources('readme', 1, 10)[1], [])
