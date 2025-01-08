import os
import re
from collections import Counter

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from common.file.models import UploadedFile
from course_assessment.models import Review


class Command(BaseCommand):
    help = 'Clean unused file'

    def add_arguments(self, parser):
        parser.add_argument('-y', '--yes', action='store_true', help='Automatically clean unused(ref_count=0) file')

    def get_review_using_file_uuid(self, review: str):
        review_using_uuid = re.findall(r'(\w{8}-\w{4}-\w{4}-\w{4}-\w{12})', review)
        return review_using_uuid

    def add_ref_to_file_model(self, uuid_list):
        uuid_count = Counter(uuid_list)
        with transaction.atomic():
            for uuid, count in uuid_count.items():
                UploadedFile.objects.filter(id=uuid).update(ref_count=count)
        self.stdout.write(self.style.SUCCESS('Successfully added ref to file model'))

    def clean_ref_0_file(self, file_path):
        try:
            if os.path.exists(file_path):
                os.remove(file_path)  # 删除文件
                print(f"file {file_path} has deleted.")
            else:
                print(f"file {file_path} not exist.")
        except Exception as e:
            print(f"delete file {file_path} failed. Error: {e}")

    def format_size(self, size):
        units = ["byte", "KB", "MB", "GB", "TB"]
        unit_index = 0
        while size >= 1024 and unit_index < len(units) - 1:
            size /= 1024
            unit_index += 1
        formatted_size = f"{size:,.2f} {units[unit_index]}"
        return formatted_size

    def sum_unused_file_size(self):
        unused_file_list = UploadedFile.objects.filter(ref_count=0)
        total_size = 0
        hash_list = []
        for file in unused_file_list:
            if file.file_hash not in hash_list:
                total_size += file.file_size
                hash_list.append(file.file_hash)
        return self.format_size(total_size)

    def handle(self, *args, **options):
        using_file_uuid_list = []
        reviews = Review.objects.all()
        for review in reviews:
            using_file_uuid_list.extend(self.get_review_using_file_uuid(review.content))
        users = get_user_model().objects.all()
        for user in users:
            using_file_uuid_list.append(str(user.avatar_uuid))
        self.add_ref_to_file_model(using_file_uuid_list)
        self.stdout.write(self.style.SUCCESS(f'unused file sum size is {self.sum_unused_file_size()}'))
        self.stdout.write(self.style.ERROR('Are you sure you want to delete the unused file? (y/N): '), ending='')
        if options['yes'] or input().lower() == 'y':
            unused_file_list = UploadedFile.objects.filter(ref_count=0)
            for file in unused_file_list:
                self.clean_ref_0_file(file.file.path)
            unused_file_list.delete()
            self.stdout.write(self.style.SUCCESS('Successfully deleted unused file'))
        else:
            self.stdout.write(self.style.WARNING('Operation cancelled.'))
