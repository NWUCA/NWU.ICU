from rest_framework import serializers

from .models import UploadedFile


class UploadedFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadedFile
        fields = ('id', 'file', 'uploaded_at', 'created_by')
        read_only_fields = ('created_by',)
