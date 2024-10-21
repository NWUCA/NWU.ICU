from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase

from course_assessment.models import Semeseter, Teacher, Course


@override_settings(DEBUG=True)
class CourseTests(APITestCase):
    fixtures = ['school_initial_data.json']

    def update_semester(self, start_year=2017):
        call_command('update_semester', start_year=start_year)

    def setUp(self):
        self.register_data = {
            "username": "testUser",
            "password": "testPassword1",
            "email": "asd@exapmple.com",
            "captcha_key": "captcha_key",
            "captcha_value": "PASSED"
        }
        self.register_userA_data = {
            "username": "testUserA",
            "password": "testPassword1",
            "email": "userA@exapmple.com",
            "captcha_key": "test_captcha",
            "captcha_value": "PASSED"
        }
        self.register_url = reverse('api:register')
        self.login_url = reverse('api:login')
        self.active_url = reverse('api:register')
        self.add_teacher_url = reverse('api:add_teacher')
        self.add_course_url = reverse('api:add_course')
        self.course_like_url = reverse('api:course_like')
        self.course_list_url = reverse('api:course_list')
        token = self.client.post(self.register_url, self.register_data, format='json').data['contents']['token']
        self.client.get(self.register_url + "?token=" + token)
        self.login_data = {
            'username': self.register_data['username'],
            'password': self.register_data['password'],
        }
        self.client.post(self.login_url, self.login_data, format='json')
        self.update_semester()

    def test_update_semester(self):
        def season_generator():
            while True:
                yield "春"
                yield "秋"

        def start_year_generator(start_year):
            while True:
                yield str(start_year)
                yield str(start_year)
                start_year += 1

        start_year = 2015
        self.update_semester(start_year)
        semester = Semeseter.objects.all()
        season = season_generator()
        year = start_year_generator(start_year)
        for i in semester:
            self.assertEqual(i.name, f'{next(year)}-{next(season)}')

    def test_add_teacher(self):
        teacher_name = 'testTeacher'
        teacher_response = self.client.post(self.add_teacher_url, data={'name': teacher_name, 'school': 1})
        teacher_id = teacher_response.data['contents']['teacher_id']
        self.assertEqual(Teacher.objects.get(id=teacher_id).name, teacher_name)

    def test_add_course(self):
        self.test_add_teacher()
        course_data = {
            "course_name": "testCourse",
            "course_school": 1,
            "course_classification": "general",
            "teacher_id": 1
        }
        course_response = self.client.post(self.add_course_url, data=course_data)
        course_id = course_response.data['contents']['course_id']
        self.assertEqual(Course.objects.get(id=course_id).name, course_data['course_name'])
        self.assertEqual(Course.objects.get(id=course_id).classification, course_data['course_classification'])

    def testCourseLike(self):
        self.test_add_teacher()
        course_data = {
            "course_name": "testCourse",
            "course_school": 1,
            "course_classification": "general",
            "teacher_id": 1
        }
        course_response = self.client.post(self.add_course_url, data=course_data)
        course_id = course_response.data['contents']['course_id']
        course_like_data = {"course_id": course_id, "like": "1"}

        course_like_response = self.client.post(self.course_like_url, data=course_like_data)
        self.assertEqual(course_like_response['contents']['like']['like'], 1)
        self.assertEqual(course_like_response['contents']['like']['dislike'], 0)
        course_like_response = self.client.post(self.course_like_url, data=course_like_data)
        self.assertEqual(course_like_response['contents']['like']['like'], 0)  # 重新点赞会取消上次的点赞
        self.assertEqual(course_like_response['contents']['like']['dislike'], 0)

        course_like_data['like'] = '-1'
        course_like_response = self.client.post(self.course_like_url, data=course_like_data)
        self.assertEqual(course_like_response['contents']['like']['like'], 0)
        self.assertEqual(course_like_response['contents']['like']['dislike'], 1)
        course_like_response = self.client.post(self.course_like_url, data=course_like_data)
        self.assertEqual(course_like_response['contents']['like']['like'], 0)
        self.assertEqual(course_like_response['contents']['like']['dislike'], 1)

    def test_course_list(self):
        self.test_add_course()
        course_list_response = self.client.get(self.course_list_url)
        self.assertEqual(len(course_list_response.data['contents']['courses']),1)
        self.assertEqual(course_list_response.data['contents']['total'],1)
        course_list_response = self.client.get(self.course_list_url+'?course_type=pe')
        self.assertEqual(len(course_list_response.data['contents']['courses']),0)
        self.assertEqual(course_list_response.data['contents']['total'],0)
