from rest_framework.test import APIRequestFactory, APISimpleTestCase

from utils.custom_pagination import StandardResultsSetPagination


class PaginationEdgeCaseTests(APISimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.paginator = StandardResultsSetPagination()

    def get_page_size(self, query_string):
        request = self.factory.get('/test/' + query_string)
        request.query_params = request.GET
        return self.paginator.get_page_size(request)

    def test_page_size_is_clamped_to_safe_bounds(self):
        self.assertEqual(self.get_page_size('?pageSize=0'), 1)
        self.assertEqual(self.get_page_size('?pageSize=-10'), 1)
        self.assertEqual(self.get_page_size('?pageSize=10000'), 100)

    def test_invalid_page_size_uses_default(self):
        self.assertEqual(self.get_page_size('?pageSize=invalid'), 10)
        self.assertEqual(self.get_page_size('?page_size=invalid'), 10)
