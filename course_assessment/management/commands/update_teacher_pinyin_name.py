from django.core.management.base import BaseCommand
from course_assessment.models import Teacher
from pypinyin import lazy_pinyin
from django.db import transaction


class Command(BaseCommand):
    help = 'Updates the pinyin field for all existing Teacher records'

    def handle(self, *args, **options):
        self.stdout.write('Starting to update Teacher pinyin...')

        teachers = Teacher.objects.all()
        total = teachers.count()
        updated = 0

        with transaction.atomic():
            for teacher in teachers:
                pinyin = ''.join(lazy_pinyin(teacher.name))
                teacher.pinyin = pinyin
                teacher.save()
                updated += 1
                if updated % 100 == 0:  # 每更新100条记录输出一次进度
                    self.stdout.write(f'Updated {updated}/{total} teachers')

        self.stdout.write(self.style.SUCCESS(f'Successfully updated pinyin for {updated} teachers'))
