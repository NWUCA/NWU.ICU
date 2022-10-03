import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from course_assessment.models import Course, Review, ReviewForm, ReviewHistory

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
            'review_histories': ReviewHistory.objects.filter(review__id__in=reviews),
        }
        print(context['review_histories'])
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
            user_review = Review.objects.get(course_id=course_id, created_by=request.user)
            modify = True
            f = ReviewForm(request.POST, instance=user_review)
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
            messages.success(request, '修改成功')
            logger.error(
                f"{request.user} 修改了 {review.course} 课程的一条评价.\n"
                f"现内容为: {review.content}\n"
                f"原内容为: {user_review.content}"
            )
        return redirect(f'/course/{course_id}/')


class LatestReviewView(ListView):
    template_name = 'latest_review.html'
    model = Review
    paginate_by = 7

    def get_queryset(self):
        review_set = (
            self.model.objects.all()
            .order_by('-created_time')
            .select_related('created_by', 'course')
            .prefetch_related('course__teachers')
        )
        return review_set

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['review_count'] = Review.objects.count()
        return context
