import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.test import SimpleTestCase, override_settings

from common.file.resource_directories import (
    add_resource_directory_paths,
    fetch_all_resource_directory_paths,
    get_cached_child_directories,
    read_resource_directory_cache,
    write_resource_directory_cache,
)
from common.file.serializers import ResourceUploadCreateSerializer
from scripts.export_resource_tree import build_resource_tree, write_json_atomically


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeResourceSession:
    directories = {
        '/': [
            {'name': 'courses', 'is_dir': True},
            {'name': 'README.md', 'is_dir': False},
        ],
        '/courses': [
            {'name': 'computer-science', 'is_dir': True},
        ],
        '/courses/computer-science': [],
    }

    def post(self, url, json, timeout):
        content = self.directories[json['path']]
        return FakeResponse({
            'code': 200,
            'message': 'success',
            'data': {
                'content': content,
                'total': len(content),
            },
        })


class ResourceDirectoryCacheTests(SimpleTestCase):
    def setUp(self):
        self.temporary_directory = TemporaryDirectory()
        self.cache_file = Path(self.temporary_directory.name) / 'directories.json'
        self.settings_override = override_settings(
            RESOURCE_DIRECTORY_CACHE_FILE=self.cache_file,
            RESOURCES_WEBSITE_URL='https://resour.nwu.icu',
        )
        self.settings_override.enable()

    def tearDown(self):
        self.settings_override.disable()
        self.temporary_directory.cleanup()

    def test_dfs_fetches_all_resource_directories(self):
        paths = fetch_all_resource_directory_paths(
            'https://resour.nwu.icu',
            session=FakeResourceSession(),
        )

        self.assertEqual(paths, {
            '/',
            '/courses',
            '/courses/computer-science',
        })

    def test_successful_null_content_is_treated_as_empty_directory(self):
        class NullContentSession:
            def post(self, url, json, timeout):
                return FakeResponse({
                    'code': 200,
                    'message': 'success',
                    'data': {'content': None, 'total': 0},
                })

        paths = fetch_all_resource_directory_paths(
            'https://resour.nwu.icu',
            session=NullContentSession(),
        )

        self.assertEqual(paths, {'/'})

    def test_cached_children_are_returned_without_contacting_resource_service(self):
        write_resource_directory_cache([
            '/',
            '/courses',
            '/courses/computer-science',
            '/documents',
        ])

        contents = get_cached_child_directories('/')

        self.assertEqual(
            [directory['path'] for directory in contents['directories']],
            ['/courses', '/documents'],
        )

    def test_approved_new_folder_adds_path_and_missing_ancestors(self):
        existing_file = {
            'path': '/README.md',
            'name': 'README.md',
            'type': 'file',
            'size': 1536,
            'size_display': '1.50 KB',
            'modified_at': None,
        }
        write_resource_directory_cache(['/'], entries=[existing_file])

        add_resource_directory_paths(['/courses/computer-science/grade-2026'])

        payload = read_resource_directory_cache()
        self.assertEqual(payload['paths'], [
            '/',
            '/courses',
            '/courses/computer-science',
            '/courses/computer-science/grade-2026',
        ])
        self.assertIn(existing_file, payload['entries'])
        self.assertIn(
            '/courses/computer-science/grade-2026',
            {entry['path'] for entry in payload['entries']},
        )
        self.assertEqual(payload['summary']['total_file_size_display'], '1.50 KB')

    def test_cache_file_is_valid_json(self):
        write_resource_directory_cache(['/', '/courses'])

        with self.cache_file.open(encoding='utf-8') as file:
            payload = json.load(file)

        self.assertEqual(payload['paths'], ['/', '/courses'])


class ResourceTreeExporterTests(SimpleTestCase):
    def test_export_contains_directories_and_files(self):
        with TemporaryDirectory() as temporary_directory:
            storage_root = Path(temporary_directory) / 'storage'
            nested_directory = storage_root / 'courses' / 'computer-science'
            nested_directory.mkdir(parents=True)
            (storage_root / 'README.md').write_bytes(b'a' * 1536)
            (nested_directory / 'syllabus.pdf').write_bytes(b'pdf')

            payload = build_resource_tree(storage_root)
            entries = {entry['path']: entry for entry in payload['entries']}

            self.assertEqual(payload['paths'], [
                '/',
                '/courses',
                '/courses/computer-science',
            ])
            self.assertEqual(entries['/courses']['type'], 'directory')
            self.assertEqual(entries['/README.md']['type'], 'file')
            self.assertEqual(entries['/README.md']['size'], 1536)
            self.assertEqual(entries['/README.md']['size_display'], '1.50 KB')
            self.assertEqual(
                entries['/courses/computer-science/syllabus.pdf']['type'],
                'file',
            )
            self.assertEqual(payload['summary']['directory_count'], 3)
            self.assertEqual(payload['summary']['file_count'], 2)
            self.assertEqual(payload['summary']['total_file_size'], 1539)

    def test_export_is_written_as_valid_json(self):
        with TemporaryDirectory() as temporary_directory:
            storage_root = Path(temporary_directory) / 'storage'
            storage_root.mkdir()
            (storage_root / 'file.txt').write_text('content', encoding='utf-8')
            output_file = Path(temporary_directory) / 'tree.json'

            payload = build_resource_tree(storage_root)
            write_json_atomically(payload, output_file)

            with output_file.open(encoding='utf-8') as file:
                written_payload = json.load(file)
            self.assertEqual(written_payload['entries'], payload['entries'])


class ResourceUploadPathValidationTests(SimpleTestCase):
    def test_direct_upload_to_root_is_rejected(self):
        serializer = ResourceUploadCreateSerializer(data={
            'target_path': '/',
        })

        self.assertFalse(serializer.is_valid())
        self.assertIn('target_path', serializer.errors)

    def test_new_folder_below_root_is_allowed(self):
        serializer = ResourceUploadCreateSerializer(data={
            'target_path': '/',
            'new_folder_name': 'new-course',
        })

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data['target_path'], '/new-course')
