"""Check the legacy installer refuses existing state before any mutations."""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'deploy-production.sh'


class FirstInstallGuardTests(unittest.TestCase):
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
mode = os.environ.get('MODE', '')
if mode == 'unavailable':
    sys.exit(1)
if args[:2] == ['ps', '-aq']:
    print('stopped-container' if mode == 'project' else '')
elif args[:2] == ['ps', '-a']:
    print('pgsql' if mode == 'pgsql' else '')
elif args[:2] == ['volume', 'ls']:
    print('nwuicu_archive-cache' if mode == 'volume' else '')
else:
    raise AssertionError('Unexpected mutation: ' + repr(args))
'''
        )
        docker.chmod(0o755)
        self.env = {
            **os.environ,
            'PATH': str(self.root) + ':' + os.environ['PATH'],
            'CALLS': str(self.calls),
        }

    def test_explicit_install_flag_is_required(self):
        result = subprocess.run(['bash', str(SCRIPT)], env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.calls.exists())

    def test_existing_or_unreadable_state_cannot_create_env_or_run_compose(self):
        for mode in ('project', 'pgsql', 'volume', 'unavailable'):
            with self.subTest(mode=mode):
                env_path = self.root / f'{mode}.env'
                result = subprocess.run(
                    ['bash', str(SCRIPT), '--fresh-install', str(env_path)],
                    env={**self.env, 'MODE': mode},
                    capture_output=True,
                    text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                if mode != 'unavailable':
                    self.assertIn('Existing NWU.ICU containers or persistent volumes', result.stderr)
                self.assertFalse(env_path.exists())
        calls = self.calls.read_text().replace('com.docker.compose.project', 'label')
        self.assertNotIn('compose', calls)
