import re

from django.contrib.auth import get_user_model
from rest_framework import serializers

from common.serializers import CaptchaSerializer


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
            email=validated_data['email']
        )
        user.set_password(validated_data['password'])
        user.save()
        return user


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)


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
