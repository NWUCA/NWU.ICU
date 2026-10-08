import re
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.test import override_settings
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient, APITestCase

from course_assessment.models import Course, Semeseter, Teacher
from course_assessment.serializer import AddCourseSerializer
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
        self.school_list_url = reverse('api:school')

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
        teacher_response = self.client.post(
            self.add_teacher_url, data={'name': teacher_name, 'school': 1}
        )
        teacher_id = teacher_response.data['contents']['teacher_id']
        self.assertEqual(Teacher.objects.get(id=teacher_id).name, teacher_name)

    def test_teacher_responses_do_not_expose_avatar(self):
        teacher_response = self.client.post(
            self.add_teacher_url,
            data={'name': 'testTeacher', 'school': 1},
        )
        teacher_id = teacher_response.data['contents']['teacher_id']

        teacher_list_response = self.client.get(self.add_teacher_url)
        teacher_item = teacher_list_response.data['contents']['results'][0]
        self.assertNotIn('avatar', teacher_item)
        self.assertNotIn('avatar_uuid', teacher_item)

        teacher_detail_response = self.client.get(reverse('api:teacher', args=[teacher_id]))
        teacher_info = teacher_detail_response.data['contents']['teacher_info']
        self.assertNotIn('avatar', teacher_info)
        self.assertNotIn('avatar_uuid', teacher_info)

    def test_add_course(self):
        self.test_add_teacher()
        course_data = {"name": "testCourse", "school": 1, "classification": "general", "teacher_id": 1}
        course_response = self.client.post(self.add_course_url, data=course_data)
        course_id = course_response.data['contents']['course_id']
        self.assertEqual(Course.objects.get(id=course_id).name, course_data['name'])
        self.assertEqual(Course.objects.get(id=course_id).classification, course_data['classification'])
        self.assertEqual(
            list(Course.objects.get(id=course_id).teachers.values_list('id', flat=True)), [1]
        )

    def multi_teacher_course_data(self):
        first = Teacher.objects.create(name='第一位教师', school_id=1)
        second = Teacher.objects.create(name='第二位教师', school_id=2)
        return {
            'name': '多教师课程',
            'school': 1,
            'classification': 'general',
            'teacher_ids': [first.id, second.id],
        }

    def test_add_course_with_multiple_teachers(self):
        data = self.multi_teacher_course_data()
        response = self.client.post(self.add_course_url, data=data, format='json')

        self.assertEqual(response.status_code, 200)
        course = Course.objects.get(id=response.data['contents']['course_id'])
        self.assertEqual(set(course.teachers.values_list('id', flat=True)), set(data['teacher_ids']))
        self.assertEqual(course.created_by, self.user)
        for teacher_id in data['teacher_ids']:
            detail = self.client.get(reverse('api:teacher', args=[teacher_id]))
            self.assertEqual(
                [item['course']['id'] for item in detail.data['contents']['course_list']], [course.id]
            )

    def test_add_course_deduplicates_teacher_ids(self):
        data = self.multi_teacher_course_data()
        data['teacher_ids'] += data['teacher_ids']
        response = self.client.post(self.add_course_url, data=data, format='json')

        self.assertEqual(response.status_code, 200)
        course = Course.objects.get(id=response.data['contents']['course_id'])
        self.assertEqual(set(course.teachers.values_list('id', flat=True)), set(data['teacher_ids']))

    def test_add_course_rejects_missing_teachers_without_creating_course(self):
        data = self.multi_teacher_course_data()
        data['teacher_ids'].append(max(data['teacher_ids']) + 1)
        response = self.client.post(self.add_course_url, data=data, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0]['field'], 'teacher')
        self.assertEqual(response.data['errors'][0]['err_code'], 'teacher_not_exist')
        self.assertFalse(Course.objects.exists())

    def test_add_course_rejects_both_teacher_fields(self):
        data = self.multi_teacher_course_data()
        data['teacher_id'] = data['teacher_ids'][0]
        response = self.client.post(self.add_course_url, data=data, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0]['field'], 'teacher')
        self.assertFalse(Course.objects.exists())

    def test_add_course_requires_at_least_one_teacher(self):
        data = self.multi_teacher_course_data()
        data.pop('teacher_ids')
        response = self.client.post(self.add_course_url, data=data, format='json')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data['errors'][0]['field'], 'teacher')
        self.assertFalse(Course.objects.exists())

    def test_add_course_rejects_invalid_teacher_lists_with_api_error_envelope(self):
        data = self.multi_teacher_course_data()
        invalid_lists = [[], None, 1, '1,2', [None], ['not-an-id'], [1.5], [True], [{}], [[1]]]
        for teacher_ids in invalid_lists:
            with self.subTest(teacher_ids=teacher_ids):
                response = self.client.post(
                    self.add_course_url,
                    data={**data, 'teacher_ids': teacher_ids},
                    format='json',
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data['errors'][0]['field'], 'teacher_ids')
                self.assertTrue(response.data['errors'][0]['err_msg'])
                self.assertFalse(Course.objects.exists())

    def test_course_creation_rolls_back_if_teacher_relations_fail(self):
        data = self.multi_teacher_course_data()
        with patch.object(
            Course.teachers.related_manager_cls, 'add', side_effect=RuntimeError('relation failure')
        ):
            with self.assertRaisesRegex(RuntimeError, 'relation failure'):
                self.client.post(self.add_course_url, data=data, format='json')
        self.assertFalse(Course.objects.exists())

    def test_course_creation_does_not_omit_teacher_deleted_after_validation(self):
        data = self.multi_teacher_course_data()
        serializer = AddCourseSerializer(
            data=data, context={'request': SimpleNamespace(user=self.user)}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        Teacher.objects.get(id=data['teacher_ids'][1]).delete()

        with self.assertRaises(ValidationError):
            serializer.save()
        self.assertFalse(Course.objects.exists())

    def test_course_like(self):
        self.test_add_teacher()
        course_data = {"name": "testCourse", "school": 1, "classification": "general", "teacher_id": 1}
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
        self.assertEqual(len(course_list_response.data['contents']['results']), 1)
        self.assertEqual(course_list_response.data['contents']['count'], 1)
        course_list_response = self.client.get(self.course_list_url + '?course_type=pe')
        self.assertEqual(len(course_list_response.data['contents']['results']), 0)
        self.assertEqual(course_list_response.data['contents']['count'], 0)

    def test_school_list_sorts_numeric_prefix_and_preserves_other_order(self):
        response = self.client.get(self.school_list_url)
        schools = response.data['contents']['schools']

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            schools[0],
            {
                'id': 2,
                'name': '101文学院',
            },
        )

        numbered_schools = [school for school in schools if re.match(r'^\d+', school['name'])]
        self.assertEqual(
            [int(re.match(r'^\d+', school['name']).group()) for school in numbered_schools],
            sorted(int(re.match(r'^\d+', school['name']).group()) for school in numbered_schools),
        )

        unnumbered_school_ids = [
            school['id'] for school in schools if not re.match(r'^\d+', school['name'])
        ]
        self.assertEqual(
            unnumbered_school_ids,
            sorted(unnumbered_school_ids),
        )
