from datetime import timedelta

from django.db import migrations, models


def populate_ends_at(apps, schema_editor):
    TrainingSession = apps.get_model('scheduling', 'TrainingSession')
    for session in TrainingSession.objects.all().iterator():
        session.ends_at = session.starts_at + timedelta(hours=2)
        session.save(update_fields=['ends_at'])


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0009_tryoutsession_description'),
    ]

    operations = [
        migrations.AddField(
            model_name='trainingsession',
            name='ends_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(populate_ends_at, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='trainingsession',
            name='ends_at',
            field=models.DateTimeField(),
        ),
    ]
