import posixpath

from rest_framework import serializers

from utils.utils import format_file_size
from .models import ResourceUploadFile, ResourceUploadRequest, UploadedFile


class UploadedFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadedFile
        fields = ('id', 'file', 'uploaded_at', 'created_by', 'file_type')
        read_only_fields = ('created_by',)


class ResourceUploadFileSerializer(serializers.ModelSerializer):
    size_display = serializers.SerializerMethodField()

    class Meta:
        model = ResourceUploadFile
        fields = ('id', 'original_name', 'relative_path', 'size', 'size_display')

    def get_size_display(self, obj):
        return format_file_size(obj.size)


class ResourceUploadRequestSerializer(serializers.ModelSerializer):
    files = ResourceUploadFileSerializer(many=True, read_only=True)
    uploaded_by = serializers.SerializerMethodField()
    reviewed_by = serializers.SerializerMethodField()
    total_size_display = serializers.SerializerMethodField()

    class Meta:
        model = ResourceUploadRequest
        fields = (
            'id', 'uploaded_by', 'target_path', 'creates_new_folder', 'status', 'total_size', 'total_size_display',
            'files', 'created_at', 'reviewed_at', 'reviewed_by', 'rejection_reason', 'files_deleted_at',
        )

    def get_uploaded_by(self, obj):
        return {'id': obj.uploaded_by_id, 'username': obj.uploaded_by.username, 'nickname': obj.uploaded_by.nickname}

    def get_reviewed_by(self, obj):
        if obj.reviewed_by is None:
            return None
        return {'id': obj.reviewed_by_id, 'username': obj.reviewed_by.username, 'nickname': obj.reviewed_by.nickname}

    def get_total_size_display(self, obj):
        return format_file_size(obj.total_size)


class ResourceUploadCreateSerializer(serializers.Serializer):
    target_path = serializers.CharField(max_length=2048)
    new_folder_name = serializers.CharField(max_length=255, required=False, allow_blank=True)

    def validate(self, attrs):
        target_path = attrs['target_path'].strip().replace('\\', '/')
        if not target_path.startswith('/') or any(part == '..' for part in target_path.split('/')):
            raise serializers.ValidationError({'target_path': '目标路径必须是合法的绝对路径'})
        target_path = posixpath.normpath(target_path)
        new_folder_name = attrs.get('new_folder_name', '').strip()
        if new_folder_name:
            if new_folder_name in {'.', '..'} or '/' in new_folder_name or '\\' in new_folder_name:
                raise serializers.ValidationError({'new_folder_name': '文件夹名称不合法'})
            target_path = posixpath.join(target_path, new_folder_name)
        if target_path == '/':
            raise serializers.ValidationError({'target_path': '禁止直接投稿到根目录，请选择子目录或新建文件夹'})
        attrs['target_path'] = target_path
        return attrs


class ResourceDirectorySerializer(serializers.Serializer):
    path = serializers.CharField(default='/', max_length=2048)

    def validate_path(self, value):
        value = value.strip().replace('\\', '/')
        if not value.startswith('/') or any(part == '..' for part in value.split('/')):
            raise serializers.ValidationError('目录路径不合法')
        return posixpath.normpath(value)
