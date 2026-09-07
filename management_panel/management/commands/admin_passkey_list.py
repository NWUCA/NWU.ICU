from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = 'List Passkey credentials for an administrator without exposing key material.'

    def add_arguments(self, parser):
        parser.add_argument('username')

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username=options['username']).first()
        if user is None:
            raise CommandError('User does not exist.')
        credentials = user.admin_passkeys.order_by('-created_at', '-id')
        if not credentials.exists():
            self.stdout.write('No Passkey credentials found.')
            return
        for credential in credentials:
            status = 'revoked' if credential.revoked_at else 'active'
            self.stdout.write(
                f'{credential.pk}\t{credential.name}\t{status}\tcreated={credential.created_at.isoformat()}\t'
                f'last_used={credential.last_used_at.isoformat() if credential.last_used_at else "never"}'
            )

