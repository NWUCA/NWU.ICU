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

from common.views import (
    Settings,
    index,
    manifest,
    save_push_subscription,
    send_test_notification,
    service_worker,
    AboutView,
    CaptchaView,
    TosView,
)
from common.file.view import (
    FileDownloadView,
    FileUploadView,
    FileDeleteView,
    FileUpdateView,
)
from course_assessment.views import (
    LatestReviewView,
    MyReviewView,
    ReviewAddView,
    ReviewDeleteView,
    CourseView,
    TeacherView,
)
from user.views import (
    Login,
    Logout,
    UsernameDuplicationView,
    RegisterView,
    PasswordResetView,
    PasswordMailResetView,
)

api_patterns = [
    path('about/', AboutView.as_view(), name='about'),

    # 课程评价
    path('review/my-review/', MyReviewView.as_view()),
    path('review/latest/', LatestReviewView.as_view()),
    path('review/add/', ReviewAddView.as_view()),
    path('review/delete/', ReviewDeleteView.as_view()),
    path('review/course/<int:course_id>/', CourseView.as_view()),
    path('review/teacher/<int:teacher_id>/', TeacherView.as_view()),

    # 用户
    path('user/login/', Login.as_view(), name='login'),
    path('user/logout/', Logout.as_view(), name='logout'),
    path('user/register/', RegisterView.as_view(), name='register'),
    path('user/username/', UsernameDuplicationView.as_view(), name='username'),
    path('user/reset/', PasswordResetView.as_view(), name='reset'),
    path('user/mail-reset/<str:uid>/<str:token>/', PasswordMailResetView.as_view(), name='mail-reset'),

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
    path('manifest.json', manifest),
    path('serviceworker.js', service_worker),
    path('', index, name='homepage'),
    path('settings/', Settings.as_view()),
    path('api/save-subscription/', save_push_subscription),
    path('api/send-test-notification', send_test_notification),
    path('captcha/', include('captcha.urls')),

    path('api/', include((api_patterns, 'api'))),
]

if "debug_toolbar" in settings.INSTALLED_APPS:
    urlpatterns += (path('__debug__/', include('debug_toolbar.urls')),)
