import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    name = models.CharField(max_length=255, null=True)
    nickname = models.CharField(max_length=30)
    college_email = models.EmailField(max_length=255, null=True)
    college_email_verified = models.BooleanField(default=False)
    avatar_uuid = models.UUIDField(default=uuid.uuid4, editable=False)
    bio = models.CharField(max_length=255, null=True)
    following = models.ManyToManyField('self', related_name='followers', symmetrical=False)
    followed_courses = models.ManyToManyField('course_assessment.Course', related_name='followCourse', blank=True)
    private_review = models.CharField(choices=[('0', '允许所有人'), ('1', '允许登录用户'), ('2', '禁止所有人')],
                                      default='false')
    private_reply = models.CharField(choices=[('0', '允许所有人'), ('1', '允许登录用户'), ('2', '禁止所有人')],
                                     default='false')
    REQUIRED_FIELDS = []

    @property
    def following_count(self):
        return self.following.count()

    @property
    def followers_count(self):
        return self.followers.count()

    @property
    def follow_course_count(self):
        return self.followed_courses.count()

    def follow_course(self, course):
        """Follow a course."""
        self.followed_courses.add(course)

    def unfollow_course(self, course):
        """Unfollow a course."""
        self.followed_courses.remove(course)

    def is_following_course(self, course):
        """Check if the user is following a course."""
        return self.followed_courses.filter(pk=course.pk).exists()

    def get_followed_courses(self):
        """Get all courses that the user is following."""
        return self.followed_courses.all()

    def follow(self, user):
        """Follow a user."""
        self.following.add(user)

    def unfollow(self, user):
        """Unfollow a user."""
        self.following.remove(user)

    def is_following(self, user):
        """Check if the user is following another user."""
        return self.following.filter(pk=user.pk).exists()

    def get_followers(self):
        """Get all followers of the user."""
        return self.followers.all()

    def get_following(self):
        """Get all users that the user is following."""
        return self.following.all()
