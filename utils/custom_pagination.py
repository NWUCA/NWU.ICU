from rest_framework.pagination import PageNumberPagination

from utils.utils import return_response


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'pageSize'
    max_page_size = 100

    def get_page_size(self, request):
        page_size = request.query_params.get(self.page_size_query_param, None)
        if page_size is None:
            page_size = request.query_params.get('page_size', self.page_size)
        try:
            return min(int(page_size), self.max_page_size)
        except (TypeError, ValueError):
            pass

    def get_paginated_response(self, data):
        return return_response(contents={
            'page': self.page.number,
            'max_page': self.page.paginator.num_pages,
            'count': self.page.paginator.count,
            'results': data
        })
