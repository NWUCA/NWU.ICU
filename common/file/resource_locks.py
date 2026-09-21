"""Resource mutations lock owner, request, job/files, then notification rows."""
from user.models import User

from .models import ResourceUploadRequest


def lock_resource_upload_request(upload_request_id):
    """Call within atomic(); ownership cannot change through the upload workflow."""
    owner_id = ResourceUploadRequest.objects.values_list('uploaded_by_id', flat=True).get(pk=upload_request_id)
    User.objects.select_for_update().get(pk=owner_id)
    return ResourceUploadRequest.objects.select_for_update().get(pk=upload_request_id)
