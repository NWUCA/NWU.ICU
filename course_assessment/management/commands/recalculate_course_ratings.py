from django.core.management.base import BaseCommand

from course_assessment.ratings import recalculate_course_ratings


class Command(BaseCommand):
    help = 'Recalculate all course ratings with one site-wide baseline'

    def add_arguments(self, parser):
        parser.add_argument('--database', default='default')

    def handle(self, *args, **options):
        count = recalculate_course_ratings(using=options['database'])
        self.stdout.write(self.style.SUCCESS(f'Updated ratings for {count} courses'))
