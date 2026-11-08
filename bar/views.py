from django.shortcuts import render
from django.contrib.auth.decorators import login_required

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
