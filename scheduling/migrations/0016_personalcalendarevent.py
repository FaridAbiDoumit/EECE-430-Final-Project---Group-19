from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0015_playermatchstat_aces_playermatchstat_assists_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='PersonalCalendarEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(max_length=120)),
                ('starts_at', models.DateTimeField()),
                ('ends_at', models.DateTimeField()),
                ('location', models.CharField(max_length=120)),
                ('notes', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('player', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='personal_calendar_events', to='scheduling.player')),
            ],
            options={
                'ordering': ['starts_at', 'id'],
            },
        ),
    ]
