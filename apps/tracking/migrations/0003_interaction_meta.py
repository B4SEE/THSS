from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tracking', '0002_campaigntracking'),
    ]

    operations = [
        migrations.AddField(
            model_name='interaction',
            name='meta',
            field=models.JSONField(blank=True, null=True),
        ),
    ]
