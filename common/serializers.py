from captcha.models import CaptchaStore
from django.conf import settings
from rest_framework import serializers

from utils.utils import get_err_msg
from .models import About, Chat


class CaptchaSerializer(serializers.Serializer):
    captcha_key = serializers.CharField()
    captcha_value = serializers.CharField()

    def validate(self, data):
        captcha_key = data.get('captcha_key')
        captcha_value = data.get('captcha_value')
        if settings.CAPTCHA_TEST_MODE:
            return data
        try:
            captcha = CaptchaStore.objects.get(hashkey=captcha_key)
            if captcha.response != captcha_value.lower():
                captcha.delete()
                raise serializers.ValidationError({'captcha': get_err_msg('captcha_error')})
        except CaptchaStore.DoesNotExist:
            raise serializers.ValidationError({'captcha': get_err_msg('captcha_overdue')})
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
    content = serializers.CharField(max_length=5000)
    classify = serializers.ChoiceField(choices=('user',), default='user')


class ChatMessageGetSerializer(serializers.Serializer):
    classify = serializers.ChoiceField(choices=tuple(message[0] for message in Chat.classify_MESSAGE))
    last_message_id = serializers.IntegerField(required=False, min_value=1)
    order = serializers.ChoiceField(choices=('before', 'after'), required=False, default='before')

    def validate(self, data):
        if data['classify'] != 'user' and ('last_message_id' in data or 'order' in self.initial_data):
            raise serializers.ValidationError({'classify': get_err_msg('operation_error')})
        return data


class SearchSerializer(serializers.Serializer):
    keyword = serializers.CharField(required=True, max_length=200)
    page_size = serializers.IntegerField(required=False, default=10, min_value=1, max_value=100)
    current_page = serializers.IntegerField(required=False, default=1, min_value=1)
    type = serializers.CharField(required=True)

    def validate(self, data):
        if data.get('type') not in ['course', 'teacher', 'review', 'resource']:
            raise serializers.ValidationError({'type': get_err_msg('operation_error')})
        return data
