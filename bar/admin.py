from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from unfold.admin import ModelAdmin, TabularInline
from unfold.forms import (
    AdminPasswordChangeForm,
    UserChangeForm,
    UserCreationForm,
)

from bar.models import (
    AuditLog,
    BarIngredient,
    BarSupplier,
    Bartender,
    Drink,
    DrinkIngredient,
    DrinksCategory,
    Order,
    OrderItem,
    StockMovement,
)
from bar.permissions import sync_bartender_group


@admin.register(Bartender)
class BartenderAdmin(UserAdmin, ModelAdmin):
    form = UserChangeForm
    add_form = UserCreationForm
    change_password_form = AdminPasswordChangeForm

    list_display = UserAdmin.list_display + ("staff_id", "role")
    list_filter = UserAdmin.list_filter + ("role",)
    fieldsets = UserAdmin.fieldsets + (
        ("Additional info", {"fields": ("staff_id", "role")}),
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            "Additional info",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "staff_id",
                    "role",
                )
            },
        ),
    )

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        sync_bartender_group(form.instance)


@admin.register(BarSupplier)
class BarSupplierAdmin(ModelAdmin):
    list_display = ("name", "phone", "email", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "phone")


@admin.register(BarIngredient)
class BarIngredientAdmin(ModelAdmin):
    list_display = (
        "name",
        "unit",
        "stock_quantity",
        "cost_per_unit",
        "min_stock_threshold",
        "supplier",
    )
    list_filter = ("unit", "supplier")
    search_fields = ("name",)
    readonly_fields = ("stock_quantity", "cost_per_unit")


@admin.register(DrinksCategory)
class DrinksCategoryAdmin(ModelAdmin):
    list_display = ("name", "is_alcohol")
    list_filter = ("is_alcohol",)
    search_fields = ("name",)


class DrinkIngredientInline(TabularInline):
    model = DrinkIngredient
    extra = 1
    autocomplete_fields = ("ingredient",)


@admin.register(Drink)
class DrinkAdmin(ModelAdmin):
    list_display = (
        "name",
        "category",
        "price",
        "volume_ml",
        "target_food_cost_pct",
        "is_active",
    )
    search_fields = ("name",)
    list_filter = ("category", "is_active")
    inlines = [DrinkIngredientInline]


class OrderItemInline(TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("unit_price_snapshot", "unit_cost_snapshot")


@admin.register(Order)
class OrderAdmin(ModelAdmin):
    list_display = (
        "id",
        "table_number",
        "status",
        "bartender",
        "total_revenue_snapshot",
        "total_cost_snapshot",
        "paid_at",
        "created_at",
    )
    list_filter = ("status", "is_paid", "created_at")
    search_fields = ("table_number", "bartender__username")
    readonly_fields = (
        "version",
        "paid_at",
        "total_revenue_snapshot",
        "total_cost_snapshot",
        "closed_by",
        "override_by",
    )
    inlines = [OrderItemInline]


class ReadOnlyLedgerAdmin(ModelAdmin):
    """Base admin for immutable append-only ledger and audit models."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyLedgerAdmin):
    list_display = (
        "created_at",
        "movement_type",
        "ingredient",
        "quantity_delta",
        "balance_after",
        "total_cost",
        "shortfall_quantity",
        "performed_by",
    )
    list_filter = ("movement_type", "created_at")
    search_fields = ("ingredient__name", "reason", "performed_by__username")
    list_select_related = ("ingredient", "performed_by", "order")


@admin.register(AuditLog)
class AuditLogAdmin(ReadOnlyLedgerAdmin):
    list_display = (
        "created_at",
        "action",
        "actor",
        "target_model",
        "target_id",
        "ip_address",
    )
    list_filter = ("action", "created_at")
    search_fields = (
        "action",
        "target_model",
        "target_id",
        "actor__username",
    )
    list_select_related = ("actor",)
