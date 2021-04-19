from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from django import forms
from django.db import models

from user.models import User


class School(models.Model):
    """院系"""

    name = models.TextField(unique=True)

    def __str__(self):
        return self.name


class Teacher(models.Model):
    name = models.CharField(max_length=20, verbose_name='姓名')
    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name='院系')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        return f'{self.name}-{self.school}'

    class Meta:
        ordering = ['school']


class TeacherForm(forms.ModelForm):
    helper = FormHelper()
    helper.add_input(Submit('submit', '提交'))

    class Meta:
        model = Teacher
        fields = ['name', 'school']


class Course(models.Model):
    classification_choices = (
        ('general', '通识'),
        ('pe', '体育'),
        ('english', '英语'),
        ('professional', '专业课'),
        ('politics', '政治'),
    )
    name = models.CharField(max_length=30, verbose_name='课程名称')
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE, verbose_name='教师')
    classification = models.TextField(choices=classification_choices, verbose_name='分类')
    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name='院系')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['school']


class CourseForm(forms.ModelForm):
    helper = FormHelper()
    helper.add_input(Submit('submit', '提交'))

    class Meta:
        model = Course
        fields = ['name', 'teacher', 'classification', 'school']
        help_texts = {'teacher': '没有找到想要的老师? <a href="/teacher/">点击添加</a>'}


class Review(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    content = models.TextField(verbose_name='内容')
    rating = models.SmallIntegerField(verbose_name='打分 (满分 5 分)')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    anonymous = models.BooleanField(verbose_name='匿名评价')

    class Meta:
        ordering = ['created_by']
        constraints = [
            models.UniqueConstraint(fields=['course', 'created_by'], name='unique_review')
        ]


class ReviewForm(forms.ModelForm):
    helper = FormHelper()
    helper.add_input(Submit('submit', '提交'))

    class Meta:
        model = Review
        fields = ['content', 'rating', 'anonymous']
        widgets = {'rating': forms.Select(choices=[(i, f'{i}分') for i in range(1, 6)])}
