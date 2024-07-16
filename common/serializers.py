from captcha.models import CaptchaStore
from django.conf import settings
from rest_framework import serializers

from .models import Bulletin, About


class CaptchaSerializer(serializers.Serializer):
    captcha_key = serializers.CharField()
    captcha_value = serializers.CharField()

    def validate(self, data):
        captcha_key = data.get('captcha_key')
        captcha_value = data.get('captcha_value')
        if settings.DEBUG:
            return data
        try:
            captcha = CaptchaStore.objects.get(hashkey=captcha_key)
            if captcha.response != captcha_value.lower():
                captcha.delete()
                raise serializers.ValidationError({"captcha": "验证码错误"})
        except CaptchaStore.DoesNotExist:
            raise serializers.ValidationError({"captcha": "验证码已失效"})
        captcha.delete()
        return data


class BulletinSerializer(serializers.ModelSerializer):
    create_time = serializers.DateTimeField(format='%Y年%m月%d日 %H:%M')
    update_time = serializers.DateTimeField(format='%Y年%m月%d日 %H:%M')

    class Meta:
        model = Bulletin
        fields = ['title', 'content', 'publisher', 'create_time', 'update_time']


class AboutSerializer(serializers.Serializer):
    create_time = serializers.DateTimeField(format='%Y年%m月%d日 %H:%M')
    update_time = serializers.DateTimeField(format='%Y年%m月%d日 %H:%M')
    content = serializers.CharField(allow_blank=True)

    class Meta:
        model = About
        fields = ['content', 'create_time', 'update_time']
