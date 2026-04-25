from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scheduling', '0023_team_staffteamassignment_match_team_player_team'),
    ]

    operations = [
        migrations.AddField(
            model_name='player',
            name='is_approved',
            field=models.BooleanField(default=True),
            preserve_default=False,
        ),
        # After adding the column with default=True for existing rows,
        # change the model default to False so new signups are pending.
        migrations.AlterField(
            model_name='player',
            name='is_approved',
            field=models.BooleanField(default=False),
        ),
    ]
