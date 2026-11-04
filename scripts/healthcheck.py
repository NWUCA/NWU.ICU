"""Probe the configured site without requiring a public DNS/TLS connection."""
import os
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

if __name__ == '__main__':
    origin = urlsplit(os.environ['FRONTEND_URL'])
    request = Request(
        'http://127.0.0.1:8000/api/user/csrf/',
        headers={
            'Host': origin.netloc,
            'X-Forwarded-Proto': origin.scheme,
        },
    )
    with urlopen(request, timeout=3) as response:
        if response.status != 200:
            raise SystemExit('Health check failed')
