from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from course_assessment.views import SchoolView


class SchoolViewTests(SimpleTestCase):
    @patch('course_assessment.views.School.objects.order_by')
    def test_school_list_preserves_stored_name_and_orders_by_id(
            self, order_by):
        order_by.return_value = [
            SimpleNamespace(
                id=1,
                name='117信息科学与技术学院 (软件学院)',
            ),
        ]

        response = SchoolView().get(request=None)

        order_by.assert_called_once_with('id')
        self.assertEqual(response.data['contents']['schools'], [{
            'id': 1,
            'name': '117信息科学与技术学院 (软件学院)',
        }])
