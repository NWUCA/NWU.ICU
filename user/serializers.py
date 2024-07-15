import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import User
from rest_framework import serializers

from common.serializers import CaptchaSerializer


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True)

    class Meta:
        model = get_user_model()
        fields = ('username', 'password', 'email')

    def validate(self, data):
        password = data.get('password')
        self.validate_password_complexity(password)
        return data

    def validate_password_complexity(self, password):
        if len(password) < 8:
            raise serializers.ValidationError("密码长度必须至少为8个字符。")
        if not re.search(r'[A-Z]', password):
            raise serializers.ValidationError("密码必须包含至少一个大写字母。")
        if not re.search(r'[a-z]', password):
            raise serializers.ValidationError("密码必须包含至少一个小写字母。")
        if not re.search(r'[0-9]', password):
            raise serializers.ValidationError("密码必须包含至少一个数字。")

    def create(self, validated_data):
        User = self.Meta.model
        user = User.objects.create(
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

        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError("Passwords do not match.")
