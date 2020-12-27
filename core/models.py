from django.db import models


class Teacher(models.Model):
    name = models.TextField()


class Subject(models.Model):
    classification_choices = (
        ('general', '通识'),
        ('pe', '体育'),
        ('english', '英语'),
        ('professional', '专业课')
    )
    name = models.TextField()
    classification = models.TextField(choices=classification_choices)
    school = models.TextField(help_text='院系')


class Course(models.Model):
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    teacher = models.ForeignKey(Teacher, on_delete=models.CASCADE)


class Review(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    content = models.TextField()
    rating = models.SmallIntegerField()
