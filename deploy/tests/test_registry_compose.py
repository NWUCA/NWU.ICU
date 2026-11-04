"""Validate the real Compose merge without starting any containers."""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND_IMAGE = 'ghcr.io/nwuca/nwu.icu@sha256:' + 'a' * 64
GATEWAY_IMAGE = 'ghcr.io/moowantfree/new_nwu_icu_frontend@sha256:' + 'b' * 64


@unittest.skipUnless(shutil.which('docker'), 'Docker Compose CLI is required for config validation')
class RegistryComposeTests(unittest.TestCase):
    def test_registry_override_removes_build_and_preserves_persistent_services(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / 'compose.env'
            env_file.write_text(
                'DB_NAME=test\nDB_USER=test\nDB_PASSWORD=not-a-production-secret\n'
                'MEDIA_STORAGE_HOST_PATH=/tmp/nwuicu-config/media\n'
                'STATIC_STORAGE_HOST_PATH=/tmp/nwuicu-config/static\n'
                'RESOURCE_INDEX_HOST_PATH=/tmp/nwuicu-config/index\n'
                'RESOURCE_STORAGE_HOST_PATH=/tmp/nwuicu-config/resources\n'
            )
            env = {
                **os.environ,
                'ENV_FILE': str(env_file),
                'BACKEND_IMAGE': BACKEND_IMAGE,
                'GATEWAY_IMAGE': GATEWAY_IMAGE,
            }
            command = [
                'docker',
                'compose',
                '--env-file',
                str(env_file),
                '-f',
                str(ROOT / 'docker-compose.production.yaml'),
            ]
            base = self.config(command, env)
            merged = self.config(
                command + ['-f', str(ROOT / 'deploy/docker-compose.server.registry.example.yaml')],
                env,
            )
        self.assertEqual(merged['name'], 'nwuicu')
        services = merged['services']
        for name in ['web', 'cron', 'resource-worker', 'archive-worker', 'archive-cleaner', 'gateway']:
            with self.subTest(service=name):
                self.assertNotIn('build', services[name])
                self.assertEqual(services[name]['pull_policy'], 'never')
                self.assertEqual(
                    services[name]['image'],
                    GATEWAY_IMAGE if name == 'gateway' else BACKEND_IMAGE,
                )
                self.assertEqual(services[name]['volumes'], base['services'][name]['volumes'])
                self.assertEqual(services[name]['networks'], base['services'][name]['networks'])
        self.assertEqual(services['db'], base['services']['db'])
        self.assertEqual(merged['volumes']['pgdata'], {'name': 'nwuicu_pgdata', 'external': True})
        self.assertEqual(merged['volumes']['archive-cache'], base['volumes']['archive-cache'])
        for name, port in [('web', '8000'), ('gateway', '18080')]:
            self.assertEqual(services[name]['ports'][0]['host_ip'], '127.0.0.1')
            self.assertEqual(services[name]['ports'][0]['published'], port)
        self.assertIn('exec gunicorn', services['web']['command'][2])
        self.assertNotIn('migrate', services['web']['command'][2])

    def test_custom_project_network_uid_and_volume_are_read_from_configuration(self):
        env_file = ROOT / '.env.production.example'
        env = {
            **os.environ,
            'ENV_FILE': str(env_file),
            'COMPOSE_PROJECT_NAME': 'campus-example',
            'PROXY_NETWORK_NAME': 'campus-proxy',
            'GATEWAY_NETWORK_ALIAS': 'campus-gateway',
            'UPLOAD_UID': '12001',
            'UPLOAD_GID': '12002',
            'POSTGRES_VOLUME_NAME': 'campus-existing-db',
            'BACKEND_PORT': '19000',
            'GATEWAY_PORT': '19080',
            'BACKEND_IMAGE': BACKEND_IMAGE,
            'GATEWAY_IMAGE': GATEWAY_IMAGE,
        }
        command = [
            'docker',
            'compose',
            '--env-file',
            str(env_file),
            '-f',
            str(ROOT / 'docker-compose.production.yaml'),
        ]
        base = self.config(command, env)
        self.assertEqual(base['name'], 'campus-example')
        self.assertEqual(base['networks']['proxy-network']['name'], 'campus-proxy')
        self.assertIn(
            'campus-gateway', base['services']['gateway']['networks']['proxy-network']['aliases']
        )
        self.assertEqual(base['services']['web']['build']['args']['UPLOAD_UID'], '12001')
        self.assertEqual(base['services']['web']['build']['args']['UPLOAD_GID'], '12002')
        self.assertEqual(
            base['services']['web']['healthcheck']['test'], ['CMD', 'python', 'scripts/healthcheck.py']
        )
        merged = self.config(
            command + ['-f', str(ROOT / 'deploy/docker-compose.server.registry.example.yaml')], env
        )
        self.assertEqual(merged['volumes']['pgdata']['name'], 'campus-existing-db')
        self.assertEqual(merged['services']['web']['ports'][0]['published'], '19000')
        self.assertEqual(merged['services']['gateway']['ports'][0]['published'], '19080')

    def config(self, command, env):
        result = subprocess.run(
            command + ['config', '--format', 'json'], env=env, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)


if __name__ == '__main__':
    unittest.main()
