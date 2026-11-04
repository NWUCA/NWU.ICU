import json

from bs4 import BeautifulSoup
from django.test import SimpleTestCase, override_settings


@override_settings(
    SECURE_SSL_REDIRECT=False,
    WEBSITE_NAME='校园 A',
    SITE_ORIGIN='https://campus.example.org',
    UNIVERSITY_SHORT_NAME='示例大学',
    UNIVERSITY_TEACHER_MAIL_SUFFIX='staff.example.org',
    UNIVERSITY_STUDENT_MAIL_SUFFIX='student.example.org',
    SITE_NAVIGATION_LINKS=[{'label': '门户', 'url': 'https://portal.example.org'}],
    SECRET_KEY='must-never-be-public',
)
class SiteConfigTests(SimpleTestCase):
    @override_settings(WEBSITE_NAME='Campus </script><script>alert(1)</script> & <')
    def test_document_bootstrap_contains_only_escaped_public_configuration(self):
        response = self.client.get('/api/site-config/bootstrap/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        document = BeautifulSoup(response.content, 'html.parser')
        scripts = document.find_all('script')
        self.assertEqual(len(scripts), 1)
        self.assertEqual(scripts[0]['id'], 'site-config-bootstrap')
        self.assertEqual(scripts[0]['type'], 'application/json')
        self.assertEqual(json.loads(scripts[0].string), self.client.get('/api/site-config/').json())
        self.assertNotIn(b'must-never-be-public', response.content)
        self.assertNotIn(b'<script>alert(1)', response.content)
        self.assertEqual(self.client.head('/api/site-config/bootstrap/').status_code, 200)

    def test_healthcheck_uses_configured_host_and_scheme(self):
        import os
        import runpy
        from unittest.mock import patch

        with patch.dict(os.environ, {'FRONTEND_URL': 'https://campus.example.org'}):
            with patch('urllib.request.urlopen') as urlopen:
                urlopen.return_value.__enter__.return_value.status = 200
                runpy.run_path('scripts/healthcheck.py', run_name='__main__')
                request = urlopen.call_args.args[0]
                self.assertEqual(request.full_url, 'http://127.0.0.1:8000/api/user/csrf/')
                self.assertEqual(request.get_header('Host'), 'campus.example.org')
                self.assertEqual(request.get_header('X-forwarded-proto'), 'https')

    def test_public_config_is_an_explicit_allowlist(self):
        response = self.client.get('/api/site-config/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        config = response.json()
        self.assertEqual(config['site_name'], '校园 A')
        self.assertEqual(config['site_origin'], 'https://campus.example.org')
        self.assertEqual(config['college_email_domains'], ['staff.example.org', 'student.example.org'])
        self.assertEqual(config['navigation_links'][0]['url'], 'https://portal.example.org')
        self.assertEqual(
            set(config),
            {
                'site_name',
                'site_origin',
                'university_name',
                'university_short_name',
                'college_email_domains',
                'registration_blocked_email_domains',
                'navigation_links',
                'analytics',
                'sentry_dsn',
                'footer_start_year',
                'frontend_repository_url',
                'backend_repository_url',
            },
        )
        self.assertNotIn(b'must-never-be-public', response.content)

    def test_resource_metadata_and_robots_use_configured_origin(self):
        from common.file.resource_seo import resource_metadata

        metadata = resource_metadata({'path': '/', 'name': '', 'type': 'directory'})
        self.assertEqual(metadata['canonical'], 'https://campus.example.org/disk')
        self.assertEqual(metadata['title'], '资料下载 - 校园 A')
        self.assertIn('校园 A', metadata['description'])
        self.assertContains(self.client.get('/robots.txt'), 'https://campus.example.org/sitemap.xml')
