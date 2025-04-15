"""
Django settings for NWU.ICU project.

Generated by 'django-admin startproject' using Django 3.1.4.

For more information on this file, see
https://docs.djangoproject.com/en/3.1/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/3.1/ref/settings/
"""
import os
from pathlib import Path

import environ

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(os.path.join(BASE_DIR, '.env'))

# Application definition

INSTALLED_APPS = [
    'course_assessment',
    'common',
    'user',
    # below are 3rd apps
    'captcha',
    'rest_framework',
    # 'silk',
    # below are django apps
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django.contrib.postgres',
]
CSRF_TRUSTED_ORIGINS = ['https://*.mydomain.com', 'https://*.127.0.0.1', 'http://localhost:5173']
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    # 'silk.middleware.SilkyMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    # 'django.middleware.csrf.CsrfViewMiddleware',
    'settings.middle.DisableCSRFMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]
REST_FRAMEWORK = {
    'EXCEPTION_HANDLER': 'utils.utils.custom_exception_handler',  # 不知道为什么会报黄
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
        # 'rest_framework.authentication.TokenAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
}
ROOT_URLCONF = 'settings.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'settings.wsgi.application'

# Database
# https://docs.djangoproject.com/en/3.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': env('DB_NAME'),
        'USER': env('DB_USER'),
        'PASSWORD': env('DB_PASSWORD'),
        'HOST': env('DB_HOST'),
        'PORT': env('DB_PORT'),
    }
}

DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

# Password validation
# https://docs.djangoproject.com/en/3.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
# https://docs.djangoproject.com/en/3.1/topics/i18n/

LANGUAGE_CODE = 'zh-hans'

USE_I18N = True
USE_L10N = True

TIME_ZONE = 'Asia/Shanghai'
USE_TZ = False

# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/3.1/howto/static-files/

STATIC_URL = '/static/'
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

AUTH_USER_MODEL = 'user.User'
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.db.DatabaseCache',  # 将cache持久化保存在硬盘, 防止意外重启导致cache丢失
        'LOCATION': 'my_cache_table',
        'TIMEOUT': 60 * 24,
    }
}
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
    },
    'formatters': {
        'simple': {
            'format': '[{asctime}] {levelname} {name}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'simple',
        },
        'file': {
            'class': 'logging.handlers.RotatingFileHandler',
            'filename': BASE_DIR / 'logs' / 'Web.log',
            'maxBytes': 10 * 1024 * 1024,
            'backupCount': 10,
            'formatter': 'simple',
        },
    },
    'root': {
        'handlers': ['console', 'file'],
        'level': 'INFO',
    },
    'loggers': {
        "django": {
            "handlers": ["console", "file"],
            "level": "INFO",
            'propagate': False,
        },
    },
}
SESSION_COOKIE_AGE = 365 * 24 * 60 * 60  # 365 days, in seconds

# 验证码设置
CAPTCHA_FONT_SIZE = 36
CAPTCHA_LENGTH = 4
CAPTCHA_CHALLENGE_FUNCT = 'captcha.helpers.random_char_challenge'
CAPTCHA_NOISE_FUNCTIONS = ('captcha.helpers.noise_arcs', 'captcha.helpers.noise_dots')
CAPTCHA_FILTER_FUNCTIONS = ('captcha.helpers.post_smooth',)
CAPTCHA_TIMEOUT = 5  # 5 minutes
CAPTCHA_IMAGE_BEFORE_FIELD = False
CAPTCHA_IMAGE_SIZE = (120, 50)

# 文件上传设置
FILE_UPLOAD_SIZE_LIMIT = {'avatar': 66 * 1024,
                          'file': 25 * 1024 * 1024,
                          'img ': 25 * 1024 * 1024}

SESSION_COOKIE_HTTPONLY = False

SECRET_KEY = env('SECRET_KEY')
CAPTCHA_TEST_MODE = env.bool('DEBUG')
DEBUG = env.bool('DEBUG')
ALLOWED_HOSTS = env('ALLOWED_HOSTS').split(',')

UNIVERSITY_MAIL_SUFFIX = env('UNIVERSITY_MAIL_SUFFIX')
UNIVERSITY_TEACHER_MAIL_SUFFIX = env('UNIVERSITY_TEACHER_MAIL_SUFFIX')
UNIVERSITY_STUDENT_MAIL_SUFFIX = env('UNIVERSITY_STUDENT_MAIL_SUFFIX')
UNIVERSITY_CHINESE_NAME = env('UNIVERSITY_CHINESE_NAME')
UNIVERSITY_ENGLISH_NAME = env('UNIVERSITY_ENGLISH_NAME')
UNIVERSITY_ENGLISH_ABBREVIATION_NAME = env('UNIVERSITY_ENGLISH_ABBREVIATION_NAME')
WEBSITE_NAME = env('WEBSITE_NAME', default='NWU.ICU')

# 默认超级用户设置
DEFAULT_SUPER_USER_ID = env('DEFAULT_SUPER_USER_ID')
DEFAULT_SUPER_USER_PASSWORD = env('DEFAULT_SUPER_USER_PASSWORD')
DEFAULT_SUPER_USER_USERNAME = env('DEFAULT_SUPER_USER_USERNAME')
DEFAULT_SUPER_USER_EMAIL = env('DEFAULT_SUPER_USER_EMAIL')

# 默认用户设置
DEFAULT_USER_AVATAR_FILE_NAME = env('DEFAULT_USER_AVATAR_FILE_NAME')
DEFAULT_USER_AVATAR_UUID = env('DEFAULT_USER_AVATAR_UUID')

# 匿名用户设置
ANONYMOUS_USER_AVATAR_FILE_NAME = env('ANONYMOUS_USER_AVATAR_FILE_NAME')
ANONYMOUS_USER_AVATAR_UUID = env('ANONYMOUS_USER_AVATAR_UUID')

# 站外链接
RESOURCES_WEBSITE_URL = env('RESOURCES_WEBSITE_URL')

# 邮箱设置
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = os.getenv('EMAIL_HOST', "smtp.your.email.server")
EMAIL_PORT = os.getenv('EMAIL_PORT', '465')
EMAIL_USE_SSL = True
# You need to make sure your SMTP server uses SSL, otherwise use TLS
# EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD')
