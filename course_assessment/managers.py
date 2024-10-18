from django.contrib.postgres.search import TrigramSimilarity, SearchVector, SearchQuery
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import models
from pypinyin import lazy_pinyin

from utils.models import SoftDeleteManager


class SearchModuleErrorException(Exception):
    def __init__(self, message="There is an error"):
        self.message = message
        super().__init__(self.message)


class SearchQuerySet(models.QuerySet):
    def search(self, query, query_table_name, select_related_fields=None, prefetch_related_fields=None):
        pinyin_query = ''.join(lazy_pinyin(query))
        vector = SearchVector(query_table_name, weight='A') + SearchVector('pinyin', weight='B')
        search_query = SearchQuery(query) | SearchQuery(pinyin_query)
        name_field = f"{query_table_name}__icontains"
        queryset = self.annotate(
            search=vector
        ).filter(
            models.Q(search=search_query) |
            models.Q(**{name_field: query}) |
            models.Q(pinyin__icontains=pinyin_query)
        ).annotate(
            rank=TrigramSimilarity(query_table_name, query) +
                 TrigramSimilarity('pinyin', pinyin_query)
        ).order_by('-rank')

        if select_related_fields:
            queryset = queryset.select_related(*select_related_fields)
        if prefetch_related_fields:
            queryset = queryset.prefetch_related(*prefetch_related_fields)

        return queryset


class SearchManager(models.Manager):
    def get_queryset(self):
        return SearchQuerySet(self.model, using=self._db)

    def search(self, query, page_size=10, current_page=1, select_related_fields=None, prefetch_related_fields=None):
        query_model_table_name_dict = {
            'course': 'name',
            'teacher': 'name',
            'review': 'content'
        }
        query_table_name = query_model_table_name_dict.get(self.model._meta.model_name, None)
        if query_table_name is None:
            raise SearchModuleErrorException('Invalid module')
        search_results = self.get_queryset().search(query, query_table_name, select_related_fields,
                                                    prefetch_related_fields)
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


class SoftDeleteSearchManager(SoftDeleteManager, SearchManager):
    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset
