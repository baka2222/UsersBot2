# Generated manually: these fields let one scenario reply contain several
# actions without changing or rewriting existing scenarios.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("simulator", "0006_add_media_reactions"),
    ]

    operations = [
        migrations.AddField(
            model_name="scenarioreply",
            name="image",
            field=models.FileField(
                blank=True,
                help_text="Необязательно. JPG, PNG, WEBP или GIF.",
                upload_to="scenario_images/%Y/%m/%d",
                verbose_name="Изображение",
            ),
        ),
        migrations.AddField(
            model_name="scenarioreply",
            name="sticker",
            field=models.FileField(
                blank=True,
                help_text="Необязательно. WEBP, TGS или WEBM.",
                upload_to="scenario_stickers/%Y/%m/%d",
                verbose_name="Стикер",
            ),
        ),
        migrations.AddField(
            model_name="scenarioreply",
            name="reaction_order",
            field=models.PositiveSmallIntegerField(
                choices=[
                    (1, "1 — первым"), (2, "2 — вторым"),
                    (3, "3 — третьим"), (4, "4 — четвёртым"),
                ],
                default=1,
                verbose_name="Порядок реакции",
            ),
        ),
        migrations.AddField(
            model_name="scenarioreply",
            name="image_order",
            field=models.PositiveSmallIntegerField(
                choices=[
                    (1, "1 — первым"), (2, "2 — вторым"),
                    (3, "3 — третьим"), (4, "4 — четвёртым"),
                ],
                default=2,
                verbose_name="Порядок изображения",
            ),
        ),
        migrations.AddField(
            model_name="scenarioreply",
            name="text_order",
            field=models.PositiveSmallIntegerField(
                choices=[
                    (1, "1 — первым"), (2, "2 — вторым"),
                    (3, "3 — третьим"), (4, "4 — четвёртым"),
                ],
                default=3,
                verbose_name="Порядок текста",
            ),
        ),
        migrations.AddField(
            model_name="scenarioreply",
            name="sticker_order",
            field=models.PositiveSmallIntegerField(
                choices=[
                    (1, "1 — первым"), (2, "2 — вторым"),
                    (3, "3 — третьим"), (4, "4 — четвёртым"),
                ],
                default=4,
                verbose_name="Порядок стикера",
            ),
        ),
    ]
