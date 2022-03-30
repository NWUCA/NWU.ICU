from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from course_assessment.models import Course, Review

from .models import ReviewForm


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
        )
        if search_string:
            course_set = course_set.filter(
                Q(name__contains=search_string) | Q(teachers__name__contains=search_string)
            )
        return course_set

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_string'] = self.request.GET.get('s', "")
        context['review_count'] = Review.objects.count()
        return context


class CourseView(LoginRequiredMixin, View):
    def get(self, request, course_id):
        course = get_object_or_404(Course, id=course_id)
        context = {
            'course': course,
            'reviews': Review.objects.filter(course_id=course_id).select_related('created_by'),
            'rating': Review.objects.filter(course_id=course_id).aggregate(Avg('rating'))[
                'rating__avg'
            ],
            'review_form': ReviewForm(),
        }
        return render(request, 'course_detail.html', context=context)


class ReviewAddView(LoginRequiredMixin, View):
    def get(self, request, course_id):
        return render(request, 'review_add.html', context={'form': ReviewForm()})

    def post(self, request, course_id):
        f = ReviewForm(request.POST)
        f.instance.created_by = request.user
        f.instance.course_id = course_id
        try:
            f.save()
            messages.success(request, '添加成功')
        except IntegrityError:
            messages.error(request, '你已经评价过本课程了')
        return redirect(f'/course/{course_id}/')
