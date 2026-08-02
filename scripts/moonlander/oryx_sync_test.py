import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("oryx_sync.py")
SPEC = importlib.util.spec_from_file_location("oryx_sync", MODULE_PATH)
assert SPEC and SPEC.loader
oryx_sync = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = oryx_sync
SPEC.loader.exec_module(oryx_sync)


def key(code="KC_TRANSPARENT"):
    return {
        "tap": {
            "code": code,
            "color": None,
            "layer": None,
            "macro": None,
            "modifier": None,
            "modifiers": None,
            "description": None,
        }
    }


def snapshot():
    return {
        "schemaVersion": 1,
        "layout": {
            "hashId": "layout-id",
            "geometry": "moonlander",
            "title": "layout",
            "privacy": False,
            "tags": [],
            "revision": {
                "model": "mk1",
                "config": {"tappingTerm": 135},
                "swatch": None,
                "navigators": None,
                "layers": [
                    {
                        "position": 0,
                        "title": "base",
                        "color": "#123456",
                        "automouse": False,
                        "keys": [key() for _ in range(72)],
                    }
                ],
                "combos": [],
            },
        },
    }


def raw(snapshot_value=None):
    value = snapshot_value or snapshot()
    layout = value["layout"]
    revision = layout["revision"]
    return {
        "hashId": layout["hashId"],
        "title": layout["title"],
        "geometry": layout["geometry"],
        "privacy": layout["privacy"],
        "tags": layout["tags"],
        "revision": {
            "hashId": "revision-id",
            "model": revision["model"],
            "config": revision["config"],
            "swatch": revision["swatch"],
            "navigators": revision["navigators"],
            "layers": [
                {"hashId": f"layer-{layer['position']}", **copy.deepcopy(layer)}
                for layer in revision["layers"]
            ],
            "combos": revision["combos"],
        },
    }


class CanonicalLayoutTests(unittest.TestCase):
    def test_strips_server_and_ui_fields(self):
        server = raw()
        server["revision"]["createdAt"] = "volatile"
        server["revision"]["layers"][0]["keys"][0]["history"] = ["volatile"]
        server["revision"]["layers"][0]["keys"][0]["about"] = "volatile"

        canonical = oryx_sync.canonical_layout(server)

        self.assertEqual(canonical, snapshot())
        self.assertNotIn("hashId", canonical["layout"]["revision"]["layers"][0])

    def test_sorts_layers_by_position(self):
        expected = snapshot()
        second = copy.deepcopy(expected["layout"]["revision"]["layers"][0])
        second["position"] = 1
        second["title"] = "second"
        expected["layout"]["revision"]["layers"].append(second)
        server = raw(expected)
        server["revision"]["layers"].reverse()

        canonical = oryx_sync.canonical_layout(server)

        self.assertEqual(
            [layer["position"] for layer in canonical["layout"]["revision"]["layers"]],
            [0, 1],
        )


class ValidationTests(unittest.TestCase):
    def test_accepts_canonical_moonlander(self):
        oryx_sync.validate_snapshot(snapshot())

    def test_rejects_wrong_key_count(self):
        value = snapshot()
        value["layout"]["revision"]["layers"][0]["keys"].pop()

        with self.assertRaisesRegex(oryx_sync.SyncError, "exactly 72"):
            oryx_sync.validate_snapshot(value)

    def test_rejects_noncanonical_key_state(self):
        value = snapshot()
        value["layout"]["revision"]["layers"][0]["keys"][0]["history"] = []

        with self.assertRaisesRegex(oryx_sync.SyncError, "non-canonical fields: history"):
            oryx_sync.validate_snapshot(value)

    def test_rejects_reordered_layers(self):
        value = snapshot()
        value["layout"]["revision"]["layers"][0]["position"] = 1

        with self.assertRaisesRegex(oryx_sync.SyncError, "contiguous"):
            oryx_sync.validate_snapshot(value)


class MutationPlanningTests(unittest.TestCase):
    def plan(self, wanted, current=None):
        current = current or snapshot()
        return oryx_sync.next_mutation(wanted, current, raw(current))

    def test_matching_layout_needs_no_mutation(self):
        self.assertIsNone(self.plan(snapshot()))

    def test_title_change_is_scoped_to_expected_layout(self):
        wanted = snapshot()
        wanted["layout"]["title"] = "new title"

        pending = self.plan(wanted)

        self.assertEqual(pending.name, "UpdateLayoutTitle")
        self.assertEqual(
            pending.variables,
            {"hashId": "layout-id", "title": "new title"},
        )

    def test_key_change_updates_whole_layer_using_fresh_hash(self):
        wanted = snapshot()
        wanted["layout"]["revision"]["layers"][0]["keys"][3] = key("KC_D")

        pending = self.plan(wanted)

        self.assertEqual(pending.name, "UpdateLayer")
        self.assertEqual(pending.variables["hashId"], "layer-0")
        self.assertEqual(pending.variables["keys"][3]["tap"]["code"], "KC_D")

    def test_config_change_uses_current_revision_hash(self):
        wanted = snapshot()
        wanted["layout"]["revision"]["config"]["tappingTerm"] = 150

        pending = self.plan(wanted)

        self.assertEqual(pending.name, "UpdateRevisionConfig")
        self.assertEqual(pending.variables["hashId"], "revision-id")

    def test_extra_remote_layer_is_deleted_from_end(self):
        current = snapshot()
        extra = copy.deepcopy(current["layout"]["revision"]["layers"][0])
        extra["position"] = 1
        current["layout"]["revision"]["layers"].append(extra)

        pending = self.plan(snapshot(), current)

        self.assertEqual(pending.name, "DeleteLayer")
        self.assertEqual(pending.variables["hashId"], "layer-1")


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def read(self):
        return json.dumps(self.payload).encode()


class GraphQLClientTests(unittest.TestCase):
    def test_sends_token_without_putting_it_in_variables(self):
        requests = []

        def opener(request):
            requests.append(request)
            return FakeResponse({"data": {"ok": True}})

        client = oryx_sync.GraphQLClient(token="secret", opener=opener)
        result = client.execute("query Test { ok }", {}, "Test")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(requests[0].headers["Authorization"], "Bearer secret")
        self.assertNotIn(b"secret", requests[0].data)

    def test_rejects_top_level_graphql_errors(self):
        client = oryx_sync.GraphQLClient(
            opener=lambda _request: FakeResponse(
                {"errors": [{"message": "Unauthorized"}]}
            )
        )

        with self.assertRaisesRegex(oryx_sync.SyncError, "Unauthorized"):
            client.execute("query Test { ok }", {}, "Test")


class DiffTests(unittest.TestCase):
    def test_diff_labels_remote_and_repository(self):
        expected = snapshot()
        current = snapshot()
        expected["layout"]["title"] = "wanted"

        difference = oryx_sync.snapshot_diff(expected, current)

        self.assertIn("--- oryx", difference)
        self.assertIn("+++ repository", difference)
        self.assertIn('+    "title": "wanted"', difference)


if __name__ == "__main__":
    unittest.main()
