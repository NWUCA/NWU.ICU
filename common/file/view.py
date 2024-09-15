from django.conf import settings
from django.http import Http404, FileResponse
from rest_framework import status, generics
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
from common.utils import get_err_msg

from common.utils import return_response
from .models import UploadedFile
from .serializers import UploadedFileSerializer


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
        file_obj = request.FILES['file']
        if file_obj.size > settings.FILE_UPLOAD_SIZE_LIMIT:
            return return_response(errors={"file": get_err_msg("file_over_size")},
                                   status_code=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)
        return return_response(contents=serializer.data, status_code=status.HTTP_201_CREATED)


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


class FileDownloadView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, file_uuid):
        try:
            file_instance = UploadedFile.objects.get(pk=file_uuid)
        except UploadedFile.DoesNotExist:
            return return_response(errors={"file": get_err_msg('file_not_exist')},
                                   status_code=status.HTTP_404_NOT_FOUND)
        response = FileResponse(file_instance.file)
        response['Content-Disposition'] = f'attachment; filename="{file_instance.file.name}"'
        return response
