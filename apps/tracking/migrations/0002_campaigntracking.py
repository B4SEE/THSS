from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('campaigns', '0006_description_nullable'),
        ('tracking', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='CampaignTracking',
            fields=[],
            options={
                'verbose_name': 'Campaign Dashboard',
                'verbose_name_plural': 'Campaign Dashboards',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('campaigns.campaign',),
        ),
    ]
