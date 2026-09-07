import hashlib
import secrets
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from management_panel.models import AdminPasskeyEnrollment


class Command(BaseCommand):
    help = 'Create a one-time browser enrollment code for an administrator Passkey.'

    def add_arguments(self, parser):
        parser.add_argument('username')

    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username=options['username']).first()
        if user is None or not user.is_active or not user.is_staff:
            raise CommandError('The target must be an active staff user.')
        now = timezone.now()
        AdminPasskeyEnrollment.objects.filter(user=user, used_at__isnull=True).update(used_at=now)
        token = secrets.token_urlsafe(32)
        AdminPasskeyEnrollment.objects.create(
            user=user,
            token_digest=hashlib.sha256(token.encode('utf-8')).hexdigest(),
            expires_at=now + timedelta(minutes=5),
        )
        self.stdout.write('Open /manage after signing in, then enter this one-time code (valid for 5 minutes):')
        self.stdout.write(self.style.SUCCESS(token))

