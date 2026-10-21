import json
import shutil
import subprocess
from datetime import date, time
from decimal import Decimal
from unittest.mock import Mock, patch

import requests
from django.conf import settings
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from .models import Booking, Package, ServiceChargeConfig, SiteSettings, User
from .views.common import compute_logistics_quote, get_cavite_geometry, get_logistics_origin


class BookingPlaceLookupTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="place-customer", role="customer")
        self.client.force_login(self.user)

    def feature(self, name="Molino III", countrycode="PH"):
        return {"geometry": {"coordinates": [120.975, 14.414]}, "properties": {
            "name": name, "city": "Bacoor", "state": "Cavite", "countrycode": countrycode,
        }}

    @patch("app.geocoding.requests.get")
    def test_search_normalizes_philippine_places_and_caches_results(self, get):
        get.return_value = Mock(json=lambda: {"features": [self.feature(), self.feature("Other", "IT")]})
        for _ in range(2):
            response = self.client.get(reverse("booking_place_search"), {"q": "Molino"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["results"], [{
                "display_name": "Molino III, Bacoor, Cavite, Philippines", "lat": 14.414, "lon": 120.975,
            }])
        get.assert_called_once()

    @patch("app.geocoding.requests.get")
    def test_reverse_uses_feature_collection_and_returns_new_address(self, get):
        get.return_value = Mock(json=lambda: {"features": [self.feature()]})
        response = self.client.get(reverse("booking_place_reverse"), {"lat": "14.414", "lng": "120.975"})
        self.assertEqual(response.json()["results"][0]["display_name"], "Molino III, Bacoor, Cavite, Philippines")
        self.assertIn("/reverse/", get.call_args.args[0])

    @patch("app.geocoding.requests.get", side_effect=requests.Timeout)
    def test_unavailable_provider_returns_actionable_failure(self, get):
        response = self.client.get(reverse("booking_place_search"), {"q": "Molino"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("map", response.json()["error"])

    @patch("app.geocoding.requests.get")
    def test_invalid_coordinates_and_short_search_do_not_call_provider(self, get):
        self.assertEqual(self.client.get(reverse("booking_place_search"), {"q": "Mo"}).json()["results"], [])
        for lat, lng in [("nan", "121"), ("91", "121"), ("14", "inf"), ("", "")]:
            self.assertEqual(self.client.get(reverse("booking_place_reverse"), {"lat": lat, "lng": lng}).status_code, 400)
        get.assert_not_called()

    def test_place_lookup_requires_authentication(self):
        self.client.logout()
        self.assertEqual(self.client.get(reverse("booking_place_search"), {"q": "Molino"}).status_code, 302)


class BookingLogisticsCoverageTests(TestCase):
    def setUp(self):
        cache.clear()
        self.config = ServiceChargeConfig.objects.create(
            pk=1, amount=1000, shop_lat="14.414", shop_lng="120.982", free_radius_km=15, per_km_rate=30,
        )

    def test_cavite_venues_pay_base_even_beyond_included_radius(self):
        for coords in [(14.414, 120.982), (14.1153, 120.9621), (14.2456, 120.8786)]:
            quote = compute_logistics_quote(*coords)
            self.assertTrue(quote["in_cavite"])
            self.assertEqual(quote["total"], Decimal("1000"))

    def test_outside_cavite_increases_with_distance_even_inside_radius(self):
        near = compute_logistics_quote(14.4445, 120.9939)  # Las Piñas, outside Cavite
        qc = compute_logistics_quote(14.676, 121.0437)
        baguio = compute_logistics_quote(16.4023, 120.596)
        self.assertFalse(near["in_cavite"])
        self.assertGreater(near["total"], Decimal("1000"))
        self.assertGreater(qc["total"], near["total"])
        self.assertGreater(baguio["total"], qc["total"])

    def test_rate_changes_apply_to_new_quotes_and_preserve_saved_bookings(self):
        original = compute_logistics_quote(16.4023, 120.596)
        user = User.objects.create_user(username="saved-quote")
        saved = Booking.objects.create(user=user, event_date=date(2099, 1, 1), event_time=time(7),
            event_location="Baguio venue", package_type="Package A", total_price=15000,
            logistics_fee=original["total"])
        self.config.per_km_rate = 300
        self.config.save()
        self.assertGreater(compute_logistics_quote(16.4023, 120.596)["total"], original["total"])
        saved.refresh_from_db()
        self.assertEqual(saved.logistics_fee, original["total"])

    def test_admin_cap_and_zero_rate_are_respected(self):
        self.config.max_fee_cap = 2000
        self.config.save()
        self.assertEqual(compute_logistics_quote(16.4023, 120.596)["total"], Decimal("2000"))
        self.config.per_km_rate = 0
        self.config.save()
        self.assertEqual(compute_logistics_quote(16.4023, 120.596)["total"], Decimal("1000"))

    @patch("app.views.common.search_places")
    def test_missing_shop_pin_uses_configured_business_address(self, search):
        self.config.shop_lat = self.config.shop_lng = None
        self.config.save()
        site = SiteSettings.load()
        site.address = "Our shop, Bacoor, Cavite"
        site.save()
        search.return_value = [{"lat": 14.414, "lon": 120.982}]
        self.assertEqual(get_logistics_origin(), (14.414, 120.982))
        self.assertEqual(get_logistics_origin(), (14.414, 120.982))
        search.assert_called_once_with(site.address)
        self.assertGreater(compute_logistics_quote(16.4023, 120.596)["total"], Decimal("1000"))

    def test_frontend_and_backend_quotes_agree(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node is required to compare live JavaScript and Python prices")
        points = [(14.414, 120.982), (14.1153, 120.9621), (14.4445, 120.9939), (14.676, 121.0437), (16.4023, 120.596)]
        script = "global.window=global; require('./static/js/booking_logistics.js'); const geometry=" + json.dumps(get_cavite_geometry())
        script += ";const points=" + json.dumps(points)
        script += "; console.log(JSON.stringify(points.map(p=>BookingLogistics.quote({base:1000,shopLat:14.414,shopLng:120.982,freeRadius:15,perKm:30,maxCap:0},p[0],p[1],geometry))))"
        result = subprocess.run([node, "-e", script], cwd=settings.BASE_DIR, capture_output=True, text=True, check=True)
        for point, client_quote in zip(points, json.loads(result.stdout)):
            server_quote = compute_logistics_quote(*point)
            self.assertEqual(client_quote["total"], float(server_quote["total"]))
            self.assertEqual(client_quote["inCavite"], server_quote["in_cavite"])

    def test_create_booking_recomputes_fee_and_overtime_on_server(self):
        user = User.objects.create_user(username="priced-customer", role="customer")
        self.client.force_login(user)
        Package.objects.create(name="Package A", price=5000)
        response = self.client.post(reverse("create_booking"), {
            "event_type": "Birthday", "event_date": "2099-01-15", "start_time": "07:00", "end_time": "10:15",
            "event_location": "Baguio event venue", "event_lat": "16.4023", "event_lng": "120.596",
            "package_type": "Package A", "total_price": "1", "design_theme": "Princess", "color_palette": "Pink, Gold",
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertTrue(response.json()["success"], response.content)
        booking = Booking.objects.get(user=user)
        self.assertEqual(booking.logistics_fee, compute_logistics_quote(16.4023, 120.596)["total"])
        self.assertEqual(booking.overtime_fee, Decimal("500"))
        self.assertEqual(booking.total_price, Decimal("5000") + booking.logistics_fee + booking.overtime_fee)
        self.assertEqual(booking.fee_policy_snapshot["included_hours"], 3)
        self.assertEqual(Decimal(booking.fee_policy_snapshot["overtime_rate"]), Decimal("500"))
        self.assertEqual(Decimal(booking.fee_policy_snapshot["logistics_base"]), Decimal("1000"))

    def test_missing_origin_does_not_silently_bill_outside_cavite_at_base(self):
        self.config.shop_lat = self.config.shop_lng = None
        self.config.save()
        quote = compute_logistics_quote(16.4023, 120.596)
        self.assertFalse(quote["configured"])
        user = User.objects.create_user(username="missing-origin", role="customer")
        self.client.force_login(user)
        response = self.client.post(reverse("create_booking"), {
            "event_type": "Birthday", "event_date": "2099-01-15", "start_time": "07:00", "end_time": "10:15",
            "event_location": "Baguio event venue", "event_lat": "16.4023", "event_lng": "120.596",
            "package_type": "Package A", "total_price": "5000", "design_theme": "Princess", "color_palette": "Pink, Gold",
        }, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertFalse(response.json()["success"])
        self.assertIn("logistics", response.json()["message"])
        self.assertFalse(Booking.objects.filter(user=user).exists())

    def test_editing_venue_refreshes_the_saved_logistics_quote(self):
        user = User.objects.create_user(username="edited-venue", role="customer")
        self.client.force_login(user)
        Package.objects.create(name="Package A", price=5000)
        booking = Booking.objects.create(user=user, event_date=date(2099, 1, 15), event_time=time(7),
            event_location="Bacoor venue", event_lat="14.414", event_lng="120.982",
            package_type="Package A", total_price=6000, logistics_fee=1000, status="pending")
        self.client.post(reverse("edit_booking", args=[booking.pk]), {
            "event_type": "Birthday", "event_date": "2099-01-15", "start_time": "07:00", "end_time": "10:00",
            "event_location": "Baguio event venue", "event_lat": "16.4023", "event_lng": "120.596",
            "package_type": "Package A", "total_price": "1", "design_theme": "Princess", "color_palette": "Pink, Gold",
        })
        booking.refresh_from_db()
        self.assertEqual(booking.logistics_fee, compute_logistics_quote(16.4023, 120.596)["total"])
        self.assertEqual(booking.total_price, Decimal("5000") + booking.logistics_fee)


class ShopSettingsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(username="shop-admin", role="admin")
        self.client.force_login(self.user)
        self.config = ServiceChargeConfig.objects.create(pk=1, amount=1000, shop_lat=14.414, shop_lng=120.982, per_km_rate=30)

    def test_site_settings_save_shop_address_and_exact_pin(self):
        response = self.client.post(reverse("admin_site_settings"), {
            "site_name": "Balloorina", "address": "New shop, Tanza, Cavite",
            "shop_lat": "14.4", "shop_lng": "120.85",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(SiteSettings.load().address, "New shop, Tanza, Cavite")
        self.config.refresh_from_db()
        self.assertEqual(self.config.shop_lat, Decimal("14.4"))
        self.assertEqual(self.config.shop_lng, Decimal("120.85"))
        self.assertEqual(self.config.per_km_rate, Decimal("30"))

    def test_changing_only_address_clears_stale_shop_pin(self):
        self.client.post(reverse("admin_site_settings"), {"site_name": "Balloorina", "address": "Relocated shop, Cavite"})
        self.config.refresh_from_db()
        self.assertIsNone(self.config.shop_lat)
        self.assertIsNone(self.config.shop_lng)

    def test_invalid_shop_pin_does_not_change_settings(self):
        self.client.post(reverse("admin_site_settings"), {
            "site_name": "Balloorina", "address": "Invalid replacement", "shop_lat": "nan", "shop_lng": "121",
        })
        self.config.refresh_from_db()
        self.assertEqual(self.config.shop_lat, Decimal("14.414"))
        self.assertNotEqual(SiteSettings.load().address, "Invalid replacement")

    def test_changing_rates_preserves_shop_pin(self):
        response = self.client.post(reverse("admin_service_charge_update"), {
            "service_charge_amount": "1000", "service_charge_notes": "Travel fee",
            "free_radius_km": "15", "per_km_rate": "300", "max_fee_cap": "0",
        })
        self.assertEqual(response.status_code, 302)
        self.config.refresh_from_db()
        self.assertEqual(self.config.per_km_rate, Decimal("300"))
        self.assertEqual(self.config.shop_lat, Decimal("14.414"))
