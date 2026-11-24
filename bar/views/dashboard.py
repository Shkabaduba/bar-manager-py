from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from bar.services.analytics import get_dashboard_snapshot


@login_required
def index(request):
    """Render the main dashboard using the cached KPI snapshot."""
    snapshot = get_dashboard_snapshot()
    context = {
        "snapshot": snapshot,
        "num_drinks": snapshot.num_drinks,
        "num_categories": snapshot.num_categories,
        "active_orders": snapshot.active_orders,
        "out_of_stock_ingredients": snapshot.out_of_stock_ingredients,
        "num_visits": request.session.get("num_visits", 1),
    }
    return render(request, "bar/index.html", context=context)
