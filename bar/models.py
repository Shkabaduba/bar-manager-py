from decimal import Decimal
import re

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse

staff_id_validator = RegexValidator(
    regex=r"^[A-Za-z0-9_-]{8,15}$",
    message=(
        "Staff ID must be 8-15 characters using letters, digits, "
        "'_' or '-'."
    ),
)

phone_validator = RegexValidator(
    regex=r"^\+?[0-9\s\-()]{7,20}$",
    message="Enter a valid phone number (7-20 characters).",
)


class BarSupplier(models.Model):
    name = models.CharField(max_length=255, unique=True)
    phone = models.CharField(max_length=20, validators=[phone_validator])
    email = models.EmailField(blank=True)
    notes = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.phone})"


class BarIngredient(models.Model):
    class Unit(models.TextChoices):
        ML = "ml", "Milliliters (ml)"
        GRAMS = "g", "Grams (g)"
        PCS = "pcs", "Pieces (pcs)"

    name = models.CharField(max_length=255, unique=True)
    unit = models.CharField(
        max_length=8,
        choices=Unit.choices,
        default=Unit.ML,
    )
    stock_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    cost_per_unit = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    min_stock_threshold = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    supplier = models.ForeignKey(
        BarSupplier,
        on_delete=models.PROTECT,
        related_name="ingredients",
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(stock_quantity__gte=0),
                name="ingredient_stock_quantity_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(cost_per_unit__gte=0),
                name="ingredient_cost_per_unit_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(min_stock_threshold__gte=0),
                name="ingredient_min_stock_gte_0",
            ),
        ]
        indexes = [
            models.Index(fields=["stock_quantity"], name="bar_ing_stock_idx"),
            models.Index(
                fields=["supplier", "name"],
                name="bar_ing_supplier_name_idx",
            ),
        ]

    def __str__(self):
        return f"{self.name} (in stock: {self.stock_quantity} {self.unit})"


class DrinksCategory(models.Model):
    name = models.CharField(max_length=255, unique=True)
    is_alcohol = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories of drinks"

    def __str__(self):
        status = "Alcoholic" if self.is_alcohol else "Non-alcoholic"
        return f"{self.name} ({status})"


class Bartender(AbstractUser):
    class Role(models.TextChoices):
        OWNER = "OWNER", "Owner / Admin"
        MANAGER = "MANAGER", "Bar Manager"
        BARTENDER = "BARTENDER", "Bartender"

    staff_id = models.CharField(
        max_length=255,
        unique=True,
        validators=[staff_id_validator],
    )
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.BARTENDER,
        db_index=True,
    )

    REQUIRED_FIELDS = ["email", "staff_id"]

    class Meta:
        verbose_name = "bartender"
        verbose_name_plural = "bartenders"
        ordering = ["username"]

    @property
    def is_owner(self):
        return self.is_superuser or self.role == self.Role.OWNER

    @property
    def is_manager(self):
        return self.role == self.Role.MANAGER

    @property
    def is_bartender(self):
        return self.role == self.Role.BARTENDER and not self.is_superuser

    @property
    def can_manage_bar(self):
        return self.is_owner or self.is_manager

    @property
    def can_force_close(self):
        return self.can_manage_bar

    @property
    def can_manage_staff(self):
        return self.is_owner

    @property
    def can_view_analytics(self):
        return self.can_manage_bar

    def __str__(self):
        return f"{self.username} ({self.first_name} {self.last_name})"

    def get_absolute_url(self):
        return reverse("bar:bartender-detail", kwargs={"pk": self.pk})

    def save(self, *args, **kwargs):
        if self.is_superuser:
            if not self.pk and self.role == self.Role.BARTENDER:
                self.role = self.Role.OWNER
            if not (self.staff_id or "").strip():
                clean_user = re.sub(
                    r"[^A-Za-z0-9_-]",
                    "",
                    str(self.username or "ADMIN"),
                )
                candidate = f"OWN_{clean_user[:11].upper()}"
                if len(candidate) < 8:
                    candidate = f"{candidate}_0001"[:15]
                self.staff_id = candidate
        super().save(*args, **kwargs)


class Drink(models.Model):
    name = models.CharField(max_length=255, unique=True)
    price = models.DecimalField(max_digits=7, decimal_places=2)
    volume_ml = models.PositiveIntegerField(default=250)
    target_food_cost_pct = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("25.00"),
    )
    is_active = models.BooleanField(default=True, db_index=True)
    description = models.TextField(blank=True, default="")
    category = models.ForeignKey(
        DrinksCategory,
        on_delete=models.PROTECT,
        related_name="drinks",
    )
    ingredients = models.ManyToManyField(
        BarIngredient,
        through="DrinkIngredient",
        related_name="drinks",
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(price__gt=0),
                name="drink_price_gt_0",
            ),
            models.CheckConstraint(
                condition=models.Q(
                    target_food_cost_pct__gt=0,
                    target_food_cost_pct__lte=100,
                ),
                name="drink_target_food_cost_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=["is_active", "name"],
                name="bar_drink_active_name_idx",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.volume_ml}ml - {self.price} ₴)"

    def get_absolute_url(self):
        return reverse("bar:drink-detail", kwargs={"pk": self.pk})


class DrinkIngredient(models.Model):
    drink = models.ForeignKey(
        Drink,
        on_delete=models.CASCADE,
        related_name="recipe_items",
    )
    ingredient = models.ForeignKey(
        BarIngredient,
        on_delete=models.PROTECT,
        related_name="drink_usages",
    )
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("50.00"),
    )

    class Meta:
        ordering = ["ingredient__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["drink", "ingredient"],
                name="unique_drink_ingredient",
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name="drink_ingredient_amount_gt_0",
            ),
        ]

    def __str__(self):
        return (
            f"{self.drink.name}: {self.ingredient.name} "
            f"({self.amount} {self.ingredient.unit})"
        )


class Order(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        PAID = "PAID", "Paid"
        CANCELLED = "CANCELLED", "Cancelled"

    table_number = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(
        max_length=16,
        choices=Status.choices,
        default=Status.OPEN,
        db_index=True,
    )
    is_paid = models.BooleanField(default=False)
    version = models.PositiveIntegerField(default=1)
    paid_at = models.DateTimeField(null=True, blank=True)
    bartender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders",
    )
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_orders",
    )
    override_reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )
    override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="overridden_orders",
    )
    total_revenue_snapshot = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    total_cost_snapshot = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    drinks = models.ManyToManyField(
        Drink,
        through="OrderItem",
        related_name="orders",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(version__gte=1),
                name="order_version_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(total_revenue_snapshot__gte=0),
                name="order_revenue_snapshot_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(total_cost_snapshot__gte=0),
                name="order_cost_snapshot_gte_0",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "-created_at"],
                name="bar_order_status_created_idx",
            ),
            models.Index(
                fields=["bartender", "status"],
                name="bar_order_bartender_status_idx",
            ),
            models.Index(
                fields=["-paid_at"],
                name="bar_order_paid_at_idx",
            ),
        ]

    def __str__(self):
        return f"Order #{self.id} (Table {self.table_number})"

    def get_absolute_url(self):
        return reverse("bar:order-detail", kwargs={"pk": self.pk})


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
    )
    drink = models.ForeignKey(
        Drink,
        on_delete=models.PROTECT,
        related_name="order_items",
    )
    quantity = models.PositiveIntegerField(default=1)
    unit_price_snapshot = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    unit_cost_snapshot = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal("0.0000"),
    )

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["order", "drink"],
                name="unique_order_drink",
            ),
            models.CheckConstraint(
                condition=models.Q(quantity__gte=1),
                name="order_item_quantity_gte_1",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_price_snapshot__gte=0),
                name="order_item_price_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_cost_snapshot__gte=0),
                name="order_item_cost_gte_0",
            ),
        ]

    def __str__(self):
        return f"Order #{self.order_id}: {self.drink.name} x{self.quantity}"


class StockMovement(models.Model):
    class MovementType(models.TextChoices):
        IN = "IN", "Stock In (Receipt)"
        OUT_ORDER = "OUT_ORDER", "Order Deduction"
        WRITEOFF = "WRITEOFF", "Write-off"
        ADJUSTMENT = "ADJUSTMENT", "Inventory Adjustment"

    ingredient = models.ForeignKey(
        BarIngredient,
        on_delete=models.PROTECT,
        related_name="movements",
    )
    movement_type = models.CharField(
        max_length=16,
        choices=MovementType.choices,
    )
    quantity_delta = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    unit_cost = models.DecimalField(
        max_digits=10,
        decimal_places=4,
        default=Decimal("0.0000"),
    )
    total_cost = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    shortfall_quantity = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    reason = models.CharField(max_length=255, blank=True, default="")
    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="stock_movements",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(balance_after__gte=0),
                name="stock_movement_balance_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(unit_cost__gte=0),
                name="stock_movement_unit_cost_gte_0",
            ),
            models.CheckConstraint(
                condition=models.Q(shortfall_quantity__gte=0),
                name="stock_movement_shortfall_gte_0",
            ),
        ]
        indexes = [
            models.Index(
                fields=["ingredient", "-created_at"],
                name="bar_sm_ing_created_idx",
            ),
            models.Index(
                fields=["movement_type", "-created_at"],
                name="bar_sm_type_created_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.movement_type} {self.ingredient.name} "
            f"({self.quantity_delta:+})"
        )


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
    )
    action = models.CharField(max_length=64, db_index=True)
    target_model = models.CharField(max_length=64, blank=True, default="")
    target_id = models.CharField(max_length=64, blank=True, default="")
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["action", "-created_at"],
                name="bar_audit_action_created_idx",
            ),
            models.Index(
                fields=["actor", "-created_at"],
                name="bar_audit_actor_created_idx",
            ),
        ]

    def __str__(self):
        return f"[{self.action}] {self.target_model}#{self.target_id}"
