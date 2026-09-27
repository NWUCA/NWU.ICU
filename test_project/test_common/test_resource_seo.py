import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from xml.etree import ElementTree

from bs4 import BeautifulSoup
from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from common.file.resource_directories import write_resource_directory_cache
from common.file.resource_seo import resource_page_url
from common.models import ResourceAccessRule
from scripts.export_resource_tree import build_resource_tree


@override_settings(SECURE_SSL_REDIRECT=False)
class ResourceSEOTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'resources'
        self.root.mkdir()
        self.folder = self.root / '课程(一)'
        self.folder.mkdir()
        self.filename = '试卷 #1% &答案.zip'
        (self.folder / self.filename).write_bytes(b'example')
        (self.folder / 'readme.md').write_text('说明 </script><script>alert(1)</script>', encoding='utf-8')
        (self.root / '.secret').write_text('hidden')
        self.settings_override = override_settings(
            RESOURCE_STORAGE_ROOT=self.root,
            RESOURCE_DIRECTORY_CACHE_FILE=Path(self.temp.name) / 'index.json',
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.reindex()

    def reindex(self):
        tree = build_resource_tree(self.root)
        write_resource_directory_cache(tree['paths'], entries=tree['entries'])

    def test_resource_document_has_public_content_without_javascript(self):
        path = '/课程(一)/' + self.filename
        response = self.client.get(resource_page_url(path))
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        document = BeautifulSoup(response.content, 'html.parser')
        self.assertEqual(document.title.text, f'{self.filename} - 课程(一) - NWU.ICU')
        self.assertEqual(document.h1.text, self.filename)
        self.assertEqual(document.find('link', rel='canonical')['href'], 'https://nwu.icu' + resource_page_url(path))
        self.assertIsNone(document.find('meta', attrs={'name': 'robots'}))
        self.assertEqual(len(document.find_all('script')), 2)
        bootstrap = json.loads(document.find(id='resource-bootstrap').string)
        self.assertEqual(bootstrap['path'], path)
        self.assertIn('<script>', bootstrap['readme'])
        api = self.client.get('/api/resources/browse/', {'path': path})
        self.assertEqual(bootstrap, api.json()['contents'])

    def test_directory_links_are_encoded_and_hidden_entries_are_absent(self):
        response = self.client.get(resource_page_url('/课程(一)'))
        document = BeautifulSoup(response.content, 'html.parser')
        links = [link['href'] for link in document.select('section[aria-label="文件列表"] a')]
        self.assertEqual(links, [resource_page_url('/课程(一)/' + self.filename)])
        self.assertNotIn('readme.md', response.content.decode())
        root = self.client.get('/disk')
        self.assertNotIn('.secret', root.content.decode())

    def test_trailing_slash_redirects_directly_and_missing_resources_return_404(self):
        self.assertRedirects(self.client.get('/disk/'), '/disk', status_code=301)
        self.assertRedirects(self.client.get(resource_page_url('/课程(一)') + '/'), resource_page_url('/课程(一)'), status_code=301)
        for url in ('/disk/not-found', '/disk/.secret', '/disk/课程(一)/readme.md', '/disk/../secret'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 404)
            self.assertEqual(response['X-Robots-Tag'], 'noindex, follow')
            self.assertNotIn('id="resource-bootstrap"', response.content.decode())

    def test_permissions_apply_to_html_and_sitemap_even_for_logged_in_requests(self):
        ResourceAccessRule.objects.create(path='/课程(一)', mode='login')
        path = '/课程(一)/' + self.filename
        denied = self.client.get(resource_page_url(path))
        self.assertEqual(denied.status_code, 401)
        self.assertNotIn(self.filename, denied.content.decode())
        user = get_user_model().objects.create_user(username='seo-reader', password='test-password')
        self.client.force_login(user)
        allowed = self.client.get(resource_page_url(path))
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed['X-Robots-Tag'], 'noindex, follow')
        sitemap = self.client.get('/sitemap.xml?page=1')
        self.assertNotIn(resource_page_url(path), sitemap.content.decode())
        ResourceAccessRule.objects.filter(path='/课程(一)').update(mode='admin')
        self.assertEqual(self.client.get(resource_page_url(path)).status_code, 404)

    def test_sitemap_uses_current_index_and_live_acl_without_scanning_tree(self):
        with patch('common.file.resource_seo.SITEMAP_PAGE_SIZE', 2):
            index = self.client.get('/sitemap.xml')
            self.assertEqual(index.status_code, 200)
            root = ElementTree.fromstring(index.content)
            self.assertEqual(len(root), 2)
            page = self.client.get('/sitemap.xml?page=1')
            self.assertEqual(len(ElementTree.fromstring(page.content)), 2)
            self.assertEqual(self.client.get('/sitemap.xml?page=3').status_code, 404)
        (self.folder / self.filename).unlink()
        self.reindex()
        page = self.client.get('/sitemap.xml?page=1').content.decode()
        self.assertNotIn(resource_page_url('/课程(一)/' + self.filename), page)
        ResourceAccessRule.objects.create(path='/课程(一)', mode='admin')
        page = self.client.get('/sitemap.xml?page=1').content.decode()
        self.assertNotIn(resource_page_url('/课程(一)'), page)
        self.assertNotIn('readme.md', page)
        self.assertNotIn('.secret', page)

    def test_discovery_types_and_storage_failures(self):
        robots = self.client.get('/robots.txt')
        self.assertEqual(robots['Content-Type'], 'text/plain; charset=utf-8')
        self.assertContains(robots, 'Sitemap: https://nwu.icu/sitemap.xml')
        self.assertEqual(self.client.get('/sitemap.xml')['Content-Type'], 'application/xml; charset=utf-8')
        with override_settings(RESOURCE_STORAGE_ROOT=self.root / 'missing'):
            unavailable = self.client.get('/disk')
            self.assertEqual(unavailable.status_code, 503)
            self.assertEqual(unavailable['Retry-After'], '300')
            self.assertNotIn('X-Robots-Tag', unavailable)
            self.assertIsNone(BeautifulSoup(unavailable.content, 'html.parser').find('meta', attrs={'name': 'robots'}))
            self.assertEqual(self.client.get('/sitemap.xml').status_code, 503)
        (Path(self.temp.name) / 'index.json').unlink()
        self.assertEqual(self.client.get('/sitemap.xml').status_code, 503)

    def test_download_gate_does_not_publish_an_unauthorized_download_link(self):
        with patch('common.file.resource_browser.download_gate_enabled', return_value=True):
            response = self.client.get(resource_page_url('/课程(一)/' + self.filename))
        document = BeautifulSoup(response.content, 'html.parser')
        self.assertFalse(document.select('a[href^="/api/resources/file/"]'))
