from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.parse import quote, urlencode, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from common.file.resource_legacy import COLLEGE_ALIASES
from common.file.resource_seo import resource_page_url
from common.models import ResourceAccessRule


@override_settings(SECURE_SSL_REDIRECT=False)
class LegacyResourceTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.filename = '试卷 #1%23 &+答案(一).pdf'
        self.folder = '/【3】学院课程/【112】物理学院'
        self.path = self.folder + '/' + self.filename
        folder = self.root / self.folder.lstrip('/')
        folder.mkdir(parents=True)
        (folder / self.filename).write_bytes(b'0123456789')
        (folder / 'second.txt').write_bytes(b'second')
        (folder / 'readme.md').write_text('hidden')
        (folder / '.secret').write_text('hidden')
        self.override = override_settings(RESOURCE_STORAGE_ROOT=self.root)
        self.override.enable()
        self.addCleanup(self.override.disable)
        cache.clear()
        self.addCleanup(cache.clear)

    def redirect(self, path, query='', method='get'):
        return getattr(self.client, method)(
            '/api/resources/legacy-redirect/',
            HTTP_X_LEGACY_URI=quote(path, safe='/') + query,
        )

    def follow_file(self, path, kind='d', **headers):
        redirect = self.redirect('/' + kind + '/local' + path, '?sign=obsolete&access=invalid')
        self.assertEqual(redirect.status_code, 301)
        url = urlsplit(redirect['Location'])
        self.assertEqual(url.netloc, 'nwu.icu')
        response = self.client.get(url.path + '?' + url.query, **headers)
        self.addCleanup(self.close_response, response)
        return response

    @staticmethod
    def close_response(response):
        # TestCase's outer transaction must survive deferred streaming cleanup.
        with patch('django.http.response.signals.request_finished.send'):
            response.close()

    def test_all_aliases_map_complete_segments_with_one_redirect(self):
        for alias, current in COLLEGE_ALIASES.items():
            for suffix in ('', '/', '/' + self.filename):
                with self.subTest(alias=alias, suffix=suffix):
                    old = '/【3】学院课程/' + alias + suffix
                    new = '/【3】学院课程/' + current + suffix.rstrip('/')
                    response = self.redirect(old)
                    self.assertEqual(response.status_code, 301)
                    self.assertEqual(response['Location'], 'https://nwu.icu' + resource_page_url(new))
        old = '/【3】学院课程/物理学院/' + self.filename
        response = self.redirect(old)
        final = self.client.get(response['Location'])
        self.assertEqual(final.status_code, 200)
        self.assertContains(final, 'NWU.ICU')

    def test_canonical_names_and_unrelated_segments_are_preserved(self):
        for path in (self.path, '/其他目录/物理学院', '/【3】学院课程/物理学院资料', '/locality/file.zip'):
            response = self.redirect(path)
            self.assertEqual(response['Location'], 'https://nwu.icu' + resource_page_url(path))

    def test_mount_root_queries_head_and_crawler_use_same_destination(self):
        for path in ('/', '/local', '/local/'):
            self.assertEqual(self.redirect(path)['Location'], 'https://nwu.icu/disk')
        response = self.redirect('/local' + self.path, '?page=2&sign=old&%74oken=secret&x=a%26b', method='head')
        self.assertEqual(response['Location'], 'https://nwu.icu' + resource_page_url(self.path) + '?page=2&x=a%26b')
        self.assertEqual(response.content, b'')
        bot = self.client.get('/api/resources/legacy-redirect/', HTTP_X_LEGACY_URI=quote(self.path), HTTP_USER_AGENT='Googlebot')
        self.assertEqual(bot['Location'], self.redirect(self.path)['Location'])

    def test_download_and_preview_return_bytes_ranges_and_disposition(self):
        old = '/【3】学院课程/物理学院/' + self.filename
        download = self.follow_file(old)
        self.assertEqual(download.status_code, 200)
        self.assertTrue(download['Content-Disposition'].startswith('attachment;'))
        self.assertEqual(b''.join(download.streaming_content), b'0123456789')
        preview = self.follow_file(old, 'p', HTTP_RANGE='bytes=2-5')
        self.assertEqual(preview.status_code, 206)
        self.assertEqual(preview['Content-Range'], 'bytes 2-5/10')
        self.assertTrue(preview['Content-Disposition'].startswith('inline;'))
        self.assertEqual(b''.join(preview.streaming_content), b'2345')
        direct = self.redirect('/d' + old)
        mounted = self.redirect('/d/local' + old)
        self.assertEqual(direct['Location'], mounted['Location'])

    def test_historical_college_file_links_reach_bytes_in_one_hop(self):
        # Fixed migration contract, independent of the production JSON: removing
        # an alias must fail this regression instead of silently shrinking it.
        aliases = (
            ('经济管理学院', '【103】经济管理学院'),
            ('公共管理学院', '【104】公共管理学院'),
            ('新闻传播学院', '【106】新闻传播学院'),
            ('法学院', '【107】法学院'),
            ('地质学系', '【110】地质学系'),
            ('物理学院', '【112】物理学院'),
            ('物理学学院', '【112】物理学院'),
            ('生科院', '【113】生科院'),
            ('数学学院', '【114】数学学院'),
            ('化工学院', '【115】化工学院'),
            ('信息科学技术学院(软件学院)', '【117】信息科学技术学院(软件学院)'),
            ('文化遗产学院', '【119】文化遗产学院'),
        )
        for alias, canonical in aliases:
            path = '/【3】学院课程/' + canonical + '/' + self.filename
            fixture = self.root / path.lstrip('/')
            fixture.parent.mkdir(parents=True, exist_ok=True)
            fixture.write_bytes(b'0123456789')
            for kind in ('d', 'p'):
                for mount in ('', '/local'):
                    with self.subTest(alias=alias, kind=kind, mount=mount):
                        old = f'/{kind}{mount}/【3】学院课程/{alias}/{self.filename}'
                        response = self.redirect(old, '?sign=expired&access=expired')
                        params = {'path': path}
                        if kind == 'p':
                            params['inline'] = '1'
                        expected = 'https://nwu.icu/api/resources/file/legacy/?' + urlencode(params)
                        self.assertEqual(response.status_code, 301)
                        self.assertEqual(response['Location'], expected)
                        self.assertTrue(response['Location'].isascii())
                        # Do not follow implicitly: a second redirect is a failure.
                        final = self.client.get(expected, HTTP_RANGE='bytes=2-5', follow=False)
                        self.addCleanup(self.close_response, final)
                        self.assertEqual(final.status_code, 206)
                        self.assertEqual(final['Content-Range'], 'bytes 2-5/10')
                        self.assertEqual(b''.join(final.streaming_content), b'2345')
                        self.assertTrue(final['Content-Disposition'].startswith(
                            'inline;' if kind == 'p' else 'attachment;'))

    def test_pdf_with_recorded_legacy_302_reaches_pdf_without_intermediate_redirect(self):
        # The only /d/ or /p/ URL with 302 records in the annual audit. Do not
        # assert today's live server behavior; pin its final resource identity.
        path = '/【1】中国特色课程(毛概马原)/研究生思政课/中国马克思主义与当代-2021版.pdf'
        content = b'%PDF-1.7\nlegacy regression fixture\n'
        fixture = self.root / path.lstrip('/')
        fixture.parent.mkdir(parents=True)
        fixture.write_bytes(content)
        expected = 'https://nwu.icu/api/resources/file/legacy/?' + urlencode({'path': path, 'inline': '1'})
        for safe in ('/', '/()'):
            for secure in (False, True):
                with self.subTest(encoded_parentheses=safe == '/', secure=secure):
                    response = self.client.get(
                        '/api/resources/legacy-redirect/', secure=secure,
                        HTTP_X_LEGACY_URI=quote('/p/local' + path, safe=safe) + '?sign=obsolete',
                    )
                    self.assertEqual(response.status_code, 301)
                    self.assertEqual(response['Location'], expected)
                    final = self.client.get(expected, HTTP_RANGE='bytes=0-7', follow=False)
                    self.addCleanup(self.close_response, final)
                    self.assertEqual(final.status_code, 206)
                    self.assertEqual(final['Content-Type'], 'application/pdf')
                    self.assertEqual(b''.join(final.streaming_content), b'%PDF-1.7')
        head = self.client.head(expected, follow=False)
        self.addCleanup(self.close_response, head)
        self.assertEqual(head.status_code, 200)
        self.assertEqual(int(head['Content-Length']), len(content))
        self.assertEqual(b''.join(head.streaming_content), b'')

    def test_missing_hidden_readme_and_invalid_paths_never_serve_files(self):
        for path in ('/../secret', '//evil.test/path', '/dir\\file', '/file\x00', '/dir//file'):
            self.assertIn(self.redirect(path).status_code, (400, 404))
        # A literal percent-encoded-looking filename is not decoded twice.
        self.assertEqual(self.redirect('/%2e%2e/secret')['Location'], 'https://nwu.icu/disk/%252e%252e/secret')
        for name in ('readme.md', '.secret'):
            self.assertEqual(self.redirect('/p/local' + self.folder + '/' + name).status_code, 404)
        self.assertEqual(self.follow_file(self.folder + '/missing.pdf').status_code, 404)
        for route in ('/api/fs/list', '/assets/old.js', '/static/old.css'):
            self.assertEqual(self.redirect(route).status_code, 410)
        self.assertEqual(self.client.get('/api/resources/legacy-redirect/').status_code, 400)

    def test_acl_is_checked_after_alias_mapping_and_on_every_file_request(self):
        old = '/【3】学院课程/物理学院/' + self.filename
        ResourceAccessRule.objects.create(path=self.folder, mode='login')
        for kind in ('d', 'p'):
            self.assertIn(self.follow_file(old, kind).status_code, (401, 403))
        user = get_user_model().objects.create_user(username='legacy-reader', password='test-password')
        self.client.force_login(user)
        for kind in ('d', 'p'):
            self.assertEqual(self.follow_file(old, kind).status_code, 200)
        ResourceAccessRule.objects.filter(path=self.folder).update(mode='admin')
        for kind in ('d', 'p'):
            self.assertEqual(self.follow_file(old, kind).status_code, 404)

    def test_download_limit_is_enforced_without_trusting_old_signatures(self):
        config = deepcopy(settings.API_RATE_LIMITS)
        config['resource_download'].update(enabled=True, anonymous='1/hour', dedupe_ttl=300)
        with override_settings(API_RATE_LIMITS=config):
            self.assertEqual(self.follow_file(self.path).status_code, 200)
            self.assertEqual(self.follow_file(self.path, 'p', HTTP_RANGE='bytes=2-5').status_code, 206)
            blocked = self.follow_file(self.folder + '/second.txt')
            self.assertEqual(blocked.status_code, 429)
            self.assertEqual(blocked.json()['contents']['captcha_scope'], 'resource_download')
            # The normal endpoint still requires its actor-bound authorization ticket.
            normal = self.client.get('/api/resources/file/?' + urlencode({'path': self.path, 'sign': 'old'}))
            self.assertEqual(normal.status_code, 429)
