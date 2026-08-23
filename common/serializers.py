from captcha.models import CaptchaStore
from django.conf import settings
from rest_framework import serializers

from utils.utils import get_err_msg
from .models import About


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
    content = serializers.CharField(max_length=500)
    classify = serializers.ChoiceField(choices=('user',), default='user')


class DirectMessageCursorSerializer(serializers.Serializer):
    before_id = serializers.IntegerField(required=False, min_value=1)
    after_id = serializers.IntegerField(required=False, min_value=1)
    last_message_id = serializers.IntegerField(required=False, min_value=1)
    order = serializers.ChoiceField(choices=('before', 'after'), required=False)
    page_size = serializers.IntegerField(required=False, min_value=1, max_value=100, default=10)

    def validate(self, data):
        if data.get('before_id') and data.get('after_id'):
            raise serializers.ValidationError('before_id and after_id are mutually exclusive.')
        legacy_id = data.get('last_message_id')
        if legacy_id and not (data.get('before_id') or data.get('after_id')):
            data[f"{data.get('order', 'before')}_id"] = legacy_id
        return data


class ConversationReadSerializer(serializers.Serializer):
    through_message_id = serializers.IntegerField(min_value=0)


class NotificationReadSerializer(serializers.Serializer):
    ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        allow_empty=False,
        max_length=100,
    )


class SearchSerializer(serializers.Serializer):
    keyword = serializers.CharField(required=True, max_length=200)
    page_size = serializers.IntegerField(required=False, default=10, min_value=1, max_value=100)
    current_page = serializers.IntegerField(required=False, default=1, min_value=1)
    type = serializers.CharField(required=True)

    def validate(self, data):
        if data.get('type') not in ['course', 'teacher', 'review', 'resource']:
            raise serializers.ValidationError({'type': get_err_msg('operation_error')})
        return data
