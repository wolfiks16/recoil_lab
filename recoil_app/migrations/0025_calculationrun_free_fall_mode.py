from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("recoil_app", "0024_userprofile_avatar_and_birth"),
    ]

    operations = [
        migrations.AddField(
            model_name="calculationrun",
            name="mode",
            field=models.CharField(
                choices=[
                    ("recoil", "Откат"),
                    ("free_fall", "Свободное падение"),
                ],
                default="recoil",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="calculationrun",
            name="input_file",
            field=models.FileField(blank=True, null=True, upload_to="uploads/"),
        ),
    ]
