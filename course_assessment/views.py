import logging

from django.db.models import Avg, Count, Q
from django.views.generic import ListView
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from course_assessment.models import Course, Review, ReviewHistory, School
from course_assessment.serializer import MyReviewSerializer, AddReviewSerializer, DeleteReviewSerializer

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
    school_mode = School
    permission_classes = [AllowAny]

    def get(self, request, course_id):
        try:
            course = (self.course_model.objects
                      .select_related('school', 'created_by')
                      .prefetch_related('teachers', 'semester')
                      .get(id=course_id))
        except Course.DoesNotExist:
            return Response({'message': 'course not find'}, status=status.HTTP_404_NOT_FOUND)
        reviews = (Review.objects.filter(course_id=course_id)
                   .select_related('created_by')
                   .order_by('-create_time'))
        reviews_data = []
        for review in reviews:
            if not review.anonymous:
                reviews_data.append({
                    'content': review.content,
                    'rating': review.rating,
                    'modify_time': review.modify_time,
                    'edited': review.edited,
                    'like': review.like,
                    'difficulty': review.difficulty,
                    'grade': review.grade,
                    'homework': review.homework,
                    'reward': review.reward,
                })
        teachers_data = []
        for teacher in course.teachers.all():
            teachers_data.append({
                'name': teacher.name,
                'id': teacher.id,
                'school': teacher.school.name if teacher.school else None,
            })
        course_info = {
            'id': course_id,
            'name': course.name,
            'created_by': course.created_by.username,
            'teachers': teachers_data,
            'semester': [semester.name for semester in course.semester.all()],
            'school': course.school.name,
            'reviews': reviews_data
        }
        return Response(course_info)


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
                )
                return Response({'message': 'create review successfully'}, status=status.HTTP_201_CREATED)
            old_content = old_review.content
            fields_to_update = ['content', 'rating', 'anonymous', 'difficulty', 'grade', 'homework', 'reward']
            for field in fields_to_update:
                setattr(old_review, field, serializer.data[field])
            old_review.save()
            if old_content != serializer.data['content']:
                self.review_history_model.objects.create(review=old_review, content=serializer.data['content'])
            return Response({'message': 'update review successfully'}, status=status.HTTP_201_CREATED)
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
                return Response({"message": "Review not exist"}, status=status.HTTP_400_BAD_REQUEST)
            if review_id.created_by == request.user:
                review_item_model = self.review_model.objects.get(id=review_id.id)
                review_item_model.delete()
                review_history_items = self.review_history_model.objects.filter(review_id=review_id.id)
                for review_history_item in review_history_items:
                    review_history_item.delete()
                return Response({"message": "delete successfully"}, status=status.HTTP_200_OK)
            else:
                return Response({"message": "wrong user"}, status=status.HTTP_401_UNAUTHORIZED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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
                           "avatar_url": "https://www.loliapi.com/acg/pp/"},
                'datetime': review.modify_time,
                'course': {"course_name": review.course.name, "course_id": review.course.id},
                'content': review.content,
                "teachers": [{"teacher_name": teacher.name, "teacher_id": teacher.id} for teacher in
                             review.course.teachers.all()],
                'edited': review.edited, }
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
            .select_related('created_by', 'course')
            .prefetch_related('course__teachers')
        )
        my_review_list = []

        for review in review_set:
            content_history = MyReviewSerializer(review).data
            temp_dict = {
                'id': review.id,
                'anonymous': review.anonymous,
                'datetime': review.modify_time,
                'course': {"course_name": review.course.name, "course_id": review.course.id},
                'content': {"current_content": review.content,
                            "content_history": [x['content'] for x in content_history['review_history']]},
                "teachers": [{"teacher_name": teacher.name, "teacher_id": teacher.id} for teacher in
                             review.course.teachers.all()],
            }
            my_review_list.append(temp_dict)
        return Response({
            "status": 200,
            "message": "Get my review successfully",
            "errors": None,
            "content": {"reviews": my_review_list}
        }, status=status.HTTP_200_OK)
