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
    FileUpdateView,
)
from common.views import (
    index,
    AboutView,
    CaptchaView,
    TosView, MessageBoxView,
)
from course_assessment.views import (
    MyReviewView,
    ReviewView,
    CourseView,
    TeacherView,
    ReviewReplyView,
    ReviewAndReplyLikeView, MyReviewReplyView, courseTeacherSearchView,
)
from user.views import (
    Login,
    Logout,
    UsernameDuplicationView,
    RegisterView,
    PasswordResetView,
    PasswordMailResetView, ProfileView, PasswordResetWhenLoginView, BindNwuEmailView,
)

api_patterns = [
    path('about/', AboutView.as_view(), name='about'),

    # 课程评价
    path('review/my-review/', MyReviewView.as_view()),
    path('review/my-review-reply/', MyReviewReplyView.as_view()),
    path('review/review/', ReviewView.as_view()),
    path('review/course/<int:course_id>/', CourseView.as_view()),
    path('review/teacher/<int:teacher_id>/', TeacherView.as_view()),
    path('review/reply/<int:review_id>/', ReviewReplyView.as_view()),
    path('review/reply/like/', ReviewAndReplyLikeView.as_view()),
    path('review/course/like/', ReviewAndReplyLikeView.as_view()),
    path('review/search/', courseTeacherSearchView.as_view()),

    # 用户
    path('user/login/', Login.as_view(), name='login'),
    path('user/profile/', ProfileView.as_view(), name='profile'),
    path('user/logout/', Logout.as_view(), name='logout'),
    path('user/register/', RegisterView.as_view(), name='register'),
    path('user/register/<str:email_b64>/<str:uid>/<str:token>/', RegisterView.as_view(),
         name='register-get'),
    path('user/username/', UsernameDuplicationView.as_view(), name='username'),
    path('user/reset/', PasswordResetView.as_view(), name='reset'),
    path('user/mail-reset/<str:uid>/<str:token>/', PasswordMailResetView.as_view(), name='mail-reset'),
    path('user/reset-login/', PasswordResetWhenLoginView.as_view(), name='reset-login'),  # 通过旧密码在登录时重置密码
    path('user/bind-nwu-email/<str:email_b64>/<str:uid>/<str:token>/', BindNwuEmailView.as_view(),
         name='bind-nwu-email-get'),
    path('user/bind-nwu-email/', BindNwuEmailView.as_view(),
         name='bind-nwu-email-post'),

    # 站内信
    path('message/',MessageBoxView.as_view(),name='messageBox'),
    path('message/<int:sender_id>',MessageBoxView.as_view(),name='messageSender'),
    # 验证码
    path('captcha/', CaptchaView.as_view(), name='captcha'),

    # tos
    path('tos/', TosView.as_view(), name='captcha'),

    # 文件操作
    path('upload/', FileUploadView.as_view(), name='file-upload'),
    path('download/<uuid:file_uuid>/', FileDownloadView.as_view(), name='file-download'),
    path('delete/<uuid:id>/', FileDeleteView.as_view(), name='file-delete'),
    path('update/<uuid:id>/', FileUpdateView.as_view(), name='file-update'),
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
