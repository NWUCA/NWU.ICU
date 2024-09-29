from django.contrib.postgres.search import TrigramSimilarity, SearchVector, SearchQuery
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import models
from pypinyin import lazy_pinyin


class SearchQuerySet(models.QuerySet):
    def search(self, query):
        pinyin_query = ''.join(lazy_pinyin(query))
        vector = SearchVector('name', weight='A') + SearchVector('pinyin', weight='B')
        search_query = SearchQuery(query) | SearchQuery(pinyin_query)
        return self.annotate(
            search=vector
        ).filter(
            models.Q(search=search_query) |
            models.Q(name__icontains=query) |
            models.Q(pinyin__icontains=pinyin_query)
        ).annotate(
            rank=TrigramSimilarity('name', query) +
                 TrigramSimilarity('pinyin', pinyin_query)
        ).order_by('-rank')


class SearchManager(models.Manager):
    def get_queryset(self):
        return SearchQuerySet(self.model, using=self._db)

    def search(self, query, page_size=10, current_page=1):
        search_results = self.get_queryset().search(query)
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
