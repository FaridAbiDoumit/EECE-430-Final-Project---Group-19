from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0016_personalcalendarevent'),
    ]

    operations = [
        migrations.AddField(
            model_name='teamgoal',
            name='metric',
            field=models.CharField(
                choices=[
                    ('goals', 'Goals'),
                    ('points', 'Points'),
                    ('assists', 'Assists'),
                    ('blocks', 'Blocks'),
                    ('aces', 'Aces'),
                    ('interceptions', 'Interceptions'),
                    ('returns', 'Returns'),
                ],
                default='points',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='teamgoal',
            name='target_value',
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.CreateModel(
            name='PlayerSorenessReport',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('soreness_level', models.PositiveSmallIntegerField()),
                ('notes', models.CharField(blank=True, max_length=200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('player', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='soreness_reports', to='scheduling.player')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
    ]
