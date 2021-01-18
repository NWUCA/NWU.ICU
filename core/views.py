from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import IntegrityError
from django.db.models import Avg
from django.shortcuts import redirect, render
from django.views import View

from core.models import Course, Review, School, Teacher


class Index(View):
    def get(self, request):
        return render(request, 'index.html')


class CourseList(LoginRequiredMixin, View):
    def get(self, request):
        context = {'courses': Course.objects.all()}
        return render(request, 'course_list.html', context=context)

    def post(self, request):
        messages.success(request, 'a test message')
        return redirect('/')


class TeacherView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'teacher.html', context={'schools': School.objects.all()})

    def post(self, request):
        name = request.POST['name']
        school = request.POST['school']
        Teacher.objects.create(name=name, school_id=school, created_by=request.user)
        messages.success(request, '添加成功')
        return redirect('/teacher')


class CourseAddView(LoginRequiredMixin, View):
    def get(self, request):
        context = {
            'classification_choices': Course.classification_choices,
            'teachers': Teacher.objects.all(),
            'schools': School.objects.all(),
        }
        return render(request, 'course_add.html', context=context)

    def post(self, request):
        name = request.POST['name']
        teacher = request.POST['teacher']
        school = request.POST['school']
        classification = request.POST['classification']
        Course.objects.create(
            name=name, school_id=school, teacher_id=teacher, classification=classification, created_by=request.user
        )
        messages.success(request, '添加成功')
        return redirect('/course/')


class CourseView(LoginRequiredMixin, View):
    def get(self, request, course_id):
        context = {
            'reviews': Review.objects.filter(course_id=course_id).select_related('created_by'),
            'rating': Review.objects.filter(course_id=course_id).aggregate(Avg('rating'))['rating__avg'],
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
                course_id=course_id, content=content, rating=rating, created_by=request.user, anonymous=anonymous
            )
            messages.success(request, '添加成功')
        except IntegrityError:
            messages.error(request, '你已经评价过本课程了')
        return redirect(f'/course/{course_id}/')
