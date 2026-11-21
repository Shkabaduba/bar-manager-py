from decimal import Decimal
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Group
from django.core.cache import cache
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from bar.models import (
    AuditLog,
    BarIngredient,
    BarSupplier,
    Bartender,
    Order,
)
from bar.permissions import (
    StaffActionNotAllowedError,
    role_required,
    validate_can_change_role,
    validate_can_delete_bartender,
)


class PublicViewTests(TestCase):
    def test_login_required(self):
        urls = [
            reverse("bar:index"),
            reverse("bar:bartender-list"),
            reverse("bar:drink-list"),
            reverse("bar:category-list"),
            reverse("bar:order-list"),
            reverse("bar:supplier-list"),
        ]
        for target_url in urls:
            response = self.client.get(target_url)
            self.assertNotEqual(response.status_code, 200)


class SecurityMiddlewareTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_security_headers_present_on_responses(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        csp_header = response["Content-Security-Policy"]
        self.assertIn("default-src 'self'", csp_header)
        self.assertIn("frame-ancestors 'none'", csp_header)
        self.assertIn("camera=()", response["Permissions-Policy"])
        self.assertEqual(response["Referrer-Policy"], "same-origin")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response["X-Frame-Options"], "DENY")

    @override_settings(RATE_LIMIT_LOGIN_MAX=3, RATE_LIMIT_LOGIN_WINDOW=60)
    def test_login_rate_limit_blocks_after_threshold(self):
        login_url = reverse("login")
        for _ in range(3):
            response = self.client.post(
                login_url,
                {"username": "nobody", "password": "wrong"},
            )
            self.assertNotEqual(response.status_code, 429)

        with self.assertLogs("bar.middleware", level="WARNING"):
            blocked_response = self.client.post(
                login_url,
                {"username": "nobody", "password": "wrong"},
            )
        self.assertEqual(blocked_response.status_code, 429)
        self.assertEqual(blocked_response["Retry-After"], "60")
        self.assertIn("Content-Security-Policy", blocked_response)

    @override_settings(
        RATE_LIMIT_MUTATION_MAX=2,
        RATE_LIMIT_MUTATION_WINDOW=60,
    )
    def test_get_requests_are_not_rate_limited(self):
        login_url = reverse("login")
        for _ in range(5):
            response = self.client.get(login_url)
            self.assertEqual(response.status_code, 200)

    @override_settings(
        RATE_LIMIT_MUTATION_MAX=2,
        RATE_LIMIT_MUTATION_WINDOW=60,
    )
    def test_mutation_rate_limit_isolates_authenticated_users(self):
        user_one = get_user_model().objects.create_user(
            username="bartender_one",
            password="test_password123",
            staff_id="STAFF_001",
        )
        user_two = get_user_model().objects.create_user(
            username="bartender_two",
            password="test_password123",
            staff_id="STAFF_002",
        )
        set_lang_url = reverse("set_language")

        self.client.force_login(user_one)
        for _ in range(2):
            response = self.client.post(set_lang_url, {"language": "uk"})
            self.assertNotEqual(response.status_code, 429)

        with self.assertLogs("bar.middleware", level="WARNING"):
            blocked_response = self.client.post(
                set_lang_url,
                {"language": "uk"},
            )
        self.assertEqual(blocked_response.status_code, 429)

        self.client.force_login(user_two)
        second_user_response = self.client.post(
            set_lang_url,
            {"language": "uk"},
        )
        self.assertEqual(second_user_response.status_code, 302)

    @override_settings(RATE_LIMIT_LOGIN_MAX=1, RATE_LIMIT_LOGIN_WINDOW=60)
    def test_htmx_rate_limit_includes_hx_trigger_header(self):
        login_url = reverse("login")
        first_response = self.client.post(
            login_url,
            {"username": "nobody", "password": "wrong"},
        )
        self.assertNotEqual(first_response.status_code, 429)

        with self.assertLogs("bar.middleware", level="WARNING"):
            blocked_response = self.client.post(
                login_url,
                {"username": "nobody", "password": "wrong"},
                HTTP_HX_REQUEST="true",
            )
        self.assertEqual(blocked_response.status_code, 429)
        trigger_data = json.loads(blocked_response["HX-Trigger"])
        self.assertEqual(trigger_data["showToast"]["level"], "error")

    def test_client_ip_trusts_forwarded_header_only_when_configured(self):
        login_url = reverse("login")
        with override_settings(
            RATE_LIMIT_LOGIN_MAX=1,
            RATE_LIMIT_LOGIN_WINDOW=60,
            RATE_LIMIT_TRUST_X_FORWARDED_FOR=False,
        ):
            first_response = self.client.post(
                login_url,
                {"username": "nobody", "password": "wrong"},
                HTTP_X_FORWARDED_FOR="1.1.1.1",
            )
            self.assertNotEqual(first_response.status_code, 429)

            with self.assertLogs("bar.middleware", level="WARNING"):
                second_response = self.client.post(
                    login_url,
                    {"username": "nobody", "password": "wrong"},
                    HTTP_X_FORWARDED_FOR="2.2.2.2",
                )
            self.assertEqual(second_response.status_code, 429)

        cache.clear()
        with override_settings(
            RATE_LIMIT_LOGIN_MAX=1,
            RATE_LIMIT_LOGIN_WINDOW=60,
            RATE_LIMIT_TRUST_X_FORWARDED_FOR=True,
        ):
            first_response = self.client.post(
                login_url,
                {"username": "nobody", "password": "wrong"},
                HTTP_X_FORWARDED_FOR="1.1.1.1",
            )
            self.assertNotEqual(first_response.status_code, 429)

            second_response = self.client.post(
                login_url,
                {"username": "nobody", "password": "wrong"},
                HTTP_X_FORWARDED_FOR="2.2.2.2",
            )
            self.assertNotEqual(second_response.status_code, 429)


class RBACPermissionsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.owner = Bartender.objects.create_user(
            username="rbac_owner",
            password="test_password123",
            staff_id="RBAC_OWN1",
            role=Bartender.Role.OWNER,
        )
        self.manager = Bartender.objects.create_user(
            username="rbac_manager",
            password="test_password123",
            staff_id="RBAC_MGR1",
            role=Bartender.Role.MANAGER,
        )
        self.bartender = Bartender.objects.create_user(
            username="rbac_bartender",
            password="test_password123",
            staff_id="RBAC_BAR1",
            role=Bartender.Role.BARTENDER,
        )

    def tearDown(self):
        cache.clear()

    def test_bartender_can_view_and_assign_but_cannot_manage_catalog(self):
        order = Order.objects.create(table_number=10)
        self.client.force_login(self.bartender)

        allowed_list_urls = [
            reverse("bar:index"),
            reverse("bar:drink-list"),
            reverse("bar:category-list"),
            reverse("bar:supplier-list"),
            reverse("bar:ingredient-list"),
            reverse("bar:bartender-list"),
            reverse("bar:order-list"),
        ]
        for target_url in allowed_list_urls:
            response = self.client.get(target_url)
            self.assertEqual(response.status_code, 200)

        assign_response = self.client.post(
            reverse("bar:toggle-assign-order", args=[order.pk])
        )
        self.assertEqual(assign_response.status_code, 302)

        forbidden_urls = [
            reverse("bar:drink-create"),
            reverse("bar:category-create"),
            reverse("bar:supplier-create"),
            reverse("bar:ingredient-create"),
            reverse("bar:bartender-create"),
            reverse("bar:bartender-update", args=[self.bartender.pk]),
            reverse("bar:bartender-delete", args=[self.bartender.pk]),
        ]
        for target_url in forbidden_urls:
            response = self.client.get(target_url)
            self.assertEqual(response.status_code, 403)

    def test_manager_can_manage_catalog_but_cannot_manage_staff(self):
        self.client.force_login(self.manager)

        manager_urls = [
            reverse("bar:drink-create"),
            reverse("bar:category-create"),
            reverse("bar:supplier-create"),
            reverse("bar:ingredient-create"),
        ]
        for target_url in manager_urls:
            response = self.client.get(target_url)
            self.assertEqual(response.status_code, 200)

        staff_urls = [
            reverse("bar:bartender-create"),
            reverse("bar:bartender-update", args=[self.bartender.pk]),
            reverse("bar:bartender-delete", args=[self.bartender.pk]),
        ]
        for target_url in staff_urls:
            response = self.client.get(target_url)
            self.assertEqual(response.status_code, 403)

    def test_owner_staff_crud_syncs_groups_and_writes_audit_log(self):
        self.client.force_login(self.owner)
        create_response = self.client.post(
            reverse("bar:bartender-create"),
            data={
                "username": "new_staff_member",
                "staff_id": "NEW_STAF1",
                "first_name": "Alex",
                "last_name": "Bar",
                "password1": "StrongPass123!",
                "password2": "StrongPass123!",
            },
        )
        self.assertEqual(create_response.status_code, 302)

        created_user = Bartender.objects.get(username="new_staff_member")
        self.assertEqual(created_user.role, Bartender.Role.BARTENDER)
        self.assertTrue(
            created_user.groups.filter(name="Bartenders").exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="STAFF_CREATED",
                target_id=str(created_user.pk),
            ).exists()
        )

        update_response = self.client.post(
            reverse("bar:bartender-update", args=[created_user.pk]),
            data={
                "staff_id": "NEW_STAF1",
                "role": Bartender.Role.MANAGER,
            },
        )
        self.assertEqual(update_response.status_code, 302)

        created_user.refresh_from_db()
        self.assertEqual(created_user.role, Bartender.Role.MANAGER)
        self.assertTrue(created_user.groups.filter(name="Managers").exists())
        self.assertFalse(
            created_user.groups.filter(name="Bartenders").exists()
        )
        self.assertTrue(Group.objects.filter(name="Managers").exists())
        self.assertTrue(
            AuditLog.objects.filter(
                action="STAFF_ROLE_UPDATED",
                target_id=str(created_user.pk),
            ).exists()
        )

    def test_owner_cannot_delete_self_or_demote_self(self):
        self.client.force_login(self.owner)

        delete_response = self.client.post(
            reverse("bar:bartender-delete", args=[self.owner.pk])
        )
        self.assertEqual(delete_response.status_code, 403)
        self.assertTrue(Bartender.objects.filter(pk=self.owner.pk).exists())

        demote_response = self.client.post(
            reverse("bar:bartender-update", args=[self.owner.pk]),
            data={
                "staff_id": self.owner.staff_id,
                "role": Bartender.Role.BARTENDER,
            },
        )
        self.assertEqual(demote_response.status_code, 403)
        self.owner.refresh_from_db()
        self.assertEqual(self.owner.role, Bartender.Role.OWNER)

    def test_cannot_delete_or_demote_last_active_owner(self):
        second_owner = Bartender.objects.create_user(
            username="second_owner",
            password="test_password123",
            staff_id="RBAC_OWN2",
            role=Bartender.Role.OWNER,
        )
        self.client.force_login(self.owner)

        delete_second_response = self.client.post(
            reverse("bar:bartender-delete", args=[second_owner.pk])
        )
        self.assertEqual(delete_second_response.status_code, 302)
        self.assertFalse(
            Bartender.objects.filter(pk=second_owner.pk).exists()
        )
        self.assertTrue(
            AuditLog.objects.filter(
                action="STAFF_DELETED",
                target_id=str(second_owner.pk),
            ).exists()
        )

        with self.assertRaises(StaffActionNotAllowedError):
            validate_can_delete_bartender(self.manager, self.owner)
        with self.assertRaises(StaffActionNotAllowedError):
            validate_can_change_role(
                self.manager,
                self.owner,
                Bartender.Role.MANAGER,
            )

    def test_htmx_forbidden_returns_403_with_hx_trigger_toast(self):
        self.client.force_login(self.bartender)
        response = self.client.get(
            reverse("bar:drink-create"),
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 403)
        trigger_payload = json.loads(response["HX-Trigger"])
        self.assertEqual(trigger_payload["showToast"]["level"], "error")

    def test_role_required_decorator_anonymous_and_roles(self):
        @role_required(Bartender.Role.MANAGER)
        def protected_endpoint(request):
            return HttpResponse("ok")

        factory = RequestFactory()

        anonymous_request = factory.get("/protected/")
        anonymous_request.user = AnonymousUser()
        anonymous_response = protected_endpoint(anonymous_request)
        self.assertEqual(anonymous_response.status_code, 302)
        self.assertIn("/accounts/login/", anonymous_response["Location"])

        bartender_request = factory.get("/protected/")
        bartender_request.user = self.bartender
        bartender_response = protected_endpoint(bartender_request)
        self.assertEqual(bartender_response.status_code, 403)

        manager_request = factory.get("/protected/")
        manager_request.user = self.manager
        manager_response = protected_endpoint(manager_request)
        self.assertEqual(manager_response.status_code, 200)

        superuser = Bartender.objects.create_superuser(
            username="rbac_superuser",
            password="test_password123",
            staff_id="RBAC_SUP1",
        )
        superuser_request = factory.get("/protected/")
        superuser_request.user = superuser
        superuser_response = protected_endpoint(superuser_request)
        self.assertEqual(superuser_response.status_code, 200)

    def test_protected_delete_and_login_blocked_audit_log(self):
        supplier = BarSupplier.objects.create(
            name="Referenced Supplier",
            phone="+380501112299",
        )
        BarIngredient.objects.create(
            name="Referenced Spirit",
            stock_quantity=Decimal("100.00"),
            supplier=supplier,
        )
        self.client.force_login(self.manager)
        delete_response = self.client.post(
            reverse("bar:supplier-delete", args=[supplier.pk])
        )
        self.assertEqual(delete_response.status_code, 302)
        self.assertEqual(
            delete_response["Location"],
            reverse("bar:supplier-list"),
        )
        self.assertTrue(BarSupplier.objects.filter(pk=supplier.pk).exists())

        self.client.logout()
        login_url = reverse("login")
        with override_settings(
            RATE_LIMIT_LOGIN_MAX=1,
            RATE_LIMIT_LOGIN_WINDOW=60,
            RATE_LIMIT_TRUST_X_FORWARDED_FOR=True,
        ):
            self.client.post(
                login_url,
                {"username": "nobody", "password": "wrong"},
                HTTP_X_FORWARDED_FOR="not-an-ip",
            )
            with self.assertLogs("bar.middleware", level="WARNING"):
                blocked_response = self.client.post(
                    login_url,
                    {"username": "nobody", "password": "wrong"},
                    HTTP_X_FORWARDED_FOR="not-an-ip",
                )
        self.assertEqual(blocked_response.status_code, 429)
        audit_entry = AuditLog.objects.filter(action="LOGIN_BLOCKED").first()
        self.assertIsNotNone(audit_entry)
        self.assertIsNone(audit_entry.ip_address)
        self.assertEqual(audit_entry.metadata["raw_ip"], "not-an-ip")
