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
    custom = mode == 'custom-project' and args[-1].endswith('campus-example')
    print('stopped-container' if mode == 'project' or custom else '')
elif args[:2] == ['ps', '-a']:
    print('pgsql' if mode == 'pgsql' else '')
elif args[:2] == ['volume', 'ls']:
    print('nwuicu_archive-cache' if mode == 'volume' else '')
elif mode == 'fresh' and args[0] in ('network', 'compose'):
    pass
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

    def test_configured_project_is_checked_before_installing(self):
        env_path = self.root / 'custom.env'
        env_path.write_text('COMPOSE_PROJECT_NAME=campus-example\n')
        result = subprocess.run(
            ['bash', str(SCRIPT), '--fresh-install', str(env_path)],
            env={**self.env, 'MODE': 'custom-project'},
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Existing NWU.ICU containers or persistent volumes', result.stderr)
        self.assertIn('com.docker.compose.project=campus-example', self.calls.read_text())

    @unittest.skipUnless(os.geteuid() == 0, 'The first-install flow requires root')
    def test_custom_project_is_used_for_startup_and_all_post_install_checks(self):
        # All Docker and directory-ownership operations stay inside these stubs.
        install = self.root / 'install'
        install.write_text('#!/bin/sh\nexit 0\n')
        install.chmod(0o755)
        template = SCRIPT.parents[1] / '.env.production.example'
        env_path = self.root / 'fresh.env'
        env_path.write_text(
            template.read_text().replace('CHANGE_ME', 'test-only')
            + '\nCOMPOSE_PROJECT_NAME=campus-example\n'
            + f'DEPLOY_ROOT={self.root}\n'
            + f'RESOURCE_STORAGE_HOST_PATH={self.root}\n'
            + f'MEDIA_STORAGE_HOST_PATH={self.root}/media\n'
            + f'STATIC_STORAGE_HOST_PATH={self.root}/static\n'
            + f'RESOURCE_INDEX_HOST_PATH={self.root}/index\n'
        )
        result = subprocess.run(
            ['bash', str(SCRIPT), '--fresh-install', str(env_path)],
            env={**self.env, 'MODE': 'fresh'},
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        calls = [line.split() for line in self.calls.read_text().splitlines()]
        compose_calls = [args for args in calls if args[0] == 'compose']
        self.assertEqual(len(compose_calls), 4)
        for args in compose_calls:
            self.assertEqual(args[args.index('-p') + 1], 'campus-example')
        self.assertIn('up', compose_calls[0])
        self.assertIn('web', compose_calls[1])
        self.assertIn('resource-worker', compose_calls[2])
        self.assertEqual(compose_calls[3][-1], 'ps')

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
