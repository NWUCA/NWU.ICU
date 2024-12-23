from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

User = get_user_model()


class Command(BaseCommand):
    help = 'Creates a default user'

    def add_arguments(self, parser):
        parser.add_argument('-y', '--yes', action='store_true', help='Automatically confirm overwriting existing user')

    def handle(self, *args, **options):
        super_user_id = int(settings.DEFAULT_SUPER_USER_ID)
        username = settings.DEFAULT_SUPER_USER_USERNAME
        email = settings.DEFAULT_SUPER_USER_PASSWORD
        password = settings.DEFAULT_SUPER_USER_PASSWORD
        if User.objects.filter(id=super_user_id).exists():
            if options['yes']:
                self.stdout.write(self.style.WARNING(f'User with id={super_user_id} already exists, ignore operation'))
                return
            else:
                confirm = input(
                    f'User with id={super_user_id} already exists, are you sure you want to overwrite it? (Y/n): ')
            if confirm.lower() == 'n':
                self.stdout.write(self.style.WARNING('Operation cancelled.'))
                return
        super_user = User.objects.create_superuser(id=super_user_id, username=username, email=email, password=password,
                                                   is_active=True, is_staff=True, is_superuser=True)
        self.stdout.write(self.style.SUCCESS(f'Successfully created user "{username}", ID is {super_user.id}'))
