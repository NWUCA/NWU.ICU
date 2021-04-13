from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.db.models import Avg
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from course_assessment.models import Course, Review

from .models import CourseForm, TeacherForm


class Index(View):
    def get(self, request):
        return render(request, 'index.html')


class CourseList(View):
    def get(self, request):
        context = {'courses': Course.objects.annotate(rating=Avg('review__rating'))}
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
        }
        return render(request, 'course_detail.html', context=context)

    def post(self, request, course_id):
        content = request.POST['content']
        rating = request.POST['rating']
        anonymous = request.POST.get('anonymous', False)
        if anonymous == 'on':
            anonymous = True
        try:
            Review.objects.create(
                course_id=course_id,
                content=content,
                rating=rating,
                created_by=request.user,
                anonymous=anonymous,
            )
            messages.success(request, '添加成功')
        except IntegrityError:
            messages.error(request, '你已经评价过本课程了')
        return redirect(f'/course/{course_id}/')
