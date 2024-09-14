from captcha.models import CaptchaStore
from django.conf import settings
from rest_framework import serializers

from .models import Bulletin, About, Chat


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





class AboutSerializer(serializers.Serializer):
    create_time = serializers.DateTimeField()
    update_time = serializers.DateTimeField()
    content = serializers.CharField(allow_blank=True)

    class Meta:
        model = About
        fields = ['content', 'create_time', 'update_time']


class ChatMessageSerializer(serializers.Serializer):
    receiver = serializers.IntegerField()
    content = serializers.CharField()
    classify = serializers.CharField(default='user')

    def validate(self, data):
        classify_list = [message[0] for message in Chat.classify_MESSAGE]
        if data['classify'] not in classify_list:
            raise serializers.ValidationError({'classify': 'out of range'})
        if data['classify'] == 'system':
            raise serializers.ValidationError({'classify': 'auth error'})
        return data
