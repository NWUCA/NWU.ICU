import re

from django.contrib.auth import get_user_model
from rest_framework import serializers

from common.file.models import UploadedFile
from common.serializers import CaptchaSerializer
from user.models import User


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
        if not (8 <= len(username) <= 29):
            raise serializers.ValidationError("用户名长度必须在8到29个字符之间")
        if not re.match(r'^\w+$', username):
            raise serializers.ValidationError("用户名只能包含字母、数字和下划线")
        pattern_checks = [
            (r'[a-z]', "用户名必须包含至少一个字母。"),
        ]

        for pattern, error_message in pattern_checks:
            if not re.search(pattern, username):
                raise serializers.ValidationError(error_message)
        if user_model.objects.filter(username=username).exists():
            raise serializers.ValidationError({"username": "已存在一位使用该名字的用户。"})
        if user_model.objects.filter(email=email).exists():
            raise serializers.ValidationError({"email": "此邮箱已被注册。"})

        password = data.get('password')
        self.validate_password_complexity(password)

        return data

    @staticmethod
    def validate_password_complexity(password):
        if len(password) < 8:
            raise serializers.ValidationError("密码长度必须至少为8个字符。")

        pattern_checks = [
            (r'[A-Z]', "密码必须包含至少一个大写字母。"),
            (r'[a-z]', "密码必须包含至少一个小写字母。"),
            (r'[0-9]', "密码必须包含至少一个数字。")
        ]

        for pattern, error_message in pattern_checks:
            if not re.search(pattern, password):
                raise serializers.ValidationError(error_message)

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


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)
    send_email = serializers.BooleanField(required=False, default=False)


class PasswordResetRequestSerializer(serializers.Serializer):  # 网页填写重置密码的表单
    email = serializers.EmailField(required=True)
    username = serializers.CharField(required=True)
    captcha_key = serializers.CharField(required=True)
    captcha_value = serializers.CharField(required=True)

    def validate(self, data):
        captcha_serializer = CaptchaSerializer(data={
            'captcha_key': data.get('captcha_key'),
            'captcha_value': data.get('captcha_value'),
        })

        if not captcha_serializer.is_valid():
            raise serializers.ValidationError("Invalid captcha")

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
            raise serializers.ValidationError("Invalid captcha")

        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError("Passwords do not match.")
        else:
            RegisterSerializer.validate_password_complexity(data['new_password'])
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
            raise serializers.ValidationError("Invalid captcha")
        user = self.context['request'].user
        if not user.check_password(data.get('old_password')):
            raise serializers.ValidationError("旧密码不正确")
        if data['new_password'] != data['confirm_password']:
            raise serializers.ValidationError("两次输入的密码不一致")
        if user.check_password(data['confirm_password']):
            raise serializers.ValidationError("新老密码不可以一致")
        else:
            RegisterSerializer.validate_password_complexity(data['new_password'])
        return data


class BindNwuEmailSerializer(serializers.Serializer):
    nwu_email = serializers.EmailField(required=True)

    def validate(self, data):
        email = data.get('nwu_email')
        if email.endswith('nwu.edu.cn'):
            return data
        else:
            raise serializers.ValidationError("不是西北大学邮箱")


class UpdateProfileSerializer(serializers.Serializer):
    username = serializers.CharField(required=False)
    nickname = serializers.CharField(required=False)
    avatar_uuid = serializers.CharField(required=False)
    bio = serializers.CharField(required=False, allow_null=True)

    def validate(self, data):
        if 'username' in data:
            user = self.context['request'].user

            username = data.get('username')
            if username != user.username:
                if not (8 <= len(username) <= 29):
                    raise serializers.ValidationError("用户名长度必须在8到29个字符之间")
                if not re.match(r'^\w+$', username):
                    raise serializers.ValidationError("用户名只能包含字母、数字和下划线")
                pattern_checks = [
                    (r'[a-zA-Z]', "用户名必须包含至少一个字母。"),
                ]

                for pattern, error_message in pattern_checks:
                    if not re.search(pattern, username):
                        raise serializers.ValidationError(error_message)
                if User.objects.filter(username=username).exists():
                    raise serializers.ValidationError({"username": "已存在一位使用该名字的用户。"})
        if 'avatar' in data:
            try:
                UploadedFile.objects.get(id=data['avatar_uuid'])
            except UploadedFile.DoesNotExist:
                raise serializers.ValidationError("头像uuid错误")
        if 'nickname' in data:
            if not (2 <= len(data['nickname']) <= 30):
                raise serializers.ValidationError("昵称长度必须在2到30之间")
            if not re.match(r'^[\u4e00-\u9fa5a-zA-Z0-9!@#$%^&*()_+~\-={}]+$', data['nickname']):
                raise serializers.ValidationError("昵称只能包含汉字、英文字母、数字和!@#$%^&*()_+~\-={}")
            return data
        return data
