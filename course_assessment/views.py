import logging
from venv import create

from django.core.cache import cache
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from common.utils import return_response
from course_assessment.models import Course, Review, ReviewHistory, School, Teacher, Semeseter, ReviewReply, \
    ReviewAndReplyLike, CourseLike
from course_assessment.permissions import CustomPermission
from course_assessment.serializer import MyReviewSerializer, AddReviewSerializer, DeleteReviewSerializer, \
    AddReviewReplySerializer, DeleteReviewReplySerializer, ReviewAndReplyLikeSerializer, CourseTeacherSearchSerializer, \
    AddCourseSerializer, TeacherSerializer, CourseLikeSerializer

logger = logging.getLogger(__name__)


class CourseList(APIView):
    permission_classes = [CustomPermission]

    def get(self, request):
        page_size = 10
        page = request.query_params.get('page', 1)
        course_type = request.query_params.get('course_type', 'all')
        if course_type not in {choice[0] for choice in Course.classification_choices}:
            course_type = 'all'
        order_by = request.query_params.get('order_by', 'rating')
        order_by_dict = {
            'rating': 'average_rating',
            'popular': 'review_count'
        }
        order_by = order_by_dict.get(order_by, 'average_rating')

        total_key = 'total_courses_count'
        total = cache.get(total_key)
        if total is None:
            total = Course.objects.count()
            cache.set(total_key, total, 30 * 60)

        courses = Course.objects.only('name', 'classification', 'teachers', 'semester').order_by(order_by,
                                                                                                 'like_count')
        paginator = Paginator(courses, page_size)
        course_page = paginator.get_page(page)
        courses_list = [{'id': course.id,
                         'name': course.get_name,
                         'teacher': course.get_teachers(),
                         'semester': course.get_semester(),
                         'review_count': course.review_count,
                         'average_rating': course.average_rating,
                         'normalized_rating': course.normalized_rating,
                         } for course in course_page.object_list]

        return return_response(contents={
            'total': total,
            'courses': courses_list,
            'has_next': course_page.has_next(),
            'has_previous': course_page.has_previous(),
            'current_page': course_page.number,
            'num_pages': paginator.num_pages,
        })


class CourseView(APIView):
    course_model = Course
    review_model = Review
    school_model = School
    permission_classes = [AllowAny]

    def get(self, request, course_id):
        try:
            course = (self.course_model.objects
                      .select_related('school', 'created_by')
                      .prefetch_related('teachers', 'semester')
                      .get(id=course_id))
        except Course.DoesNotExist:
            return return_response(errors={'course': '未找到课程'}, status_code=status.HTTP_404_NOT_FOUND)
        reviews = (Review.objects.filter(course_id=course_id)
                   .select_related('created_by')
                   .order_by('-create_time'))
        reviews_data = []
        for review in reviews:
            reviewReplies = ReviewReply.objects.filter(review=review).select_related('created_by').order_by(
                '-create_time')
            if not review.anonymous:
                reviews_data.append({
                    'id': review.id,
                    'content': review.content,
                    'rating': review.rating,
                    'modified_time': review.modify_time,
                    'created_time': review.create_time,
                    'edited': review.edited,
                    'like': {'like': review.like_count,
                             'dislike': review.dislike_count},
                    'difficulty': review.get_difficulty_display(),
                    'grade': review.get_grade_display(),
                    'homework': review.get_homework_display(),
                    'reward': review.get_reward_display(),
                    'semester': review.semester.name,
                    'author': {'id': review.created_by.id, 'name': review.created_by.nickname,
                               'avatar': review.created_by.avatar_uuid},
                    'reply': [{'content': reviewReply.content,
                               'created_time': reviewReply.create_time,
                               'created_by': {'id': review.created_by.id, 'name': review.created_by.nickname,
                                              'avatar': review.created_by.avatar_uuid},
                               'like': {'like': reviewReply.like_count,
                                        'dislike': reviewReply.dislike_count}}
                              for reviewReply in reviewReplies]
                })
        teachers_data = []
        for teacher in course.teachers.all():
            teachers_data.append({
                'id': teacher.id,
                'name': teacher.name,
                'school': teacher.school.get_name if teacher.school else None,
            })
        course_info = {
            'id': course_id,
            'code': course.course_code,
            'name': course.get_name,
            'category': course.get_classification_display(),
            'teachers': teachers_data,
            'semester': [semester.name for semester in course.semester.all()],
            'school': course.school.get_name,
            'like': {'like': course.like_count, 'dislike': course.dislike_count},
            'rating_avg': f"{course.average_rating:.1f}",
            'normalized_rating_avg': f"{course.normalized_rating:.1f}",
            'reviews': reviews_data
        }
        return return_response(contents=course_info)

    def post(self, request):
        serializer = AddCourseSerializer(data=request.data)
        # todo 判断老师是新增还是原来的, 并且新建的课程要保证和之前的不重复 按照老师 学院 课程来
        if serializer.is_valid():
            if serializer.validated_data['teacher_exist']:
                course = Course.objects.get(name=serializer.validated_data['name'],
                                            teacher_id=serializer.validated_data['teacher_id'])


class SchoolView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        schools = School.objects.all()
        return return_response(
            contents={'schools': [{'id': school.id, 'name': school.get_name} for school in schools]}, )


class ReviewView(APIView):
    review_model = Review
    review_history_model = ReviewHistory
    permission_classes = [CustomPermission]

    def get(self, request):  # 最近课程评价
        current_page = int(request.query_params.get('currentPage', 1))
        page_size = int(request.query_params.get('pageSize', 10))
        desc = request.query_params.get('desc', '1')
        review__all_set = (
            Review.objects.all()
            .order_by(('-' if desc == '1' else '') + 'modify_time')
            .select_related('created_by', 'course', 'course__school')
            .prefetch_related('course__teachers')
        )
        paginator = Paginator(review__all_set, page_size)
        try:
            review_page = paginator.page(current_page)
        except PageNotAnInteger:
            review_page = paginator.page(1)
        except EmptyPage:
            review_page = paginator.page(paginator.num_pages)
        review_list = []
        for review in review_page:
            temp_dict = {
                'id': review.id,
                'author': {"name": "匿名用户" if review.anonymous else review.created_by.nickname,
                           "id": -1 if review.anonymous else review.created_by.id,
                           "avatar_uuid": "183840a7-4099-41ea-9afa-e4220e379651" if review.anonymous else review.created_by.avatar_uuid},
                'datetime': review.modify_time,
                'course': {"name": review.course.get_name, "id": review.course.id, 'semester': review.semester.name, },
                'content': review.content,
                "teachers": [{"name": teacher.name, "id": teacher.id} for teacher in
                             review.course.teachers.all()],
                'edited': review.edited,
                'is_student': review.created_by.college_email,
            }
            review_list.append(temp_dict)
        return return_response(
            contents={"reviews": review_list, "total": paginator.count, 'has_next': review_page.has_next(),
                      'has_previous': review_page.has_previous(), 'current_page': review_page.number, })

    def post(self, request):
        serializer = AddReviewSerializer(data=request.data)
        if serializer.is_valid():
            course = Course.objects.get(id=serializer.data['course'])
            semester = Semeseter.objects.get(id=serializer.data['semester'])
            updated = False
            try:
                review = self.review_model.all_objects.get(course=course, created_by=request.user)
                if review.is_deleted:
                    review.restore()
                fields_to_update = ['content', 'rating', 'anonymous', 'difficulty', 'grade', 'homework', 'reward']
                for field in fields_to_update:
                    setattr(review, field, serializer.data[field])
                review.semester = semester
                review.save()

                if review.content != serializer.data['content']:
                    self.review_history_model.objects.create(review=review, content=serializer.data['content'])
                message = '更新课程评价成功'
                updated = True
            except Review.DoesNotExist:
                # 创建新评论
                review = self.review_model.objects.create(
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
                message = '成功创建课程评价'

            if semester not in course.semester.all():
                course.semester.add(semester)

            return return_response(
                message=message,
                contents={'review': review.id, 'updated': updated})
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

    def delete(self, request):
        serializer = DeleteReviewSerializer(data=request.data)
        if serializer.is_valid():
            try:
                review_id = self.review_model.objects.get(id=serializer.validated_data['review_id'])
            except Review.DoesNotExist:
                return return_response(errors={"course": "课程评价不存在"}, status_code=status.HTTP_400_BAD_REQUEST)
            if review_id.created_by == request.user:
                review_item_model = self.review_model.objects.get(id=review_id.id)
                review_item_model.soft_delete()
                review_history_items = self.review_history_model.objects.filter(review_id=review_id.id)
                for review_history_item in review_history_items:
                    review_history_item.soft_delete()
                return return_response(message="删除课程评价成功")
            else:
                return return_response(errors={"user": "用户错误"}, status_code=status.HTTP_401_UNAUTHORIZED)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class TeacherView(APIView):
    model = Teacher
    permission_classes = [AllowAny]

    def get(self, request, teacher_id):
        try:
            teacher = Teacher.objects.get(id=teacher_id)
        except Teacher.DoesNotExist:
            return return_response(errors={'teacher': "教师不存在"}, status_code=status.HTTP_404_NOT_FOUND)
        teacher_info = {
            'id': teacher.id,
            'name': teacher.name,
            'school': teacher.school.get_name if teacher.school else None,
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
                    'name': course.get_name,
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
        serializer = TeacherSerializer(data=request.data)
        if serializer.is_valid():
            teachers = Teacher.objects.search(serializer.validated_data['name'], page_size=1, current_page=1)
            teacher_list = [{'id': teacher.id, 'name': teacher.name, 'school': teacher.school.get_name} for teacher in
                            teachers['results']]
            return return_response(contents=teacher_list)
        return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class MyReviewView(APIView):
    permission_classes = [IsAuthenticated]
    model = Review

    def get(self, request):
        desc = request.query_params.get('desc', '1')
        review_set = (
            self.model.objects.filter(created_by=self.request.user)
            .order_by(('-' if desc == '1' else '') + 'modify_time')
            .select_related('created_by', 'course', 'semester')
            .prefetch_related('course__teachers')
        )
        my_review_list = []

        for review in review_set:
            content_history = MyReviewSerializer(review).data
            temp_dict = {
                'id': review.id,
                'anonymous': review.anonymous,
                'datetime': review.modify_time,
                'course': {"name": review.course.get_name, "id": review.course.id,
                           'semester': review.semester.name, },
                'like': {'like': review.like_count, 'dislike': review.dislike_count},
                'content': {"current_content": review.content,
                            "content_history": [x['content'] for x in content_history['review_history']]},
                "teachers": [{"name": teacher.name, "id": teacher.id} for teacher in
                             review.course.teachers.all()],

            }
            my_review_list.append(temp_dict)
        return return_response(contents=my_review_list)


class MyReviewReplyView(APIView):
    permission_classes = [IsAuthenticated]
    model = ReviewReply

    def get(self, request):
        desc = request.query_params.get('desc', '1')
        review_reply_set = (
            self.model.objects.filter(created_by=self.request.user)
            .order_by(('-' if desc == '1' else '') + 'create_time')
            .select_related('created_by', 'review')
        )
        my_review_reply_list = []
        for review_reply in review_reply_set:
            my_review_reply_list.append({
                'id': review_reply.id,
                'content': review_reply.review.content,
                'datetime': review_reply.create_time,
                'course': {"name": review_reply.review.course.get_name, "id": review_reply.review.course.id,
                           'semester': review_reply.review.semester.name, },
                'reply': {'id': review_reply.review.id, 'content': review_reply.content},
                'like': {'like': review_reply.like_count, 'dislike': review_reply.dislike_count},
            })
        return return_response(contents=my_review_reply_list)


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
            return return_response(errors={'course': '未找到课程评价'}, status_code=status.HTTP_404_NOT_FOUND)
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
            try:
                review = Review.objects.get(id=serializer.validated_data['review_id'])
            except Review.DoesNotExist:
                return return_response(errors={'course': '未找到课程评价'}, status_code=status.HTTP_404_NOT_FOUND)
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
                return return_response(errors={'review': '课程评价不存在'}, status_code=status.HTTP_404_NOT_FOUND)
            try:
                ReviewReply.objects.get(id=serializer.validated_data['reply_id'], review=review,
                                        created_by=request.user).delete()
            except ReviewReply.DoesNotExist:
                return return_response(errors={'review': '课程评价回复不存在'}, status_code=status.HTTP_404_NOT_FOUND)
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
            try:
                review_object = Review.objects.get(id=serializer.validated_data['review_id'])
            except Review.DoesNotExist:
                return return_response(errors={'review': 'review not exist'}, status_code=status.HTTP_404_NOT_FOUND)
            try:
                review_reply_object = None if serializer.validated_data['reply_id'] == 0 else ReviewReply.objects.get(
                    id=serializer.validated_data['reply_id'])
            except ReviewReply.DoesNotExist:
                return return_response(errors={'review': '点赞对象不存在'}, status_code=status.HTTP_404_NOT_FOUND)

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


class CourseLikeView(APIView):
    permission_classes = [CustomPermission]

    @transaction.atomic
    def post(self, request):
        serializer = CourseLikeSerializer(data=request.data)
        if serializer.is_valid():
            try:
                course = Course.objects.get(id=serializer.validated_data['course_id'])
            except Course.DoesNotExist:
                return return_response(errors={'course': '课程不存在'}, status_code=status.HTTP_404_NOT_FOUND)
            course_like, created = CourseLike.objects.get_or_create(
                course=course,
                created_by=request.user,
                like=serializer.validated_data['like']
            )
            if not created:
                course_like.delete()
            course.refresh_from_db()
            return return_response(contents={'name': course.get_name, 'id': course.id,
                                             'like': {'like': course.like_count, 'dislike': course.dislike_count}})
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class CourseTeacherSearchView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = CourseTeacherSearchSerializer(data=request.data)
        if serializer.is_valid():
            return_list = {}
            if serializer.validated_data.get('search_flag') == 'course_and_teacher':
                course_name, teacher_name = serializer.validated_data.get('course_name'), serializer.validated_data.get(
                    'teacher_name')
                if course_name and teacher_name:
                    courses = Course.objects.filter(
                        Q(name__icontains=course_name) & Q(teachers__name__icontains=teacher_name)
                    ).select_related('school').prefetch_related('teachers')
                    course_list = []
                    for course in courses:
                        course_list.append({
                            'course': {
                                'id': course.id,
                                'classification': course.get_classification_display(),
                                'name': course.get_name,
                                'course_code': course.course_code,
                                'teachers': [{'id': teacher.id, 'name': teacher.name, 'school': teacher.school.get_name}
                                             for
                                             teacher in
                                             course.teachers.all()],
                                'school': course.school.get_name,

                                'average_rating': course.average_rating,
                                'normalized_rating': course.normalized_rating,
                            },
                        })
                    return return_response(contents=course_list)
                else:
                    return return_response(errors={'field': 'field missed'}, status_code=status.HTTP_400_BAD_REQUEST)
            if serializer.validated_data.get('search_flag') == 'course':
                course_name = serializer.validated_data['course_name']
                courses = (Course.objects.filter(name__icontains=course_name)
                           .select_related('school', ).prefetch_related('teachers'))
                course_list = []
                for course in courses:
                    course_list.append({
                        'id': course.id,
                        'classification': course.get_classification_display(),
                        'name': course.get_name,
                        'course_code': course.course_code,
                        'teachers': [{'id': teacher.id, 'name': teacher.name, 'school': teacher.school.get_name} for
                                     teacher
                                     in course.teachers.all()],
                        'school': course.school.get_name,

                        'average_rating': course.average_rating,
                        'normalized_rating': course.normalized_rating,
                    })
                return_list['course'] = course_list

            if serializer.validated_data.get('search_flag') == 'teacher':
                teacher_name = serializer.validated_data['teacher_name']
                teachers = Teacher.objects.filter(name__icontains=teacher_name).select_related('school')
                teacher_list = []
                for teacher in teachers:
                    teacher_list.append({
                        'id': teacher.id,
                        'name': teacher.name,
                        'school': teacher.school.get_name,
                    })
                return_list['teacher'] = teacher_list
            return return_response(contents=return_list, status_code=status.HTTP_400_BAD_REQUEST)
        else:
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
