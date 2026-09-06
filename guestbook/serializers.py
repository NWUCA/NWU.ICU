from bs4 import BeautifulSoup, Comment
from rest_framework import serializers

from .models import GuestbookReport

ALLOWED_TAGS = {'p', 'br', 'strong', 'em', 's', 'u'}
DISCARDED_TAGS = {'script', 'style', 'iframe', 'object', 'embed', 'template'}


def clean_guestbook_html(value):
    soup = BeautifulSoup(value or '', 'html.parser')
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    # Work from leaves to parents so removed subtrees leave no stale tag references.
    for tag in reversed(soup.find_all(True)):
        if tag.name in DISCARDED_TAGS:
            tag.decompose()
        elif tag.name not in ALLOWED_TAGS:
            tag.unwrap()
        else:
            tag.attrs = {}
    return str(soup).strip(), soup.get_text().strip()


class GuestbookReplySerializer(serializers.Serializer):
    content = serializers.CharField(max_length=16_000)
    submission_id = serializers.UUIDField(required=False)

    def validate_content(self, value):
        content, text = clean_guestbook_html(value)
        if not text:
            raise serializers.ValidationError('内容不能为空。')
        if len(text) > 500:
            raise serializers.ValidationError('内容不能超过 500 字。')
        return content


class GuestbookContentSerializer(GuestbookReplySerializer):
    anonymous = serializers.BooleanField(default=False)


class AnnouncementContentSerializer(GuestbookContentSerializer):
    title = serializers.CharField(max_length=100, trim_whitespace=True)

    def validate_title(self, value):
        if not value:
            raise serializers.ValidationError('标题不能为空。')
        return value


class GuestbookLikeSerializer(serializers.Serializer):
    liked = serializers.BooleanField()


class GuestbookReportSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=GuestbookReport.REASON_CHOICES)
    detail = serializers.CharField(max_length=500, required=False, allow_blank=True)
