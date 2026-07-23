import logging
import posixpath
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePosixPath

from django.conf import settings
from django.db import transaction
from django.http import Http404, FileResponse
from rest_framework import status, generics
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.views import APIView

from settings.log import TelegramBotHandler
from utils.utils import get_err_msg
from utils.utils import format_file_size, return_response
from .resource_directories import (
    ResourceDirectoryCacheError,
    get_cached_child_directories,
)
from .models import ResourceUploadFile, ResourceUploadRequest, UploadedFile
from .serializers import (
    ResourceDirectorySerializer,
    ResourceUploadCreateSerializer,
    ResourceUploadRequestSerializer,
    UploadedFileSerializer,
)


logger = logging.getLogger(__name__)
resource_upload_notification_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix='resource-upload-notification',
)
RESOURCE_UPLOAD_MAX_FILE_SIZE = 100 * 1024 * 1024
RESOURCE_UPLOAD_MAX_FILE_COUNT = 20
RESOURCE_UPLOAD_ALLOWED_EXTENSIONS = {
    '.7z', '.avif', '.bmp', '.bz2', '.csv', '.doc', '.docx', '.gif', '.gz', '.heic', '.heif', '.ico', '.jfif',
    '.jpeg', '.jpg', '.md', '.ods', '.odp', '.odt', '.pdf', '.png', '.ppt', '.pptx', '.rar', '.svg', '.tar',
    '.tif', '.tiff', '.txt', '.webp', '.xls', '.xlsx', '.xz', '.zip',
}


def build_resource_upload_telegram_message(upload_request):
    file_lines = '\n'.join(
        f'- {item.relative_path} ({format_file_size(item.size)})'
        for item in upload_request.files.all()
    )
    return (
        f'收到新的资料上传请求 #{upload_request.pk}\n'
        f'用户: {upload_request.uploaded_by.username} (ID: {upload_request.uploaded_by_id})\n'
        f'目标路径: {upload_request.target_path}\n'
        f'总大小: {format_file_size(upload_request.total_size)}\n'
        f'文件:\n{file_lines}'
    )


def send_resource_upload_telegram_notification(upload_request_id, message):
    if not settings.TELEGRAM_BOT_API_TOKEN or not settings.TELEGRAM_CHAT_ID:
        logger.warning(
            'Skipped Telegram notification for resource upload request %s: '
            'TELEGRAM_BOT_API_TOKEN or TELEGRAM_CHAT_ID is not configured',
            upload_request_id,
        )
        return
    try:
        handler = TelegramBotHandler(send_timeout=10)
        handler.setFormatter(logging.Formatter('%(message)s'))
        handler.handle(logging.LogRecord(__name__, logging.INFO, '', 0, message, (), None))
    except Exception:
        logger.exception('Failed to send Telegram notification for resource upload request %s', upload_request_id)


def enqueue_resource_upload_telegram_notification(upload_request):
    message = build_resource_upload_telegram_message(upload_request)
    resource_upload_notification_executor.submit(
        send_resource_upload_telegram_notification,
        upload_request.pk,
        message,
    )


class FileDeleteView(generics.DestroyAPIView):
    queryset = UploadedFile.objects.all()
    serializer_class = UploadedFileSerializer
    permission_classes = [IsAuthenticated]
    lookup_field = 'id'

    def delete(self, request, *args, **kwargs):
        try:
            instance = self.get_object()
            if instance.created_by != request.user and not request.user.is_staff:
                return return_response(errors={"auth": get_err_msg('auth_error')},
                                       status_code=status.HTTP_403_FORBIDDEN)
            self.perform_destroy(instance)
            return return_response(message="delete success", status_code=status.HTTP_204_NO_CONTENT)
        except Http404:
            return return_response(errors={"file": get_err_msg('file_not_exist')},
                                   status_code=status.HTTP_404_NOT_FOUND)


class FileUploadView(generics.CreateAPIView):
    queryset = UploadedFile.objects.all()
    serializer_class = UploadedFileSerializer
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        if serializer.is_valid():
            file = serializer.validated_data['file']
            serializer.validated_data['file_name'] = file.name
            file_size = file.size
            serializer.save(created_by=request.user, file_size=file_size)
            return return_response(contents={'uuid': serializer.instance.id}, status_code=status.HTTP_201_CREATED)
        return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)


class FileUpdateView(generics.UpdateAPIView):
    queryset = UploadedFile.objects.all()
    serializer_class = UploadedFileSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser)
    lookup_field = 'id'

    def update(self, request, *args, **kwargs):
        try:
            partial = kwargs.pop('partial', False)
            instance = self.get_object()
            if instance.created_by != request.user and not request.user.is_staff:
                return return_response(errors={"auth": get_err_msg('auth_error')},
                                       status_code=status.HTTP_403_FORBIDDEN)

            if 'file' in request.FILES:
                file_obj = request.FILES['file']
                if file_obj.size > settings.FILE_UPLOAD_SIZE_LIMIT:
                    return return_response(errors={"file": get_err_msg('file_over_size')},
                                           status_code=status.HTTP_400_BAD_REQUEST)

            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            serializer.save()

            return return_response(contents=serializer.data)
        except Http404:
            return return_response(errors={"file": get_err_msg('file_not_exist')},
                                   status_code=status.HTTP_404_NOT_FOUND)


class ResourceDirectoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = ResourceDirectorySerializer(data=request.query_params)
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        current_path = serializer.validated_data['path']
        try:
            contents = get_cached_child_directories(current_path)
        except ResourceDirectoryCacheError:
            logger.exception('Failed to read cached resource directories for %s', current_path)
            return return_response(
                errors={'directory': get_err_msg('resource_service_unavailable')},
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return return_response(contents=contents)


class ResourceUploadRequestView(APIView):
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [IsAuthenticated]

    def get(self, request):
        upload_requests = ResourceUploadRequest.objects.filter(uploaded_by=request.user).prefetch_related('files')
        return return_response(contents={'upload_requests': ResourceUploadRequestSerializer(upload_requests, many=True).data})

    def post(self, request):
        serializer = ResourceUploadCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return return_response(errors=serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)
        files = request.FILES.getlist('files')
        if not files:
            return return_response(
                errors={'files': get_err_msg('resource_upload_files_required')},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if len(files) > RESOURCE_UPLOAD_MAX_FILE_COUNT:
            return return_response(
                errors={'files': get_err_msg('resource_upload_too_many_files')},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        relative_paths = request.data.getlist('relative_paths') if hasattr(request.data, 'getlist') else []
        if relative_paths and len(relative_paths) != len(files):
            return return_response(
                errors={'relative_paths': get_err_msg('resource_upload_path_count_mismatch')},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        normalized_paths = []
        for index, uploaded_file in enumerate(files):
            if uploaded_file.size > RESOURCE_UPLOAD_MAX_FILE_SIZE:
                return return_response(
                    errors={'files': get_err_msg('resource_upload_file_too_large')},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            if PurePosixPath(uploaded_file.name).suffix.lower() not in RESOURCE_UPLOAD_ALLOWED_EXTENSIONS:
                return return_response(
                    errors={'files': get_err_msg('resource_upload_file_type_not_allowed')},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            relative_path = relative_paths[index] if relative_paths else uploaded_file.name
            relative_path = relative_path.strip().replace('\\', '/')
            normalized_path = posixpath.normpath(relative_path)
            if normalized_path.startswith('/') or normalized_path in {'.', '..'} or any(
                    part == '..' for part in normalized_path.split('/')):
                return return_response(
                    errors={'relative_paths': get_err_msg('resource_upload_invalid_relative_path')},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            normalized_paths.append(normalized_path)
        if len(set(normalized_paths)) != len(normalized_paths):
            return return_response(
                errors={'relative_paths': get_err_msg('resource_upload_duplicate_path')},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        with transaction.atomic():
            creates_new_folder = bool(serializer.validated_data.get('new_folder_name'))
            upload_request = ResourceUploadRequest.objects.create(
                uploaded_by=request.user,
                target_path=serializer.validated_data['target_path'],
                creates_new_folder=creates_new_folder,
                total_size=sum(uploaded_file.size for uploaded_file in files),
            )
            ResourceUploadFile.objects.bulk_create([
                ResourceUploadFile(
                    upload_request=upload_request,
                    file=uploaded_file,
                    original_name=uploaded_file.name,
                    relative_path=normalized_paths[index],
                    size=uploaded_file.size,
                )
                for index, uploaded_file in enumerate(files)
            ])
        upload_request = ResourceUploadRequest.objects.prefetch_related('files').get(pk=upload_request.pk)
        enqueue_resource_upload_telegram_notification(upload_request)
        return return_response(
            contents={'upload_request': ResourceUploadRequestSerializer(upload_request).data},
            status_code=status.HTTP_201_CREATED,
        )


class ResourceUploadFileDownloadView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, file_id):
        try:
            upload_file = ResourceUploadFile.objects.get(pk=file_id)
            file_handle = upload_file.file.open('rb')
        except (ResourceUploadFile.DoesNotExist, FileNotFoundError, ValueError):
            return return_response(
                errors={'file': get_err_msg('file_not_exist')},
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return FileResponse(
            file_handle,
            as_attachment=True,
            filename=upload_file.original_name,
        )


class FileDownloadView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, file_uuid):
        try:
            file_instance = UploadedFile.objects.get(pk=file_uuid)
        except UploadedFile.DoesNotExist:
            return return_response(errors={"file": get_err_msg('file_not_exist')},
                                   status_code=status.HTTP_404_NOT_FOUND)
        try:
            response = FileResponse(file_instance.file)
        except FileNotFoundError:
            return return_response(errors={"file": get_err_msg('file_not_exist')},
                                   status_code=status.HTTP_404_NOT_FOUND)
        response['Content-Disposition'] = f'attachment; filename="{file_instance.file.name}"'
        return response
