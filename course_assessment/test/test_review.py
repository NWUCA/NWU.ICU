from django.core.exceptions import ObjectDoesNotExist
from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from course_assessment.models import Review, ReviewHistory


@override_settings(DEBUG=True)
class CourseTests(APITestCase):
    fixtures = ['school_initial_data.json']

    def update_semester(self, start_year=2017):
        call_command('update_semester', start_year=start_year)

    def add_teacher_course(self):
        teacher_name = 'testTeacher'
        teacher_response = self.client.post(reverse('api:add_teacher'), data={'name': teacher_name, 'school': 1})
        teacher_id = teacher_response.data['contents']['teacher_id']
        course_data = {
            "course_name": "testCourse",
            "course_school": 1,
            "course_classification": "general",
            "teacher_id": teacher_id
        }
        course_response = self.client.post(reverse('api:add_course'), data=course_data)
        course_id = course_response.data['contents']['course_id']
        return course_id

    def setUp(self):
        self.register_data = {
            "username": "testUser",
            "password": "testPassword1",
            "email": "asd@exapmple.com",
            "captcha_key": "captcha_key",
            "captcha_value": "PASSED"
        }
        self.register_url = reverse('api:register')
        self.review_list_url = reverse('api:latest_review')
        self.review_url = reverse('api:review')
        token = self.client.post(self.register_url, self.register_data, format='json').data['contents']['token']
        self.client.get(self.register_url + "?token=" + token)
        self.login_data = {
            'username': self.register_data['username'],
            'password': self.register_data['password'],
        }
        self.client.post(reverse('api:login'), self.login_data, format='json')
        self.update_semester()

    def test_add_review(self):
        course_id = self.add_teacher_course()
        review_data = {
            "course": course_id,
            "content": "test_message",
            "rating": 2,
            "anonymous": False,
            "difficulty": 2,
            "grade": 1,
            "homework": 2,
            "reward": 1,
            "semester": 1
        }
        add_review_response = self.client.post(self.review_url, review_data)
        latest_review_list_response = self.client.get(self.review_list_url)
        self.assertEqual(add_review_response.data['contents']['review_id'],
                         latest_review_list_response.data['contents']['reviews'][-1]['id'])
        self.assertEqual(latest_review_list_response.data['contents']['total'], 1)
        return add_review_response.data['contents']['review_id'], course_id

    def test_delete_review(self):
        review_id, _ = self.test_add_review()
        delete_review_response = self.client.delete(self.review_url, data={'review_id': review_id})
        self.assertEqual(delete_review_response.data['contents']['review_id'], review_id)
        latest_review_list_response = self.client.get(self.review_list_url)
        with self.assertRaises(ObjectDoesNotExist):
            Review.objects.get(id=review_id)
        self.assertEqual(Review.all_objects.get(id=review_id).is_deleted, True)
        self.assertEqual(latest_review_list_response.data['contents']['total'], 0)

    def test_edit_review(self):
        review_id, course_id = self.test_add_review()
        review = Review.objects.get(id=review_id)
        old_review_content = review.content
        edit_review_data = {
            "course": course_id,
            "content": "test_message_edit",
            "rating": 3,
            "anonymous": False,
            "difficulty": 3,
            "grade": 2,
            "homework": 3,
            "reward": 2,
            "semester": 1
        }
        edit_review_response = self.client.put(self.review_url, edit_review_data)
        self.assertEqual(edit_review_response.data['contents']['review_id'], review_id)
        review.refresh_from_db()
        self.assertNotEquals(review.content, old_review_content)
        review_history = ReviewHistory.objects.get(review=review)
        self.assertEqual(review_history.content, old_review_content)

        self.assertEqual(review.content, edit_review_data['content'])
        self.assertEqual(review.rating, edit_review_data['rating'])
        self.assertEqual(review.difficulty, edit_review_data['difficulty'])
        self.assertEqual(review.grade, edit_review_data['grade'])
        self.assertEqual(review.homework, edit_review_data['homework'])
        self.assertEqual(review.reward, edit_review_data['reward'])
        self.assertEqual(review.semester_id, edit_review_data['semester'])
        self.assertEqual(review.anonymous, edit_review_data['anonymous'])
