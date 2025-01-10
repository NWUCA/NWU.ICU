import logging

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
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
from utils.custom_pagination import StandardResultsSetPagination
from utils.utils import return_response, get_err_msg, get_msg_msg, userUtils

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

    def get_user_option(self, review, user, reply=None, course=None):
        if user.id is None:
            return 0
        if course is not None:
            try:
                user_review_option = CourseLike.objects.get(course=course, created_by=user).like
            except (CourseLike.DoesNotExist, AttributeError):
                user_review_option = 0
            return user_review_option
        try:
            user_review_option = ReviewAndReplyLike.objects.get(review=review, created_by=user,
                                                                review_reply=reply).like
        except (ReviewAndReplyLike.DoesNotExist, AttributeError):
            user_review_option = 0
        return user_review_option

    def get(self, request, course_id):
        try:
            course = (Course.objects
                      .select_related('school', 'created_by')
                      .prefetch_related('teachers', 'semester')
                      .get(id=course_id))
        except Course.DoesNotExist:
            return return_response(errors={'course': get_err_msg('course_not_exist')},
                                   status_code=status.HTTP_404_NOT_FOUND)
        reviews = (Review.objects.filter(course_id=course_id)
                   .select_related('created_by', 'semester')
                   .order_by('-create_time'))
        try:
            if not request.user.is_anonymous:
                request_user_review = Review.objects.get(course_id=course_id, created_by=request.user)
                request_user_review_id = request_user_review.id
            else:
                request_user_review_id = None
        except Review.DoesNotExist:
            request_user_review_id = None
        reviews_data = []
        for review in reviews:
            reviewReplies = ReviewReply.objects.filter(review=review).select_related('created_by').order_by(
                '-create_time')
            reviews_data.append({
                'id': review.id,
                'content': review.content,
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
                'author': {'id': -1 if (
                        review.anonymous and review.created_by.id != request.user.id) else review.created_by.id,
                           'nickname': get_msg_msg(
                               'anonymous_user_nickname') if review.anonymous else review.created_by.nickname,
                           'avatar': settings.ANONYMOUS_USER_AVATAR_UUID if review.anonymous else review.created_by.avatar_uuid,
                           'anonymous': review.anonymous},
                'reply': [{'id': reviewReply.id,
                           'floor_number': index + 1,
                           'content': reviewReply.content,
                           'created_time': reviewReply.create_time,
                           'parent': 0 if (reviewReply.parent is None) else reviewReply.parent.id,
                           'created_by': {'id': reviewReply.created_by.id, 'name': reviewReply.created_by.nickname,
                                          'avatar': reviewReply.created_by.avatar_uuid},
                           'like': {'like': reviewReply.like_count,
                                    'dislike': reviewReply.dislike_count,
                                    'user_option': self.get_user_option(review=review, user=request.user,
                                                                        reply=reviewReply)}, }
                          for index, reviewReply in enumerate(reviewReplies)]
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
            'reviews': reviews_data,
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
        schools = School.objects.all()
        return return_response(
            contents={'schools': [{'id': school.id, 'name': school.get_name()} for school in schools]}, )


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
            review_list = self.get_paginated_response(self.build_review_list(page))
            return review_list

        return return_response(errors={'review': get_err_msg('review_not_exist')})

    def build_review_list(self, review_page):
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
                'edited': review.edited,
            })
        return review_list


class ReviewView(APIView):
    review_history_model = ReviewHistory
    permission_classes = [CustomPermission]

    def put(self, request):
        serializer = AddReviewSerializer(data=request.data)
        if serializer.is_valid():
            course = Course.objects.get(id=serializer.data['course'])
            semester = Semeseter.objects.get(id=serializer.data['semester'])
            try:
                review = Review.objects.get(course=course, created_by=request.user)
            except Review.DoesNotExist:
                return return_response(contents={'review': get_err_msg('review_not_exist')},
                                       status_code=HTTP_404_NOT_FOUND)
            ReviewHistory.objects.create(review=review, content=review.content, is_deleted=False)
            fields_to_update = ['content', 'rating', 'anonymous', 'difficulty', 'grade', 'homework', 'reward']
            for field in fields_to_update:
                setattr(review, field, serializer.data[field])
            review.semester = semester
            review.edited = True
            review.save()
            return return_response(message=get_msg_msg('review_update_success'), contents={'review_id': review.id})
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

    def post(self, request):
        serializer = AddReviewSerializer(data=request.data)
        if serializer.is_valid():
            course = Course.objects.get(id=serializer.data['course'])
            semester = Semeseter.objects.get(id=serializer.data['semester'])
            try:
                review = Review.objects.get(course=course, created_by=request.user)
            except Review.DoesNotExist:
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
                return return_response(message=get_msg_msg('review_create_success'), contents={'review_id': review.id})
            return return_response(contents={'review': review.id}, errors={'review': get_err_msg('review_has_exist')},
                                   status_code=HTTP_404_NOT_FOUND)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

    def delete(self, request):
        serializer = DeleteReviewSerializer(data=request.data)
        if serializer.is_valid():
            review = Review.objects.get(id=serializer.validated_data['review_id'])
            if review.created_by == request.user:
                review_item_model = Review.objects.get(id=review.id)
                review_item_model.soft_delete()
                review_history_items = self.review_history_model.objects.filter(review_id=review.id)
                for review_history_item in review_history_items:
                    review_history_item.soft_delete()
                review_reply_items = ReviewReply.objects.filter(review_id=review.id)
                for review_reply_item in review_reply_items:
                    review_reply_item.soft_delete()
                return return_response(message=get_msg_msg('delete_review_success'), contents={'review_id': review.id})
            else:
                return return_response(errors={"auth": get_err_msg('auth_error')},
                                       status_code=status.HTTP_401_UNAUTHORIZED)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class TeacherView(APIView):
    model = Teacher
    permission_classes = [CustomPermission]

    def get(self, request, teacher_id):
        try:
            teacher = Teacher.objects.get(id=teacher_id)
        except Teacher.DoesNotExist:
            return return_response(errors={'teacher': get_err_msg('teacher_not_exist')},
                                   status_code=status.HTTP_404_NOT_FOUND)
        teacher_info = {
            'id': teacher.id,
            'name': teacher.name,
            'avatar_uuid': teacher.avatar_uuid,
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
    def user_private(request, user_id=None, view_type='review'):
        if user_id is None and request.user.id is None:
            return return_response(errors={'user': get_err_msg('not_login')}, status_code=status.HTTP_401_UNAUTHORIZED)
        lookup_user_id = request.user.id if (user_id is None and request.user.id is not None) else user_id
        try:
            user = User.objects.get(id=lookup_user_id)
        except User.DoesNotExist:
            return return_response(errors={'user': get_err_msg('user_not_exist')},
                                   status_code=status.HTTP_400_BAD_REQUEST)
        private_key = user.private_review if view_type == 'review' else user.private_reply
        if private_key == '2':
            return return_response(errors={'review': get_err_msg(f'{view_type}_private')},
                                   status_code=status.HTTP_400_BAD_REQUEST)
        if private_key == '1' and request.user.id is None:
            return return_response(errors={'review': get_err_msg(f'{view_type}_private')},
                                   status_code=status.HTTP_400_BAD_REQUEST)
        return lookup_user_id

    def get(self, request, user_id=None):
        desc = request.query_params.get('desc', '1')
        view_type = request.query_params.get('type', 'review')
        if view_type not in ['review', 'reply']:
            return return_response(errors={'view_type': get_err_msg('view_type_error')},
                                   status_code=status.HTTP_400_BAD_REQUEST)
        lookup_user_id = self.user_private(request, user_id, view_type=view_type)
        if type(lookup_user_id) == Response:
            return lookup_user_id
        else:
            is_me = (user_id == request.user.id) or (request.user.id is not None and user_id is None)
            if view_type == 'review':
                query_set = (
                    Review.objects.filter(created_by=lookup_user_id)
                    .order_by(('-' if desc == '1' else '') + 'modify_time')
                    .select_related('created_by', 'course', 'semester')
                    .prefetch_related('course__teachers')
                )
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
                    my_review_list = self.build_reply_list(page, is_me)
                return self.get_paginated_response(my_review_list)
            return return_response(errors={'review': get_err_msg(f'{view_type}_not_exist')})

    def build_reply_list(self, reply_page, is_me: bool):
        my_reply_list = []
        for review_reply in reply_page:
            my_reply_list.append({
                'id': review_reply.id,
                'content': review_reply.review.content,
                'datetime': review_reply.create_time,
                'course': {"name": review_reply.review.course.get_name(), "id": review_reply.review.course.id,
                           'semester': review_reply.review.semester.name, },
                'reply': {'id': review_reply.review.id, 'content': review_reply.content},
                'like': {'like': review_reply.like_count, 'dislike': review_reply.dislike_count},
            })
        return my_reply_list

    def build_my_review_list(self, my_review_page, is_me: bool):
        my_review_list = []
        for review in my_review_page:
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
            elif review.anonymous:
                tmp_dict = {}
            tmp_dict.update({'is_me': is_me})
            my_review_list.append(tmp_dict)
        return my_review_list


class ReviewReplyView(APIView):
    permission_classes = [CustomPermission]

    def get_reply_info(self, reply):
        return {
            "id": reply.id,
            "create_time": reply.create_time,
            "content": reply.content,
            'author': {"id": reply.created_by.id, 'nickname': reply.created_by.nickname},
            'like': {'like': reply.like_count, 'dislike': reply.dislike_count},
            'parent_id': 0 if reply.parent is None else reply.parent.id,
        }

    def get(self, request, review_id):
        try:
            review = Review.objects.get(id=review_id)
        except Review.DoesNotExist:
            return return_response(errors={'course': get_err_msg('review_not_exist')},
                                   status_code=status.HTTP_404_NOT_FOUND)
        reply_list = []
        try:
            review_replies = ReviewReply.objects.order_by('id').filter(review=review)
            for review_reply in review_replies:
                reply_list.append(self.get_reply_info(review_reply))
        except ReviewReply.DoesNotExist:
            pass
        return return_response(message='课程评价获取成功', contents=reply_list)

    def post(self, request):
        serializer = AddReviewReplySerializer(data=request.data)
        if serializer.is_valid():
            review = Review.objects.get(id=serializer.validated_data['review_id'])
            parent_id = serializer.validated_data['parent_id']
            parent = None if parent_id == 0 else ReviewReply.objects.get(id=parent_id)
            reply = ReviewReply.objects.create(
                review=review,
                parent=parent,
                content=serializer.validated_data['content'],
                created_by=request.user
            )
            return return_response(message='成功创建课程评价回复', contents={'reply_id': reply.id},
                                   status_code=status.HTTP_201_CREATED)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

    def delete(self, request):

        serializer = DeleteReviewReplySerializer(data=request.data)
        if serializer.is_valid():
            try:
                review = Review.objects.get(id=serializer.validated_data['review_id'])
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
            review_object = Review.objects.get(id=serializer.validated_data['review_id'])
            try:
                review_reply_object = None if serializer.validated_data['reply_id'] == 0 else ReviewReply.objects.get(
                    id=serializer.validated_data['reply_id'])
            except ReviewReply.DoesNotExist:
                return return_response(errors={'review': get_err_msg('reply_not_exist')},
                                       status_code=status.HTTP_404_NOT_FOUND)

            try:
                review_and_reply_like = ReviewAndReplyLike.objects.get(review=review_object, created_by=request.user,
                                                                       review_reply=review_reply_object)
            except ReviewAndReplyLike.DoesNotExist:
                ReviewAndReplyLike.objects.create(review=review_object, review_reply=review_reply_object,
                                                  like=serializer.validated_data['like_or_dislike'],
                                                  created_by=request.user)
                return return_response(contents={'like': self.like_dislike_count(review_object, review_reply_object)})

            if serializer.validated_data['like_or_dislike'] == 0 or serializer.validated_data[
                'like_or_dislike'] == review_and_reply_like.like:
                review_and_reply_like.delete()
            else:
                review_and_reply_like.like = serializer.validated_data['like_or_dislike']
                review_and_reply_like.save()

            return return_response(contents={'like': self.like_dislike_count(review_object, review_reply_object)}, )
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class CourseLikeView(APIView):
    permission_classes = [CustomPermission]

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
