from rest_framework import serializers

from .models import Bulletin, About


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
