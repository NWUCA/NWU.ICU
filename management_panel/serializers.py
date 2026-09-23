from rest_framework import serializers
from common.file.serializers import ResourceDirectorySerializer
from guestbook.serializers import validate_announcement_rich_content


class ResourceUploadBlacklistSerializer(ResourceDirectorySerializer):
    path = serializers.CharField(max_length=2048)
    action = serializers.ChoiceField(choices=('add', 'remove'))

    def validate_path(self, value):
        path = '/' + super().validate_path(value).lstrip('/')
        if path == '/':
            raise serializers.ValidationError('请选择要限制投稿的子文件夹')
        return path


class PasskeyRegistrationOptionsSerializer(serializers.Serializer):
    enrollment_code = serializers.CharField(max_length=128, trim_whitespace=True)
    name = serializers.CharField(max_length=100, trim_whitespace=True)


class PasskeyRegistrationVerifySerializer(serializers.Serializer):
    credential = serializers.JSONField()


class PasskeyAuthenticationVerifySerializer(serializers.Serializer):
    credential = serializers.JSONField()


class ReportResolutionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=('dismiss', 'remove'))
    note = serializers.CharField(max_length=500, trim_whitespace=True)


class AnnouncementVisibilitySerializer(serializers.Serializer):
    visible = serializers.BooleanField()


class AboutContentSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=16_000)

    def validate_content(self, value):
        return validate_announcement_rich_content(
            value,
            request=self.context.get('request'),
            existing_content=self.context.get('existing_content', ''),
            label='关于本站',
        )


class ResourceReviewSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=('approve', 'reject', 'retry'))
    expected_revision = serializers.IntegerField(min_value=1)
    target_path = serializers.CharField(max_length=2048, required=False, allow_blank=True)
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True)

    def validate(self, attrs):
        if attrs['action'] in {'approve', 'retry'} and not attrs.get('target_path', '').strip():
            raise serializers.ValidationError({'target_path': '通过或重试发布时必须填写最终目录'})
        if attrs['action'] == 'reject' and not attrs.get('reason', '').strip():
            raise serializers.ValidationError({'reason': '拒绝投稿时必须填写理由'})
        return attrs


class TelegramNotificationSettingsSerializer(serializers.Serializer):
    user_registration_enabled = serializers.BooleanField()
    guestbook_entry_enabled = serializers.BooleanField()
    course_review_enabled = serializers.BooleanField()
    reply_enabled = serializers.BooleanField()
