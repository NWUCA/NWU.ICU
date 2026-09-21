import tempfile
from concurrent.futures import ThreadPoolExecutor
from io import StringIO
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch
from uuid import uuid4

from django.conf import settings
from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import close_old_connections, connection
from django.test import RequestFactory, SimpleTestCase, TransactionTestCase, override_settings
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APIRequestFactory, APITestCase, force_authenticate

from common.file.models import UploadedFile
from common.file.references import (
    collect_file_reference_counts,
    ensure_file_references,
    file_is_referenced,
    file_lifecycle,
    file_reference_ids,
)
from common.file.view import FileUpdateView
from common.models import About, Announcement, Bulletin
from course_assessment.models import Course, Review, ReviewHistory, School, Semeseter, Teacher
from guestbook.announcements import publish_announcement
from guestbook.models import GuestbookEntry
from test_project.common import create_user
from user.models import User


class AttachmentUrlTests(SimpleTestCase):
    def test_current_and_legacy_urls_but_not_arbitrary_uuid_text(self):
        file_id = uuid4()
        for content in (
            f'<img src="/api/download/{file_id}/">',
            f'<a href="https://old.example/api/download/{str(file_id).upper()}?download=1">file</a>',
            f'[file](/api/download/{file_id}/#anchor)',
        ):
            with self.subTest(content=content):
                self.assertEqual(file_reference_ids(content), {file_id})
        self.assertEqual(file_reference_ids(f'An arbitrary identifier: {file_id}'), set())
        self.assertEqual(file_reference_ids(f'/api/download/{file_id}invalid'), set())


class FileLifecycleTests(APITestCase):
    def setUp(self):
        self.media_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.user = create_user(is_active=True)
        self.client.force_authenticate(self.user)

    def upload(self, data=b'attachment', **kwargs):
        return UploadedFile.objects.create(
            file=SimpleUploadedFile('attachment.txt', data), file_size=len(data),
            created_by=self.user, **kwargs,
        )

    def review(self, content):
        school = School.objects.create(name='附件测试院系')
        semester = Semeseter.objects.create(name='2026秋')
        course = Course.objects.create(
            course_code='attachment', name='附件测试课程', school=school,
            classification='general', created_by=self.user,
        )
        return Review.objects.create(
            course=course, semester=semester, created_by=self.user, content=content,
            rating=4, difficulty=3, grade=3, homework=3, reward=3,
        )

    def clean(self):
        output = StringIO()
        with self.captureOnCommitCallbacks(execute=True):
            call_command('clean_unused_file', yes=True, stdout=output)
        return output.getvalue()

    def test_cleanup_keeps_a_shared_file_referenced_by_another_record(self):
        unused = self.upload()
        avatar = self.upload(file_type='avatar')
        self.assertEqual(unused.file.name, avatar.file.name)
        User.objects.filter(pk=self.user.pk).update(avatar_uuid=avatar.pk)

        output = self.clean()

        self.assertIn('0.00 byte', output)
        self.assertFalse(UploadedFile.objects.filter(pk=unused.pk).exists())
        avatar.refresh_from_db()
        self.assertEqual(avatar.ref_count, 1)
        self.assertTrue(avatar.file.storage.exists(avatar.file.name))

    def test_cleanup_deletes_the_last_shared_storage_object_only_once(self):
        first = self.upload()
        self.upload()
        with patch.object(first.file.storage, 'delete', wraps=first.file.storage.delete) as delete:
            self.clean()
        self.assertFalse(UploadedFile.objects.exists())
        self.assertFalse(first.file.storage.exists(first.file.name))
        delete.assert_called_once_with(first.file.name)

    def test_stale_positive_counter_does_not_keep_an_unused_file(self):
        unused = self.upload()
        UploadedFile.objects.filter(pk=unused.pk).update(ref_count=7)
        About.objects.create(content=f'Ordinary UUID text: {unused.pk}')
        self.clean()
        self.assertFalse(UploadedFile.objects.filter(pk=unused.pk).exists())
        self.assertFalse(unused.file.storage.exists(unused.file.name))

    def test_cancelling_cleanup_does_not_change_counters_or_files(self):
        unused = self.upload()
        UploadedFile.objects.filter(pk=unused.pk).update(ref_count=7)
        with patch('builtins.input', return_value='n'):
            call_command('clean_unused_file', stdout=StringIO())
        unused.refresh_from_db()
        self.assertEqual(unused.ref_count, 7)
        self.assertTrue(unused.file.storage.exists(unused.file.name))

    def test_cleanup_rechecks_references_added_after_the_preview(self):
        avatar = self.upload(file_type='avatar')

        def confirm():
            User.objects.filter(pk=self.user.pk).update(avatar_uuid=avatar.pk)
            return 'y'

        with patch('builtins.input', side_effect=confirm), self.captureOnCommitCallbacks(execute=True):
            call_command('clean_unused_file', stdout=StringIO())
        self.assertTrue(UploadedFile.objects.filter(pk=avatar.pk).exists())
        self.assertTrue(avatar.file.storage.exists(avatar.file.name))

    def test_current_avatar_rejects_delete_and_replace_without_a_cached_count(self):
        avatar = self.upload(file_type='avatar')
        response = self.client.post(reverse('api:my_profile'), {'avatar_uuid': str(avatar.pk)}, format='json')
        self.assertEqual(response.status_code, 200)
        avatar.refresh_from_db()
        self.assertEqual(avatar.ref_count, 0)

        deleted = self.client.delete(reverse('api:file-delete', args=[avatar.pk]))
        self.assertEqual(deleted.status_code, 409)
        request = APIRequestFactory().put(
            '/unused-file-update/', {'file': SimpleUploadedFile('new.txt', b'new'), 'file_type': 'file'},
            format='multipart',
        )
        force_authenticate(request, self.user)
        replaced = FileUpdateView.as_view()(request, id=avatar.pk)
        self.assertEqual(replaced.status_code, 409)
        self.assertTrue(avatar.file.storage.exists(avatar.file.name))

    def test_all_preserved_content_and_system_avatars_are_protected(self):
        files = [self.upload(data=f'file-{index}'.encode()) for index in range(8)]
        content = lambda file: f'<img src="/api/download/{file.pk}/">'
        review = self.review(content(files[0]))
        review.soft_delete()
        ReviewHistory.all_objects.create(review=review, content=content(files[1]), is_deleted=True)
        GuestbookEntry.all_objects.create(
            author=self.user, content=content(files[2]), board=GuestbookEntry.BOARD_ANNOUNCEMENT,
            is_deleted=True,
        )
        Teacher.objects.create(name='附件教师', avatar_uuid=files[3].pk)
        Announcement.objects.create(content=content(files[4]), type='all')
        Bulletin.objects.create(title='附件公告', content=content(files[5]), publisher=self.user)
        About.objects.create(content=f'[file](https://legacy.example/api/download/{files[6].pk})')
        User.objects.filter(pk=self.user.pk).update(avatar_uuid=files[7].pk)
        default = self.upload(data=b'default', id=settings.DEFAULT_USER_AVATAR_UUID)
        anonymous = self.upload(data=b'anonymous', id=settings.ANONYMOUS_USER_AVATAR_UUID)
        files.extend((default, anonymous))

        for file in files:
            with self.subTest(file=file.pk):
                self.assertTrue(file_is_referenced(file.pk))
                self.assertEqual(self.client.delete(reverse('api:file-delete', args=[file.pk])).status_code, 409)
        self.clean()
        counts = collect_file_reference_counts()
        for file in files:
            file.refresh_from_db()
            self.assertEqual(file.ref_count, counts[file.pk])
            self.assertGreater(file.ref_count, 0)
            self.assertTrue(file.file.storage.exists(file.file.name))

    def test_missing_new_references_rejected_but_existing_broken_links_can_be_edited(self):
        broken = f'<img src="/api/download/{uuid4()}/">'
        with file_lifecycle():
            with self.assertRaises(ValidationError):
                ensure_file_references(broken)
            ensure_file_references(broken + '<p>Edited text</p>', broken)

    def test_announcement_revalidates_a_file_deleted_after_serializer_validation(self):
        file = self.upload(file_type='img')
        content = f'<img src="/api/download/{file.pk}/">'
        UploadedFile.objects.filter(pk=file.pk).delete()
        with self.assertRaises(ValidationError):
            publish_announcement(author=self.user, data={'title': '公告', 'content': content})
        self.assertFalse(GuestbookEntry.objects.exists())

    def test_admin_reports_missing_attachment_as_a_form_error(self):
        request = RequestFactory().get('/admin/common/about/add/')
        request.user = self.user
        form_class = admin.site._registry[About].get_form(request)
        form = form_class(data={
            'title': 'About', 'content': f'<img src="/api/download/{uuid4()}/">',
            'weight': 0, 'type': 'about',
        })
        self.assertFalse(form.is_valid())
        self.assertIn('content', form.errors)

    def test_admin_can_edit_existing_broken_links_and_create_teacher_without_avatar(self):
        request = RequestFactory().get('/admin/')
        request.user = self.user
        about = About.objects.create(content=f'<img src="/api/download/{uuid4()}/">')
        about_form = admin.site._registry[About].get_form(request, about)(
            instance=about,
            data={'title': 'Edited title', 'content': about.content, 'weight': 0, 'type': 'about'},
        )
        self.assertTrue(about_form.is_valid(), about_form.errors)

        school = School.objects.create(name='Teacher school')
        teacher_form_class = admin.site._registry[Teacher].get_form(
            request, fields=('name', 'school', 'created_by', 'avatar_uuid'),
        )
        self.assertNotIn('search_vector', teacher_form_class.base_fields)
        self.assertIsNone(teacher_form_class().initial['avatar_uuid'])
        teacher_form = teacher_form_class(data={
            'name': 'No avatar teacher', 'school': school.pk, 'created_by': self.user.pk,
            'avatar_uuid': '',
        })
        self.assertTrue(teacher_form.is_valid(), teacher_form.errors)
        self.assertIsNone(teacher_form.save().avatar_uuid)


@skipUnless(connection.vendor == 'postgresql', 'Requires PostgreSQL advisory locks')
class FileLifecycleConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.media_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.media_directory.cleanup)
        self.settings_override = override_settings(MEDIA_ROOT=self.media_directory.name)
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)
        self.user = create_user(is_active=True)
        self.file = UploadedFile.objects.create(
            file=SimpleUploadedFile('shared.txt', b'shared'), file_size=6, created_by=self.user,
            file_type='avatar',
        )

    def concurrently(self, *actions):
        barrier = Barrier(len(actions))

        def run(action):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET lock_timeout = '5s'")
                barrier.wait(timeout=10)
                client = APIClient()
                client.force_authenticate(self.user)
                return action(client)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=len(actions)) as executor:
            futures = [executor.submit(run, action) for action in actions]
            return [future.result(timeout=20) for future in futures]

    def test_setting_avatar_and_deleting_never_leave_a_broken_reference(self):
        profile, deleted = self.concurrently(
            lambda client: client.post(reverse('api:my_profile'), {'avatar_uuid': str(self.file.pk)}, format='json'),
            lambda client: client.delete(reverse('api:file-delete', args=[self.file.pk])),
        )
        self.assertIn((profile.status_code, deleted.status_code), {(200, 409), (400, 204)})
        self.user.refresh_from_db()
        if profile.status_code == 200:
            self.assertEqual(self.user.avatar_uuid, self.file.pk)
            self.assertTrue(UploadedFile.objects.filter(pk=self.file.pk).exists())
            self.assertTrue(self.file.file.storage.exists(self.file.file.name))
        else:
            self.assertNotEqual(self.user.avatar_uuid, self.file.pk)

    def test_setting_avatar_and_cleanup_never_leave_a_broken_reference(self):
        def cleanup(client):
            call_command('clean_unused_file', yes=True, stdout=StringIO())

        profile, _ = self.concurrently(
            lambda client: client.post(reverse('api:my_profile'), {'avatar_uuid': str(self.file.pk)}, format='json'),
            cleanup,
        )
        self.assertIn(profile.status_code, (200, 400))
        self.user.refresh_from_db()
        if profile.status_code == 200:
            self.assertEqual(self.user.avatar_uuid, self.file.pk)
            self.assertTrue(UploadedFile.objects.filter(pk=self.file.pk).exists())
            self.assertTrue(self.file.file.storage.exists(self.file.file.name))
        else:
            self.assertNotEqual(self.user.avatar_uuid, self.file.pk)

    def test_deduplicating_upload_and_deleting_do_not_deadlock_or_remove_new_file(self):
        uploaded, deleted = self.concurrently(
            lambda client: client.post(
                reverse('api:file-upload'),
                {'file': SimpleUploadedFile('new.txt', b'shared'), 'file_type': 'file'}, format='multipart',
            ),
            lambda client: client.delete(reverse('api:file-delete', args=[self.file.pk])),
        )
        self.assertEqual(uploaded.status_code, 201)
        self.assertEqual(deleted.status_code, 204)
        new_file = UploadedFile.objects.get(pk=uploaded.data['contents']['uuid'])
        with new_file.file.open('rb') as handle:
            self.assertEqual(handle.read(), b'shared')
