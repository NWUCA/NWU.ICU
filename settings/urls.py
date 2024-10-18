"""NWU.ICU URL Configuration

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/3.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.conf import settings
from django.contrib import admin
from django.urls import include
from django.urls import path

from common.file.view import (
    FileDownloadView,
    FileUploadView,
    FileDeleteView,
)
from common.views import (
    index,
    AboutView,
    CaptchaView,
    TosView, MessageBoxView, BulletinListView, MessageUnreadView,
)
from course_assessment.views import (
    MyReviewView,
    ReviewView,
    CourseView,
    TeacherView,
    ReviewReplyView,
    ReviewAndReplyLikeView, MyReviewReplyView, CourseTeacherSearchView, CourseList, CourseLikeView, SchoolView,
    LatestReviewView, SemesterView,
)
from user.views import (
    Login,
    Logout,
    UsernameDuplicationView,
    RegisterView,
    PasswordResetView,
    PasswordMailResetView, ProfileView, PasswordResetWhenLoginView, BindCollegeEmailView, ActiveUser,
)

api_patterns = [

    # 课程评价
    path('assessment/my/review/', MyReviewView.as_view()),
    path('assessment/my/reply/', MyReviewReplyView.as_view()),
    path('assessment/review/', ReviewView.as_view()),
    path('assessment/review/<int:review_id>/', ReviewView.as_view()),
    path('assessment/latest-review/', LatestReviewView.as_view()),
    path('assessment/courselist/', CourseList.as_view()),
    path('assessment/course/<int:course_id>/', CourseView.as_view()),
    path('assessment/course/', CourseView.as_view()),
    path('assessment/course/like/', CourseLikeView.as_view()),
    path('assessment/teacher/<int:teacher_id>/', TeacherView.as_view()),
    path('assessment/teacher/', TeacherView.as_view()),
    path('assessment/reply/<int:review_id>/', ReviewReplyView.as_view()),
    path('assessment/reply/', ReviewReplyView.as_view()),
    path('assessment/reply/like/', ReviewAndReplyLikeView.as_view()),
    path('assessment/course/like/', ReviewAndReplyLikeView.as_view()),
    path('assessment/search/', CourseTeacherSearchView.as_view()),
    path('assessment/school/', SchoolView.as_view()),
    path('assessment/semester/', SemesterView.as_view()),
    # 用户
    path('user/login/', Login.as_view(), name='login'),
    path('user/profile/', ProfileView.as_view(), name='profile'),
    path('user/logout/', Logout.as_view(), name='logout'),
    path('user/register/', RegisterView.as_view(), name='register'),
    path('user/active/', ActiveUser.as_view(), name='active'),
    path('user/username/', UsernameDuplicationView.as_view(), name='username'),
    path('user/reset/', PasswordResetView.as_view(), name='reset'),
    path('user/mail-reset/<str:token>/', PasswordMailResetView.as_view(), name='mail-reset'),
    path('user/reset-login/', PasswordResetWhenLoginView.as_view(), name='reset-login'),  # 通过旧密码在登录时重置密码
    path('user/bind-college-email/<str:token>/', BindCollegeEmailView.as_view(),
         name='bind-college-email-get'),
    path('user/bind-college-email/', BindCollegeEmailView.as_view(),
         name='bind-college-email-post'),

    # 站内信
    path('message/', MessageBoxView.as_view(), name='send_message'),
    path('message/unread/', MessageUnreadView.as_view(), name='unread_message'),
    path('message/<str:classify>/<int:chatter_id>', MessageBoxView.as_view(), name='check_particular_message'),
    path('message/<str:classify>/', MessageBoxView.as_view(), name='check_all_message'),

    # 验证码
    path('captcha/', CaptchaView.as_view(), name='captcha'),

    # tos
    path('tos/', TosView.as_view(), name='captcha'),
    path('about/', AboutView.as_view(), name='about'),
    path('bulletins/', BulletinListView.as_view(), name='bulletins'),

    # 文件操作
    path('upload/', FileUploadView.as_view(), name='file-upload'),
    path('download/<uuid:file_uuid>/', FileDownloadView.as_view(), name='file-download'),
    path('delete/<uuid:id>/', FileDeleteView.as_view(), name='file-delete'),
    # path('update/<uuid:id>/', FileUpdateView.as_view(), name='file-update'),
]
urlpatterns = [
    path('admin/', admin.site.urls),
    # path('silk/', include('silk.urls', namespace='silk')),
    path('', index, name='homepage'),
    path('api/captcha/', include('captcha.urls')),

    path('api/', include((api_patterns, 'api'))),
]

if "debug_toolbar" in settings.INSTALLED_APPS:
    urlpatterns += (path('__debug__/', include('debug_toolbar.urls')),)
