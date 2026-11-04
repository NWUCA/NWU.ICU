"""Exercise the HTTP verifier against a local server, never production."""

import json
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'verify-release-http.py'


class ReleaseHTTPTests(unittest.TestCase):
    def setUp(self):
        html = (
            '<html><script src="/assets/app.js"></script>'
            '<link rel="stylesheet" href="/assets/app.css"></html>'
        )
        self.routes = {
            '/': (200, 'text/html', html),
            '/assets/app.js': (200, 'text/javascript', 'console.log("ok")'),
            '/assets/app.css': (200, 'text/css', 'body {color: black}'),
            '/review/timeline': (200, 'text/html', '<html>timeline</html>'),
            '/manage': (200, 'text/html', '<html>manage</html>'),
            '/disk': (200, 'text/html', '<html>resources</html>'),
            '/disk/': (301, 'text/html', 'canonical redirect'),
            '/media/release-check': (404, 'text/html', 'not found'),
            '/api/assessment/school/': (
                200,
                'application/json',
                json.dumps({'errors': [], 'contents': {'schools': [{'id': 1, 'name': 'School'}]}}),
            ),
            '/api/user/csrf/': (
                200,
                'application/json',
                json.dumps({'errors': [], 'contents': {'csrf_token': 'test-token'}}),
            ),
        }
        routes = self.routes

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                status, content_type, body = routes.get(self.path, (404, 'text/plain', 'missing'))
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                if status == 302:
                    self.send_header('Location', '/manage')
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def run_check(self):
        base = f'http://127.0.0.1:{self.server.server_port}'
        return subprocess.run(
            [sys.executable, str(SCRIPT), '--site', base, '--api', base],
            capture_output=True,
            text=True,
            timeout=20,
        )

    def test_real_html_assets_and_api_pass(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn('test-token', result.stdout)

    def test_redirect_is_not_accepted_as_success(self):
        self.routes['/'] = (302, 'text/html', 'redirect')
        self.assertNotEqual(self.run_check().returncode, 0)

    def test_missing_or_html_asset_fails(self):
        for response in (
            (404, 'text/plain', 'missing'),
            (200, 'text/html', '<html>SPA</html>'),
            (200, 'text/javascript', '<html>SPA</html>'),
        ):
            with self.subTest(response=response):
                self.routes['/assets/app.js'] = response
                self.assertNotEqual(self.run_check().returncode, 0)

    def test_api_error_or_missing_token_fails_without_leaking_body(self):
        for contents in ({}, {'csrf_token': ''}):
            self.routes['/api/user/csrf/'] = (
                200,
                'application/json',
                json.dumps({'errors': [], 'contents': contents, 'secret': 'must-not-print'}),
            )
            result = self.run_check()
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('must-not-print', result.stdout + result.stderr)

    def test_empty_business_data_fails(self):
        self.routes['/api/assessment/school/'] = (
            200,
            'application/json',
            json.dumps({'errors': [], 'contents': {'schools': []}}),
        )
        self.assertNotEqual(self.run_check().returncode, 0)

    def test_public_media_is_rejected(self):
        self.routes['/media/release-check'] = (200, 'text/html', 'public')
        self.assertNotEqual(self.run_check().returncode, 0)
