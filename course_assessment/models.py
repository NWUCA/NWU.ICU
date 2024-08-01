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
    course_code = models.CharField(max_length=30, verbose_name='课程号')
    name = models.CharField(max_length=30, verbose_name='课程名称', db_index=True)
    teachers = models.ManyToManyField(Teacher, db_index=True, related_name='books')
    classification = models.TextField(choices=classification_choices, verbose_name='分类')
    school = models.ForeignKey(School, on_delete=models.CASCADE, verbose_name='院系')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, null=True)
    created_time = models.DateTimeField(auto_now_add=True)
    semester = models.ManyToManyField(Semeseter, verbose_name="开课学期")

    def __str__(self):
        return f"{self.id}-{self.name}-{self.get_teachers()}"

    def get_teachers(self):
        return ",".join([t.name for t in self.teachers.all()])

    class Meta:
        ordering = ['school']


class Review(models.Model):
    DIFFICULTY_CHOICES = [
        (1, '简单'),
        (2, '中等'),
        (3, '困难'),
    ]
    GRADE_CHOICES = [
        (1, '超好'),
        (2, '一般'),
        (3, '杀手'),
    ]
    HOMEWORK_CHOICES = [
        (1, '不多'),
        (2, '中等'),
        (3, '超多'),
    ]
    REWARD_CHOICES = [
        (1, '很多'),
        (2, '一般'),
        (3, '没有'),
    ]

    source_choice = (('user', '用户生成'),)

    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    content = models.TextField(verbose_name='内容')
    rating = models.SmallIntegerField(verbose_name='打分 (满分 5 分)')
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    anonymous = models.BooleanField(verbose_name='匿名评价', default=True)
    create_time = models.DateTimeField(auto_now_add=True)
    modify_time = models.DateTimeField(auto_now=True)
    # 不能使用 create_time 和 modify_time 是否相等来判断是否已编辑
    # 因为在 save model 的时候两者的时间会有微小的差异
    edited = models.BooleanField(verbose_name="已编辑", default=False)
    like = models.IntegerField(default=0, verbose_name='点赞')
    difficulty = models.PositiveSmallIntegerField(verbose_name='课程难度', choices=DIFFICULTY_CHOICES)
    grade = models.PositiveSmallIntegerField(verbose_name='给分高低', choices=GRADE_CHOICES)
    homework = models.PositiveSmallIntegerField(verbose_name='作业多少', choices=HOMEWORK_CHOICES)
    reward = models.PositiveSmallIntegerField(verbose_name='收获多少', choices=REWARD_CHOICES)
    source = models.CharField(verbose_name='来源', default='user', max_length=20)
    semester = models.ForeignKey(Semeseter, on_delete=models.CASCADE, verbose_name="开课学期")

    class Meta:
        constraints = [models.UniqueConstraint(fields=['course', 'created_by'], name='unique_review')]


class ReviewHistory(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    content = models.TextField(verbose_name='内容')
    create_time = models.DateTimeField(auto_now_add=True)


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['content', 'rating', 'difficulty', 'grade', 'homework', 'reward']
