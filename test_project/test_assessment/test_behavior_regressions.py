from tempfile import TemporaryDirectory
from uuid import uuid4

from django.contrib import admin
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import RequestFactory, override_settings
from django.urls import reverse
from rest_framework.test import APIClient, APITestCase

from course_assessment.models import Course, Review, ReviewReply, School, Semeseter
from test_project.common import create_user
from user.models import User


class ReviewBehaviorRegressionTests(APITestCase):
    def setUp(self):
        self.author = create_user(is_active=True)
        self.other = create_user(username='other', email='other@example.com', is_active=True)
        self.school = School.objects.create(name='Review regression school')
        self.semester = Semeseter.objects.create(name='2026-2027秋季')
        self.client.force_authenticate(self.author)

    def make_review(self, *, anonymous=False, content='paginationneedle'):
        course = Course.objects.create(
            name=f'Course {Course.objects.count()}', school=self.school, classification='general',
        )
        return Review.objects.create(
            course=course, created_by=self.author, semester=self.semester,
            content=content, anonymous=anonymous, rating=3,
            difficulty=3, grade=3, homework=3, reward=3,
        )

    def test_public_profile_filters_anonymous_reviews_before_pagination(self):
        self.make_review(anonymous=True)
        visible = self.make_review()
        self.make_review(anonymous=True)
        url = reverse('api:user_review', args=[self.author.pk])
        visitor = APIClient()
        for user in (None, self.other):
            with self.subTest(visitor=user):
                visitor.force_authenticate(user)
                response = visitor.get(url, {'pageSize': 1})
                self.assertEqual(response.status_code, 200)
                page = response.data['contents']
                self.assertEqual(page['count'], 1)
                self.assertEqual(page['max_page'], 1)
                self.assertEqual([item['id'] for item in page['results']], [visible.pk])

        own_page = self.client.get(url, {'pageSize': 1}).data['contents']
        self.assertEqual(own_page['count'], 3)
        self.assertEqual(own_page['max_page'], 3)
        self.assertEqual(len(own_page['results']), 1)

    def test_profile_with_only_anonymous_reviews_has_no_public_count(self):
        self.make_review(anonymous=True)
        response = APIClient().get(reverse('api:user_review', args=[self.author.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['contents']['count'], 0)
        self.assertEqual(response.data['contents']['results'], [])

    def test_reply_owner_can_delete_after_parent_review_is_deleted(self):
        review = self.make_review()
        reply = ReviewReply.objects.create(review=review, created_by=self.author, content='own reply')
        other_reply = ReviewReply.objects.create(review=review, created_by=self.other, content='other reply')
        review.soft_delete()
        url = reverse('api:add_reply')

        forbidden = self.client.delete(url, {'review_id': review.pk, 'reply_id': other_reply.pk})
        self.assertEqual(forbidden.status_code, 404)
        self.assertTrue(ReviewReply.objects.filter(pk=other_reply.pk).exists())

        wrong_review = self.make_review()
        mismatched = self.client.delete(url, {'review_id': wrong_review.pk, 'reply_id': reply.pk})
        self.assertEqual(mismatched.status_code, 404)

        accepted = self.client.delete(url, {'review_id': review.pk, 'reply_id': reply.pk})
        self.assertEqual(accepted.status_code, 200)
        self.assertFalse(ReviewReply.objects.filter(pk=reply.pk).exists())
        self.assertTrue(ReviewReply.all_objects.get(pk=reply.pk).is_deleted)

    def test_review_search_returns_distinct_pages_with_tied_ranks(self):
        reviews = [self.make_review() for _ in range(3)]
        request_data = {'type': 'review', 'keyword': 'paginationneedle', 'page_size': 2}
        first = self.client.post(reverse('api:search'), {**request_data, 'current_page': 1})
        second = self.client.post(reverse('api:search'), {**request_data, 'current_page': 2})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        first_page, second_page = first.data['contents'], second.data['contents']
        self.assertEqual(first_page['current_page'], 1)
        self.assertEqual(second_page['current_page'], 2)
        self.assertEqual(first_page['total_count'], 3)
        self.assertEqual([row['id'] for row in first_page['search_result']], [r.pk for r in reviews[:2]])
        self.assertEqual([row['id'] for row in second_page['search_result']], [reviews[2].pk])

    def test_user_admin_add_and_change_forms_build(self):
        request = RequestFactory().get('/admin/user/user/')
        request.user = self.author
        model_admin = admin.site._registry[User]
        for instance in (None, self.author):
            with self.subTest(instance=instance):
                form = model_admin.get_form(request, obj=instance)
                self.assertIn('username', form.base_fields)
                self.assertNotIn('cookie_last_update', form.base_fields)

    def review_payload(self, review, content):
        return {
            'course': review.course_id, 'semester': review.semester_id,
            'content': content, 'rating': 3, 'anonymous': False,
            'difficulty': 3, 'grade': 3, 'homework': 3, 'reward': 3,
        }

    def test_review_edit_keeps_current_historical_and_soft_deleted_attachments(self):
        review = self.make_review()
        with TemporaryDirectory() as directory, override_settings(MEDIA_ROOT=directory):
            uploaded = self.client.post(reverse('api:file-upload'), {
                'file': SimpleUploadedFile('notes.txt', b'course notes'), 'file_type': 'file',
            }, format='multipart')
            self.assertEqual(uploaded.status_code, 201)
            file_id = uploaded.data['contents']['uuid']
            download_url = reverse('api:file-download', args=[file_id])
            delete_url = reverse('api:file-delete', args=[file_id])
            review_url = reverse('api:review')
            linked_content = f'<p>Notes: <a href="{download_url}">download</a></p>'

            linked = self.client.put(review_url, self.review_payload(review, linked_content))
            self.assertEqual(linked.status_code, 200)
            self.assertEqual(self.client.delete(delete_url).status_code, 409)

            edited = self.client.put(review_url, self.review_payload(review, 'updated without the link'))
            self.assertEqual(edited.status_code, 200)
            self.assertEqual(self.client.delete(delete_url).status_code, 409)

            self.assertEqual(self.client.delete(review_url, {'review_id': review.pk}).status_code, 200)
            self.assertEqual(self.client.delete(delete_url).status_code, 409)
            self.assertEqual(self.client.get(download_url).status_code, 200)

    def test_new_review_attachment_must_exist_but_old_broken_links_remain_editable(self):
        review = self.make_review()
        broken = f'<a href="/api/download/{uuid4()}/">missing</a>'
        response = self.client.put(reverse('api:review'), self.review_payload(review, broken))
        self.assertEqual(response.status_code, 400)
        review.refresh_from_db()
        self.assertNotIn('missing', review.content)

        # Existing legacy content may already refer to a missing attachment.
        Review.objects.filter(pk=review.pk).update(content=broken)
        response = self.client.put(reverse('api:review'), self.review_payload(review, broken + ' edited'))
        self.assertEqual(response.status_code, 200)
