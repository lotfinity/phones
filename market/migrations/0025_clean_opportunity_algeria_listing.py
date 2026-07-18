from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("market", "0024_phonelisting_store_warranty"),
    ]

    operations = [
        migrations.AddField(
            model_name="phoneopportunitysnapshot",
            name="algeria_listing",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="clean_opportunity_snapshots",
                to="market.phonelisting",
            ),
        ),
        migrations.AddField(
            model_name="laptopopportunitysnapshot",
            name="algeria_listing",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="clean_opportunity_snapshots",
                to="market.laptoplisting",
            ),
        ),
        migrations.AddField(
            model_name="consoleopportunitysnapshot",
            name="algeria_listing",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="clean_opportunity_snapshots",
                to="market.consolelisting",
            ),
        ),
    ]
