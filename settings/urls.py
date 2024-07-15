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
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView, SpectacularRedocView

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
from course_assessment.views import (
    LatestReviewView,
    MyReviewView
)
from user.views import Login, Logout, RegisterView, PasswordResetView

api_patterns = [
    path('about/', AboutView.as_view(), name='schema'),

    # 课程评价
    path('review/my-review', MyReviewView.as_view()),
    path('review/lastest', LatestReviewView.as_view()),

    # 用户
    path('user/login/', Login.as_view(), name='login'),
    path('user/logout/', Logout.as_view(), name='logout'),
    path('user/register/', RegisterView.as_view(), name='register'),
    path('user/reset/', PasswordResetView.as_view(), name='reset'),

    # 验证码
    path('captcha/', CaptchaView.as_view(), name='captcha'),

    # tos
    path('tos/', TosView.as_view(), name='captcha'),
]
urlpatterns = [
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/schema/swagger-ui/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/schema/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
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
