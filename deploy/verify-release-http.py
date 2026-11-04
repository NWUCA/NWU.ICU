#!/usr/bin/env python3
"""Read-only HTTP smoke checks; redirects and HTML masquerading as assets fail."""

import argparse
import json
import sys
from html.parser import HTMLParser
from urllib.error import HTTPError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Assets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('src'):
            self.assets.add((attrs['src'], 'js'))
        if tag == 'link' and 'stylesheet' in attrs.get('rel', '').split() and attrs.get('href'):
            self.assets.add((attrs['href'], 'css'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Checks:
    def __init__(self, host=None):
        self.opener = build_opener(NoRedirect())
        self.headers = {'User-Agent': 'nwuicu-release-check', 'Cache-Control': 'no-cache'}
        if host:
            self.headers.update({'Host': host, 'X-Forwarded-Proto': 'https'})

    def get(self, url, expected=200):
        request = Request(url, headers=self.headers)
        try:
            response = self.opener.open(request, timeout=15)
        except HTTPError as error:
            response = error
        with response:
            require(response.code == expected, f'Expected HTTP {expected}, got {response.code}')
            body = response.read(16 * 1024 * 1024 + 1)
            require(len(body) <= 16 * 1024 * 1024, 'Unexpectedly large smoke response')
            return response.headers.get_content_type(), body

    def json(self, url):
        content_type, body = self.get(url)
        require(content_type == 'application/json', 'Expected JSON content type')
        payload = json.loads(body)
        require(isinstance(payload, dict) and payload.get('errors') == [], 'Invalid API envelope')
        require('contents' in payload, 'Missing API contents')
        return payload['contents']

    def site(self, base):
        content_type, body = self.get(base + '/')
        require(content_type == 'text/html', 'Expected homepage HTML')
        parser = Assets()
        parser.feed(body.decode('utf-8'))
        require({'js', 'css'} <= {kind for _, kind in parser.assets}, 'Missing homepage JS/CSS')
        for path, kind in sorted(parser.assets):
            url = urljoin(base + '/', path)
            require(urlsplit(url).netloc == urlsplit(base).netloc, 'Unexpected external asset')
            asset_type, asset_body = self.get(url)
            allowed = {'text/css'} if kind == 'css' else {'text/javascript', 'application/javascript'}
            require(asset_type in allowed and asset_body.strip(), f'Invalid {kind} asset')
            require(
                not asset_body.lstrip().lower().startswith((b'<!doctype html', b'<html')),
                'HTML asset fallback',
            )
        for path in ('/review/timeline', '/manage', '/disk'):
            content_type, body = self.get(base + path)
            require(content_type == 'text/html' and body.strip(), f'Invalid HTML route: {path}')
        self.get(base + '/media/release-check', expected=404)
        schools = self.json(base + '/api/assessment/school/')
        require(
            isinstance(schools, dict) and isinstance(schools.get('schools'), list),
            'Invalid schools response',
        )
        require(bool(schools['schools']), 'Production schools list is empty')

    def csrf(self, base):
        contents = self.json(base + '/api/user/csrf/')
        require(
            isinstance(contents, dict)
            and isinstance(contents.get('csrf_token'), str)
            and bool(contents['csrf_token']),
            'Missing CSRF token',
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', default='https://nwu.icu')
    parser.add_argument('--api', default='https://api.nwu.icu')
    parser.add_argument('--host', help='Host header for loopback checks during maintenance')
    args = parser.parse_args()
    try:
        check = Checks(args.host)
        check.site(args.site.rstrip('/'))
        check.csrf(args.site.rstrip('/'))
        check.csrf(args.api.rstrip('/'))
    except ValueError as error:
        print(f'HTTP release checks failed: {error}', file=sys.stderr)
        return 1
    except Exception as error:
        # Do not print response bodies, cookies, tokens or query strings.
        print(f'HTTP release checks failed ({type(error).__name__}).', file=sys.stderr)
        return 1
    print('HTTP status, JSON, homepage JS/CSS and read-only routes passed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
