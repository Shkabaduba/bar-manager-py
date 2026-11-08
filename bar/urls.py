from django.urls import path

from .views import (
    index,
    DrinksCategoryListView,
    BarIngredientListView,
    BarSupplierListView,
    DrinksListView,
    BartenderListView,
    OrderListView,
)

urlpatterns = [
    path("", index, name="index"),
    path("drinks/", DrinksListView.as_view(), name="drink-list"),
    path("categories/", DrinksCategoryListView.as_view(), name="category-list"),
    path("suppliers/", BarSupplierListView.as_view(), name="supplier-list"),
    path("ingredients/", BarIngredientListView.as_view(), name="ingredient-list"),
    path("bartenders/", BartenderListView.as_view(), name="bartender-list"),
    path("orders/", OrderListView.as_view(), name="order-list"),
]

app_name = "bar"
