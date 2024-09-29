from django.core.management.base import BaseCommand
from soupsieve.util import lower

from course_assessment.models import Teacher, Course
from pypinyin import lazy_pinyin
from django.db import transaction


class Command(BaseCommand):
    help = 'Updates the pinyin field for all existing module records'

    def add_arguments(self, parser):
        parser.add_argument('module_name', type=str, help='module name')

    def handle(self, *args, **options):
        module_name = lower(options['module_name'])
        module_name_list = ['teacher', 'course']
        if module_name not in module_name_list:
            self.stdout.write('invalid module name')
            return
        module_dict = {
            'teacher': Teacher,
            'course': Course
        }
        self.stdout.write(f'Starting to update {module_name} pinyin...')
        items = module_dict.get(module_name).objects.all()
        total = items.count()
        updated = 0

        with transaction.atomic():
            for item in items:
                pinyin = ''.join(lazy_pinyin(item.name))
                item.pinyin = pinyin
                item.save()
                updated += 1
                if updated % 100 == 0:
                    self.stdout.write(f'Updated {updated}/{total} {module_name}')

        self.stdout.write(self.style.SUCCESS(f'Successfully updated pinyin for {updated} {module_name}'))
