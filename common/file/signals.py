import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.db.models.signals import pre_save
from django.dispatch import receiver

from common.file.models import UploadedFile
from settings import settings


def get_max_file_size(file_type):
    return settings.FILE_UPLOAD_SIZE_LIMIT.get(file_type, 25 * 1024 * 1024)


def compress_image_with_resize(input_file, target_size):
    img = Image.open(input_file)
    aspect_ratio = img.size[0] / img.size[1]
    quality = 95
    width = img.size[0]
    height = img.size[1]

    while True:
        output_file = BytesIO()
        img_resized = img.resize((width, height), Image.Resampling.LANCZOS)
        img_resized.save(output_file, 'WEBP', quality=quality)
        size = len(output_file.getvalue())
        if size <= target_size:
            break
        if quality > 5:
            quality -= 5
        else:
            width = int(width * 0.9)
            height = int(width / aspect_ratio)
            quality = 95
        if width < 100 or height < 100:
            break
    output_file.seek(0)
    output_file = InMemoryUploadedFile(
        output_file, None, Path(input_file.name).with_suffix('.webp'), 'image/webp', size, None
    )
    return output_file


def calculate_file_hash(file, chunk_size=8192):
    hasher = hashlib.new('sha256')
    while chunk := file.read(chunk_size):
        hasher.update(chunk)
    return hasher.hexdigest()


def compare_file_hash(file_hash):
    uploaded_files = UploadedFile.objects.filter(file_hash=file_hash).order_by('uploaded_at')
    if len(uploaded_files) > 0:
        exist_file = uploaded_files.first()
        return exist_file
    else:
        return None


@receiver(pre_save, sender=UploadedFile)
def file_handler(sender, instance: UploadedFile, **kwargs):
    if hasattr(instance, '_processed'):
        return
    file_type = instance.file_type
    if instance.file_size > get_max_file_size(file_type):
        instance.file = compress_image_with_resize(instance.file, get_max_file_size(file_type))
        instance.file_name = instance.file.name
        instance.file_size = instance.file.size
    file_hash = calculate_file_hash(instance.file)
    instance.file_hash = file_hash
    exist_file = compare_file_hash(file_hash)
    if exist_file is not None:
        instance.file = exist_file.file
        instance.file_size = exist_file.file_size
    instance._processed = True
