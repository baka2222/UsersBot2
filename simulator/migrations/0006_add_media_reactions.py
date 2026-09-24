# Generated manually to keep this production migration independent of the local dev environment.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("simulator", "0005_apicredentials_telegramaccount_api_credentials"),
    ]

    operations = [
        migrations.AddField(
            model_name="messagetemplate",
            name="content_type",
            field=models.CharField(
                choices=[
                    ("text", "Текст"), ("reaction", "Реакция"),
                    ("image", "Изображение"), ("sticker", "Стикер"),
                ],
                default="text", max_length=12, verbose_name="Тип ответа",
            ),
        ),
        migrations.AddField(
            model_name="messagetemplate",
            name="reaction",
            field=models.CharField(blank=True, help_text="Emoji, например 👍, ❤️ или 🔥. Реакция ставится на сообщение-триггер.", max_length=32, verbose_name="Реакция"),
        ),
        migrations.AddField(
            model_name="messagetemplate",
            name="media",
            field=models.FileField(blank=True, help_text="Для изображения загрузите JPG, PNG, WEBP или GIF. Для стикера — WEBP, TGS или WEBM.", upload_to="template_media/%Y/%m/%d", verbose_name="Изображение или стикер"),
        ),
        migrations.AlterField(
            model_name="messagetemplate",
            name="text",
            field=models.TextField(blank=True, verbose_name="Текст сообщения / подпись"),
        ),
        migrations.AddField(
            model_name="scenarioreply",
            name="content_type",
            field=models.CharField(
                choices=[
                    ("text", "Текст"), ("reaction", "Реакция"),
                    ("image", "Изображение"), ("sticker", "Стикер"),
                ],
                default="text", help_text="Для текста оставьте «Текст». Для реакции, изображения или стикера заполните соответствующее поле ниже.", max_length=12, verbose_name="Тип ответа",
            ),
        ),
        migrations.AddField(
            model_name="scenarioreply",
            name="reaction",
            field=models.CharField(blank=True, help_text="Emoji для ответа-реакции на сообщение-триггер.", max_length=32, verbose_name="Реакция"),
        ),
        migrations.AddField(
            model_name="scenarioreply",
            name="media",
            field=models.FileField(blank=True, help_text="Для изображения: JPG, PNG, WEBP или GIF. Для стикера: WEBP, TGS или WEBM.", upload_to="scenario_media/%Y/%m/%d", verbose_name="Изображение или стикер"),
        ),
        migrations.AddField(
            model_name="dialogmessage",
            name="content_type",
            field=models.CharField(
                choices=[
                    ("text", "Текст"), ("reaction", "Реакция"),
                    ("image", "Изображение"), ("sticker", "Стикер"),
                ],
                default="text", max_length=12, verbose_name="Тип содержимого",
            ),
        ),
        migrations.AddField(
            model_name="dialogmessage",
            name="reaction",
            field=models.CharField(blank=True, max_length=32, verbose_name="Реакция"),
        ),
        migrations.AddField(
            model_name="dialogmessage",
            name="media",
            field=models.FileField(blank=True, upload_to="dialog_media/%Y/%m/%d", verbose_name="Файл"),
        ),
        migrations.AddField(
            model_name="dialogmessage",
            name="reaction_to_tg_id",
            field=models.BigIntegerField(blank=True, help_text="Служебное поле: реакция всегда привязана к конкретному сообщению Telegram.", null=True, verbose_name="ID сообщения для реакции"),
        ),
    ]
