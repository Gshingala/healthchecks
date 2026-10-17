from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from django.conf import settings
from django.urls import Resolver404, resolve

from hc.api.models import Check
from hc.test import BaseTestCase

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

SPEC_PATH = Path(settings.BASE_DIR) / "planning" / "api" / "openapi.yaml"
HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
STATUS_KEY = re.compile(r"^([1-5][0-9][0-9]|[1-5]XX|default)$")

# Routes added or changed by route stories. Each must be documented in the
# spec with its method; later route stories append to this list.
CHANGED_ROUTES = [
    ("GET", "/api/v3/maintenance/"),
    ("POST", "/api/v3/maintenance/"),
    ("GET", "/api/v3/maintenance/{uuid}"),
    ("DELETE", "/api/v3/maintenance/{uuid}"),
    ("POST", "/api/v3/maintenance/{uuid}/end"),
    ("GET", "/api/v3/checks/"),
    ("POST", "/api/v3/checks/"),
    ("GET", "/api/v3/checks/{uuid}"),
    ("POST", "/api/v3/checks/{uuid}"),
    ("DELETE", "/api/v3/checks/{uuid}"),
    ("POST", "/api/v3/checks/{uuid}/pause"),
    ("POST", "/api/v3/checks/{uuid}/resume"),
    ("GET", "/projects/{code}/maintenance/"),
    ("POST", "/projects/{code}/maintenance/add/"),
    ("GET", "/projects/{code}/maintenance/preview/"),
    ("POST", "/projects/{code}/maintenance/{mw_code}/edit/"),
    ("POST", "/projects/{code}/maintenance/{mw_code}/end/"),
    ("POST", "/projects/{code}/maintenance/{mw_code}/remove/"),
    ("GET", "/projects/{code}/checks/"),
    ("GET", "/checks/{code}/details/"),
    ("GET", "/checks/{code}/log/"),
    ("GET", "/checks/{code}/log_events/"),
    ("GET", "/checks/{code}/status/"),
]

# Views serving several operations, keyed by (view, method)
DISPATCHED_OPERATIONS = {
    ("hc.api.views.maintenance", "GET"): "get_maintenance_windows",
    ("hc.api.views.maintenance", "POST"): "create_maintenance_window",
    ("hc.api.views.maintenance_single", "GET"): "get_maintenance_window",
    ("hc.api.views.maintenance_single", "DELETE"): "delete_maintenance_window",
    ("hc.api.views.checks", "GET"): "get_checks",
    ("hc.api.views.checks", "POST"): "create_check",
    ("hc.api.views.single", "GET"): "get_check",
    ("hc.api.views.single", "POST"): "update_check",
    ("hc.api.views.single", "DELETE"): "delete_check",
}
PATH_PARAM = re.compile(r"{(\w+)}")


def _refs(node: Any) -> list[str]:
    if isinstance(node, dict):
        found = [node["$ref"]] if isinstance(node.get("$ref"), str) else []
        for value in node.values():
            found.extend(_refs(value))
        return found
    if isinstance(node, list):
        return [ref for item in node for ref in _refs(item)]
    return []


def _resolve(spec: dict[str, Any], ref: str) -> Any:
    node: Any = spec
    for part in ref.removeprefix("#/").split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


class MaintenanceContractTestCase(BaseTestCase):
    def setUp(self) -> None:
        super().setUp()
        if yaml is None:
            self.skipTest("PyYAML not installed")

        with SPEC_PATH.open(encoding="utf-8") as f:
            self.spec = yaml.safe_load(f)

    def operations(self) -> list[tuple[str, str, dict[str, Any]]]:
        result = []
        for path, item in self.spec["paths"].items():
            for method, operation in item.items():
                if method in HTTP_METHODS:
                    result.append((method, path, operation))
        return result

    def test_it_is_valid_openapi_3(self) -> None:
        self.assertTrue(str(self.spec["openapi"]).startswith("3."))
        self.assertTrue(self.spec["info"]["title"])
        self.assertTrue(self.spec["info"]["version"])
        self.assertTrue(self.spec["paths"])

        operation_ids = []
        for method, path, operation in self.operations():
            label = f"{method.upper()} {path}"
            self.assertTrue(operation.get("operationId"), label)
            operation_ids.append(operation["operationId"])

            self.assertIn("responses", operation, label)
            responses = operation["responses"]
            self.assertTrue(responses, label)
            for status in responses:
                self.assertRegex(str(status), STATUS_KEY, label)

        self.assertEqual(len(operation_ids), len(set(operation_ids)))

        for ref in _refs(self.spec):
            self.assertTrue(ref.startswith("#/"), ref)
            self.assertIsNotNone(_resolve(self.spec, ref), ref)

    def test_it_documents_every_changed_route(self) -> None:
        for method, path in CHANGED_ROUTES:
            self.assertIn(path, self.spec["paths"])
            self.assertIn(method.lower(), self.spec["paths"][path], path)

    def test_it_matches_window_schema(self) -> None:
        schema = self.spec["components"]["schemas"]["Window"]

        r = self.csrf_client.post(
            "/api/v3/maintenance/",
            {"name": "Deploy 42", "duration": 3600},
            content_type="application/json",
            HTTP_X_API_KEY="X" * 32,
        )
        self.assertEqual(r.status_code, 201)

        keys = set(r.json().keys())
        self.assertEqual(keys, set(schema["properties"].keys()))
        self.assertTrue(set(schema["required"]) <= keys)

    def test_it_matches_check_schema(self) -> None:
        schema = self.spec["components"]["schemas"]["Check"]
        check = Check.objects.create(project=self.project, name="Backups")

        r = self.client.get(f"/api/v3/checks/{check.code}", HTTP_X_API_KEY="X" * 32)
        self.assertEqual(r.status_code, 200)

        keys = set(r.json().keys())
        self.assertTrue(set(schema["required"]) <= keys)
        self.assertTrue(keys <= set(schema["properties"].keys()))

    def path_examples(self, path: str, operation: dict[str, Any]) -> dict[str, str]:
        item = self.spec["paths"][path]
        examples = {}
        for param in item.get("parameters", []) + operation.get("parameters", []):
            if "$ref" in param:
                param = _resolve(self.spec, param["$ref"])
            if param.get("in") == "path":
                examples[param["name"]] = str(param["example"])
        return examples

    def test_it_serves_every_changed_operation(self) -> None:
        changed = [
            (method.upper(), path, operation)
            for method, path, operation in self.operations()
            if operation.get("x-change") in ("added", "changed")
        ]
        self.assertTrue(changed)

        for method, path, operation in changed:
            label = f"{method} {path}"
            examples = self.path_examples(path, operation)
            url = PATH_PARAM.sub(lambda m: examples[m.group(1)], path)

            try:
                match = resolve(url)
            except Resolver404:
                self.fail(f"{label} is not in the URLconf")

            view = f"{match.func.__module__}.{match.func.__name__}"
            view_name = DISPATCHED_OPERATIONS.get((view, method), match.func.__name__)
            self.assertEqual(view_name, operation["operationId"], label)

            r = self.client.generic(method, url)
            self.assertNotIn(r.status_code, (404, 405), label)
