from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.views import generic

from .models import (
    BarIngredient,
    BarSupplier,
    Bartender,
    Drink,
    DrinksCategory,
    Order,
)


@login_required
def index(request):
    num_drinks = Drink.objects.count()
    num_categories = DrinksCategory.objects.count()
    out_of_stock_ingredients = BarIngredient.objects.filter(
        stock_quantity=0
    ).count()
    active_orders = Order.objects.filter(is_paid=False).count()

    num_visits = request.session.get("num_visits", 0)
    request.session["num_visits"] = num_visits + 1

    context = {
        "num_drinks": num_drinks,
        "num_categories": num_categories,
        "active_orders": active_orders,
        "out_of_stock_ingredients": out_of_stock_ingredients,
        "num_visits": num_visits + 1,
    }

    return render(request, "bar/index.html", context=context)


class DrinksCategoryListView(LoginRequiredMixin, generic.ListView):
    model = DrinksCategory
    context_object_name = "category_list"
    template_name = "bar/category_list.html"
    paginate_by = 5


class BarSupplierListView(LoginRequiredMixin, generic.ListView):
    model = BarSupplier
    context_object_name = "supplier_list"
    template_name = "bar/supplier_list.html"
    paginate_by = 5


class BarIngredientListView(LoginRequiredMixin, generic.ListView):
    model = BarIngredient
    context_object_name = "ingredient_list"
    template_name = "bar/ingredient_list.html"
    paginate_by = 5

    def get_queryset(self):
        queryset = BarIngredient.objects.select_related("supplier")
        return queryset


class DrinksListView(LoginRequiredMixin, generic.ListView):
    model = Drink
    context_object_name = "drink_list"
    template_name = "bar/drink_list.html"
    paginate_by = 5

    def get_queryset(self):
        queryset = Drink.objects.select_related("category")
        return queryset


class BartenderListView(LoginRequiredMixin, generic.ListView):
    model = Bartender
    context_object_name = "bartender_list"
    template_name = "bar/bartender_list.html"
    paginate_by = 5


class OrderListView(LoginRequiredMixin, generic.ListView):
    model = Order
    context_object_name = "order_list"
    template_name = "bar/order_list.html"
    paginate_by = 5

    def get_queryset(self):
        queryset = Order.objects.prefetch_related("drinks").select_related("bartender")
        return queryset
