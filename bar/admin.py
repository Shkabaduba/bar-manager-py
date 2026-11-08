from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    BarIngredient,
    BarSupplier,
    Bartender,
    Drink,
    DrinksCategory,
    Order,
)


@admin.register(Bartender)
class BartenderAdmin(UserAdmin):
    list_display = UserAdmin.list_display + ("staff_id",)
    fieldsets = UserAdmin.fieldsets + (
        (("Additional info", {"fields": ("staff_id",)}),)
    )
    add_fieldsets = UserAdmin.add_fieldsets + (
        (
            (
                "Additional info",
                {
                    "fields": (
                        "first_name",
                        "last_name",
                        "staff_id",
                    )
                },
            ),
        )
    )


@admin.register(BarSupplier)
class BarSupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "phone", "email")
    search_fields = ("name",)


@admin.register(BarIngredient)
class BarIngredientAdmin(admin.ModelAdmin):
    list_display = ("name", "stock_quantity", "supplier")
    search_fields = ("name",)
    list_filter = ("supplier",)


@admin.register(DrinksCategory)
class DrinksCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "is_alcohol")
    list_filter = ("is_alcohol",)
    search_fields = ("name",)


@admin.register(Drink)
class DrinkAdmin(admin.ModelAdmin):
    list_display = ("name", "price", "volume_ml", "category")
    search_fields = ("name",)
    list_filter = ("category",)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("id", "table_number", "bartender", "is_paid", "created_at")
    list_filter = ("is_paid", "created_at")
    search_fields = ("table_number", "bartender__username")
