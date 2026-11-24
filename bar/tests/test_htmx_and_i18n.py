from decimal import Decimal
import json
import re

from django.conf import settings
from django.contrib.staticfiles import finders
from django.core.cache import cache
from django.db import connection
from django.template.loader import render_to_string
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import translation
import polib

from bar.forms import DrinksCategoryForm
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
)
from bar.services.orders import (
    close_and_pay_order,
    create_order,
    set_order_item,
)


class HtmxPartialsAndInteractiveTests(TestCase):
    def setUp(self):
        cache.clear()
        self.manager = Bartender.objects.create_user(
            username="htmx_manager",
            password="test_password123",
            staff_id="HTMX_MGR1",
            role=Bartender.Role.MANAGER,
        )
        self.bartender = Bartender.objects.create_user(
            username="htmx_bartender",
            password="test_password123",
            staff_id="HTMX_BAR1",
            role=Bartender.Role.BARTENDER,
        )
        self.supplier = BarSupplier.objects.create(
            name="HTMX Spirits",
            phone="+380501112200",
        )
        self.category = DrinksCategory.objects.create(name="HTMX Classics")
        self.gin = BarIngredient.objects.create(
            name="HTMX Gin",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal("500.00"),
            cost_per_unit=Decimal("1.5000"),
            min_stock_threshold=Decimal("50.00"),
            supplier=self.supplier,
        )
        self.tonic = BarIngredient.objects.create(
            name="HTMX Tonic",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal("20.00"),
            cost_per_unit=Decimal("0.5000"),
            min_stock_threshold=Decimal("50.00"),
            supplier=self.supplier,
        )
        self.straight_gin = Drink.objects.create(
            name="HTMX Straight Gin",
            price=Decimal("200.00"),
            volume_ml=50,
            target_food_cost_pct=Decimal("25.00"),
            category=self.category,
        )
        DrinkIngredient.objects.create(
            drink=self.straight_gin,
            ingredient=self.gin,
            amount=Decimal("50.00"),
        )
        self.gin_tonic = Drink.objects.create(
            name="HTMX Gin Tonic",
            price=Decimal("250.00"),
            volume_ml=200,
            target_food_cost_pct=Decimal("25.00"),
            category=self.category,
        )
        DrinkIngredient.objects.create(
            drink=self.gin_tonic,
            ingredient=self.gin,
            amount=Decimal("50.00"),
        )
        DrinkIngredient.objects.create(
            drink=self.gin_tonic,
            ingredient=self.tonic,
            amount=Decimal("100.00"),
        )

    def tearDown(self):
        cache.clear()

    def test_all_list_views_serve_partials_unless_hx_boosted(self):
        self.client.force_login(self.manager)
        routes_and_regions = (
            ("bar:category-list", "category-list-region"),
            ("bar:supplier-list", "supplier-list-region"),
            ("bar:ingredient-list", "ingredient-list-region"),
            ("bar:drink-list", "drink-list-region"),
            ("bar:bartender-list", "bartender-list-region"),
            ("bar:order-list", "order-list-region"),
            ("bar:stock-movement-list", "stock-movement-list-region"),
            ("bar:audit-list", "audit-log-list-region"),
        )
        for route_name, region_id in routes_and_regions:
            partial_resp = self.client.get(
                reverse(route_name),
                HTTP_HX_REQUEST="true",
            )
            self.assertEqual(partial_resp.status_code, 200)
            partial_html = partial_resp.content.decode("utf-8")
            self.assertIn(f'id="{region_id}"', partial_html)
            self.assertNotIn("<!DOCTYPE", partial_html)
            self.assertNotIn("<html", partial_html)

            boosted_resp = self.client.get(
                reverse(route_name),
                HTTP_HX_REQUEST="true",
                HTTP_HX_BOOSTED="true",
            )
            self.assertEqual(boosted_resp.status_code, 200)
            boosted_html = boosted_resp.content.decode("utf-8")
            self.assertIn("<!DOCTYPE", boosted_html)
            self.assertIn(f'id="{region_id}"', boosted_html)

    def test_drawer_crud_oob_and_stock_writeoff_toast(self):
        self.client.force_login(self.manager)

        cat_form_resp = self.client.get(
            reverse("bar:category-create"),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(cat_form_resp.status_code, 200)
        cat_form_html = cat_form_resp.content.decode("utf-8")
        self.assertIn('hx-target="#drawer-body"', cat_form_html)
        self.assertNotIn("<!DOCTYPE", cat_form_html)

        cat_save_resp = self.client.post(
            reverse("bar:category-create"),
            data={"name": "HTMX Spritz", "is_alcohol": True},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(cat_save_resp.status_code, 200)
        cat_oob_html = cat_save_resp.content.decode("utf-8")
        self.assertIn(
            'hx-swap-oob="outerHTML:#category-list-region"',
            cat_oob_html,
        )
        self.assertIn(
            'id="kpi-num-categories" hx-swap-oob="true"',
            cat_oob_html,
        )
        cat_trigger = json.loads(cat_save_resp["HX-Trigger"])
        self.assertTrue(cat_trigger["closeDrawer"])
        self.assertTrue(cat_trigger["categoriesChanged"])
        self.assertEqual(cat_trigger["showToast"]["level"], "success")

        sup_save_resp = self.client.post(
            reverse("bar:supplier-create"),
            data={
                "name": "HTMX Wines",
                "phone": "+380501119988",
                "email": "wine@htmx.bar",
                "is_active": True,
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(sup_save_resp.status_code, 200)
        self.assertIn(
            'hx-swap-oob="outerHTML:#supplier-list-region"',
            sup_save_resp.content.decode("utf-8"),
        )
        sup_trigger = json.loads(sup_save_resp["HX-Trigger"])
        self.assertTrue(sup_trigger["suppliersChanged"])
        self.assertTrue(sup_trigger["closeDrawer"])

        ing_save_resp = self.client.post(
            reverse("bar:ingredient-create"),
            data={
                "name": "HTMX Vermouth",
                "unit": BarIngredient.Unit.ML,
                "min_stock_threshold": "100.00",
                "supplier": self.supplier.pk,
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(ing_save_resp.status_code, 200)
        self.assertIn(
            'hx-swap-oob="outerHTML:#ingredient-list-region"',
            ing_save_resp.content.decode("utf-8"),
        )
        ing_trigger = json.loads(ing_save_resp["HX-Trigger"])
        self.assertTrue(ing_trigger["ingredientsChanged"])

        stock_in_resp = self.client.post(
            reverse("bar:stock-in"),
            data={
                "ingredient": self.gin.pk,
                "quantity": "100.00",
                "unit_cost": "2.1000",
                "reason": "HTMX delivery",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(stock_in_resp.status_code, 200)
        self.assertIn(
            'hx-swap-oob="outerHTML:#stock-movement-list-region"',
            stock_in_resp.content.decode("utf-8"),
        )
        stock_trigger = json.loads(stock_in_resp["HX-Trigger"])
        self.assertTrue(stock_trigger["stockChanged"])
        self.gin.refresh_from_db()
        self.assertEqual(self.gin.stock_quantity, Decimal("600.00"))

        bad_writeoff = self.client.post(
            reverse("bar:stock-writeoff"),
            data={
                "ingredient": self.tonic.pk,
                "quantity": "500.00",
                "reason": "Over writeoff",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(bad_writeoff.status_code, 200)
        self.assertNotIn("<!DOCTYPE", bad_writeoff.content.decode("utf-8"))
        writeoff_trigger = json.loads(bad_writeoff["HX-Trigger"])
        self.assertEqual(writeoff_trigger["showToast"]["level"], "error")

        order_drawer_get = self.client.get(
            reverse("bar:order-create"),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(order_drawer_get.status_code, 200)
        self.assertNotIn("<!DOCTYPE", order_drawer_get.content.decode("utf-8"))

        order_drawer_post = self.client.post(
            reverse("bar:order-create"),
            data={"table_number": 33, "assign_to_me": "on"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(order_drawer_post.status_code, 204)
        created_order = Order.objects.get(table_number=33)
        self.assertEqual(
            order_drawer_post["HX-Redirect"],
            reverse("bar:order-detail", args=[created_order.pk]),
        )
        order_trigger = json.loads(order_drawer_post["HX-Trigger"])
        self.assertTrue(order_trigger["closeDrawer"])

    def test_pos_htmx_actions_deficit_force_close_and_cancel(self):
        order = create_order(table_number=7)
        self.client.force_login(self.bartender)

        assign_resp = self.client.post(
            reverse("bar:toggle-assign-order", args=[order.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(assign_resp.status_code, 200)
        assign_html = assign_resp.content.decode("utf-8")
        self.assertIn('id="order-pos-workspace"', assign_html)
        self.assertNotIn("<!DOCTYPE", assign_html)
        self.assertEqual(
            json.loads(assign_resp["HX-Trigger"])["showToast"]["level"],
            "success",
        )

        add_resp = self.client.post(
            reverse("bar:order-add-item", args=[order.pk]),
            data={"drink_id": self.straight_gin.pk, "delta": 1},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(add_resp.status_code, 200)
        self.assertEqual(
            OrderItem.objects.get(
                order=order,
                drink=self.straight_gin,
            ).quantity,
            1,
        )

        set_resp = self.client.post(
            reverse(
                "bar:order-set-item",
                args=[order.pk, self.straight_gin.pk],
            ),
            data={"quantity": 2},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(set_resp.status_code, 200)
        self.assertEqual(
            OrderItem.objects.get(
                order=order,
                drink=self.straight_gin,
            ).quantity,
            2,
        )

        remove_resp = self.client.post(
            reverse(
                "bar:order-remove-item",
                args=[order.pk, self.straight_gin.pk],
            ),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(remove_resp.status_code, 200)
        self.assertFalse(OrderItem.objects.filter(order=order).exists())

        self.client.post(
            reverse("bar:order-add-item", args=[order.pk]),
            data={"drink_id": self.straight_gin.pk, "delta": 1},
            HTTP_HX_REQUEST="true",
        )
        pay_ok = self.client.post(
            reverse("bar:order-pay", args=[order.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(pay_ok.status_code, 200)
        pay_ok_html = pay_ok.content.decode("utf-8")
        self.assertIn('id="kpi-active-orders" hx-swap-oob="true"', pay_ok_html)
        self.assertEqual(
            json.loads(pay_ok["HX-Trigger"])["showToast"]["level"],
            "success",
        )
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.PAID)

        shortage_order = create_order(
            table_number=19,
            bartender=self.bartender,
        )
        set_order_item(
            order_id=shortage_order.pk,
            drink_id=self.gin_tonic.pk,
            quantity=1,
        )
        bartender_deficit = self.client.post(
            reverse("bar:order-pay", args=[shortage_order.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(bartender_deficit.status_code, 409)
        self.assertEqual(
            bartender_deficit["HX-Retarget"],
            "#order-pos-workspace",
        )
        self.assertEqual(bartender_deficit["HX-Reswap"], "outerHTML")
        bartender_deficit_html = bartender_deficit.content.decode("utf-8")
        self.assertIn('id="order-deficit-panel"', bartender_deficit_html)
        self.assertNotIn('name="force_override"', bartender_deficit_html)
        self.assertEqual(
            json.loads(bartender_deficit["HX-Trigger"])["showToast"]["level"],
            "warning",
        )

        self.client.force_login(self.manager)
        manager_deficit = self.client.post(
            reverse("bar:order-pay", args=[shortage_order.pk]),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(manager_deficit.status_code, 409)
        self.assertIn(
            'name="force_override"',
            manager_deficit.content.decode("utf-8"),
        )

        force_ok = self.client.post(
            reverse("bar:order-pay", args=[shortage_order.pk]),
            data={
                "force_override": "1",
                "override_reason": "Reserved bar bottle",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(force_ok.status_code, 200)
        force_ok_html = force_ok.content.decode("utf-8")
        self.assertIn(
            'id="kpi-active-orders" hx-swap-oob="true"',
            force_ok_html,
        )
        self.assertEqual(
            json.loads(force_ok["HX-Trigger"])["showToast"]["level"],
            "success",
        )
        shortage_order.refresh_from_db()
        self.assertEqual(shortage_order.status, Order.Status.PAID)
        self.assertTrue(
            AuditLog.objects.filter(
                action="FORCE_CLOSE_ORDER",
                target_id=str(shortage_order.pk),
            ).exists()
        )

        cancel_order_obj = create_order(
            table_number=25,
            bartender=self.bartender,
        )
        self.client.force_login(self.bartender)
        cancel_resp = self.client.post(
            reverse("bar:order-cancel", args=[cancel_order_obj.pk]),
            data={"reason": "Customer changed mind"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(cancel_resp.status_code, 200)
        cancel_html = cancel_resp.content.decode("utf-8")
        self.assertIn('id="kpi-active-orders" hx-swap-oob="true"', cancel_html)
        self.assertEqual(
            json.loads(cancel_resp["HX-Trigger"])["showToast"]["level"],
            "success",
        )
        cancel_order_obj.refresh_from_db()
        self.assertEqual(cancel_order_obj.status, Order.Status.CANCELLED)

    def test_drink_calculator_template_preview_and_analytics_htmx(self):
        self.client.force_login(self.manager)
        create_page = self.client.get(reverse("bar:drink-create"))
        self.assertEqual(create_page.status_code, 200)
        create_html = create_page.content.decode("utf-8")
        self.assertIn('id="drink-costing-preview"', create_html)
        self.assertIn('id="empty-recipe-row-template"', create_html)

        preview_resp = self.client.post(
            reverse("bar:drink-costing-preview"),
            data={
                "price": "300.00",
                "target_food_cost_pct": "25.00",
                "recipe_items-TOTAL_FORMS": "1",
                "recipe_items-0-ingredient": str(self.gin.pk),
                "recipe_items-0-amount": "50.00",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(preview_resp.status_code, 200)
        preview_html = preview_resp.content.decode("utf-8")
        self.assertNotIn("<!DOCTYPE", preview_html)
        self.assertIn("HTMX Gin", preview_html)
        self.assertIn("75.00 ₴", preview_html)
        self.assertIn("100.00%", preview_html)

        analytics_resp = self.client.get(
            reverse("bar:analytics"),
            {"period": "30d"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(analytics_resp.status_code, 200)
        analytics_html = analytics_resp.content.decode("utf-8")
        self.assertIn('id="analytics-region"', analytics_html)
        self.assertIn("(30d)", analytics_html)
        self.assertNotIn("<!DOCTYPE", analytics_html)


class CyberBentoShellAndAssetsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.manager = Bartender.objects.create_user(
            username="bento_manager",
            password="test_password123",
            staff_id="BNT_MGR01",
            role=Bartender.Role.MANAGER,
        )
        self.bartender = Bartender.objects.create_user(
            username="bento_bar",
            password="test_password123",
            staff_id="BNT_BAR01",
            role=Bartender.Role.BARTENDER,
        )

    def tearDown(self):
        cache.clear()

    def test_static_bundle_files_exist_and_findable(self):
        static_assets = (
            "css/app.min.css",
            "css/animations.min.css",
            "css/tokens.css",
            "css/bento.css",
            "css/components.css",
            "css/animations.css",
            "js/htmx.min.js",
            "js/app.js",
            "img/cyber_bar_bg.jpg",
            "img/pixel_bar_logo.jpg",
            "img/cocktail_negroni.jpg",
            "img/cocktail_whiskey_sour.jpg",
            "img/cocktail_lemonade.jpg",
            "img/cocktail_signature.jpg",
            "img/cocktail_classic.jpg",
        )
        for asset_path in static_assets:
            disk_path = settings.BASE_DIR / "static" / asset_path
            self.assertTrue(disk_path.is_file(), f"Missing {disk_path}")
            self.assertIsNotNone(finders.find(asset_path))

    def test_shell_drops_cdns_and_enforces_strict_csp(self):
        login_resp = self.client.get(reverse("login"))
        self.assertEqual(login_resp.status_code, 200)
        login_html = login_resp.content.decode("utf-8")

        for asset_name in (
            "css/app.min.css",
            "css/animations.min.css",
            "data-async-style",
            'media="print"',
            "js/htmx.min.js",
            "js/app.js",
        ):
            self.assertIn(asset_name, login_html)

        self.assertNotIn("onload=", login_html.lower())
        self.assertNotIn("cdn.tailwindcss.com", login_html)
        self.assertNotIn("cdn.jsdelivr.net", login_html)
        self.assertIn(reverse("set_language"), login_html)
        script_tags = re.findall(
            r"<script\b[^>]*>",
            login_html,
            flags=re.IGNORECASE,
        )
        self.assertTrue(script_tags)
        for script_tag in script_tags:
            self.assertIn("src=", script_tag)

        app_csp = login_resp["Content-Security-Policy"]
        self.assertIn("script-src 'self';", app_csp)
        self.assertNotIn("cdn.tailwindcss.com", app_csp)

        self.client.force_login(self.manager)
        index_resp = self.client.get(reverse("bar:index"))
        self.assertEqual(index_resp.status_code, 200)
        self.assertIn(
            "script-src 'self';",
            index_resp["Content-Security-Policy"],
        )

        admin_resp = self.client.get("/admin/login/")
        self.assertEqual(admin_resp.status_code, 200)
        self.assertIn(
            "'unsafe-eval'",
            admin_resp["Content-Security-Policy"],
        )

    def test_role_aware_sidebar_and_bento_dashboard(self):
        self.client.force_login(self.bartender)
        bar_resp = self.client.get(reverse("bar:index"))
        self.assertEqual(bar_resp.status_code, 200)
        bar_html = bar_resp.content.decode("utf-8")
        self.assertIn('id="kpi-active-orders"', bar_html)
        self.assertIn('id="kpi-num-drinks"', bar_html)
        self.assertIn('id="kpi-out-of-stock"', bar_html)
        self.assertIn('id="kpi-num-categories"', bar_html)
        self.assertIn(reverse("set_language"), bar_html)
        self.assertNotIn(reverse("bar:analytics"), bar_html)
        self.assertNotIn(reverse("bar:audit-list"), bar_html)
        self.assertNotIn(reverse("bar:stock-movement-list"), bar_html)
        self.assertNotIn("Today Shift Financial Pulse", bar_html)

        self.client.force_login(self.manager)
        mgr_resp = self.client.get(reverse("bar:index"))
        self.assertEqual(mgr_resp.status_code, 200)
        mgr_html = mgr_resp.content.decode("utf-8")
        self.assertIn(reverse("bar:analytics"), mgr_html)
        self.assertIn(reverse("bar:audit-list"), mgr_html)
        self.assertIn(reverse("bar:stock-movement-list"), mgr_html)
        self.assertIn("Today Shift Financial Pulse", mgr_html)

    def test_logged_out_403_and_form_fields_partial_rendering(self):
        self.client.force_login(self.bartender)
        forbidden_resp = self.client.get(reverse("bar:drink-create"))
        self.assertEqual(forbidden_resp.status_code, 403)
        forbidden_html = forbidden_resp.content.decode("utf-8")
        self.assertIn("403", forbidden_html)
        self.assertIn("Back to Dashboard", forbidden_html)

        logged_out_html = render_to_string("registration/logged_out.html")
        self.assertIn("Shift Ended", logged_out_html)
        self.assertIn(reverse("login"), logged_out_html)

        invalid_form = DrinksCategoryForm(
            data={"name": "", "is_alcohol": True}
        )
        self.assertFalse(invalid_form.is_valid())
        rendered_fields = render_to_string(
            "includes/form_fields.html",
            {"form": invalid_form},
        )
        self.assertIn('class="field-group"', rendered_fields)
        self.assertIn('class="field-checkbox-row"', rendered_fields)
        self.assertIn('class="field-error"', rendered_fields)

    def test_crispy_forms_removed_from_settings_and_all_templates(self):
        self.assertNotIn("crispy_forms", settings.INSTALLED_APPS)
        self.assertNotIn("crispy_bootstrap4", settings.INSTALLED_APPS)
        self.assertFalse(hasattr(settings, "CRISPY_TEMPLATE_PACK"))
        templates_dir = settings.BASE_DIR / "templates"
        for template_file in templates_dir.rglob("*.html"):
            content = template_file.read_text(encoding="utf-8")
            self.assertNotIn(
                "crispy",
                content,
                f"Unexpected crispy reference in {template_file}",
            )

    def test_all_cyber_bento_pages_and_svg_chart_render(self):
        owner = Bartender.objects.create_user(
            username="bento_owner",
            password="test_password123",
            staff_id="BNT_OWN01",
            role=Bartender.Role.OWNER,
        )
        supplier = BarSupplier.objects.create(
            name="Bento Wines",
            phone="+380501112233",
        )
        category = DrinksCategory.objects.create(name="Bento Cocktails")
        ingredient = BarIngredient.objects.create(
            name="Bento Gin",
            unit=BarIngredient.Unit.ML,
            stock_quantity=Decimal("500.00"),
            cost_per_unit=Decimal("1.5000"),
            supplier=supplier,
        )
        drink = Drink.objects.create(
            name="Bento Martini",
            price=Decimal("240.00"),
            volume_ml=90,
            category=category,
        )
        DrinkIngredient.objects.create(
            drink=drink,
            ingredient=ingredient,
            amount=Decimal("60.00"),
        )
        order = create_order(table_number=5, bartender=self.bartender)
        set_order_item(order_id=order.pk, drink_id=drink.pk, quantity=1)

        self.client.force_login(owner)
        empty_analytics = self.client.get(reverse("bar:analytics"))
        self.assertEqual(empty_analytics.status_code, 200)
        empty_html = empty_analytics.content.decode("utf-8")
        self.assertIn("<svg", empty_html)
        self.assertNotIn('class="bar-revenue"', empty_html)

        with self.captureOnCommitCallbacks(execute=True):
            close_and_pay_order(order_id=order.pk, actor=self.bartender)
        paid_analytics = self.client.get(
            reverse("bar:analytics"),
            {"period": "7d"},
        )
        self.assertEqual(paid_analytics.status_code, 200)
        paid_html = paid_analytics.content.decode("utf-8")
        self.assertIn("<svg", paid_html)
        self.assertIn('class="bar-revenue"', paid_html)

        calc_resp = self.client.get(reverse("bar:drink-create"))
        self.assertEqual(calc_resp.status_code, 200)
        calc_html = calc_resp.content.decode("utf-8")
        self.assertIn("data-add-recipe-row", calc_html)
        self.assertIn('id="empty-recipe-row-template"', calc_html)

        page_urls = (
            reverse("bar:category-create"),
            reverse("bar:supplier-create"),
            reverse("bar:ingredient-create"),
            reverse("bar:bartender-create"),
            reverse("bar:order-create"),
            reverse("bar:stock-in"),
            reverse("bar:stock-writeoff"),
            reverse("bar:stock-adjustment"),
            reverse("bar:drink-detail", args=[drink.pk]),
            reverse("bar:order-detail", args=[order.pk]),
            reverse("bar:category-delete", args=[category.pk]),
            reverse("bar:supplier-delete", args=[supplier.pk]),
            reverse("bar:ingredient-delete", args=[ingredient.pk]),
            reverse("bar:drink-delete", args=[drink.pk]),
            reverse("bar:bartender-delete", args=[self.bartender.pk]),
        )
        for target_url in page_urls:
            resp = self.client.get(target_url)
            self.assertEqual(resp.status_code, 200, f"Failed {target_url}")

    def test_bartender_detail_eliminates_extra_orders_count_query(self):
        category = DrinksCategory.objects.create(name="Query Category")
        drink = Drink.objects.create(
            name="Query Spritz",
            price=Decimal("180.00"),
            volume_ml=200,
            category=category,
        )
        order = create_order(table_number=3, bartender=self.bartender)
        set_order_item(order_id=order.pk, drink_id=drink.pk, quantity=1)
        close_and_pay_order(order_id=order.pk, actor=self.bartender)

        self.client.force_login(self.manager)
        with CaptureQueriesContext(connection) as query_ctx:
            detail_resp = self.client.get(
                reverse("bar:bartender-detail", args=[self.bartender.pk])
            )
        self.assertEqual(detail_resp.status_code, 200)
        detail_html = detail_resp.content.decode("utf-8")
        self.assertIn("1 paid checks", detail_html)
        self.assertIn("180.00 ₴", detail_html)
        extra_count_queries = [
            query["sql"]
            for query in query_ctx.captured_queries
            if 'FROM "bar_order"' in query["sql"]
            and "COUNT(" in query["sql"]
            and '"bar_bartender"' not in query["sql"]
        ]
        self.assertEqual(extra_count_queries, [])

    def test_uah_currency_pixel_art_and_button_hover_css(self):
        category = DrinksCategory.objects.create(name="Signature Cocktails")
        drink = Drink.objects.create(
            name="Classic Negroni",
            price=Decimal("360.00"),
            volume_ml=90,
            category=category,
        )
        order = create_order(table_number=7, bartender=self.bartender)
        set_order_item(order_id=order.pk, drink_id=drink.pk, quantity=1)

        self.client.force_login(self.manager)
        urls_with_expected = (
            (
                reverse("bar:index"),
                ("cyber_bar_bg.jpg", "pixel_bar_logo.jpg", "₴"),
            ),
            (
                reverse("bar:drink-list"),
                ("cocktail_negroni.jpg", "360.00 ₴"),
            ),
            (
                reverse("bar:drink-detail", args=[drink.pk]),
                ("cocktail_negroni.jpg", "360.00 ₴"),
            ),
            (
                reverse("bar:order-detail", args=[order.pk]),
                ("cocktail_negroni.jpg", "360.00 ₴"),
            ),
            (reverse("bar:analytics"), ("₴",)),
        )
        for target_url, expected_tokens in urls_with_expected:
            response = self.client.get(target_url)
            self.assertEqual(response.status_code, 200)
            html = response.content.decode("utf-8")
            self.assertIsNone(re.search(r"\$\d", html), f"$ in {target_url}")
            for token in expected_tokens:
                self.assertIn(token, html)

        css_path = settings.BASE_DIR / "static" / "css" / "components.css"
        css_text = css_path.read_text(encoding="utf-8")
        min_css_path = settings.BASE_DIR / "static" / "css" / "app.min.css"
        min_css_text = min_css_path.read_text(encoding="utf-8")
        for selector in (
            ".btn.btn-primary:hover",
            ".btn.btn-success:hover",
            ".btn.btn-warning:hover",
            ".btn.btn-error:hover",
            ".btn.btn-info:hover",
        ):
            self.assertIn(selector, css_text)
        self.assertIn(".btn.btn-primary:hover", min_css_text)
        self.assertIn(".btn.btn-success:hover", min_css_text)

        bento_path = settings.BASE_DIR / "static" / "css" / "bento.css"
        bento_text = bento_path.read_text(encoding="utf-8")
        app_shell_match = re.search(
            r"\.app-shell\s*\{([^}]*)\}",
            bento_text,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(app_shell_match)
        self.assertNotIn("z-index:", app_shell_match.group(1))
        backdrop_match = re.search(
            r"\.sidebar-backdrop\s*\{([^}]*)\}",
            bento_text,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(backdrop_match)
        self.assertIn("cursor: pointer;", backdrop_match.group(1))

        index_html = self.client.get(reverse("bar:index")).content.decode(
            "utf-8"
        )
        self.assertIn("data-sidebar-close", index_html)
        self.assertIn('<header class="site-header">', index_html)
        self.assertIn('<footer class="site-footer">', index_html)

        anon_client = self.client_class()
        login_resp = anon_client.get(reverse("login"))
        self.assertEqual(login_resp.status_code, 200)
        login_html = login_resp.content.decode("utf-8")
        self.assertIn("data-login-canvas", login_html)

        forbidden_symbols = ("🍸", "🏆", "🧮", "⬇", "⚠", "☰", "✕", "✓")
        for target_url in (
            reverse("bar:index"),
            reverse("bar:analytics"),
            reverse("bar:drink-create"),
            reverse("bar:order-detail", args=[order.pk]),
        ):
            page_html = self.client.get(target_url).content.decode("utf-8")
            for symbol in forbidden_symbols:
                self.assertNotIn(
                    symbol,
                    page_html,
                    f"Unexpected symbol {symbol!r} in {target_url}",
                )


class LocalizationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.manager = Bartender.objects.create_user(
            username="i18n_manager",
            password="test_password123",
            staff_id="I18N_MGR1",
            role=Bartender.Role.MANAGER,
        )
        self.bartender = Bartender.objects.create_user(
            username="i18n_bartender",
            password="test_password123",
            staff_id="I18N_BAR1",
            role=Bartender.Role.BARTENDER,
        )

    def tearDown(self):
        cache.clear()

    def test_uk_po_and_mo_catalog_complete_and_placeholders_match(self):
        locale_dir = (
            settings.BASE_DIR / "locale" / "uk" / "LC_MESSAGES"
        )
        po_path = locale_dir / "django.po"
        mo_path = locale_dir / "django.mo"
        self.assertTrue(po_path.is_file())
        self.assertTrue(mo_path.is_file())

        po_file = polib.pofile(str(po_path))
        self.assertGreater(len(po_file), 250)
        placeholder_re = re.compile(r"%\([a-zA-Z0-9_]+\)s")
        for entry in po_file:
            self.assertTrue(
                entry.msgstr.strip(),
                f"Empty translation for {entry.msgid!r}",
            )
            self.assertEqual(
                set(placeholder_re.findall(entry.msgid)),
                set(placeholder_re.findall(entry.msgstr)),
                f"Mismatched placeholders in {entry.msgid!r}",
            )

        with translation.override("uk"):
            self.assertEqual(translation.gettext("Dashboard"), "Дашборд")
            self.assertEqual(
                translation.gettext("Orders (POS)"),
                "Замовлення (POS)",
            )
            self.assertEqual(
                translation.gettext("Food Cost %"),
                "Food Cost %",
            )
            self.assertEqual(
                translation.gettext("Table %(num)s"),
                "Стіл %(num)s",
            )
            self.assertEqual(
                translation.gettext("Access Denied"),
                "Доступ заборонено",
            )

    def test_set_language_switches_en_uk_and_persists_cookie(self):
        self.client.force_login(self.bartender)

        uk_resp = self.client.post(
            reverse("set_language"),
            data={"language": "uk", "next": reverse("bar:index")},
        )
        self.assertEqual(uk_resp.status_code, 302)
        lang_cookie = uk_resp.cookies[settings.LANGUAGE_COOKIE_NAME]
        self.assertEqual(lang_cookie.value, "uk")
        self.assertTrue(lang_cookie["httponly"])
        self.assertEqual(lang_cookie["samesite"], "Lax")

        dash_uk = self.client.get(reverse("bar:index"))
        self.assertEqual(dash_uk.status_code, 200)
        dash_uk_html = dash_uk.content.decode("utf-8")
        self.assertIn('<html lang="uk"', dash_uk_html)
        self.assertIn("Панель керування баром", dash_uk_html)
        self.assertIn("Активні замовлення", dash_uk_html)
        self.assertIn("Залишки складу", dash_uk_html)

        en_resp = self.client.post(
            reverse("set_language"),
            data={"language": "en", "next": reverse("bar:index")},
        )
        self.assertEqual(en_resp.status_code, 302)
        dash_en = self.client.get(reverse("bar:index"))
        dash_en_html = dash_en.content.decode("utf-8")
        self.assertIn('<html lang="en"', dash_en_html)
        self.assertIn("Bar Manager Dashboard", dash_en_html)

    def test_uk_locale_renders_login_analytics_pos_and_403_cleanly(self):
        order = create_order(table_number=4, bartender=self.bartender)
        self.client.cookies[settings.LANGUAGE_COOKIE_NAME] = "uk"

        login_uk = self.client.get(reverse("login"))
        self.assertEqual(login_uk.status_code, 200)
        self.assertIn(
            "Увійдіть, щоб розпочати зміну",
            login_uk.content.decode("utf-8"),
        )

        self.client.force_login(self.bartender)
        forbidden_uk = self.client.get(reverse("bar:drink-create"))
        self.assertEqual(forbidden_uk.status_code, 403)
        self.assertIn(
            "Доступ заборонено",
            forbidden_uk.content.decode("utf-8"),
        )

        pos_uk = self.client.get(
            reverse("bar:order-detail", args=[order.pk])
        )
        self.assertEqual(pos_uk.status_code, 200)
        self.assertIn("Зведення чека", pos_uk.content.decode("utf-8"))

        self.client.force_login(self.manager)
        analytics_uk = self.client.get(reverse("bar:analytics"))
        self.assertEqual(analytics_uk.status_code, 200)
        self.assertIn(
            "Щоденний прихід та витрати",
            analytics_uk.content.decode("utf-8"),
        )
