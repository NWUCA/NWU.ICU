from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from rest_framework.test import APITestCase, APIClient

from course_assessment.models import Semeseter, Teacher, Course
from test_project.common import create_user, login_user


@override_settings(DEBUG=True)
class CourseTests(APITestCase):
    fixtures = ['school_initial_data.json']

    def setUp(self):
        call_command('flush', '--noinput')
        call_command('loaddata', 'school_initial_data.json')
        call_command('update_semester', start_year=2017)
        self.client = APIClient()
        self.user = create_user(is_active=True)
        login_user(self.client)
        self.add_teacher_url = reverse('api:add_teacher')
        self.add_course_url = reverse('api:add_course')
        self.course_like_url = reverse('api:course_like')
        self.course_list_url = reverse('api:course_list')

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
        call_command('update_semester', start_year=start_year)
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
            "name": "testCourse",
            "school": 1,
            "classification": "general",
            "teacher_id": 1
        }
        course_response = self.client.post(self.add_course_url, data=course_data)
        course_id = course_response.data['contents']['course_id']
        self.assertEqual(Course.objects.get(id=course_id).name, course_data['name'])
        self.assertEqual(Course.objects.get(id=course_id).classification, course_data['classification'])

    def testCourseLike(self):
        self.test_add_teacher()
        course_data = {
            "name": "testCourse",
            "school": 1,
            "classification": "general",
            "teacher_id": 1
        }
        course_response = self.client.post(self.add_course_url, data=course_data)
        course_id = course_response.data['contents']['course_id']
        course_like_data = {"course_id": course_id, "like": "1"}

        course_like_response = self.client.post(self.course_like_url, data=course_like_data)
        self.assertEqual(course_like_response.data['contents']['like']['like'], 1)
        self.assertEqual(course_like_response.data['contents']['like']['dislike'], 0)
        course_like_response = self.client.post(self.course_like_url, data=course_like_data)
        self.assertEqual(course_like_response.data['contents']['like']['like'], 0)  # 重新点赞会取消上次的点赞
        self.assertEqual(course_like_response.data['contents']['like']['dislike'], 0)

        course_like_data['like'] = '-1'
        course_like_response = self.client.post(self.course_like_url, data=course_like_data)
        self.assertEqual(course_like_response.data['contents']['like']['like'], 0)
        self.assertEqual(course_like_response.data['contents']['like']['dislike'], 1)
        course_like_response = self.client.post(self.course_like_url, data=course_like_data)
        self.assertEqual(course_like_response.data['contents']['like']['like'], 0)
        self.assertEqual(course_like_response.data['contents']['like']['dislike'], 0)

    def test_course_list(self):
        self.test_add_course()
        course_list_response = self.client.get(self.course_list_url)
        self.assertEqual(len(course_list_response.data['contents']['courses']), 1)
        self.assertEqual(course_list_response.data['contents']['total'], 1)
        course_list_response = self.client.get(self.course_list_url + '?course_type=pe')
        self.assertEqual(len(course_list_response.data['contents']['courses']), 0)
        self.assertEqual(course_list_response.data['contents']['total'], 0)
