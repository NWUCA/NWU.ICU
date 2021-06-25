from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.db.models import Avg, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import ListView

from course_assessment.models import Course, Review

from .models import CourseForm, ReviewForm, TeacherForm


class CourseList(ListView):
    template_name = 'course_list.html'
    model = Course

    def get_queryset(self):
        search_string = self.request.GET.get('s', "")
        course_set = self.model.objects.all()
        if search_string:
            course_set = self.model.objects.filter(
                Q(name__contains=search_string) | Q(teacher__name__contains=search_string)
            )
        return course_set

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['courses'] = (
            self.get_queryset().order_by('school').annotate(rating=Avg('review__rating'))
        )
        context['search_string'] = self.request.GET.get('s', "")
        return context


class TeacherView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'teacher.html', context={'form': TeacherForm()})

    def post(self, request):
        f = TeacherForm(request.POST)
        f.instance.created_by = request.user
        f.save()
        messages.success(request, '添加成功')
        return redirect('/course/')


class CourseAddView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'course_add.html', context={'form': CourseForm()})

    def post(self, request):
        f = CourseForm(request.POST)
        f.instance.created_by = request.user
        f.save()
        messages.success(request, '添加成功')
        return redirect('/course/')


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
