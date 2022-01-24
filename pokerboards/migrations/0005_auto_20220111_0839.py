# Generated by Django 2.2 on 2022-01-11 08:39

from django.conf import settings
import django.contrib.postgres.fields
import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('pokerboards', '0004_auto_20220105_0752'),
    ]

    operations = [
        migrations.AlterField(
            model_name='pokerboard',
            name='deck',
            field=django.contrib.postgres.fields.ArrayField(base_field=models.DecimalField(decimal_places=3, max_digits=17, validators=[django.core.validators.MaxValueValidator(100000000000000.0), django.core.validators.MinValueValidator(0.001)]), size=52),
        ),
        migrations.AlterField(
            model_name='userpokerboard',
            name='user',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='pokerboards', to=settings.AUTH_USER_MODEL),
        ),
    ]