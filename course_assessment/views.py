import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from course_assessment.models import Course, Review

from .models import ReviewForm

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
            .order_by('created_by')
        )
        aggregation = reviews.aggregate(
            Avg('rating'), Avg('grade'), Avg('homework'), Avg('reward'), Avg('difficulty')
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
            'review_form': ReviewForm(),
        }
        return render(request, 'course_detail.html', context=context)


class ReviewAddView(LoginRequiredMixin, View):
    def get(self, request, course_id):
        course = get_object_or_404(Course, id=course_id)
        form = ReviewForm()
        # print(type(form['difficulty']))
        # print(form['difficulty'])
        return render(request, 'review_add.html', context={'form': form, 'course': course})

    def post(self, request, course_id):
        f = ReviewForm(request.POST)
        f.instance.created_by = request.user
        f.instance.course_id = course_id
        if not f.is_valid():
            messages.error(request, '表单字段错误')
            return redirect(f'/course/{course_id}/')
        try:
            review = f.save()
            messages.success(request, '添加成功')
            logger.error(f"{request.user} 为 {review.course} 课程添加了一条评价, 内容为: {review.content}")
        except IntegrityError:
            messages.error(request, '你已经评价过本课程了')
        return redirect(f'/course/{course_id}/')


class LatestReviewView(ListView):
    template_name = 'latest_review.html'
    model = Review
    paginate_by = 10

    def get_queryset(self):
        review_set = self.model.objects.all().order_by('-created_time').select_related('created_by')
        return review_set

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['review_count'] = Review.objects.count()
        return context
