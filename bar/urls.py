from django.urls import path

from .views import (
    index,
    DrinksCategoryListView,
    BarIngredientListView,
    BarSupplierListView,
    DrinksListView,
    BartenderListView,
    OrderListView,
    OrderDetailView,
    DrinkDetailView,
    BartenderDetailView,
    toggle_assign_order,
    DrinkCreateView,
    DrinkUpdateView,
    DrinkDeleteView,
    BartenderCreateView,
    BartenderStaffUpdateView,
    BartenderDeleteView,
)


urlpatterns = [
    path("", index, name="index"),
    path("drinks/", DrinksListView.as_view(), name="drink-list"),
    path("categories/", DrinksCategoryListView.as_view(), name="category-list"),
    path("suppliers/", BarSupplierListView.as_view(), name="supplier-list"),
    path("ingredients/", BarIngredientListView.as_view(), name="ingredient-list"),
    path("bartenders/", BartenderListView.as_view(), name="bartender-list"),
    path("orders/", OrderListView.as_view(), name="order-list"),
    path("orders/<int:pk>/", OrderDetailView.as_view(), name="order-detail"),
    path("drinks/<int:pk>/", DrinkDetailView.as_view(), name="drink-detail"),
    path("bartenders/<int:pk>/", BartenderDetailView.as_view(), name="bartender-detail"),
    path("orders/<int:pk>/toggle-assign/", toggle_assign_order, name="toggle-assign-order"),
    path("drinks/create/", DrinkCreateView.as_view(), name="drink-create"),
    path("drinks/<int:pk>/update/", DrinkUpdateView.as_view(), name="drink-update"),
    path("drinks/<int:pk>/delete/", DrinkDeleteView.as_view(), name="drink-delete"),
    path("bartenders/create/", BartenderCreateView.as_view(), name="bartender-create"),
    path("bartenders/<int:pk>/update/", BartenderStaffUpdateView.as_view(), name="bartender-update"),
    path("bartenders/<int:pk>/delete/", BartenderDeleteView.as_view(), name="bartender-delete"),
]

app_name = "bar"
