import posixpath
import warnings

from PIL import Image, UnidentifiedImageError
from django.conf import settings
from rest_framework import serializers

from utils.utils import format_file_size
from .resource_notifications import get_resource_public_url
from .models import ResourceUploadFile, ResourceUploadRequest, UploadedFile


class UploadedFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = UploadedFile
        fields = ('id', 'file', 'uploaded_at', 'created_by', 'file_type')
        read_only_fields = ('created_by',)

    def validate(self, attrs):
        uploaded_file = attrs.get('file')
        file_type = attrs.get('file_type', getattr(self.instance, 'file_type', 'file'))
        if uploaded_file is None:
            return attrs

        final_limit = settings.FILE_UPLOAD_SIZE_LIMIT.get(file_type, 25 * 1024 * 1024)
        source_limit = 25 * 1024 * 1024 if file_type in {'avatar', 'img'} else final_limit
        if uploaded_file.size > source_limit:
            raise serializers.ValidationError({'file': '上传文件超过大小限制'})

        if file_type in {'avatar', 'img'}:
            if not str(getattr(uploaded_file, 'content_type', '')).startswith('image/'):
                raise serializers.ValidationError({'file': '上传内容不是有效图片'})
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    image = Image.open(uploaded_file)
                    image.verify()
            except (
                    UnidentifiedImageError,
                    OSError,
                    Image.DecompressionBombError,
                    Image.DecompressionBombWarning,
            ):
                raise serializers.ValidationError({'file': '上传内容不是有效图片'})
            finally:
                uploaded_file.seek(0)
        return attrs

    def update(self, instance, validated_data):
        uploaded_file = validated_data.get('file')
        if uploaded_file is not None:
            instance.file_name = uploaded_file.name
            instance.file_size = uploaded_file.size
        return super().update(instance, validated_data)


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
    resource_url = serializers.SerializerMethodField()

    class Meta:
        model = ResourceUploadRequest
        fields = (
            'id', 'uploaded_by', 'target_path', 'creates_new_folder', 'status', 'total_size', 'total_size_display',
            'files', 'created_at', 'reviewed_at', 'reviewed_by', 'rejection_reason', 'files_deleted_at',
            'resource_url',
        )

    def get_uploaded_by(self, obj):
        return {'id': obj.uploaded_by_id, 'username': obj.uploaded_by.username, 'nickname': obj.uploaded_by.nickname}

    def get_reviewed_by(self, obj):
        if obj.reviewed_by is None:
            return None
        return {'id': obj.reviewed_by_id, 'username': obj.reviewed_by.username, 'nickname': obj.reviewed_by.nickname}

    def get_total_size_display(self, obj):
        return format_file_size(obj.total_size)

    def get_resource_url(self, obj):
        if obj.status != ResourceUploadRequest.STATUS_APPROVED:
            return None
        return get_resource_public_url(obj.target_path)


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
