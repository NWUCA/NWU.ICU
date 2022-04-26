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
from django.urls import include, path, re_path

from common.views import (
    Settings,
    about,
    index,
    manifest,
    save_push_subscription,
    send_test_notification,
    service_worker,
    tos,
)
from course_assessment.views import CourseList, CourseView, ReviewAddView
from report.views import ReportIndex, check_cookie_status
from user.views import Login, Logout, RefreshCookies

urlpatterns = [
    path('admin/', admin.site.urls),
    # path('silk/', include('silk.urls', namespace='silk')),
    path('manifest.json', manifest),
    path('serviceworker.js', service_worker),
    path('', index),
    path('tos/', tos),
    path('about/', about),
    path('settings/', Settings.as_view()),
    path('api/save-subscription/', save_push_subscription),
    path('api/send-test-notification', send_test_notification),
    path('course_list/', CourseList.as_view()),
    path('login/', Login.as_view()),
    path('logout/', Logout.as_view()),
    path('course/<int:course_id>/', CourseView.as_view()),
    path('course/<int:course_id>/review_add/', ReviewAddView.as_view()),
    path('report/', ReportIndex.as_view()),
    path('api/report/check-cookie-status/', check_cookie_status),
    re_path(r'^report/*$', ReportIndex.as_view()),  # 会有人访问 /// 这样的坑爹路径
    path('refresh_cookies/', RefreshCookies.as_view()),
]

if "debug_toolbar" in settings.INSTALLED_APPS:
    urlpatterns += (path('__debug__/', include('debug_toolbar.urls')),)
