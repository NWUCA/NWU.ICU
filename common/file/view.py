import logging
import posixpath
from concurrent.futures import ThreadPoolExecutor
from pathlib import PurePosixPath

from django.conf import settings
from django.db import transaction
from django.db.models import Case, IntegerField, Value, When
from django.http import Http404, FileResponse
from rest_framework import status, generics
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny, IsAdminUser, IsAuthenticated
from rest_framework.views import APIView
from settings.log import TelegramBotHandler

from utils.utils import get_err_msg
from utils.utils import return_response
from .resource_directories import (
    ResourceDirectoryCacheError,
    get_cached_child_directories,
)
from .models import ResourceUploadFile, ResourceUploadRequest, UploadedFile
from .resource_notifications import queue_resource_upload_notifications
from .serializers import (
    ResourceDirectorySerializer,
    ResourceUploadCreateSerializer,
    ResourceUploadRequestSerializer,
    UploadedFileSerializer,
)


logger = logging.getLogger(__name__)
resource_upload_notification_executor = ThreadPoolExecutor(
    max_workers=1,
    thread_name_prefix='resource-upload-legacy-notification',
)
RESOURCE_UPLOAD_MAX_FILE_SIZE = 100 * 1024 * 1024
RESOURCE_UPLOAD_MAX_FILE_COUNT = 20
RESOURCE_UPLOAD_ALLOWED_EXTENSIONS = {
    '.7z', '.avif', '.bmp', '.bz2', '.csv', '.doc', '.docx', '.gif', '.gz', '.heic', '.heif', '.ico', '.jfif',
    '.jpeg', '.jpg', '.md', '.ods', '.odp', '.odt', '.pdf', '.png', '.ppt', '.pptx', '.rar', '.svg', '.tar',
    '.tif', '.tiff', '.txt', '.webp', '.xls', '.xlsx', '.xz', '.zip',
}


def send_resource_upload_telegram_notification(upload_request_id, message):
    """Deprecated compatibility helper. New uploads use ResourceNotificationOutbox."""
    if not settings.TELEGRAM_BOT_API_TOKEN or not settings.TELEGRAM_CHAT_ID:
        return
    handler = TelegramBotHandler(send_timeout=10)
    handler.setFormatter(logging.Formatter('%(message)s'))
    handler.handle(logging.LogRecord(__name__, logging.INFO, '', 0, message, (), None))


def enqueue_resource_upload_telegram_notification(upload_request, event='created'):
    """Deprecated compatibility helper retained for existing integrations."""
    file_lines = '\n'.join(
        f'- {item.relative_path}' for item in upload_request.files.all()
    )
    resource_upload_notification_executor.submit(
        send_resource_upload_telegram_notification,
        upload_request.pk,
        f'资料上传请求 #{upload_request.pk}\n{file_lines}',
    )


def validate_resource_upload_files(files, relative_paths, reserved_relative_paths=()):
    if relative_paths and len(relative_paths) != len(files):
        return None, {'relative_paths': get_err_msg('resource_upload_path_count_mismatch')}

    normalized_paths = []
    for index, uploaded_file in enumerate(files):
        if uploaded_file.size > RESOURCE_UPLOAD_MAX_FILE_SIZE:
            return None, {'files': get_err_msg('resource_upload_file_too_large')}
        if PurePosixPath(uploaded_file.name).suffix.lower() not in RESOURCE_UPLOAD_ALLOWED_EXTENSIONS:
            return None, {'files': get_err_msg('resource_upload_file_type_not_allowed')}

        relative_path = relative_paths[index] if relative_paths else uploaded_file.name
        relative_path = relative_path.strip().replace('\\', '/')
        normalized_path = posixpath.normpath(relative_path)
        if normalized_path.startswith('/') or normalized_path in {'.', '..'} or any(
                part == '..' for part in normalized_path.split('/')):
            return None, {'relative_paths': get_err_msg('resource_upload_invalid_relative_path')}
        normalized_paths.append(normalized_path)

    all_relative_paths = [*reserved_relative_paths, *normalized_paths]
    if len(set(all_relative_paths)) != len(all_relative_paths):
        return None, {'relative_paths': get_err_msg('resource_upload_duplicate_path')}
    return normalized_paths, None


def delete_resource_upload_files_from_storage(files):
    for upload_file in files:
        if not upload_file.file:
            continue
        try:
            upload_file.file.storage.delete(upload_file.file.name)
        except Exception:
            logger.exception('Failed to delete resource upload file %s from storage', upload_file.pk)


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
                file_type = request.data.get('file_type', instance.file_type)
                limit = settings.FILE_UPLOAD_SIZE_LIMIT.get(file_type, 25 * 1024 * 1024)
                if file_type in {'avatar', 'img'}:
                    limit = 25 * 1024 * 1024
                if file_obj.size > limit:
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


class ResourceUploadConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return return_response(contents={
            'max_file_size': RESOURCE_UPLOAD_MAX_FILE_SIZE,
            'max_file_count': RESOURCE_UPLOAD_MAX_FILE_COUNT,
            'allowed_extensions': sorted(RESOURCE_UPLOAD_ALLOWED_EXTENSIONS),
        })


class ResourceUploadRequestView(APIView):
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [IsAuthenticated]

    def get(self, request):
        upload_requests = (
            ResourceUploadRequest.objects
            .filter(uploaded_by=request.user)
            .annotate(
                status_order=Case(
                    When(status=ResourceUploadRequest.STATUS_REJECTED, then=Value(0)),
                    When(status=ResourceUploadRequest.STATUS_PENDING, then=Value(1)),
                    default=Value(2),
                    output_field=IntegerField(),
                ),
            )
            .prefetch_related('files')
            .order_by('status_order', '-created_at')
        )
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
        normalized_paths, validation_errors = validate_resource_upload_files(files, relative_paths)
        if validation_errors:
            return return_response(
                errors=validation_errors,
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
            # The outbox row belongs to the same transaction as the submission.
            queue_resource_upload_notifications(upload_request, event='created')
        upload_request = ResourceUploadRequest.objects.prefetch_related('files').get(pk=upload_request.pk)
        return return_response(
            contents={'upload_request': ResourceUploadRequestSerializer(upload_request).data},
            status_code=status.HTTP_201_CREATED,
        )


class ResourceUploadRequestDetailView(APIView):
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [IsAuthenticated]

    def put(self, request, request_id):
        path_serializer = ResourceUploadCreateSerializer(data=request.data)
        if not path_serializer.is_valid():
            return return_response(errors=path_serializer.errors, status_code=status.HTTP_400_BAD_REQUEST)

        files = request.FILES.getlist('files')
        relative_paths = request.data.getlist('relative_paths') if hasattr(request.data, 'getlist') else []
        raw_remove_file_ids = request.data.getlist('remove_file_ids') if hasattr(request.data, 'getlist') else []
        try:
            remove_file_ids = {int(file_id) for file_id in raw_remove_file_ids}
        except (TypeError, ValueError):
            return return_response(
                errors={'remove_file_ids': get_err_msg('resource_upload_invalid_file_ids')},
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        try:
            expected_revision = int(request.data.get('expected_revision'))
        except (TypeError, ValueError):
            return return_response(
                errors={'expected_revision': get_err_msg('resource_upload_invalid_revision')},
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            upload_request = (
                ResourceUploadRequest.objects
                .select_for_update()
                .filter(pk=request_id, uploaded_by=request.user)
                .first()
            )
            if upload_request is None:
                return return_response(
                    errors={'upload_request': get_err_msg('resource_upload_not_found')},
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            if upload_request.files_deleted_at:
                return return_response(
                    errors={'upload_request': get_err_msg('resource_upload_staging_expired')},
                    status_code=status.HTTP_409_CONFLICT,
                )
            if upload_request.status not in {
                ResourceUploadRequest.STATUS_PENDING,
                ResourceUploadRequest.STATUS_REJECTED,
            }:
                return return_response(
                    errors={'upload_request': get_err_msg('resource_upload_not_editable')},
                    status_code=status.HTTP_409_CONFLICT,
                )
            if upload_request.revision != expected_revision:
                return return_response(
                    errors={'upload_request': '投稿内容已更新，请刷新后重试'},
                    status_code=status.HTTP_409_CONFLICT,
                )

            existing_files = list(upload_request.files.select_for_update().all())
            existing_file_ids = {upload_file.pk for upload_file in existing_files}
            if not remove_file_ids.issubset(existing_file_ids):
                return return_response(
                    errors={'remove_file_ids': get_err_msg('resource_upload_invalid_file_ids')},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            removed_files = [
                upload_file for upload_file in existing_files
                if upload_file.pk in remove_file_ids
            ]
            kept_files = [
                upload_file for upload_file in existing_files
                if upload_file.pk not in remove_file_ids
            ]
            final_file_count = len(kept_files) + len(files)
            if final_file_count == 0:
                return return_response(
                    errors={'files': get_err_msg('resource_upload_files_required')},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            if final_file_count > RESOURCE_UPLOAD_MAX_FILE_COUNT:
                return return_response(
                    errors={'files': get_err_msg('resource_upload_too_many_files')},
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            normalized_paths, validation_errors = validate_resource_upload_files(
                files,
                relative_paths,
                reserved_relative_paths=[upload_file.relative_path for upload_file in kept_files],
            )
            if validation_errors:
                return return_response(
                    errors=validation_errors,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            if remove_file_ids:
                ResourceUploadFile.objects.filter(
                    upload_request=upload_request,
                    pk__in=remove_file_ids,
                ).delete()
                transaction.on_commit(
                    lambda deleted_files=removed_files: delete_resource_upload_files_from_storage(deleted_files)
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

            upload_request.target_path = path_serializer.validated_data['target_path']
            upload_request.creates_new_folder = bool(path_serializer.validated_data.get('new_folder_name'))
            upload_request.total_size = (
                sum(upload_file.size for upload_file in kept_files)
                + sum(uploaded_file.size for uploaded_file in files)
            )
            upload_request.status = ResourceUploadRequest.STATUS_PENDING
            upload_request.reviewed_at = None
            upload_request.reviewed_by = None
            upload_request.rejection_reason = ''
            upload_request.publish_error = ''
            upload_request.files_deleted_at = None
            upload_request.revision += 1
            upload_request.save(update_fields=(
                'target_path',
                'creates_new_folder',
                'total_size',
                'status',
                'reviewed_at',
                'reviewed_by',
                'rejection_reason',
                'publish_error',
                'files_deleted_at',
                'revision',
                'updated_at',
            ))

            # The edit and administrator notification succeed or roll back together.
            queue_resource_upload_notifications(upload_request, event='updated')
        upload_request = ResourceUploadRequest.objects.prefetch_related('files').get(pk=upload_request.pk)
        return return_response(
            contents={'upload_request': ResourceUploadRequestSerializer(upload_request).data},
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
