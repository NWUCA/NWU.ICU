from crispy_forms.helper import FormHelper
from crispy_forms.layout import Submit
from django import forms
from django.db import models

from user.models import User


class Semeseter(models.Model):
    """开课学期"""

    name = models.CharField(max_length=20)

    def __str__(self):
        return self.name


class School(models.Model):
    """院系"""

    name = models.TextField(unique=True)

    def __str__(self):
        return self.name


class Teacher(models.Model):
    """
    教务系统中课表只能够获取到教师姓名, 故对于重名的老师, 我们只能认为他们是同一个人
    """

    name = models.CharField(max_length=20, verbose_name='姓名')
    # 因为是根据课程确定的教师院系, 可能不准确
    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name='院系', null=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    created_time = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.name}'

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
        ('required', '必修'),
        ('optional', '选修'),
    )  # 从教务系统导入的课表中只有通识, 必修, 选修三类
    course_id = models.CharField(max_length=30, verbose_name='课程号')
    name = models.CharField(max_length=30, verbose_name='课程名称', db_index=True)
    teachers = models.ManyToManyField(Teacher, db_index=True, related_name='books')
    classification = models.TextField(choices=classification_choices, verbose_name='分类')
    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name='院系')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    created_time = models.DateTimeField(auto_now_add=True)
    semester = models.ManyToManyField(Semeseter, verbose_name="开课学期")

    def __str__(self):
        return f"{self.name}-{self.get_teachers()}"

    def get_teachers(self):
        return ",".join([t.name for t in self.teachers.all()])

    class Meta:
        ordering = ['school']


class CourseForm(forms.ModelForm):
    helper = FormHelper()
    helper.add_input(Submit('submit', '提交'))

    class Meta:
        model = Course
        fields = ['name', 'teachers', 'classification', 'school']
        help_texts = {'teacher': '没有找到想要的老师? <a href="/teacher/">点击添加</a>'}


class Review(models.Model):
    step_choices = (
        ('low', '低'),
        ('medium', '中'),
        ('high', '高'),
    )

    source_choice = (('user', '用户生成'),)

    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    content = models.TextField(verbose_name='内容')
    rating = models.SmallIntegerField(verbose_name='打分 (满分 5 分)')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    anonymous = models.BooleanField(verbose_name='匿名评价', default=True)
    created_time = models.DateTimeField(auto_now_add=True)
    like = models.IntegerField(default=0, verbose_name='点赞')
    difficulty = models.PositiveSmallIntegerField(verbose_name='课程难度')
    grade = models.PositiveSmallIntegerField(verbose_name='给分高低')
    homework = models.PositiveSmallIntegerField(verbose_name='作业多少')
    reward = models.PositiveSmallIntegerField(verbose_name='收获多少')
    source = models.CharField(verbose_name='来源', default='user', max_length=20)
    # TODO: 文件/图片上传

    class Meta:
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
        help_texts = {'content': '可以从课程难度、作业多少、给分好坏、收获大小等方面阐述'}
