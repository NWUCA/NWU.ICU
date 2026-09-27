"""Run real backup shell workflows with isolated fake external commands."""
import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


DEPLOY = Path(__file__).resolve().parents[1]
STAMP = '20300101_040000'


class BackupScriptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.env = {**os.environ, 'PATH': str(self.bin) + ':' + os.environ['PATH'], 'CALLS': str(self.root/'calls')}
        self.command('date', f"import sys\nprint('{STAMP}' if sys.argv[1:] == ['+%Y%m%d_%H%M%S'] else '2030-01-01T04:00:00+08:00')")

    def command(self, name, body):
        script = self.bin/name
        script.write_text('#!/usr/bin/env python3\n' + body + '\n')
        script.chmod(0o755)

    def producer(self, failure=''):
        self.env['FAILURE'] = failure
        self.command('docker', '''import os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as log:
    log.write(' '.join(args) + '\\n')
if 'printenv' in args:
    print('business' if args[-1] == 'POSTGRES_DB' else 'backup-user')
elif 'pg_dump' in args:
    assert all(flag in args for flag in ('-Fc', '--no-owner', '--no-privileges'))
    database = args[args.index('-d')+1]
    print('archive:' + database)
    if os.environ['FAILURE'] == 'dump:' + database:
        sys.exit(2)
elif 'pg_restore' in args:
    archive = sys.stdin.read().strip()
    assert archive.startswith('archive:')
    if '--file=/dev/null' in args:
        if os.environ['FAILURE'] == 'read:' + archive.split(':')[1]:
            sys.exit(2)
    elif '--list' in args:
        print('TOC ' + archive)
    else:
        raise AssertionError(args)
else:
    raise AssertionError(args)
''')
        text = (DEPLOY/'nwuicu-db-backup').read_text()
        text = text.replace('/root/nwuicuBack/daily', str(self.root/'daily'))
        text = text.replace('/run/lock/nwuicu-db-backup.lock', str(self.root/'backup.lock'))
        script = self.root/'backup.sh'
        script.write_text(text)
        return subprocess.run(['bash', str(script)], env=self.env, capture_output=True, text=True)

    def test_both_databases_are_verified_and_published_together(self):
        run = self.producer()
        self.assertEqual(run.returncode, 0, run.stderr)
        folder = self.root/'daily'/STAMP
        self.assertEqual(len(list(folder.glob('*.dump'))), 2)
        self.assertEqual(len(list(folder.glob('*.list'))), 2)
        self.assertIn('backup_format_version=2', (folder/'metadata.txt').read_text())
        self.assertEqual(len((folder/'SHA256SUMS').read_text().splitlines()), 5)
        self.assertEqual(subprocess.run(['sha256sum', '-c', 'SHA256SUMS'], cwd=folder, capture_output=True).returncode, 0)
        calls = (self.root/'calls').read_text()
        self.assertEqual(calls.count('pg_restore --file=/dev/null'), 2)
        self.assertEqual(folder.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(file.stat().st_mode & 0o077 == 0 for file in folder.iterdir()))

    def test_failure_never_publishes_a_partial_backup_or_changes_previous_backup(self):
        for failure in ('dump:business', 'dump:umami', 'read:business', 'read:umami'):
            with self.subTest(failure=failure):
                # Each simulated run uses a separate output path, just like daily timestamps.
                original_root = self.root
                self.root = original_root/failure.replace(':','-')
                self.root.mkdir()
                old = self.root/'daily'/'20291231_040000'
                old.mkdir(parents=True)
                (old/'keep').write_text('previous backup')
                run = self.producer(failure)
                self.assertNotEqual(run.returncode, 0)
                self.assertFalse((self.root/'daily'/STAMP).exists())
                self.assertTrue((self.root/'daily'/('.incomplete_'+STAMP)).is_dir())
                self.assertEqual((old/'keep').read_text(), 'previous backup')
                self.root = original_root

    def make_archive(self, version):
        remote = self.root/'remote'
        remote.mkdir()
        files = []
        for prefix in (('nwuicu',) if version == 1 else ('nwuicu','umami')):
            for suffix in ('dump','list'):
                name = f'{prefix}_full_{STAMP}.{suffix}'
                (remote/name).write_text(prefix+' '+suffix)
                files.append(name)
        (remote/'metadata.txt').write_text('database=business\n' + ('backup_format_version=2\numami_database=umami\n' if version==2 else ''))
        self.manifest(remote, files+['metadata.txt'])
        return remote

    def manifest(self, directory, files):
        (directory/'SHA256SUMS').write_text(''.join(hashlib.sha256((directory/name).read_bytes()).hexdigest()+'  '+name+'\n' for name in files))

    def download(self, remote):
        self.env['REMOTE_FIXTURE'] = str(remote)
        self.command('ssh', f"print('{STAMP}')")
        self.command('scp', '''import os, shutil, sys
from pathlib import Path
for file in Path(os.environ['REMOTE_FIXTURE']).iterdir():
    shutil.copy2(file, Path(sys.argv[-1])/file.name)
''')
        text = (DEPLOY/'nas-download-latest-db-backup').read_text().replace('/opt/nwuicu-db-backups',str(self.root/'nas'))
        script = self.root/'download.sh'
        script.write_text(text)
        return subprocess.run(['bash',str(script)],env=self.env,capture_output=True,text=True)

    def test_nas_accepts_legacy_backup_and_already_present_backup(self):
        remote = self.make_archive(1)
        self.assertEqual(self.download(remote).returncode,0)
        again = self.download(remote)
        self.assertEqual(again.returncode,0,again.stderr)
        self.assertIn('already present',again.stdout)

    def test_nas_accepts_dual_backup_and_already_present_backup(self):
        remote = self.make_archive(2)
        run = self.download(remote)
        self.assertEqual(run.returncode,0,run.stderr)
        self.assertEqual(len(list((self.root/'nas'/'backups'/STAMP).glob('*.dump'))),2)
        self.assertEqual(self.download(remote).returncode,0)

    def test_nas_rejects_missing_umami_even_when_manifest_matches_remaining_files(self):
        remote=self.make_archive(2)
        (remote/f'umami_full_{STAMP}.dump').unlink()
        self.manifest(remote,[p.name for p in remote.iterdir() if p.name!='SHA256SUMS'])
        self.assertNotEqual(self.download(remote).returncode,0)
        self.assertFalse((self.root/'nas'/'backups'/STAMP).exists())

    def test_nas_rejects_corrupt_umami_without_publishing(self):
        remote=self.make_archive(2)
        (remote/f'umami_full_{STAMP}.dump').write_text('corrupted')
        self.assertNotEqual(self.download(remote).returncode,0)
        self.assertFalse((self.root/'nas'/'backups'/STAMP).exists())

    def test_nas_requires_manifest_to_cover_umami(self):
        remote=self.make_archive(2)
        self.manifest(remote,[f'nwuicu_full_{STAMP}.dump',f'nwuicu_full_{STAMP}.list','metadata.txt'])
        self.assertNotEqual(self.download(remote).returncode,0)

    def test_nas_rejects_unknown_metadata_version(self):
        remote=self.make_archive(2)
        (remote/'metadata.txt').write_text('backup_format_version=3\n')
        self.assertNotEqual(self.download(remote).returncode,0)
