from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import TestCase, override_settings
from rest_framework.test import APIRequestFactory

from common.file.resource_browser import ResourceBrowseView, ResourceFileView, search_resources
from common.file.resource_directories import write_resource_directory_cache


class ResourceBrowserTests(TestCase):
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

    def test_search_uses_local_index_hides_readme_and_removes_stale_results(self):
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
