from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('course_assessment', '0017_teacher_pinyin_teacher_search_vector_and_more')
    ]

    operations = [
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS pg_trgm;",
            "DROP EXTENSION IF EXISTS pg_trgm;"
        ),
        migrations.RunSQL(
            "CREATE EXTENSION IF NOT EXISTS zhparser;",
            "DROP EXTENSION IF EXISTS zhparser;"
        ),
    ]
