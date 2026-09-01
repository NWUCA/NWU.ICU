from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import F
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated

from utils.custom_pagination import StandardResultsSetPagination
from utils.throttle import CaptchaUserRateThrottle
from utils.utils import get_user_avatar_info, return_response

from .models import GuestbookEntry, GuestbookLike, GuestbookReport
from .serializers import (
    GuestbookContentSerializer,
    GuestbookLikeSerializer,
    GuestbookReplySerializer,
    GuestbookReportSerializer,
)

DELETED_CONTENT = '[内容已删除]'


def entry_author(entry, request):
    if entry.anonymous:
        return {
            'id': None,
            'nickname': '匿名用户',
            'avatar': str(settings.ANONYMOUS_USER_AVATAR_UUID),
            'has_avatar': True,
        }
    return {
        'id': entry.author_id,
        'nickname': entry.author.nickname,
        **get_user_avatar_info(entry.author),
    }


def serialize_entry(entry, request, *, include_reply_count=True):
    is_authenticated = bool(request.user and request.user.is_authenticated)
    payload = {
        'id': entry.id,
        'root_id': entry.root_id,
        'parent_id': entry.parent_id,
        'content': DELETED_CONTENT if entry.is_deleted else entry.content,
        'anonymous': entry.anonymous,
        'is_deleted': entry.is_deleted,
        'created_at': entry.created_at,
        'like_count': entry.like_count,
        'author': entry_author(entry, request),
        'is_me': is_authenticated and entry.author_id == request.user.id,
        'liked_by_me': is_authenticated and GuestbookLike.objects.filter(
            entry_id=entry.id, user_id=request.user.id
        ).exists(),
    }
    if include_reply_count:
        root_id = entry.root_id or entry.id
        payload['reply_count'] = GuestbookEntry.all_objects.filter(root_id=root_id).count()
    return payload


def get_entry_or_none(entry_id):
    try:
        return GuestbookEntry.all_objects.select_related('author', 'parent', 'root').get(id=entry_id)
    except GuestbookEntry.DoesNotExist:
        return None


class GuestbookListView(GenericAPIView):
    pagination_class = StandardResultsSetPagination
    permission_classes = [AllowAny]

    def get(self, request):
        entries = GuestbookEntry.all_objects.filter(parent__isnull=True).select_related('author')
        page = self.paginate_queryset(entries)
        return self.get_paginated_response([serialize_entry(entry, request) for entry in page])

    def post(self, request):
        if not request.user.is_authenticated:
            return return_response(errors={'login': {'err_code': 'not_login', 'err_msg': '请先登录'}}, status_code=401)
        serializer = GuestbookContentSerializer(data=request.data)
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        entry = GuestbookEntry.objects.create(author=request.user, **serializer.validated_data)
        return return_response(
            message='留言发布成功', contents={'entry': serialize_entry(entry, request)}, status_code=status.HTTP_201_CREATED
        )

    def get_throttles(self):
        return [CaptchaUserRateThrottle()] if self.request.method == 'POST' else []


class GuestbookDetailView(GenericAPIView):
    permission_classes = [AllowAny]
    def get(self, request, entry_id):
        entry = get_entry_or_none(entry_id)
        if entry is None:
            return return_response(errors={'entry': {'err_code': 'not_found', 'err_msg': '留言不存在'}}, status_code=404)
        root = entry.root if entry.root_id else entry
        return return_response(contents={'entry': serialize_entry(root, request)})

    def delete(self, request, entry_id):
        if not request.user.is_authenticated:
            return return_response(errors={'login': {'err_code': 'not_login', 'err_msg': '请先登录'}}, status_code=401)
        entry = get_entry_or_none(entry_id)
        if entry is None:
            return return_response(errors={'entry': {'err_code': 'not_found', 'err_msg': '留言不存在'}}, status_code=404)
        if entry.author_id != request.user.id:
            return return_response(errors={'auth': {'err_code': 'auth_error', 'err_msg': '无权删除此内容'}}, status_code=403)
        if not entry.is_deleted:
            entry.soft_delete()
        return return_response(message='留言已删除', contents={'entry_id': entry.id})


class GuestbookRepliesView(GenericAPIView):
    pagination_class = StandardResultsSetPagination
    permission_classes = [AllowAny]

    def get(self, request, entry_id):
        parent = get_entry_or_none(entry_id)
        if parent is None:
            return return_response(errors={'entry': {'err_code': 'not_found', 'err_msg': '留言不存在'}}, status_code=404)
        entries = GuestbookEntry.all_objects.filter(parent_id=parent.id).select_related('author').order_by('created_at', 'id')
        page = self.paginate_queryset(entries)
        return self.get_paginated_response([serialize_entry(entry, request, include_reply_count=False) for entry in page])

    def post(self, request, entry_id):
        if not request.user.is_authenticated:
            return return_response(errors={'login': {'err_code': 'not_login', 'err_msg': '请先登录'}}, status_code=401)
        parent = get_entry_or_none(entry_id)
        if parent is None:
            return return_response(errors={'entry': {'err_code': 'not_found', 'err_msg': '留言不存在'}}, status_code=404)
        if parent.is_deleted:
            return return_response(errors={'entry': {'err_code': 'deleted', 'err_msg': '已删除内容不能继续回复'}}, status_code=400)
        serializer = GuestbookReplySerializer(data=request.data)
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        root_id = parent.root_id or parent.id
        entry = GuestbookEntry.objects.create(
            author=request.user, parent=parent, root_id=root_id, anonymous=False, **serializer.validated_data
        )
        return return_response(
            message='回复发布成功', contents={'entry': serialize_entry(entry, request, include_reply_count=False)},
            status_code=status.HTTP_201_CREATED,
        )

    def get_throttles(self):
        return [CaptchaUserRateThrottle()] if self.request.method == 'POST' else []


class GuestbookContextView(GenericAPIView):
    permission_classes = [AllowAny]
    def get(self, request, entry_id):
        entry = get_entry_or_none(entry_id)
        if entry is None:
            return return_response(errors={'entry': {'err_code': 'not_found', 'err_msg': '留言不存在'}}, status_code=404)
        path = []
        current = entry
        while current is not None:
            path.append(current.id)
            current = current.parent
        return return_response(contents={'root_id': entry.root_id or entry.id, 'path': list(reversed(path))})


class GuestbookLikeView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, entry_id):
        entry = get_entry_or_none(entry_id)
        if entry is None:
            return return_response(errors={'entry': {'err_code': 'not_found', 'err_msg': '留言不存在'}}, status_code=404)
        if entry.is_deleted:
            return return_response(errors={'entry': {'err_code': 'deleted', 'err_msg': '已删除内容不能点赞'}}, status_code=400)
        serializer = GuestbookLikeSerializer(data=request.data)
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        liked = serializer.validated_data['liked']
        try:
            with transaction.atomic():
                if liked:
                    _, created = GuestbookLike.objects.get_or_create(entry=entry, user=request.user)
                    if created:
                        GuestbookEntry.all_objects.filter(id=entry.id).update(like_count=F('like_count') + 1)
                else:
                    deleted, _ = GuestbookLike.objects.filter(entry=entry, user=request.user).delete()
                    if deleted:
                        GuestbookEntry.all_objects.filter(id=entry.id, like_count__gt=0).update(like_count=F('like_count') - 1)
        except IntegrityError:
            pass
        entry.refresh_from_db(fields=('like_count',))
        return return_response(contents={'liked': liked, 'like_count': entry.like_count})


class GuestbookReportView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, entry_id):
        entry = get_entry_or_none(entry_id)
        if entry is None or entry.is_deleted:
            return return_response(errors={'entry': {'err_code': 'not_found', 'err_msg': '留言不存在'}}, status_code=404)
        serializer = GuestbookReportSerializer(data=request.data)
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        report, created = GuestbookReport.objects.get_or_create(
            entry=entry, reporter=request.user, defaults=serializer.validated_data
        )
        return return_response(
            message='举报已提交' if created else '你已经举报过此内容',
            contents={'report_id': report.id, 'created': created},
            status_code=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )
