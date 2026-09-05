from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from common.file.resource_directories import (
    read_resource_directory_cache,
    write_resource_directory_cache,
)
from common.file.resource_publish import ResourcePublishError, publish_resource_upload


class FakeFiles:
    def __init__(self, files):
        self._files = files

    def all(self):
        return self._files


def make_upload_file(source_path, relative_path):
    return SimpleNamespace(
        file=SimpleNamespace(path=str(source_path)),
        relative_path=relative_path,
    )


class ResourcePublishTests(SimpleTestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        temporary_root = Path(self.temporary_directory.name)
        self.storage_root = temporary_root / 'storage'
        self.staging_root = temporary_root / 'media'
        self.cache_file = temporary_root / 'resource-tree.json'
        self.storage_root.mkdir()
        self.staging_root.mkdir()
        self.settings_override = override_settings(
            RESOURCE_STORAGE_ROOT=self.storage_root,
            RESOURCE_DIRECTORY_CACHE_FILE=self.cache_file,
            RESOURCES_WEBSITE_URL='https://resour.nwu.icu',
        )
        self.settings_override.enable()
        write_resource_directory_cache(['/'])

    def tearDown(self):
        self.settings_override.disable()
        self.temporary_directory.cleanup()

    def test_publish_copies_files_keeps_staged_originals_and_updates_tree(self):
        first_source = self.staging_root / 'first.bin'
        second_source = self.staging_root / 'second.bin'
        first_source.write_bytes(b'first')
        second_source.write_bytes(b'second')
        upload_request = SimpleNamespace(
            target_path='/courses/new-course',
            files=FakeFiles([
                make_upload_file(first_source, 'README.md'),
                make_upload_file(second_source, 'slides/week-1.pdf'),
            ]),
        )

        entries = publish_resource_upload(upload_request)

        self.assertEqual(
            (self.storage_root / 'courses' / 'new-course' / 'README.md').read_bytes(),
            b'first',
        )
        self.assertEqual(
            (self.storage_root / 'courses' / 'new-course' / 'slides' / 'week-1.pdf').read_bytes(),
            b'second',
        )
        self.assertTrue(first_source.exists())
        self.assertTrue(second_source.exists())
        self.assertEqual(len(entries), 2)

        cache = read_resource_directory_cache()
        self.assertIn('/courses/new-course', cache['paths'])
        self.assertIn('/courses/new-course/slides', cache['paths'])
        entries_by_path = {entry['path']: entry for entry in cache['entries']}
        self.assertEqual(entries_by_path['/courses/new-course/README.md']['size'], 5)
        self.assertEqual(entries_by_path['/courses/new-course/slides/week-1.pdf']['size'], 6)

    def test_existing_destination_is_not_overwritten_and_partial_copy_is_rolled_back(self):
        first_source = self.staging_root / 'first.bin'
        second_source = self.staging_root / 'second.bin'
        first_source.write_bytes(b'first')
        second_source.write_bytes(b'second')
        destination_directory = self.storage_root / 'courses'
        destination_directory.mkdir()
        existing_destination = destination_directory / 'existing.txt'
        existing_destination.write_bytes(b'keep-me')
        upload_request = SimpleNamespace(
            target_path='/courses',
            files=FakeFiles([
                make_upload_file(first_source, 'copied-before-error.txt'),
                make_upload_file(second_source, 'existing.txt'),
            ]),
        )

        with self.assertRaisesRegex(ResourcePublishError, '目标文件已存在'):
            publish_resource_upload(upload_request)

        self.assertEqual(existing_destination.read_bytes(), b'keep-me')
        self.assertFalse((destination_directory / 'copied-before-error.txt').exists())
        self.assertTrue(first_source.exists())
        self.assertTrue(second_source.exists())

    def test_interrupted_publish_resumes_from_verified_final_file(self):
        source = self.staging_root / 'notes.txt'
        source.write_bytes(b'content')
        destination_directory = self.storage_root / 'courses'
        destination_directory.mkdir()
        destination = destination_directory / 'notes.txt'
        destination.write_bytes(b'content')
        upload_file = make_upload_file(source, 'notes.txt')
        # This is the durable marker written immediately before os.replace.
        upload_file.published_path = '/courses/notes.txt'
        upload_file.content_hash = 'ed7002b439e9ac845f22357d822bac1444730fbdb6016d3ec9432297b9ec9f73'
        upload_file.published_at = None
        source.unlink()
        upload_request = SimpleNamespace(target_path='/courses', files=FakeFiles([upload_file]))

        entries = publish_resource_upload(upload_request)

        self.assertEqual(entries[0]['path'], '/courses/notes.txt')
        self.assertIsNotNone(upload_file.published_at)
        self.assertEqual(destination.read_bytes(), b'content')

    def test_concurrent_destination_creation_is_not_overwritten(self):
        source = self.staging_root / 'notes.txt'
        source.write_bytes(b'content')
        upload_request = SimpleNamespace(
            target_path='/courses',
            files=FakeFiles([make_upload_file(source, 'notes.txt')]),
        )
        destination = self.storage_root / 'courses' / 'notes.txt'

        def create_competing_file_then_fail(_temporary_path, final_path):
            Path(final_path).write_bytes(b'competitor')
            raise FileExistsError

        with patch('common.file.resource_publish.os.link', side_effect=create_competing_file_then_fail):
            with self.assertRaisesRegex(ResourcePublishError, '目标文件已存在'):
                publish_resource_upload(upload_request)

        self.assertEqual(destination.read_bytes(), b'competitor')

    @override_settings(RESOURCE_STORAGE_ROOT=None)
    def test_missing_storage_root_configuration_is_reported(self):
        upload_request = SimpleNamespace(target_path='/courses', files=FakeFiles([]))

        with self.assertRaisesRegex(ResourcePublishError, 'RESOURCE_STORAGE_ROOT'):
            publish_resource_upload(upload_request)
