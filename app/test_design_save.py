"""Regression coverage for canvas saves larger than Django's default limit."""

import base64
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import RequestFactory, SimpleTestCase, override_settings

from app.views.designs import save_user_design


class DesignSaveSizeTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_authenticated=True, role="customer")

    def request(self, payload):
        request = self.factory.post(
            "/my-designs/save/", payload, content_type="application/json"
        )
        request.user = self.user
        return request

    @patch("app.views.designs.log_action")
    @patch("app.views.designs.create_saved_design")
    def test_design_above_old_limit_keeps_full_editable_data(self, create, log_action):
        create.return_value = SimpleNamespace(id=42)
        canvas_json = json.dumps({"objects": [{"src": "x" * (3 * 1024 * 1024)}]})
        image_bytes = b"preview image bytes"
        request = self.request({
            "name": "Large design",
            "canvas_json": canvas_json,
            "thumbnail": "data:image/png;base64," + base64.b64encode(image_bytes).decode(),
        })
        self.assertGreater(int(request.META["CONTENT_LENGTH"]), 2621440)
        self.assertLess(int(request.META["CONTENT_LENGTH"]), settings.DATA_UPLOAD_MAX_MEMORY_SIZE)

        response = save_user_design(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["id"], 42)
        self.assertEqual(create.call_args.kwargs["canvas_json"], canvas_json)
        self.assertEqual(create.call_args.kwargs["thumbnail"].read(), image_bytes)

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=1024)
    @patch("app.views.designs.UserDesign.objects.create")
    def test_exceeding_configured_limit_returns_readable_413(self, create):
        response = save_user_design(self.request({"canvas_json": "x" * 2048}))

        self.assertEqual(response.status_code, 413)
        result = json.loads(response.content)
        self.assertEqual(result["status"], "error")
        self.assertIn("size limit", result["message"])
        self.assertNotIn("settings.", result["message"])
        create.assert_not_called()

    @patch("app.views.designs.log_action")
    @patch("app.views.designs.get_object_or_404")
    def test_existing_design_can_still_be_updated(self, get_design, log_action):
        design = Mock(id=42)
        design.name = "Original name"
        design.design_offer_id = None
        design.base_package_id = None
        get_design.return_value = design
        canvas_json = '{"objects": [{"type": "rect"}]}'

        response = save_user_design(self.request({
            "id": 42, "name": "", "canvas_json": canvas_json,
        }))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(design.name, "Original name")
        self.assertEqual(design.canvas_json, canvas_json)
        design.save.assert_called_once_with()

    def test_empty_canvas_still_rejected(self):
        response = save_user_design(self.request({"name": "Empty"}))
        self.assertEqual(response.status_code, 400)

    def test_non_customer_still_rejected(self):
        self.user.role = "admin"
        response = save_user_design(self.request({"canvas_json": "{}"}))
        self.assertEqual(response.status_code, 403)
