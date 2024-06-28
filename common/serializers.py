from rest_framework import serializers

from .models import Bulletins


class BulletinSerializer(serializers.ModelSerializer):
    create_time = serializers.DateTimeField(format='%Y年%m月%d日 %H:%M')
    update_time = serializers.DateTimeField(format='%Y年%m月%d日 %H:%M')

    class Meta:
        model = Bulletins
        fields = ['title', 'content', 'publisher', 'create_time', 'update_time']


class AboutSerializer(serializers.Serializer):
    day_difference = serializers.IntegerField()
    cost_money = serializers.FloatField()