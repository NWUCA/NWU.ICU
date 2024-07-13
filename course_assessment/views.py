import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from course_assessment.models import Course, Review, ReviewForm, ReviewHistory
from course_assessment.review_serializer import ReviewSerializer

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


class ReviewAddView(LoginRequiredMixin, View):
    def get(self, request, course_id):
        course = get_object_or_404(Course, id=course_id)
        context = {'course': course}
        try:
            user_review = Review.objects.get(course_id=course_id, created_by=request.user)
            form = ReviewForm(instance=user_review)
            context['modify'] = True
        except Review.DoesNotExist:
            form = ReviewForm()
            context['modify'] = False
        context['form'] = form
        # print(type(form['difficulty']))
        # print(form['difficulty'])
        return render(request, 'review_add.html', context=context)

    def post(self, request, course_id):
        try:
            old_review = Review.objects.get(course_id=course_id, created_by=request.user)
            old_content = old_review.content
            modify = True
            f = ReviewForm(request.POST, instance=old_review)
            f.instance.edited = True
        except Review.DoesNotExist:
            modify = False
            f = ReviewForm(request.POST)
        f.instance.created_by = request.user
        f.instance.course_id = course_id
        if not f.is_valid():
            messages.error(request, '表单字段错误')
            return redirect(f'/course/{course_id}/')

        review = f.save()
        if not modify:
            messages.success(request, '添加成功')
            logger.error(f"{request.user} 为 {review.course} 课程添加了一条评价, 内容为: {review.content}")
        else:
            ReviewHistory.objects.create(
                review=review,
                content=old_content,
            )
            messages.success(request, '修改成功')
            logger.error(
                f"{request.user} 修改了 {review.course} 课程的一条评价.\n"
                f"现内容为: {review.content}\n"
                f"原内容为: {old_content}"
            )
        return redirect(f'/course/{course_id}/')


class LatestReviewView(APIView):
    permission_classes = [AllowAny]
    model = Review

    def get(self, request):
        current_page = int(request.query_params.get('currentPage', 1))
        page_size = int(request.query_params.get('pageSize', 10))
        desc = request.query_params.get('desc', '1')
        review__all_set = (
            Review.objects.all()
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
            content_history = ReviewSerializer(review).data
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
