from django.db import models
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from user.models import User


class Semeseter(models.Model):
    """开课学期"""

    name = models.CharField(max_length=20, null=True, blank=True)

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
    average_rating = models.FloatField(default=0.0, verbose_name='平均评分', null=True)
    normalized_rating = models.FloatField(default=0.0, verbose_name='归一化平均评分', null=True)

    def __str__(self):
        return f"{self.id}-{self.name}-{self.get_teachers()}"

    @property
    def get_name(self):
        return self.name.replace('）', ')').replace('（', '(')

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
    like_count = models.IntegerField(default=0, verbose_name='点赞')
    dislike_count = models.IntegerField(default=0, verbose_name='点踩')
    difficulty = models.PositiveSmallIntegerField(verbose_name='课程难度', choices=DIFFICULTY_CHOICES)
    grade = models.PositiveSmallIntegerField(verbose_name='给分高低', choices=GRADE_CHOICES)
    homework = models.PositiveSmallIntegerField(verbose_name='作业多少', choices=HOMEWORK_CHOICES)
    reward = models.PositiveSmallIntegerField(verbose_name='收获多少', choices=REWARD_CHOICES)
    source = models.CharField(verbose_name='来源', default='user', max_length=20)
    semester = models.ForeignKey(Semeseter, default=1, on_delete=models.CASCADE, verbose_name="开课学期")

    class Meta:
        constraints = [models.UniqueConstraint(fields=['course', 'created_by'], name='unique_review')]


class ReviewHistory(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    content = models.TextField(verbose_name='内容')
    create_time = models.DateTimeField(auto_now_add=True)


class ReviewReply(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    content = models.TextField()
    create_time = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    like_count = models.IntegerField(default=0, verbose_name='点赞')
    dislike_count = models.IntegerField(default=0, verbose_name='点踩')


class ReviewAndReplyLike(models.Model):
    review_reply = models.ForeignKey(ReviewReply, on_delete=models.CASCADE, null=True)
    review = models.ForeignKey(Review, on_delete=models.CASCADE)
    create_time = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    like = models.SmallIntegerField(default=0, null=True)


def update_like_dislike_counts(instance):
    if instance.review and not instance.review_reply:
        review = instance.review
        review.like_count = ReviewAndReplyLike.objects.filter(review=review, like=1).count()
        review.dislike_count = ReviewAndReplyLike.objects.filter(review=review, like=-1).count()
        review.save()

    if instance.review_reply:
        review_reply = instance.review_reply
        review_reply.like_count = ReviewAndReplyLike.objects.filter(review_reply=review_reply, like=1).count()
        review_reply.dislike_count = ReviewAndReplyLike.objects.filter(review_reply=review_reply, like=-1).count()
        review_reply.save()


@receiver(post_save, sender=ReviewAndReplyLike)
@receiver(post_delete, sender=ReviewAndReplyLike)
def review_and_reply_like_changed(sender, instance, **kwargs):
    update_like_dislike_counts(instance)
