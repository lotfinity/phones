from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("market", "0023_parsedlistingcandidate_console_specs_json_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="phonelisting",
            name="store_warranty",
            field=models.CharField(blank=True, max_length=240),
        ),
    ]
