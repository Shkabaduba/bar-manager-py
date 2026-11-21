from decimal import Decimal

import django.core.validators
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bar", "0002_remove_drink_bartenders_alter_order_bartender"),
    ]

    operations = [
        migrations.AddField(
            model_name="barsupplier",
            name="is_active",
            field=models.BooleanField(db_index=True, default=True),
        ),
        migrations.AddField(
            model_name="barsupplier",
            name="notes",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AlterField(
            model_name="barsupplier",
            name="phone",
            field=models.CharField(
                max_length=20,
                validators=[
                    django.core.validators.RegexValidator(
                        message="Enter a valid phone number (7-20 characters).",
                        regex=r"^\+?[0-9\s\-()]{7,20}$",
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name="baringredient",
            name="cost_per_unit",
            field=models.DecimalField(
                decimal_places=4,
                default=Decimal("0.0000"),
                max_digits=10,
            ),
        ),
        migrations.AddField(
            model_name="baringredient",
            name="min_stock_threshold",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=12,
            ),
        ),
        migrations.AddField(
            model_name="baringredient",
            name="unit",
            field=models.CharField(
                choices=[
                    ("ml", "Milliliters (ml)"),
                    ("g", "Grams (g)"),
                    ("pcs", "Pieces (pcs)"),
                ],
                default="ml",
                max_length=8,
            ),
        ),
        migrations.AlterField(
            model_name="baringredient",
            name="stock_quantity",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=12,
            ),
        ),
        migrations.AlterField(
            model_name="baringredient",
            name="supplier",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="ingredients",
                to="bar.barsupplier",
            ),
        ),
        migrations.AddField(
            model_name="bartender",
            name="role",
            field=models.CharField(
                choices=[
                    ("OWNER", "Owner / Admin"),
                    ("MANAGER", "Bar Manager"),
                    ("BARTENDER", "Bartender"),
                ],
                db_index=True,
                default="BARTENDER",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="bartender",
            name="staff_id",
            field=models.CharField(
                max_length=255,
                unique=True,
                validators=[
                    django.core.validators.RegexValidator(
                        message=(
                            "Staff ID must be 8-15 characters using letters, "
                            "digits, '_' or '-'."
                        ),
                        regex=r"^[A-Za-z0-9_-]{8,15}$",
                    )
                ],
            ),
        ),
        migrations.AddField(
            model_name="drink",
            name="description",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="drink",
            name="is_active",
            field=models.BooleanField(db_index=True, default=True),
        ),
        migrations.AddField(
            model_name="drink",
            name="target_food_cost_pct",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("25.00"),
                max_digits=5,
            ),
        ),
        migrations.AlterField(
            model_name="drink",
            name="category",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="drinks",
                to="bar.drinkscategory",
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="closed_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="closed_orders",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="override_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="overridden_orders",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="override_reason",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
        migrations.AddField(
            model_name="order",
            name="paid_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="order",
            name="status",
            field=models.CharField(
                choices=[
                    ("OPEN", "Open"),
                    ("IN_PROGRESS", "In Progress"),
                    ("PAID", "Paid"),
                    ("CANCELLED", "Cancelled"),
                ],
                db_index=True,
                default="OPEN",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="total_cost_snapshot",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=12,
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="total_revenue_snapshot",
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal("0.00"),
                max_digits=12,
            ),
        ),
        migrations.AddField(
            model_name="order",
            name="version",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.CreateModel(
            name="DrinkIngredient",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "amount",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("50.00"),
                        max_digits=10,
                    ),
                ),
                (
                    "drink",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recipe_items",
                        to="bar.drink",
                    ),
                ),
                (
                    "ingredient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="drink_usages",
                        to="bar.baringredient",
                    ),
                ),
            ],
            options={
                "ordering": ["ingredient__name"],
            },
        ),
        migrations.CreateModel(
            name="OrderItem",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("quantity", models.PositiveIntegerField(default=1)),
                (
                    "unit_price_snapshot",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=10,
                    ),
                ),
                (
                    "unit_cost_snapshot",
                    models.DecimalField(
                        decimal_places=4,
                        default=Decimal("0.0000"),
                        max_digits=10,
                    ),
                ),
                (
                    "drink",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="order_items",
                        to="bar.drink",
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="items",
                        to="bar.order",
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
            },
        ),
        migrations.CreateModel(
            name="StockMovement",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "movement_type",
                    models.CharField(
                        choices=[
                            ("IN", "Stock In (Receipt)"),
                            ("OUT_ORDER", "Order Deduction"),
                            ("WRITEOFF", "Write-off"),
                            ("ADJUSTMENT", "Inventory Adjustment"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "quantity_delta",
                    models.DecimalField(decimal_places=2, max_digits=12),
                ),
                (
                    "balance_after",
                    models.DecimalField(decimal_places=2, max_digits=12),
                ),
                (
                    "unit_cost",
                    models.DecimalField(
                        decimal_places=4,
                        default=Decimal("0.0000"),
                        max_digits=10,
                    ),
                ),
                (
                    "total_cost",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=12,
                    ),
                ),
                (
                    "shortfall_quantity",
                    models.DecimalField(
                        decimal_places=2,
                        default=Decimal("0.00"),
                        max_digits=12,
                    ),
                ),
                (
                    "reason",
                    models.CharField(blank=True, default="", max_length=255),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "ingredient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="movements",
                        to="bar.baringredient",
                    ),
                ),
                (
                    "order",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stock_movements",
                        to="bar.order",
                    ),
                ),
                (
                    "performed_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="stock_movements",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("action", models.CharField(db_index=True, max_length=64)),
                (
                    "target_model",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                (
                    "target_id",
                    models.CharField(blank=True, default="", max_length=64),
                ),
                ("metadata", models.JSONField(blank=True, default=dict)),
                (
                    "ip_address",
                    models.GenericIPAddressField(blank=True, null=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="audit_logs",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at", "-id"],
            },
        ),
    ]
