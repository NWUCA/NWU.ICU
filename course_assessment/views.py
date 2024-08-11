import logging

from django.db.models import Avg, Count, Q
from django.views.generic import ListView
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from course_assessment.models import Course, Review, ReviewHistory, School, Teacher, Semeseter, ReviewReply, \
    ReviewAndReplyLike
from course_assessment.permissions import CustomPermission
from course_assessment.serializer import MyReviewSerializer, AddReviewSerializer, DeleteReviewSerializer, \
    AddReviewReplySerializer, DeleteReviewReplySerializer, ReviewAndReplyLikeSerializer, CourseTeacherSearchSerializer

logger = logging.getLogger(__name__)


class CourseList(ListView):
    template_name = 'course_list.html'
    model = Course
    paginate_by = 15

    def get_queryset(self):
        search_string = self.request.GET.get('s', "")
        course_set = (
            self.model.objects.all()
            .annotate(rating=Avg('review__rating'), num=Count('review'))
            .order_by('-num')
            .prefetch_related('teachers', 'review_set')
        )
        if search_string:
            items = search_string.split(' ')
            for item in items:
                course_set = course_set.filter(
                    Q(name__contains=item) | Q(teachers__name__contains=item)
                )
        return course_set

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_string'] = self.request.GET.get('s', "")
        context['review_count'] = Review.objects.count()
        return context


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
            return Response({'message': '未找到课程'}, status=status.HTTP_404_NOT_FOUND)
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
                'school': teacher.school.name if teacher.school else None,
            })
        course_info = {
            'id': course_id,
            'code': course.course_code,
            'name': course.get_name,
            'category': course.get_classification_display(),
            'teachers': teachers_data,
            'semester': [semester.name for semester in course.semester.all()],
            'school': course.school.name,
            'rating_avg': f"{course.average_rating:.1f}",
            'normalized_rating_avg': f"{course.normalized_rating:.1f}",
            'reviews': reviews_data
        }
        return Response({'message': course_info})


class ReviewAddView(APIView):
    review_model = Review
    review_history_model = ReviewHistory
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = AddReviewSerializer(data=request.data)
        if serializer.is_valid():
            course = Course.objects.get(id=serializer.data['course'])
            try:
                old_review = self.review_model.objects.get(course=course, created_by=request.user)
            except Review.DoesNotExist:
                self.review_model.objects.create(
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
                    semester=Semeseter.objects.get(id=serializer.data['semester']),
                )
                return Response({'message': '成功创建课程评价'}, status=status.HTTP_201_CREATED)
            old_content = old_review.content
            fields_to_update = ['content', 'rating', 'anonymous', 'difficulty', 'grade', 'homework', 'reward']
            for field in fields_to_update:
                setattr(old_review, field, serializer.data[field])
            old_review.save()
            if old_content != serializer.data['content']:
                self.review_history_model.objects.create(review=old_review, content=serializer.data['content'])
            return Response({'message': '更新课程评价成功'}, status=status.HTTP_201_CREATED)
        else:
            return Response({"message": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


class ReviewDeleteView(APIView):
    review_model = Review
    review_history_model = ReviewHistory
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = DeleteReviewSerializer(data=request.data)
        if serializer.is_valid():
            try:
                review_id = self.review_model.objects.get(id=serializer.validated_data['review_id'])
            except Review.DoesNotExist:
                return Response({"message": "课程评价不存在"}, status=status.HTTP_400_BAD_REQUEST)
            if review_id.created_by == request.user:
                review_item_model = self.review_model.objects.get(id=review_id.id)
                review_item_model.delete()
                review_history_items = self.review_history_model.objects.filter(review_id=review_id.id)
                for review_history_item in review_history_items:
                    review_history_item.delete()
                return Response({"message": "删除课程评价成功"}, status=status.HTTP_200_OK)
            else:
                return Response({"message": "用户错误"}, status=status.HTTP_401_UNAUTHORIZED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TeacherView(APIView):
    model = Teacher
    permission_classes = [AllowAny]

    def get(self, request, teacher_id):
        teacher = Teacher.objects.get(id=teacher_id)
        teacher_info = {
            'id': teacher.id,
            'name': teacher.name,
            'school': teacher.school.name if teacher.school else None,
        }

        courses = Course.objects.filter(teachers__id=teacher_id)
        teacher_course_list = []
        for course in courses:
            reviews = Review.objects.filter(course=course)
            rating_avg = course.average_rating
            normalized_avg_rating = course.normalized_rating
            review_count = reviews.count()
            teacher_course_list.append({
                'course_id': course.id,
                'course_semester': ",".join([semester.name for semester in course.semester.all()]),
                'course_code': course.course_code,
                'course_name': course.get_name,
                'rating_avg': rating_avg,
                'normalized_rating_avg': normalized_avg_rating,
                'review_count': review_count,
            })
        teacher_course_info = {
            'teacher_info': teacher_info,
            "course_list": teacher_course_list
        }
        return Response({'message': teacher_course_info}, status=status.HTTP_200_OK)


class LatestReviewView(APIView):
    permission_classes = [AllowAny]
    model = Review

    def get(self, request):
        current_page = int(request.query_params.get('currentPage', 1))
        page_size = int(request.query_params.get('pageSize', 10))
        desc = request.query_params.get('desc', '1')
        review__all_set = (
            self.model.objects.all()
            .order_by(('-' if desc == '1' else '') + 'modify_time')
            .select_related('created_by', 'course', 'course__school')
            .prefetch_related('course__teachers')
        )
        total = review__all_set.count()
        review_set = review__all_set[(current_page - 1) * page_size:(current_page - 1) * page_size + page_size]
        review_list = []
        for review in review_set:
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
                'is_student': review.created_by.nwu_email is not None and not review.anonymous,
            }
            review_list.append(temp_dict)
        return Response({
            "errors": None,
            "content": {"reviews": review_list, "total": total}
        }, status=status.HTTP_200_OK)


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
        return Response({
            "message": {"reviews": my_review_list}
        }, status=status.HTTP_200_OK)


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
        return Response({'message': my_review_reply_list}, status=status.HTTP_200_OK)


class ReviewReplyView(APIView):
    permission_classes = [CustomPermission]

    def get(self, request, review_id):
        try:
            review = Review.objects.get(id=review_id)
        except Review.DoesNotExist:
            return Response({'message': '未找到课程评价'}, status=status.HTTP_404_NOT_FOUND)
        reply_list = []
        try:
            review_replies = ReviewReply.objects.order_by('create_time').filter(review=review)
            for review_reply in review_replies:
                reply_list.append({"id": review_reply.id,
                                   "create_time": review_reply.create_time,
                                   "content": review_reply.content,
                                   "created_by_id": review_reply.created_by.id,
                                   "created_by_name": review_reply.created_by.nickname,
                                   'like': review_reply.like_count,
                                   'dislike': review_reply.dislike_count, })
        except ReviewReply.DoesNotExist:
            pass

        return Response({'message': reply_list}, status=status.HTTP_200_OK)

    def post(self, request, review_id):
        try:
            review = Review.objects.get(id=review_id)
        except Review.DoesNotExist:
            return Response({'message': '未找到课程评价'}, status=status.HTTP_404_NOT_FOUND)
        serializer = AddReviewReplySerializer(data=request.data)
        if serializer.is_valid():
            ReviewReply.objects.create(review=review, content=serializer.validated_data['content'],
                                       created_by=request.user, )
            return Response({'message': '成功创建课程评价回复'}, status=status.HTTP_201_CREATED)
        else:
            return Response({'message': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, review_id):
        try:
            review = Review.objects.get(id=review_id)
        except Review.DoesNotExist:
            return Response({'message': '课程评价不存在'}, status=status.HTTP_404_NOT_FOUND)
        serializer = DeleteReviewReplySerializer(data=request.data)
        if serializer.is_valid():
            try:
                ReviewReply.objects.get(id=serializer.validated_data['reply_id'], review=review,
                                        created_by=request.user).delete()
            except ReviewReply.DoesNotExist:
                return Response({'message': '课程评价回复不存在'}, status=status.HTTP_404_NOT_FOUND)
            return Response({'message': '成功删除课程评价回复'}, status=status.HTTP_200_OK)
        else:
            return Response({'message': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)


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
                return Response({'message': 'review not exist'}, status=status.HTTP_404_NOT_FOUND)

            review_reply_object = None if serializer.validated_data['reply_id'] == 0 else ReviewReply.objects.get(
                id=serializer.validated_data['reply_id'])

            try:
                review_and_reply_like = ReviewAndReplyLike.objects.get(review=review_object, created_by=request.user,
                                                                       review_reply=review_reply_object)
            except ReviewAndReplyLike.DoesNotExist:
                ReviewAndReplyLike.objects.create(review=review_object, review_reply=review_reply_object,
                                                  like=serializer.validated_data['like_or_dislike'],
                                                  created_by=request.user)
                return Response({'message': self.like_dislike_count(review_object, review_reply_object)},
                                status=status.HTTP_200_OK)

            if serializer.validated_data['like_or_dislike'] == 0 or serializer.validated_data[
                'like_or_dislike'] == review_and_reply_like.like:
                review_and_reply_like.delete()
            else:
                review_and_reply_like.like = serializer.validated_data['like_or_dislike']
                review_and_reply_like.save()

            return Response({'message': self.like_dislike_count(review_object, review_reply_object)},
                            status=status.HTTP_200_OK)


class courseTeacherSearchView(APIView):
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
                                'teachers': [{'id': teacher.id, 'name': teacher.name, 'school': teacher.school.name} for
                                             teacher in
                                             course.teachers.all()],
                                'school': course.school.name,

                                'average_rating': course.average_rating,
                                'normalized_rating': course.normalized_rating,
                            },
                        })
                    return Response({'message': course_list}, status.HTTP_200_OK)
                else:
                    return Response({'message': 'field missed'}, status=status.HTTP_400_BAD_REQUEST)
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
                        'teachers': [{'id': teacher.id, 'name': teacher.name, 'school': teacher.school.name} for teacher
                                     in course.teachers.all()],
                        'school': course.school.name,

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
                        'school': teacher.school.name,
                    })
                return_list['teacher'] = teacher_list
            return Response({'message': return_list}, status=status.HTTP_400_BAD_REQUEST)
        else:
            return Response({'message': serializer.errors}, status=status.HTTP_400_BAD_REQUEST)
