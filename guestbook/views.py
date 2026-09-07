from django.conf import settings
from django.db import transaction
from django.db.models import Count, Exists, F, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated

from utils.custom_pagination import StandardResultsSetPagination
from utils.throttle import CaptchaUserRateThrottle
from utils.utils import get_user_avatar_info, return_response

from .models import GuestbookEntry, GuestbookLike, GuestbookReport
from .notifications import notify_guestbook_like, notify_guestbook_reply
from .submissions import create_submission, previous_submission
from .serializers import (
    AnnouncementContentSerializer,
    GuestbookContentSerializer,
    GuestbookLikeSerializer,
    GuestbookReplySerializer,
    GuestbookReportSerializer,
)

DELETED_CONTENT = '[内容已删除]'


def with_entry_counts(entries, request):
    children = GuestbookEntry.all_objects.filter(parent_id=OuterRef('pk')).order_by().values('parent_id')
    descendants = GuestbookEntry.all_objects.filter(root_id=OuterRef('pk')).order_by().values('root_id')
    likes = GuestbookLike.objects.filter(entry_id=OuterRef('pk'), user_id=request.user.pk)
    return entries.select_related('author').annotate(
        children_count=Coalesce(Subquery(children.annotate(n=Count('pk')).values('n')), 0, output_field=IntegerField()),
        descendant_count=Coalesce(Subquery(descendants.annotate(n=Count('pk')).values('n')), 0, output_field=IntegerField()),
        current_user_liked=Exists(likes) if request.user.is_authenticated else Value(False),
    )


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
    children_count = getattr(entry, 'children_count', None)
    if children_count is None:
        children_count = GuestbookEntry.all_objects.filter(parent_id=entry.id).count()
    liked = getattr(entry, 'current_user_liked', None)
    if liked is None:
        liked = is_authenticated and GuestbookLike.objects.filter(entry_id=entry.id, user_id=request.user.id).exists()
    payload = {
        'id': entry.id,
        'root_id': entry.root_id,
        'parent_id': entry.parent_id,
        'title': entry.title,
        'content': DELETED_CONTENT if entry.is_deleted else entry.content,
        'anonymous': entry.anonymous,
        'is_deleted': entry.is_deleted,
        'created_at': entry.created_at,
        'like_count': entry.like_count,
        'author': entry_author(entry, request),
        'is_me': is_authenticated and entry.author_id == request.user.id,
        'liked_by_me': liked,
        'children_count': children_count,
    }
    if include_reply_count:
        total = getattr(entry, 'descendant_count', None)
        payload['reply_count'] = (
            (total if total is not None else GuestbookEntry.all_objects.filter(root_id=entry.id).count())
            if entry.is_root else children_count
        )
    return payload


def get_entry_or_none(entry_id, *, lock=False, board=None):
    try:
        entries = GuestbookEntry.all_objects.select_related('author', 'parent', 'root')
        if lock:
            entries = entries.select_for_update(of=('self',))
        if board is not None:
            entries = entries.filter(board=board)
        return entries.get(id=entry_id)
    except GuestbookEntry.DoesNotExist:
        return None


class GuestbookListView(GenericAPIView):
    pagination_class = StandardResultsSetPagination
    permission_classes = [AllowAny]
    board = GuestbookEntry.BOARD_GUESTBOOK
    board_label = '留言'

    def get(self, request):
        entries = with_entry_counts(GuestbookEntry.all_objects.filter(parent__isnull=True, board=self.board), request)
        page = self.paginate_queryset(entries)
        return self.get_paginated_response([serialize_entry(entry, request) for entry in page])

    def post(self, request):
        if not request.user.is_authenticated:
            return return_response(errors={'login': {'err_code': 'not_login', 'err_msg': '请先登录'}}, status_code=401)
        if self.board == GuestbookEntry.BOARD_ANNOUNCEMENT and not request.user.is_staff:
            return return_response(
                errors={'auth': {'err_code': 'auth_error', 'err_msg': '仅管理员可以发布公告'}}, status_code=403
            )
        serializer_class = (
            AnnouncementContentSerializer
            if self.board == GuestbookEntry.BOARD_ANNOUNCEMENT
            else GuestbookContentSerializer
        )
        serializer = serializer_class(data=request.data)
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        if self.board == GuestbookEntry.BOARD_ANNOUNCEMENT:
            data = {**data, 'anonymous': False}
        entry, _ = create_submission(request.user, data, board=self.board)
        return return_response(
            message=f'{self.board_label}发布成功', contents={'entry': serialize_entry(entry, request)}, status_code=status.HTTP_201_CREATED
        )

    def get_throttles(self):
        return [CaptchaUserRateThrottle()] if self.request.method == 'POST' else []


class GuestbookDetailView(GenericAPIView):
    permission_classes = [AllowAny]
    board = GuestbookEntry.BOARD_GUESTBOOK
    board_label = '留言'
    def get(self, request, entry_id):
        entry = get_entry_or_none(entry_id, board=self.board)
        if entry is None:
            return return_response(errors={'entry': {'err_code': 'not_found', 'err_msg': '留言不存在'}}, status_code=404)
        root = entry.root if entry.root_id else entry
        return return_response(contents={'entry': serialize_entry(root, request)})

    def delete(self, request, entry_id):
        if not request.user.is_authenticated:
            return return_response(errors={'login': {'err_code': 'not_login', 'err_msg': '请先登录'}}, status_code=401)
        entry = get_entry_or_none(entry_id, board=self.board)
        if entry is None:
            return return_response(errors={'entry': {'err_code': 'not_found', 'err_msg': '留言不存在'}}, status_code=404)
        if entry.author_id != request.user.id:
            return return_response(errors={'auth': {'err_code': 'auth_error', 'err_msg': '无权删除此内容'}}, status_code=403)
        if not entry.is_deleted:
            entry.soft_delete()
        return return_response(message=f'{self.board_label}已删除', contents={'entry_id': entry.id})


class GuestbookRepliesView(GenericAPIView):
    pagination_class = StandardResultsSetPagination
    permission_classes = [AllowAny]
    board = GuestbookEntry.BOARD_GUESTBOOK

    def get(self, request, entry_id):
        parent = get_entry_or_none(entry_id, board=self.board)
        if parent is None:
            return return_response(errors={'entry': {'err_code': 'not_found', 'err_msg': '留言不存在'}}, status_code=404)
        entries = with_entry_counts(GuestbookEntry.all_objects.filter(parent_id=parent.id), request).order_by('created_at', 'id')
        page = self.paginate_queryset(entries)
        return self.get_paginated_response([serialize_entry(entry, request) for entry in page])

    @transaction.atomic
    def post(self, request, entry_id):
        if not request.user.is_authenticated:
            return return_response(errors={'login': {'err_code': 'not_login', 'err_msg': '请先登录'}}, status_code=401)
        parent = get_entry_or_none(entry_id, lock=True, board=self.board)
        if parent is None:
            return return_response(errors={'entry': {'err_code': 'not_found', 'err_msg': '留言不存在'}}, status_code=404)
        serializer = GuestbookReplySerializer(data=request.data)
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        entry = previous_submission(request.user, serializer.validated_data, parent, self.board)
        if not entry:
            if parent.is_deleted:
                return return_response(errors={'entry': {'err_code': 'deleted', 'err_msg': '已删除内容不能继续回复'}}, status_code=400)
            entry, created = create_submission(request.user, serializer.validated_data, parent, self.board)
            if created:
                notify_guestbook_reply(entry)
        return return_response(
            message='回复发布成功', contents={'entry': serialize_entry(entry, request, include_reply_count=False)},
            status_code=status.HTTP_201_CREATED,
        )

    def get_throttles(self):
        return [CaptchaUserRateThrottle()] if self.request.method == 'POST' else []


class GuestbookContextView(GenericAPIView):
    permission_classes = [AllowAny]
    board = GuestbookEntry.BOARD_GUESTBOOK
    def get(self, request, entry_id):
        entry = get_entry_or_none(entry_id, board=self.board)
        if entry is None:
            return return_response(errors={'entry': {'err_code': 'not_found', 'err_msg': '留言不存在'}}, status_code=404)
        path = []
        current = entry
        while current is not None and current.id not in path:
            path.append(current.id)
            current = current.parent
        path.reverse()
        entries = with_entry_counts(GuestbookEntry.all_objects.filter(id__in=path), request).in_bulk()
        return return_response(contents={
            'root_id': entry.root_id or entry.id,
            'path': path,
            'entries': [serialize_entry(entries[entry_id], request) for entry_id in path],
        })


class GuestbookLikeView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    board = GuestbookEntry.BOARD_GUESTBOOK

    @transaction.atomic
    def put(self, request, entry_id):
        entry = get_entry_or_none(entry_id, lock=True, board=self.board)
        if entry is None:
            return return_response(errors={'entry': {'err_code': 'not_found', 'err_msg': '留言不存在'}}, status_code=404)
        if entry.is_deleted:
            return return_response(errors={'entry': {'err_code': 'deleted', 'err_msg': '已删除内容不能点赞'}}, status_code=400)
        serializer = GuestbookLikeSerializer(data=request.data)
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        liked = serializer.validated_data['liked']
        if liked:
            _, changed = GuestbookLike.objects.get_or_create(entry=entry, user=request.user)
            if changed:
                GuestbookEntry.all_objects.filter(id=entry.id).update(like_count=F('like_count') + 1)
        else:
            changed, _ = GuestbookLike.objects.filter(entry=entry, user=request.user).delete()
            if changed:
                GuestbookEntry.all_objects.filter(id=entry.id, like_count__gt=0).update(like_count=F('like_count') - 1)
        entry.refresh_from_db(fields=('like_count',))
        if changed:
            notify_guestbook_like(entry, mark_unread=liked and request.user.id != entry.author_id)
        return return_response(contents={'liked': liked, 'like_count': entry.like_count})


class GuestbookReportView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    board = GuestbookEntry.BOARD_GUESTBOOK

    def post(self, request, entry_id):
        entry = get_entry_or_none(entry_id, board=self.board)
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


class AnnouncementListView(GuestbookListView):
    board = GuestbookEntry.BOARD_ANNOUNCEMENT
    board_label = '公告'

    def post(self, request):
        return return_response(
            errors={'auth': {'err_code': 'management_required', 'err_msg': '请通过管理员面板发布公告'}},
            status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        )


class AnnouncementDetailView(GuestbookDetailView):
    board = GuestbookEntry.BOARD_ANNOUNCEMENT
    board_label = '公告'

    def delete(self, request, entry_id):
        entry = get_entry_or_none(entry_id, board=self.board)
        if entry is not None and entry.is_root:
            return return_response(
                errors={'auth': {'err_code': 'management_required', 'err_msg': '公告只能通过管理员后台删除'}},
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return super().delete(request, entry_id)


class AnnouncementRepliesView(GuestbookRepliesView):
    board = GuestbookEntry.BOARD_ANNOUNCEMENT


class AnnouncementContextView(GuestbookContextView):
    board = GuestbookEntry.BOARD_ANNOUNCEMENT


class AnnouncementLikeView(GuestbookLikeView):
    board = GuestbookEntry.BOARD_ANNOUNCEMENT


class AnnouncementReportView(GuestbookReportView):
    board = GuestbookEntry.BOARD_ANNOUNCEMENT

    def post(self, request, entry_id):
        entry = get_entry_or_none(entry_id, board=self.board)
        if entry is not None and entry.is_root:
            return return_response(
                errors={'auth': {'err_code': 'auth_error', 'err_msg': '公告不能被举报'}}, status_code=403
            )
        return super().post(request, entry_id)
