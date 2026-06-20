from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("saed", "0002_alter_program_category"),
    ]

    operations = [
        migrations.AddField(
            model_name="program",
            name="trainer",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="training_programs",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
