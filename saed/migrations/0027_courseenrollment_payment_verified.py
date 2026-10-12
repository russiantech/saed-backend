from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("saed", "0026_add_password_reset_code_created_at")]

    operations = [
        migrations.AddField(
            model_name="courseenrollment",
            name="payment_verified",
            field=models.BooleanField(default=False),
        ),
    ]
