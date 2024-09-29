from django.contrib.contenttypes.models import ContentType
from django.contrib.postgres.search import TrigramSimilarity, SearchVector, SearchQuery
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import models
from pypinyin import lazy_pinyin


class SearchModuleErrorException(Exception):

    def __init__(self, message="There is an error"):
        self.message = message
        super().__init__(self.message)


class SearchQuerySet(models.QuerySet):
    def search(self, query, query_table_name):
        pinyin_query = ''.join(lazy_pinyin(query))
        vector = SearchVector(query_table_name, weight='A') + SearchVector('pinyin', weight='B')
        search_query = SearchQuery(query) | SearchQuery(pinyin_query)
        name_field = f"{query_table_name}__icontains"
        return self.annotate(
            search=vector
        ).filter(
            models.Q(search=search_query) |
            models.Q(**{name_field: query}) |
            models.Q(pinyin__icontains=pinyin_query)
        ).annotate(
            rank=TrigramSimilarity(query_table_name, query) +
                 TrigramSimilarity('pinyin', pinyin_query)
        ).order_by('-rank')


class SearchManager(models.Manager):
    def get_queryset(self):
        return SearchQuerySet(self.model, using=self._db)

    def search(self, query, page_size=10, current_page=1):
        query_model_table_name_dict = {
            'course': 'name',
            'teacher': 'name',
            'review': 'content'
        }
        query_table_name = query_model_table_name_dict.get(self.model._meta.model_name, None)
        if query_model_table_name_dict is None:
            raise SearchModuleErrorException('Invalid module')
        search_results = self.get_queryset().search(query, query_table_name)
        paginator = Paginator(search_results, page_size)
        try:
            paginated_results = paginator.page(current_page)
        except PageNotAnInteger:
            paginated_results = paginator.page(1)
        except EmptyPage:
            paginated_results = paginator.page(paginator.num_pages)

        return {
            'results': list(paginated_results),
            'total_pages': paginator.num_pages,
            'current_page': paginated_results.number,
            'has_next': paginated_results.has_next(),
            'has_previous': paginated_results.has_previous(),
            'total_count': paginator.count
        }
