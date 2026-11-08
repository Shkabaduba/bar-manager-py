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
    num_bartenders = Bartender.objects.count()
    num_suppliers = BarSupplier.objects.count()
    num_ingredients = BarIngredient.objects.count()
    num_orders = Order.objects.count()

    num_visits = request.session.get("num_visits", 0)
    request.session["num_visits"] = num_visits + 1

    context = {
        "num_drinks": num_drinks,
        "num_categories": num_categories,
        "num_bartenders": num_bartenders,
        "num_suppliers": num_suppliers,
        "num_ingredients": num_ingredients,
        "num_orders": num_orders,
        "num_visits": num_visits + 1,
    }

    return render(request, "bar/index.html", context=context)
