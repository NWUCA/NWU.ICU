import logging

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from management_panel.models import AdminPasskeyCredential, AdminPasskeyState


logger = logging.getLogger('management.security')


class Command(BaseCommand):
    help = 'Revoke one or all Passkey credentials for an administrator.'

    def add_arguments(self, parser):
        parser.add_argument('username')
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--credential-id', type=int)
        group.add_argument('--all', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        user = get_user_model().objects.filter(username=options['username']).first()
        if user is None:
            raise CommandError('User does not exist.')
        credentials = AdminPasskeyCredential.objects.select_for_update().filter(user=user, revoked_at__isnull=True)
        if not options['all']:
            credentials = credentials.filter(pk=options['credential_id'])
        changed = credentials.update(revoked_at=timezone.now())
        if not changed:
            raise CommandError('No matching active Passkey credential found.')
        state, _ = AdminPasskeyState.objects.select_for_update().get_or_create(user=user)
        AdminPasskeyState.objects.filter(pk=state.pk).update(revision=F('revision') + 1)
        logger.info('passkey credentials revoked user_id=%s count=%s', user.pk, changed)
        self.stdout.write(self.style.SUCCESS(f'Revoked {changed} Passkey credential(s).'))
