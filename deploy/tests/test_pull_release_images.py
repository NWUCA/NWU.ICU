"""Exercise the release pull script without contacting Docker or production."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / 'pull-release-images'
BACKEND = 'a' * 40
FRONTEND = 'b' * 40
BACKEND_IMAGE = 'ghcr.io/nwuca/nwu.icu@sha256:' + 'c' * 64
GATEWAY_IMAGE = 'ghcr.io/moowantfree/new_nwu_icu_frontend@sha256:' + 'd' * 64


class PullReleaseImagesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.calls = self.root / 'calls'
        docker = self.root / 'docker'
        docker.write_text(
            '''#!/usr/bin/env python3
import os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as log:
    log.write(' '.join(args) + '\\n')
backend = args[2].startswith('ghcr.io/nwuca/') if len(args) > 2 else False
failure = os.environ.get('FAILURE', '')
if args[0] == 'pull':
    print('pull progress')
    sys.exit(1 if failure == 'pull' else 0)
assert args[:2] == ['image', 'inspect'], args
fmt = args[-1]
if '.Os' in fmt:
    print('linux/arm64' if failure == 'platform' else 'linux/amd64')
elif '.RepoDigests' in fmt:
    if failure != 'no-digest':
        print(os.environ['GATEWAY_IMAGE'])
        if failure == 'multiple-digests':
            print('ghcr.io/moowantfree/new_nwu_icu_frontend@sha256:' + 'e'*64)
elif 'org.opencontainers.image.source' in fmt:
    print('https://github.com/' + ('NWUCA/NWU.ICU' if backend else 'MooWantFree/new_nwu_icu_frontend'))
elif 'org.opencontainers.image.revision' in fmt:
    revision = os.environ['BACKEND' if backend else 'FRONTEND']
    failed = failure == ('backend-revision' if backend else 'frontend-revision')
    print('wrong' if failed else revision)
elif 'io.nwuicu.backend-commit' in fmt:
    print('wrong' if failure == 'pair' else os.environ['BACKEND'])
elif 'io.nwuicu.backend-image' in fmt:
    image = os.environ['BACKEND_IMAGE']
    print('ghcr.io/other/image@sha256:' + 'c'*64 if failure == 'repository' else image)
else:
    raise AssertionError(fmt)
'''
        )
        docker.chmod(0o755)
        self.env = {
            **os.environ,
            'PATH': str(self.root) + ':' + os.environ['PATH'],
            'CALLS': str(self.calls),
            'BACKEND': BACKEND,
            'FRONTEND': FRONTEND,
            'BACKEND_IMAGE': BACKEND_IMAGE,
            'GATEWAY_IMAGE': GATEWAY_IMAGE,
        }

    def run_script(self, *args, failure=''):
        return subprocess.run(
            ['bash', str(SCRIPT), *args],
            env={**self.env, 'FAILURE': failure},
            capture_output=True,
            text=True,
        )

    def test_pulls_paired_digest_and_emits_manifest_only_after_verification(self):
        result = self.run_script(BACKEND, FRONTEND)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout,
            f'BACKEND_COMMIT={BACKEND}\nFRONTEND_COMMIT={FRONTEND}\n'
            f'BACKEND_IMAGE={BACKEND_IMAGE}\nGATEWAY_IMAGE={GATEWAY_IMAGE}\n',
        )
        calls = self.calls.read_text()
        self.assertIn(f'pull --platform linux/amd64 {BACKEND_IMAGE}', calls)
        self.assertNotIn(f'ghcr.io/nwuca/nwu.icu:sha-{BACKEND}', calls)
        self.assertNotIn('compose', calls)
        self.assertNotIn('build', calls)

    def test_accepts_explicit_gateway_digest(self):
        result = self.run_script(BACKEND, FRONTEND, GATEWAY_IMAGE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'pull --platform linux/amd64 {GATEWAY_IMAGE}', self.calls.read_text())

    def test_explicit_digest_ignores_other_local_manifest_aliases(self):
        result = self.run_script(BACKEND, FRONTEND, GATEWAY_IMAGE, failure='multiple-digests')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'GATEWAY_IMAGE={GATEWAY_IMAGE}', result.stdout)

    def test_rejects_invalid_input_before_contacting_docker(self):
        for args in [
            [],
            [BACKEND],
            ['master', FRONTEND],
            [BACKEND, FRONTEND, 'ghcr.io/other/image@sha256:' + 'd' * 64],
        ]:
            with self.subTest(args=args):
                self.assertNotEqual(self.run_script(*args).returncode, 0)
                self.assertFalse(self.calls.exists())

    def test_failures_never_emit_a_partial_manifest(self):
        for failure in [
            'pull',
            'platform',
            'no-digest',
            'frontend-revision',
            'backend-revision',
            'pair',
            'repository',
            'multiple-digests',
        ]:
            with self.subTest(failure=failure):
                result = self.run_script(BACKEND, FRONTEND, failure=failure)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
