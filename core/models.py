from django.db import models
from user.models import User


class School(models.Model):
    """院系"""
    name = models.TextField(unique=True)

    def __str__(self):
        return self.name


class Teacher(models.Model):
    name = models.TextField()
    school = models.ForeignKey(School, on_delete=models.CASCADE)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)

    def __str__(self):
        return f'{self.name}-{self.school}'


class Course(models.Model):
    classification_choices = (
        ('general', '通识'),
        ('pe', '体育'),
        ('english', '英语'),
        ('professional', '专业课'),
        ('politics', '政治'),
    )
    name = models.TextField()
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)
    classification = models.TextField(choices=classification_choices)
    school = models.ForeignKey(School, on_delete=models.CASCADE)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)


class Review(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    content = models.TextField()
    rating = models.SmallIntegerField()
    created_by = models.ForeignKey(User, on_delete=models.CASCADE)
    anonymous = models.BooleanField()
