import datetime

from django.core.management.base import BaseCommand

from course_assessment.models import Semeseter


class Command(BaseCommand):
    help = 'Updates the semester annually'

    def handle(self, *args, **options):
        self.stdout.write(f'Starting to update semester...')
        current_date = datetime.datetime.now()
        current_year = current_date.year
        current_month = current_date.month
        start_year = 2017
        semester_list = []
        spring_semester_month = 3
        autumn_semester_month = 7
        for year in range(start_year, current_year + 1):
            if year != current_year:
                semester_list.append(f'{year}-春')
                semester_list.append(f'{year}-秋')
            else:
                if current_month >= spring_semester_month:
                    semester_list.append(f'{year}-春')
                if current_month >= autumn_semester_month:
                    semester_list.append(f'{year}-秋')
        items = Semeseter.objects.all().order_by('id')
        for item in items:
            item.name = semester_list[0]
            item.save()
            semester_list.pop(0)
        for i in semester_list:
            Semeseter.objects.create(name=i)
        self.stdout.write(f'Update semester successful!...')
