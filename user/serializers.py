import re

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from rest_framework import serializers
from soupsieve.util import lower

import settings.settings
from common.file.models import UploadedFile
from common.serializers import CaptchaSerializer
from user.models import User
from common.utils import get_err_msg


def username_checker(username):
    if not (8 <= len(username) <= 29):
        raise serializers.ValidationError({'username': get_err_msg('username_not_match_length')})
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        raise serializers.ValidationError({'username': get_err_msg('username_invalid_char')})
    pattern_checks = [
        (r'[a-z]', '用户名必须包含至少一个字母'),
    ]

    for pattern, error_message in pattern_checks:
        if not re.search(pattern, username):
            raise serializers.ValidationError({'username': error_message})
    if User.objects.filter(username=username).exists():
        raise serializers.ValidationError({'username': get_err_msg('username_duplicate')})


def password_complexity_checker(password):
    if len(password) < 8 or len(password) > 30:
        raise serializers.ValidationError({'password': get_err_msg('password_not_match_length')})

    pattern_checks = [r'[A-Z]', r'[a-z]', r'[0-9]']

    for pattern in pattern_checks:
        if not re.search(pattern, password):
            raise serializers.ValidationError({'password': get_err_msg('password_invalid_char')})


class RegisterSerializer(serializers.ModelSerializer):
    username = serializers.CharField(
        required=True
    )
    email = serializers.EmailField(
        required=True
    )
    password = serializers.CharField(write_only=True, required=True)
    captcha_key = serializers.CharField(required=True)
    captcha_value = serializers.CharField(required=True)

    class Meta:
        model = get_user_model()
        fields = ('username', 'password', 'email', 'captcha_key', 'captcha_value')

    def validate(self, data):
        # 先验证验证码
        captcha_serializer = CaptchaSerializer(data={
            'captcha_key': data.get('captcha_key'),
            'captcha_value': data.get('captcha_value'),
        })

        if not captcha_serializer.is_valid():
            raise serializers.ValidationError(captcha_serializer.errors)

        user_model = self.Meta.model
        username = data.get('username')
        email = data.get('email')
        username_checker(username)
        if lower(email).endswith(settings.settings.UNIVERSITY_MAIL_SUFFIX):
            raise serializers.ValidationError({"email": get_err_msg('invalid_college_email')})
        if user_model.objects.filter(email=email).exists():
            raise serializers.ValidationError({'email': get_err_msg('email_duplicate')})

        password = data.get('password')
        password_complexity_checker(password)

        return data

    def create(self, validated_data):
        user_model = self.Meta.model
        user = user_model.objects.create(
            username=validated_data['username'],
            email=validated_data['email'],
            nickname=validated_data['username'],
        )
        user.set_password(validated_data['password'])
        user.save()
        return user


class UsernameDuplicationSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)

    def validate(self, data):
        username_checker(data.get('username'))
        return data


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)
    send_email = serializers.BooleanField(required=False, default=False)


class PasswordResetRequestSerializer(serializers.Serializer):  # 找回密码界面填写重置密码的表单
    email = serializers.EmailField(required=True)
    captcha_key = serializers.CharField(required=True)
    captcha_value = serializers.CharField(required=True)

    def validate(self, data):
        captcha_serializer = CaptchaSerializer(data={
            'captcha_key': data.get('captcha_key'),
            'captcha_value': data.get('captcha_value'),
        })

        if not captcha_serializer.is_valid():
            raise serializers.ValidationError('Invalid captcha')

        return data


class PasswordResetMailRequestSerializer(serializers.Serializer):  # 点击邮箱重置链接的表单
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)
    captcha_key = serializers.CharField(required=True)
    captcha_value = serializers.CharField(required=True)

    def validate(self, data):
        captcha_serializer = CaptchaSerializer(data={
            'captcha_key': data.get('captcha_key'),
            'captcha_value': data.get('captcha_value'),
        })

        if not captcha_serializer.is_valid():
            raise serializers.ValidationError('Invalid captcha')

        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError('Passwords do not match.')
        else:
            password_complexity_checker(data['new_password'])
        return data


class PasswordResetWhenLoginSerializer(serializers.Serializer):  # 点击邮箱重置链接的表单
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)
    confirm_password = serializers.CharField(write_only=True)
    captcha_key = serializers.CharField(required=True)
    captcha_value = serializers.CharField(required=True)

    def validate(self, data):
        captcha_serializer = CaptchaSerializer(data={
            'captcha_key': data.get('captcha_key'),
            'captcha_value': data.get('captcha_value'),
        })

        if not captcha_serializer.is_valid():
            raise serializers.ValidationError('Invalid captcha')
        user = self.context['request'].user
        if not user.check_password(data.get('old_password')):
            raise serializers.ValidationError({'password': get_err_msg('password_old_not_true')})
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError({'password': get_err_msg('password_re_not_consistent')})
        if user.check_password(data['confirm_password']):
            raise serializers.ValidationError({'password': get_err_msg('password_re_equal_old')})
        else:
            password_complexity_checker(data['new_password'])
        return data


class BindCollegeEmailSerializer(serializers.Serializer):
    college_email = serializers.EmailField(required=True)

    def validate(self, data):
        email = data.get('college_email')
        if email.endswith(settings.settings.UNIVERSITY_MAIL_SUFFIX):
            return data
        else:
            raise serializers.ValidationError({'mail':get_err_msg('not_college_email')})


class UpdateProfileSerializer(serializers.Serializer):
    username = serializers.CharField(required=False)
    nickname = serializers.CharField(required=False)
    avatar = serializers.CharField(required=False)
    bio = serializers.CharField(required=False, allow_null=True, max_length=255)

    def validate(self, data):
        if 'username' in data:
            user = self.context['request'].user
            username = data.get('username')
            if username != user.username:
                username_checker(username)
        if 'avatar' in data:
            try:
                UploadedFile.objects.get(id=data['avatar'])
            except (UploadedFile.DoesNotExist, ValidationError):
                raise serializers.ValidationError({'avatar': get_err_msg('avatar_uuid_error')})
        if 'nickname' in data:
            if not (2 <= len(data['nickname']) <= 30):
                raise serializers.ValidationError({'nickname': get_err_msg('nickname_not_match_length')})
            if not re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9!@#$%^&*()_+~\-={}]+$', data['nickname']):
                raise serializers.ValidationError(
                    {'nickname': get_err_msg('nickname_invalid_char')})
            return data
        return data
