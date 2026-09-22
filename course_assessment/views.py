import logging
import re
from typing import List

from django.conf import settings
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.status import HTTP_404_NOT_FOUND
from rest_framework.views import APIView

from course_assessment.models import Course, Review, ReviewHistory, School, Teacher, Semeseter, ReviewReply, \
    ReviewAndReplyLike, CourseLike
from course_assessment.permissions import CustomPermission
from course_assessment.serializer import MyReviewSerializer, AddReviewSerializer, AddReviewReplySerializer, \
    DeleteReviewReplySerializer, ReviewAndReplyLikeSerializer, AddCourseSerializer, \
    CourseLikeSerializer, AddTeacherSerializer, DeleteReviewSerializer
from user.models import User
from common.file.references import ensure_file_references, file_lifecycle
from common.models import Notification
from management_panel.telegram_notifications import notify_course_review, notify_course_review_reply
from utils.custom_pagination import StandardResultsSetPagination
from utils.throttle import (
    InteractionAnonRateThrottle,
    InteractionUserRateThrottle,
    CatalogWriteRateThrottle,
    ReplyWriteRateThrottle,
    ReviewWriteRateThrottle,
)
from utils.utils import return_response, get_err_msg, get_msg_msg, userUtils, get_user_avatar_info

logger = logging.getLogger(__name__)


class CourseList(GenericAPIView):
    permission_classes = [CustomPermission]
    pagination_class = StandardResultsSetPagination

    def get(self, request):
        course_type = request.query_params.get('course_type', 'all')
        order_by = request.query_params.get('order_by', 'rating')
        course_type = course_type if course_type in {choice[0] for choice in Course.classification_choices} else 'all'
        order_by = {'rating': '-average_rating', 'popular': '-review_count'}.get(order_by, 'average_rating')
        total_key = 'total_courses_count' + course_type
        total = cache.get(total_key)
        if total is None:
            total = Course.objects.count() if course_type == 'all' else Course.objects.filter(
                classification=course_type).count()
            cache.set(total_key, total, timeout=None)
        courses = Course.objects.select_related('school').prefetch_related('semester', 'teachers')
        if course_type != 'all':
            courses = courses.filter(classification=course_type)
        courses = courses.order_by(order_by, 'like_count')
        course_page = self.paginate_queryset(courses)
        courses_list = [{'id': course.id,
                         'name': course.get_name(),
                         'classification': course.get_classification(),
                         'teacher': course.get_teachers(),
                         'semester': course.get_semester(),
                         'review_count': course.review_count,
                         'average_rating': course.average_rating,
                         'normalized_rating': course.normalized_rating,
                         } for course in course_page]
        return self.get_paginated_response(courses_list)


class CourseView(APIView):
    permission_classes = [CustomPermission]

    def get_throttles(self):
        if self.request.method == 'POST':
            return [CatalogWriteRateThrottle()]
        return []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.user_likes_cache = {}

    def preload_user_likes(self, user, reviews):
        if user.id is None:
            return
        if reviews:
            likes_query = ReviewAndReplyLike.objects.filter(
                created_by=user,
                review__in=reviews
            ).select_related('review', 'review_reply')
            for like in likes_query:
                key = (like.review_id, like.review_reply_id)
                self.user_likes_cache[key] = like.like

    def get_user_option(self, review, user, reply=None, course=None):
        if user.id is None:
            return 0
        if course is not None:
            try:
                user_review_option = CourseLike.objects.get(course=course, created_by=user).like
            except (CourseLike.DoesNotExist, AttributeError):
                user_review_option = 0
            return user_review_option
        key = (review.id, reply.id if reply else None)
        return self.user_likes_cache.get(key, 0)

    def get(self, request, course_id):
        try:
            course = (Course.objects
                      .select_related('school', 'created_by')
                      .prefetch_related('teachers', 'semester', 'teachers__school')
                      .get(id=course_id))
        except Course.DoesNotExist:
            return return_response(errors={'course': get_err_msg('course_not_exist')},
                                   status_code=status.HTTP_404_NOT_FOUND)
        reviews = (Review.all_objects.filter(course_id=course_id)
                   .filter(Q(is_deleted=False) | Q(reviewreply__is_deleted=False))
                   .select_related('created_by', 'semester')
                   .distinct())
        semester_filter = request.query_params.get('semester')
        rating_filter = request.query_params.get('rating')
        if semester_filter:
            try:
                reviews = reviews.filter(semester_id=int(semester_filter), is_deleted=False)
            except ValueError:
                return return_response(errors={'semester': '学期参数不合法'}, status_code=400)
        if rating_filter:
            try:
                rating_value = int(rating_filter)
            except ValueError:
                rating_value = 0
            if rating_value not in range(1, 6):
                return return_response(errors={'rating': '评分参数不合法'}, status_code=400)
            reviews = reviews.filter(rating=rating_value, is_deleted=False)

        sort = request.query_params.get('sort', 'liked')
        ordering = {
            'liked': ('-like_count', '-create_time', '-id'),
            'newest': ('-create_time', '-id'),
            'oldest': ('create_time', 'id'),
            'highest': ('-rating', '-create_time', '-id'),
            'lowest': ('rating', '-create_time', '-id'),
        }.get(sort)
        if ordering is None:
            return return_response(errors={'sort': '排序参数不合法'}, status_code=400)
        reviews = reviews.order_by(*ordering)

        try:
            page_size = max(1, min(int(request.query_params.get('pageSize', 10)), 50))
            page_number = max(1, int(request.query_params.get('page', 1)))
        except ValueError:
            return return_response(errors={'page': '分页参数不合法'}, status_code=400)
        focus_review_id = request.query_params.get('focus_review_id')
        focus_reply_id = request.query_params.get('focus_reply_id')
        if focus_reply_id and not focus_review_id:
            try:
                focus_review_id = ReviewReply.all_objects.filter(
                    id=int(focus_reply_id), review__course_id=course_id,
                ).values_list('review_id', flat=True).first()
            except ValueError:
                return return_response(errors={'focus_reply_id': '回复参数不合法'}, status_code=400)
        if focus_review_id:
            try:
                focus_review_id = int(focus_review_id)
                ordered_ids = list(reviews.values_list('id', flat=True))
                if focus_review_id in ordered_ids:
                    page_number = ordered_ids.index(focus_review_id) // page_size + 1
            except ValueError:
                return return_response(errors={'focus_review_id': '评价参数不合法'}, status_code=400)
        paginator = Paginator(reviews, page_size)
        review_page = paginator.get_page(page_number)
        reviews = list(review_page.object_list)
        self.preload_user_likes(request.user, reviews=reviews)
        try:
            if not request.user.is_anonymous:
                request_user_review = Review.objects.get(course_id=course_id, created_by=request.user)
                request_user_review_id = request_user_review.id
                request_user_review_data = {
                    'id': request_user_review.id,
                    'content': request_user_review.content,
                    'rating': request_user_review.rating,
                    'anonymous': request_user_review.anonymous,
                    'difficulty': request_user_review.difficulty,
                    'grade': request_user_review.grade,
                    'homework': request_user_review.homework,
                    'reward': request_user_review.reward,
                    'semester': request_user_review.semester_id,
                }
            else:
                request_user_review_id = None
                request_user_review_data = None
        except Review.DoesNotExist:
            request_user_review_id = None
            request_user_review_data = None
        reviews_data = []
        for review in reviews:
            reply_queryset = ReviewReply.all_objects.filter(review=review).select_related(
                'created_by', 'parent').order_by('id')
            reply_count = reply_queryset.count()
            review_replies: List[ReviewReply] = list(reply_queryset[:20])
            reviews_data.append({
                'id': review.id,
                'is_deleted': review.is_deleted,
                'content': '内容已被删除' if review.is_deleted else review.content,
                'rating': review.rating,
                'modified_time': review.modify_time,
                'created_time': review.create_time,
                'edited': review.edited,
                'like': {'like': review.like_count,
                         'dislike': review.dislike_count,
                         'user_option': self.get_user_option(review=review, user=request.user)},
                'difficulty': review.difficulty,
                'grade': review.grade,
                'homework': review.homework,
                'reward': review.reward,
                'semester': review.semester.name,
                'author': ({
                    'id': 0,
                    'nickname': '已删除用户',
                    'avatar': '',
                    'anonymous': True,
                } if review.is_deleted else {'id': -1 if (
                        review.anonymous and review.created_by.id != request.user.id) else review.created_by.id,
                           'nickname': get_msg_msg(
                               'anonymous_user_nickname') if review.anonymous else review.created_by.nickname,
                           'avatar': settings.ANONYMOUS_USER_AVATAR_UUID if review.anonymous else review.created_by.avatar_uuid,
                           'anonymous': review.anonymous,
                           **({} if review.anonymous else {
                               'uuid': review.created_by.uuid,
                               'has_avatar': str(review.created_by.avatar_uuid) != str(settings.DEFAULT_USER_AVATAR_UUID),
                           })}),
                'reply': [{'id': reviewReply.id,
                           'floor_number': index + 1,
                           'content': reviewReply.content if not reviewReply.is_deleted else "内容已删除",
                           'created_time': reviewReply.create_time,
                           'parent': 0 if (reviewReply.parent is None) else reviewReply.parent.id,
                           'created_by': {'id': reviewReply.created_by.id if not reviewReply.is_deleted else 0,
                                          'name': reviewReply.created_by.nickname if not reviewReply.is_deleted else "未知用户",
                                          **(get_user_avatar_info(reviewReply.created_by)
                                             if not reviewReply.is_deleted else {'avatar': ""})},
                           'like': {'like': reviewReply.like_count,
                                    'dislike': reviewReply.dislike_count,
                                    'user_option': self.get_user_option(
                                        review=review, reply=reviewReply, user=request.user)},
                           'is_deleted': reviewReply.is_deleted, }
                          for index, reviewReply in enumerate(review_replies)],
                'reply_count': reply_count,
                'reply_next_cursor': review_replies[-1].id if reply_count > len(review_replies) else None,
            })
        teachers_data = []
        for teacher in course.teachers.all():
            teachers_data.append({
                'id': teacher.id,
                'avatar_uuid': teacher.avatar_uuid,
                'name': teacher.name,
                'school': teacher.school.get_name() if teacher.school else None,
                'course': [{'id': course.id, 'name': course.get_name()} for course in
                           Course.objects.filter(teachers__id=teacher.id) if course.id != course_id]
            })
        course_info = {
            'id': course_id,
            'code': course.course_code,
            'name': course.get_name(),
            'category': course.get_classification_display(),
            'teachers': teachers_data,
            'semester': [semester.name for semester in course.semester.all()],
            'school': course.school.get_name(),
            'like': {'like': course.like_count, 'dislike': course.dislike_count,
                     'user_option': self.get_user_option(review=None, course=course, user=request.user)},
            'rating_avg': f"{course.average_rating:.1f}",
            'normalized_rating_avg': f"{course.normalized_rating:.1f}",
            'request_user_review_id': request_user_review_id,
            'request_user_review': request_user_review_data,
            'total_review_count': Review.objects.filter(course_id=course_id).count(),
            'reviews': {
                'page': review_page.number,
                'max_page': paginator.num_pages,
                'count': paginator.count,
                'results': reviews_data,
                'facets': {
                    'semesters': list(
                        Review.objects.filter(course_id=course_id)
                        .values('semester_id', 'semester__name')
                        .annotate(count=Count('id')).order_by('-semester__name')
                    ),
                    'ratings': list(
                        Review.objects.filter(course_id=course_id)
                        .values('rating').annotate(count=Count('id')).order_by('-rating')
                    ),
                },
            },
            'other_dup_name_course': [
                {'course_id': course.id, 'teacher_name': course.get_teachers(), 'rating': course.normalized_rating} for
                course in
                Course.objects.filter(name=course.get_name()) if course.id != course_id]
        }
        return return_response(contents=course_info)

    def post(self, request):
        serializer = AddCourseSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            course = serializer.create(serializer.validated_data)
            return return_response(message=get_msg_msg('course_create_success'), contents={'course_id': course.id})
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class SchoolView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        schools = list(School.objects.order_by('id'))

        numbered_schools = []
        unnumbered_schools = []
        for school in schools:
            number_match = re.match(r'^\d+', school.name)
            if number_match:
                numbered_schools.append((int(number_match.group()), school))
            else:
                unnumbered_schools.append(school)

        numbered_schools.sort(key=lambda item: item[0])
        schools = [school for _, school in numbered_schools] + unnumbered_schools
        return return_response(
            contents={
                'schools': [
                    {'id': school.id, 'name': school.name}
                    for school in schools
                ]
            },
        )


class LatestReviewView(GenericAPIView):
    review_model = Review
    permission_classes = [AllowAny]
    pagination_class = StandardResultsSetPagination

    def get(self, request):
        desc = request.query_params.get('desc', '1')
        review_all_set = Review.objects.all().order_by(('-' if desc == '1' else '') + 'modify_time').select_related(
            'created_by', 'course', 'course__school').prefetch_related('course__teachers')

        page = self.paginate_queryset(review_all_set)
        if page is not None:
            review_list = self.get_paginated_response(self.build_review_list(page, request.user))
            return review_list

        return return_response(errors={'review': get_err_msg('review_not_exist')})

    def build_review_list(self, review_page, user):
        user_options = {}
        if user.is_authenticated:
            user_options = dict(
                ReviewAndReplyLike.objects.filter(
                    created_by=user,
                    review__in=review_page,
                    review_reply__isnull=True,
                ).values_list('review_id', 'like')
            )

        review_list = []
        for review in review_page:
            review_list.append({
                'id': review.id,
                'author': userUtils.get_user_info_in_review(review),
                'datetime': review.modify_time,
                'course': {
                    "name": review.course.get_name(),
                    "id": review.course.id,
                    'semester': review.semester.name,
                },
                'content': review.content,
                "teachers": [{"name": teacher.name, "id": teacher.id} for teacher in review.course.teachers.all()],
                'like': {
                    'like': review.like_count,
                    'dislike': review.dislike_count,
                    'user_option': user_options.get(review.id, 0),
                },
                'edited': review.edited,
            })
        return review_list


class ReviewView(APIView):
    review_history_model = ReviewHistory
    permission_classes = [CustomPermission]

    def get_throttles(self):
        if self.request.method in {'POST', 'PUT'}:
            return [ReviewWriteRateThrottle()]
        return []

    @file_lifecycle()
    def put(self, request):
        serializer = AddReviewSerializer(data=request.data)
        if serializer.is_valid():
            course = Course.objects.get(id=serializer.data['course'])
            semester = Semeseter.objects.get(id=serializer.data['semester'])
            try:
                review = Review.objects.select_for_update().get(course=course, created_by=request.user)
            except Review.DoesNotExist:
                return return_response(contents={'review': get_err_msg('review_not_exist')},
                                       status_code=HTTP_404_NOT_FOUND)
            fields_to_update = ['content', 'rating', 'anonymous', 'difficulty', 'grade', 'homework', 'reward']
            new_values = {field: serializer.validated_data[field] for field in fields_to_update}
            new_values['semester'] = semester
            if all(getattr(review, field) == value for field, value in new_values.items()):
                return return_response(message=get_msg_msg('review_update_success'), contents={'review_id': review.id})

            ensure_file_references(new_values['content'], previous_content=review.content)
            ReviewHistory.objects.create(review=review, content=review.content, is_deleted=False)
            for field in fields_to_update:
                setattr(review, field, new_values[field])
            review.semester = semester
            review.edited = True
            review.save()
            return return_response(message=get_msg_msg('review_update_success'), contents={'review_id': review.id})
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

    @file_lifecycle()
    def post(self, request):
        serializer = AddReviewSerializer(data=request.data)
        if serializer.is_valid():
            course = Course.objects.get(id=serializer.data['course'])
            semester = Semeseter.objects.get(id=serializer.data['semester'])
            try:
                review = Review.objects.get(course=course, created_by=request.user)
            except Review.DoesNotExist:
                ensure_file_references(serializer.validated_data['content'])
                review = Review.objects.create(
                    course=course,
                    content=serializer.data['content'],
                    created_by=request.user,
                    rating=serializer.data['rating'],
                    anonymous=serializer.data['anonymous'],
                    edited=False,
                    difficulty=serializer.data['difficulty'],
                    grade=serializer.data['grade'],
                    homework=serializer.data['homework'],
                    reward=serializer.data['reward'],
                    semester=semester,
                )
                if semester not in course.semester.all():
                    course.semester.add(semester)
                notify_course_review(review)
                return return_response(message=get_msg_msg('review_create_success'), contents={'review_id': review.id})
            return return_response(contents={'review': review.id}, errors={'review': get_err_msg('review_has_exist')},
                                   status_code=HTTP_404_NOT_FOUND)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

    @file_lifecycle()
    def delete(self, request):
        serializer = DeleteReviewSerializer(data=request.data)
        if serializer.is_valid():
            review = Review.objects.select_for_update().get(id=serializer.validated_data['review_id'])
            if review.created_by == request.user:
                review.soft_delete()
                review_history_items = self.review_history_model.objects.filter(review_id=review.id)
                for review_history_item in review_history_items:
                    review_history_item.soft_delete()
                # Replies belong to their own authors, so deleting the review keeps
                # the full reply tree. Scrub the deleted text from notification snapshots.
                notification_keys = [f'like:review:{review.id}:{review.created_by_id}']
                notification_keys.extend(
                    f'reply:{reply_id}:{review.created_by_id}'
                    for reply_id in ReviewReply.all_objects.filter(
                        review_id=review.id, parent=None,
                    ).values_list('id', flat=True)
                )
                for notification in Notification.objects.select_for_update().filter(
                        dedupe_key__in=notification_keys):
                    payload = notification.payload
                    raw_post = payload.get('raw_post')
                    if raw_post is None:
                        raw_post = payload.get('raw_info', {}).get('raw_post')
                    if (raw_post and raw_post.get('classify') == 'review'
                            and raw_post.get('id') == review.id):
                        raw_post['content'] = '内容已被删除'
                        notification.payload = payload
                        notification.save(update_fields=('payload', 'updated_at'))
                return return_response(message=get_msg_msg('delete_review_success'), contents={'review_id': review.id})
            else:
                return return_response(errors={"auth": get_err_msg('auth_error')},
                                       status_code=status.HTTP_401_UNAUTHORIZED)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class TeacherView(GenericAPIView):
    model = Teacher
    permission_classes = [CustomPermission]
    pagination_class = StandardResultsSetPagination

    def get_throttles(self):
        if self.request.method == 'POST':
            return [CatalogWriteRateThrottle()]
        return []

    def get_teacher_list(self, school=None):
        if school is None:
            teacher_page = self.paginate_queryset(Teacher.objects.all().select_related('school'))
        else:
            teacher_page = self.paginate_queryset(
                Teacher.objects.filter(school__name__icontains=school).select_related('school'))
        teacher_list = []
        for teacher in teacher_page:
            teacher_list.append(
                {"id": teacher.id, "name": teacher.name,
                 "school": teacher.school.get_name()})
        return self.get_paginated_response(teacher_list)

    def get(self, request, teacher_id=None):
        if teacher_id is None:
            school = request.query_params.get('school', None)
            return self.get_teacher_list(school)
        else:
            try:
                teacher = Teacher.objects.get(id=teacher_id)
            except Teacher.DoesNotExist:
                return return_response(errors={'teacher': get_err_msg('teacher_not_exist')},
                                       status_code=status.HTTP_404_NOT_FOUND)
            teacher_info = {
                'id': teacher.id,
                'name': teacher.name,
                'school': teacher.school.get_name() if teacher.school else None,
            }

            courses = Course.objects.filter(teachers__id=teacher_id)
            teacher_course_list = []
            for course in courses:
                reviews = Review.objects.filter(course=course)
                rating_avg = course.average_rating
                normalized_avg_rating = course.normalized_rating
                review_count = reviews.count()
                teacher_course_list.append({
                    'course': {
                        'id': course.id,
                        'semester': ",".join([semester.name for semester in course.semester.all()]),
                        'code': course.course_code,
                        'name': course.get_name(),
                    },
                    'rating_avg': rating_avg,
                    'normalized_rating_avg': normalized_avg_rating,
                    'review_count': review_count,
                })
            teacher_course_info = {
                'teacher_info': teacher_info,
                "course_list": teacher_course_list
            }
            return return_response(contents=teacher_course_info)

    def post(self, request):
        serializer = AddTeacherSerializer(data=request.data)
        if serializer.is_valid():
            school = School.objects.get(id=serializer.validated_data['school'])
            try:
                Teacher.objects.get(name=serializer.validated_data['name'], school=school)
            except Teacher.DoesNotExist:
                teacher = Teacher.objects.create(name=serializer.validated_data['name'], school=school,
                                                 created_by=request.user)
                return return_response(message=get_msg_msg('teacher_create_success'),
                                       contents={'teacher_id': teacher.id})
            return return_response(errors={"teacher": get_err_msg('teacher_has_exist')}, )
        else:
            return return_response(errors=serializer.errors)


class MyReviewView(GenericAPIView):
    permission_classes = [CustomPermission]
    pagination_class = StandardResultsSetPagination

    @staticmethod
    def user_private(request, user_id, view_type='review'):
        try:
            user = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return return_response(errors={'user': get_err_msg('user_not_exist')},
                                   status_code=status.HTTP_400_BAD_REQUEST)
        private_key = user.private_review if view_type == 'review' else user.private_reply
        if private_key == 2 and request.user.id != user_id:
            return return_response(errors={'review': get_err_msg(f'{view_type}_private')},
                                   status_code=status.HTTP_403_FORBIDDEN)
        if private_key == 1 and request.user.id is None:
            return return_response(errors={'review': get_err_msg(f'{view_type}_login_private')},
                                   status_code=status.HTTP_403_FORBIDDEN)
        return user_id

    def get(self, request, user_id):
        desc = request.query_params.get('desc', '1')
        view_type = {'user_review': 'review', 'user_reply': 'reply'}.get(request.resolver_match.url_name, 'review')
        lookup_user_id = self.user_private(request, user_id, view_type=view_type)
        if type(lookup_user_id) == Response:
            return lookup_user_id
        else:
            is_me = (user_id == request.user.id)
            if view_type == 'review':
                query_set = (
                    Review.objects.filter(created_by=lookup_user_id)
                    .order_by(('-' if desc == '1' else '') + 'modify_time', 'pk')
                    .select_related('created_by', 'course', 'semester')
                    .prefetch_related('course__teachers')
                )
                if not is_me:
                    query_set = query_set.filter(anonymous=False)
            else:
                query_set = (
                    ReviewReply.objects.filter(created_by=lookup_user_id)
                    .order_by(('-' if desc == '1' else '') + 'create_time')
                    .select_related('created_by', 'review')
                )
            page = self.paginate_queryset(query_set)
            if page is not None:
                if view_type == 'review':
                    my_review_list = self.build_my_review_list(page, is_me)
                else:
                    my_review_list = self.build_reply_list(page)
                return self.get_paginated_response(my_review_list)
            return return_response(errors={'review': get_err_msg(f'{view_type}_not_exist')})

    def build_reply_list(self, reply_page):
        my_reply_list = []
        for review_reply in reply_page:
            review_deleted = review_reply.review.is_deleted
            my_reply_list.append({
                'id': review_reply.id,
                'review': {
                    'author': ({
                        'id': 0,
                        'nickname': '已删除用户',
                        'avatar_uuid': '',
                        'is_student': False,
                    } if review_deleted else userUtils.get_user_info_in_review(review_reply.review)),
                    'content': '内容已被删除' if review_deleted else review_reply.review.content,
                    'is_deleted': review_deleted,
                },
                'datetime': review_reply.create_time,
                'course': {"name": review_reply.review.course.get_name(), "id": review_reply.review.course.id,
                           'semester': review_reply.review.semester.name, },
                'reply': {'id': review_reply.id, 'content': review_reply.content},
                'like': {'like': review_reply.like_count, 'dislike': review_reply.dislike_count},
            })
        return my_reply_list

    def build_my_review_list(self, my_review_page, is_me: bool):
        my_review_list = []
        for review in my_review_page:
            if is_me or not review.anonymous:
                content_history = MyReviewSerializer(review).data
                tmp_dict = {
                    'id': review.id,
                    'datetime': review.modify_time,
                    'semester': review.semester.name,
                    'course': {
                        "name": review.course.get_name(),
                        "id": review.course.id,
                        'semester': review.semester.name,
                    },
                    'like': {'like': review.like_count, 'dislike': review.dislike_count},
                    'content': {"current_content": review.content},
                    "teachers": [
                        {"name": teacher.name, "id": teacher.id}
                        for teacher in review.course.teachers.all()
                    ],
                    'rating': {
                        'rating': review.rating,
                        'difficulty': review.difficulty,
                        'grade': review.grade,
                        'homework': review.homework,
                        'reward': review.reward
                    }
                }
                if is_me:
                    tmp_dict['anonymous'] = review.anonymous
                    tmp_dict['content']['content_history'] = [
                        x['content'] for x in content_history['review_history']
                    ]
                my_review_list.append(tmp_dict)
        return my_review_list


class ReviewReplyView(APIView):
    permission_classes = [CustomPermission]

    def get_throttles(self):
        if self.request.method == 'POST':
            return [ReplyWriteRateThrottle()]
        return []

    def get_reply_info(self, reply, user):
        user_option = 0
        if user.is_authenticated:
            user_option = (ReviewAndReplyLike.objects.filter(
                created_by=user, review_reply=reply,
            ).values_list('like', flat=True).first() or 0)
        return {
            "id": reply.id,
            'floor_number': ReviewReply.all_objects.filter(
                review_id=reply.review_id, id__lte=reply.id,
            ).count(),
            "created_time": reply.create_time,
            "content": '内容已删除' if reply.is_deleted else reply.content,
            'created_by': ({'id': 0, 'name': '未知用户', 'avatar': ''}
                           if reply.is_deleted else {
                               'id': reply.created_by.id,
                               'name': reply.created_by.nickname,
                               **get_user_avatar_info(reply.created_by),
                           }),
            'like': {
                'like': reply.like_count,
                'dislike': reply.dislike_count,
                'user_option': user_option,
            },
            'parent': 0 if reply.parent is None else reply.parent.id,
            'is_deleted': reply.is_deleted,
        }

    def get(self, request, review_id):
        try:
            review = Review.all_objects.get(id=review_id)
        except Review.DoesNotExist:
            return return_response(errors={'course': get_err_msg('review_not_exist')},
                                   status_code=status.HTTP_404_NOT_FOUND)
        replies = ReviewReply.all_objects.filter(review=review).select_related(
            'created_by', 'parent',
        ).order_by('id')
        target = request.query_params.get('target')
        if target:
            try:
                current = replies.get(id=int(target))
            except (ValueError, ReviewReply.DoesNotExist):
                return return_response(
                    errors={'reply': get_err_msg('reply_not_exist')},
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            lineage = []
            seen = set()
            while current is not None and current.id not in seen:
                seen.add(current.id)
                lineage.append(current)
                current = current.parent
            lineage.reverse()
            return return_response(message='课程评价获取成功', contents={
                'count': replies.count(),
                'next_cursor': None,
                'results': [self.get_reply_info(reply, request.user) for reply in lineage],
            })

        after = request.query_params.get('after')
        if after:
            try:
                replies = replies.filter(id__gt=int(after))
            except ValueError:
                return return_response(errors={'after': '游标参数不合法'}, status_code=400)
        total_count = ReviewReply.all_objects.filter(review=review).count()
        batch = list(replies[:21])
        has_more = len(batch) > 20
        batch = batch[:20]
        return return_response(message='课程评价获取成功', contents={
            'count': total_count,
            'next_cursor': batch[-1].id if has_more else None,
            'results': [self.get_reply_info(reply, request.user) for reply in batch],
        })

    @transaction.atomic
    def post(self, request):
        serializer = AddReviewReplySerializer(data=request.data)
        if serializer.is_valid():
            review = Review.all_objects.get(id=serializer.validated_data['review_id'])
            parent_id = serializer.validated_data['parent_id']
            parent = None if parent_id == 0 else ReviewReply.objects.get(id=parent_id)
            reply = ReviewReply.objects.create(
                review=review,
                parent=parent,
                content=serializer.validated_data['content'],
                created_by=request.user
            )
            notify_course_review_reply(reply)
            return return_response(message='成功创建课程评价回复', contents={'reply_id': reply.id},
                                   status_code=status.HTTP_201_CREATED)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

    def delete(self, request):

        serializer = DeleteReviewReplySerializer(data=request.data)
        if serializer.is_valid():
            try:
                review = Review.all_objects.get(id=serializer.validated_data['review_id'])
            except Review.DoesNotExist:
                return return_response(errors={'review': get_err_msg('review_not_exist')},
                                       status_code=status.HTTP_404_NOT_FOUND)
            try:
                review_reply = ReviewReply.objects.get(id=serializer.validated_data['reply_id'], review=review,
                                                       created_by=request.user)
            except ReviewReply.DoesNotExist:
                return return_response(errors={'review': get_err_msg('reply_not_exist')},
                                       status_code=status.HTTP_404_NOT_FOUND)
            review_reply.soft_delete()
            return return_response(message='成功删除课程评价回复')
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class ReviewAndReplyLikeView(APIView):
    permission_classes = [CustomPermission]

    def get_throttles(self):
        if self.request.method == 'POST':
            return [InteractionAnonRateThrottle(), InteractionUserRateThrottle()]
        return []

    def like_dislike_count(self, review_object, review_reply_object):
        if review_reply_object:
            review_reply_object.refresh_from_db()
            return {'like': review_reply_object.like_count, 'dislike': review_reply_object.dislike_count}
        else:
            review_object.refresh_from_db()
            return {'like': review_object.like_count, 'dislike': review_object.dislike_count}

    def post(self, request):
        serializer = ReviewAndReplyLikeSerializer(data=request.data)
        if serializer.is_valid():
            review_object = Review.all_objects.get(id=serializer.validated_data['review_id'])
            try:
                review_reply_object = None if serializer.validated_data['reply_id'] == 0 else ReviewReply.objects.get(
                    id=serializer.validated_data['reply_id'], review=review_object)
            except ReviewReply.DoesNotExist:
                return return_response(errors={'review': get_err_msg('reply_not_exist')},
                                       status_code=status.HTTP_404_NOT_FOUND)

            review_and_reply_like, created = ReviewAndReplyLike.objects.get_or_create(
                review=review_object,
                created_by=request.user,
                review_reply=review_reply_object,
                defaults={'like': serializer.validated_data['like_or_dislike']},
            )
            if created:
                return return_response(contents={'like': self.like_dislike_count(review_object, review_reply_object)})

            if serializer.validated_data['like_or_dislike'] == review_and_reply_like.like:
                review_and_reply_like.delete()
            else:
                review_and_reply_like.like = serializer.validated_data['like_or_dislike']
                review_and_reply_like.save()

            return return_response(contents={'like': self.like_dislike_count(review_object, review_reply_object)}, )
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class CourseLikeView(APIView):
    permission_classes = [CustomPermission]

    def get_throttles(self):
        if self.request.method == 'POST':
            return [InteractionAnonRateThrottle(), InteractionUserRateThrottle()]
        return []

    @transaction.atomic
    def post(self, request):
        serializer = CourseLikeSerializer(data=request.data)
        if serializer.is_valid():
            course = Course.objects.get(id=serializer.validated_data['course_id'])
            course_like, created = CourseLike.objects.get_or_create(
                course=course,
                created_by=request.user,
            )
            if course_like.like == serializer.validated_data['like']:
                course_like.delete()
            else:
                course_like.like = serializer.validated_data['like']
                course_like.save()
            course.refresh_from_db()
            return return_response(contents={'name': course.get_name(), 'id': course.id,
                                             'like': {'like': course.like_count, 'dislike': course.dislike_count}})
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class SemesterView(APIView):
    permission_classes = [CustomPermission]

    def get(self, request):
        semesters = Semeseter.objects.all()
        semester_dict = {}
        for semester in semesters:
            semester_dict[semester.id] = semester.name
        return return_response(contents=semester_dict)


class ReviewAnalysisView(APIView):
    permission_classes = [CustomPermission]

    def get_daily_counts(self, queryset, date_field):
        return (
            queryset
            .annotate(date=TruncDate(date_field))
            .values('date')
            .annotate(count=Count('id'))
            .order_by('date')
        )

    def accumulate_counts(self, daily_counts, date_statistics):
        total = 0
        for entry in daily_counts:
            date_str = entry['date'].strftime('%Y-%m-%d')
            date_statistics[date_str] = date_statistics.get(date_str, 0) + entry['count']
            total += entry['count']
        return total

    def get(self, request):
        contribute = cache.get('contribute')
        if contribute is None:
            date_statistics = {}
            total = 0
            review_not_edit_daily_counts = self.get_daily_counts(Review.objects.all(), 'create_time')
            review_edited_daily_counts = self.get_daily_counts(Review.objects.filter(edited=True), 'modify_time')
            reply_daily_counts = self.get_daily_counts(ReviewReply.objects.all(), 'create_time')
            total += self.accumulate_counts(review_not_edit_daily_counts, date_statistics)
            total += self.accumulate_counts(review_edited_daily_counts, date_statistics)
            total += self.accumulate_counts(reply_daily_counts, date_statistics)
            cache.set('contribute', {'total': total, 'contribute': date_statistics}, timeout=60 * 60)
            return return_response(contents={'total': total, 'contribute': date_statistics})
        else:
            return return_response(contents=contribute)
