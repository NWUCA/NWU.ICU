from django.conf import settings
from django.http import Http404, FileResponse
from rest_framework import status, generics
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

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
                return Response({"error": "You do not have permission to delete this file."},
                                status=status.HTTP_403_FORBIDDEN)
            self.perform_destroy(instance)
            return Response({"message": "delete success"}, status=status.HTTP_204_NO_CONTENT)
        except Http404:
            return Response({"error": "File not found."}, status=status.HTTP_404_NOT_FOUND)


class FileUploadView(generics.CreateAPIView):
    queryset = UploadedFile.objects.all()
    serializer_class = UploadedFileSerializer
    parser_classes = (MultiPartParser, FormParser)
    permission_classes = [IsAuthenticated]

    def create(self, request, *args, **kwargs):
        file_obj = request.FILES['file']
        if file_obj.size > settings.FILE_UPLOAD_SIZE_LIMIT:
            return Response({"error": "File too large. Size should not exceed 25 MB."},
                            status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(created_by=request.user)

        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)


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
                return Response({"error": "You do not have permission to update this file."},
                                status=status.HTTP_403_FORBIDDEN)

            if 'file' in request.FILES:
                file_obj = request.FILES['file']
                if file_obj.size > settings.FILE_UPLOAD_SIZE_LIMIT:
                    return Response({"error": "File too large. Size should not exceed 25 MB."},
                                    status=status.HTTP_400_BAD_REQUEST)

            serializer = self.get_serializer(instance, data=request.data, partial=partial)
            serializer.is_valid(raise_exception=True)
            serializer.save()

            return Response(serializer.data)
        except Http404:
            return Response({"error": "File not found."}, status=status.HTTP_404_NOT_FOUND)


class FileDownloadView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, file_uuid):
        try:
            file_instance = UploadedFile.objects.get(pk=file_uuid)
        except UploadedFile.DoesNotExist:
            return Response({"error": "File not found."}, status=status.HTTP_404_NOT_FOUND)
        response = FileResponse(file_instance.file)
        response['Content-Disposition'] = f'attachment; filename="{file_instance.file.name}"'
        return response