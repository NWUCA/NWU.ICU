import logging

from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, render
from django.views import View
from django.views.generic import ListView
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from course_assessment.models import Course, Review
from course_assessment.serializer import MyReviewSerializer

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


class CourseView(View):
    def get(self, request, course_id):
        course = get_object_or_404(Course, id=course_id)
        reviews = (
            Review.objects.filter(course_id=course_id)
            .select_related('created_by')
            .order_by('-create_time')
        )
        aggregation = reviews.aggregate(
            Avg('rating'), Avg('grade'), Avg('homework'), Avg('reward'), Avg('difficulty')
        )

        is_reviewed = (
            False
            if not request.user.is_authenticated
            else reviews.filter(created_by=request.user).exists()
        )

        context = {
            'course': course,
            'reviews': reviews,
            'rating': aggregation['rating__avg'],
            'grade': Review.GRADE_CHOICES[round(aggregation['grade__avg']) - 1][1]
            if aggregation['grade__avg']
            else '暂无',
            'homework': Review.HOMEWORK_CHOICES[round(aggregation['homework__avg']) - 1][1]
            if aggregation['homework__avg']
            else '暂无',
            'reward': Review.REWARD_CHOICES[round(aggregation['reward__avg']) - 1][1]
            if aggregation['reward__avg']
            else '暂无',
            'difficulty': Review.DIFFICULTY_CHOICES[round(aggregation['difficulty__avg']) - 1][1]
            if aggregation['difficulty__avg']
            else '暂无',
            'is_reviewed': is_reviewed,
            # 'review_histories': ReviewHistory.objects.filter(review__id__in=reviews),
        }
        # print(context['review_histories'])
        return render(request, 'course_detail.html', context=context)


class ReviewAddView(APIView):
    model = Review
    permission_classes = [IsAuthenticated]

    def post(self, request):
        defaults = {
            "course": Course.objects.get(id=request.data['course']),
            "content": request.data['content'],
            "created_by": request.user,
            "rating": request.data['rating'],
            "anonymous": request.data['anonymous'],
            "edited": False,
            "difficulty": request.data['difficulty'],
            "grade": request.data['grade'],
            "homework": request.data['homework'],
            "reward": request.data['reward'],
            "source": request.data['source'],
        }
        obj, created = self.model.objects.update_or_create(
            defaults=defaults
        )
        return Response({"message": "Created" if created else "Updated", "course": obj.course.name},
                        status=status.HTTP_201_CREATED)


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
