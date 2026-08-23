from django.db import migrations, models
from django.db.models.functions import Lower


def normalize_and_deduplicate_verified_college_emails(apps, schema_editor):
    User = apps.get_model('user', 'User')
    claimed_emails = set()
    for user in User.objects.exclude(college_email__isnull=True).order_by('pk').iterator():
        normalized_email = user.college_email.strip().lower()
        update_fields = []
        if user.college_email != normalized_email:
            user.college_email = normalized_email
            update_fields.append('college_email')
        if user.college_email_verified:
            if normalized_email in claimed_emails:
                user.college_email_verified = False
                update_fields.append('college_email_verified')
            else:
                claimed_emails.add(normalized_email)
        if update_fields:
            user.save(update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [
        ('user', '0010_user_private_reply_user_private_review'),
    ]

    operations = [
        migrations.RunPython(
            normalize_and_deduplicate_verified_college_emails,
            migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name='user',
            constraint=models.UniqueConstraint(
                Lower('college_email'),
                condition=models.Q(college_email_verified=True, college_email__isnull=False),
                name='unique_verified_college_email_ci',
            ),
        ),
    ]
