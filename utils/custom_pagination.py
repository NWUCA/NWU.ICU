from rest_framework.pagination import PageNumberPagination

from utils.utils import return_response


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'
    max_page_size = 100

    def get_paginated_response(self, data):
        return return_response(contents={
            'page': self.page.number,
            'max_page': self.page.paginator.num_pages,
            'count': self.page.paginator.count,
            'results': data
        })
