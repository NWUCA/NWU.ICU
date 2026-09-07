import re

from bs4 import BeautifulSoup, Comment
from rest_framework import serializers

from common.file.models import UploadedFile
from .models import GuestbookReport

ALLOWED_TAGS = {'p', 'br', 'strong', 'em', 's', 'u'}
DISCARDED_TAGS = {'script', 'style', 'iframe', 'object', 'embed', 'template'}
ANNOUNCEMENT_IMAGE_PATH = re.compile(
    r'^/api/download/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/$',
    re.IGNORECASE,
)


def _clean_html(value, *, allow_images=False):
    soup = BeautifulSoup(value or '', 'html.parser')
    image_ids = set()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    # Work from leaves to parents so removed subtrees leave no stale tag references.
    for tag in reversed(soup.find_all(True)):
        if tag.name in DISCARDED_TAGS:
            tag.decompose()
        elif tag.name == 'img' and allow_images:
            match = ANNOUNCEMENT_IMAGE_PATH.fullmatch(tag.get('src', ''))
            if not match:
                tag.decompose()
                continue
            image_id = match.group(1).lower()
            image_ids.add(image_id)
            attrs = {'src': f'/api/download/{image_id}/'}
            alt = tag.get('alt', '').strip()[:200]
            if alt:
                attrs['alt'] = alt
            tag.attrs = attrs
        elif tag.name not in ALLOWED_TAGS:
            tag.unwrap()
        else:
            tag.attrs = {}
    return str(soup).strip(), soup.get_text().strip(), image_ids


def clean_guestbook_html(value):
    content, text, _ = _clean_html(value)
    return content, text


def clean_announcement_html(value):
    return _clean_html(value, allow_images=True)


def announcement_image_ids(value):
    return clean_announcement_html(value)[2]


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

    def validate_content(self, value):
        content, text, image_ids = clean_announcement_html(value)
        if not text and not image_ids:
            raise serializers.ValidationError('内容不能为空。')
        if len(text) > 500:
            raise serializers.ValidationError('内容不能超过 500 字。')
        request = self.context.get('request')
        valid_image_ids = set()
        if request and image_ids:
            valid_image_ids = {
                str(image_id) for image_id in UploadedFile.objects.filter(
                    id__in=image_ids,
                    created_by=request.user,
                    file_type='img',
                ).values_list('id', flat=True)
            }
        if valid_image_ids != image_ids:
            raise serializers.ValidationError('公告只能使用当前管理员上传的有效图片。')
        return content

    def validate_title(self, value):
        if not value:
            raise serializers.ValidationError('标题不能为空。')
        return value


class GuestbookLikeSerializer(serializers.Serializer):
    liked = serializers.BooleanField()


class GuestbookReportSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=GuestbookReport.REASON_CHOICES)
    detail = serializers.CharField(max_length=500, required=False, allow_blank=True)
