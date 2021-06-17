from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.db.models import Avg, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from course_assessment.models import Course, Review

from .models import CourseForm, ReviewForm, TeacherForm


class CourseList(View):
    def get(self, request):
        search_string = request.GET.get('s', "")
        if search_string:
            course_set = Course.objects.filter(
                Q(name__contains=search_string) | Q(teacher__name__contains=search_string)
            )
        else:
            course_set = Course.objects.all()
        context = {
            'courses': course_set.order_by('school').annotate(rating=Avg('review__rating')),
            'search_string': search_string,
        }
        return render(request, 'course_list.html', context=context)

    def post(self, request):
        messages.success(request, 'a test message')
        return redirect('/')


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
