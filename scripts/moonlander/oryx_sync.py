#!/usr/bin/env python3
"""Synchronize a repository-owned Moonlander layout with Oryx."""

from __future__ import annotations

import argparse
import copy
import difflib
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


ENDPOINT = "https://oryx.zsa.io/graphql"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SNAPSHOT = ROOT / "lib" / "moonlander-layout.json"
KEY_FIELDS = (
    "glowColor",
    "lockGlowColor",
    "customLabel",
    "tappingTerm",
    "tap",
    "hold",
    "doubleTap",
    "tapHold",
    "icon",
    "emoji",
)

LAYOUT_QUERY = """
query LayoutSnapshot($hashId: String!, $geometry: String!, $revisionId: String!) {
  layout(hashId: $hashId, geometry: $geometry, revisionId: $revisionId) {
    hashId title geometry privacy
    tags { hashId name }
    revision {
      hashId model config swatch navigators qmkVersion
      layers { hashId title position color automouse keys }
      combos { name layerIdx keyIndices trigger }
    }
  }
}
"""

MY_LAYOUTS_QUERY = """
query MyLayouts {
  myLayouts {
    hashId
    revisions { hashId qmkVersion }
  }
}
"""

FORK_REVISION_MUTATION = """
mutation ForkRevision($hashId: String!) {
  forkRevision(hashId: $hashId) { hashId }
}
"""

DELETE_LAYOUT_MUTATION = """
mutation DeleteLayout($hashId: String!) {
  deleteLayout(hashId: $hashId) { hashId }
}
"""


class SyncError(RuntimeError):
    pass


class GraphQLClient:
    def __init__(
        self,
        token: str | None = None,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        self.token = token
        self.opener = opener

    def execute(
        self,
        query: str,
        variables: dict[str, Any],
        operation_name: str,
    ) -> dict[str, Any]:
        body = json.dumps(
            {
                "operationName": operation_name,
                "query": query,
                "variables": variables,
            }
        ).encode()
        headers = {"content-type": "application/json"}
        if self.token:
            headers["authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(ENDPOINT, body, headers)
        try:
            response = self.opener(request)
            payload = json.loads(response.read())
        except (OSError, urllib.error.HTTPError, json.JSONDecodeError) as error:
            raise SyncError(f"Oryx request failed: {error}") from error
        if payload.get("errors"):
            messages = "; ".join(error["message"] for error in payload["errors"])
            raise SyncError(f"Oryx rejected {operation_name}: {messages}")
        if "data" not in payload:
            raise SyncError(f"Oryx returned no data for {operation_name}")
        return payload["data"]


def canonical_key(key: dict[str, Any]) -> dict[str, Any]:
    return {
        field: key[field]
        for field in KEY_FIELDS
        if field in key and key[field] is not None
    }


def canonical_layout(layout: dict[str, Any]) -> dict[str, Any]:
    revision = layout["revision"]
    layers = sorted(revision["layers"], key=lambda layer: layer["position"])
    return {
        "schemaVersion": 1,
        "layout": {
            "hashId": layout["hashId"],
            "geometry": layout["geometry"],
            "title": layout["title"],
            "privacy": layout["privacy"],
            "tags": sorted(layout.get("tags") or [], key=lambda tag: tag["hashId"]),
            "revision": {
                "model": revision["model"],
                "config": revision.get("config"),
                "swatch": revision.get("swatch"),
                "navigators": revision.get("navigators"),
                "layers": [
                    {
                        "position": layer["position"],
                        "title": layer.get("title"),
                        "color": layer.get("color"),
                        "automouse": bool(layer.get("automouse")),
                        "keys": [canonical_key(key) for key in layer["keys"]],
                    }
                    for layer in layers
                ],
                "combos": revision.get("combos") or [],
            },
        },
    }


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    if snapshot.get("schemaVersion") != 1:
        raise SyncError("unsupported or missing schemaVersion")
    layout = snapshot.get("layout")
    if not isinstance(layout, dict):
        raise SyncError("layout must be an object")
    if layout.get("geometry") != "moonlander":
        raise SyncError("this synchronizer only accepts Moonlander layouts")
    if not isinstance(layout.get("hashId"), str) or not layout["hashId"]:
        raise SyncError("layout.hashId must be a non-empty string")
    revision = layout.get("revision")
    if not isinstance(revision, dict):
        raise SyncError("layout.revision must be an object")
    layers = revision.get("layers")
    if not isinstance(layers, list) or not layers:
        raise SyncError("layout.revision.layers must be a non-empty array")
    positions = [layer.get("position") for layer in layers]
    if positions != list(range(len(layers))):
        raise SyncError("layer positions must be contiguous and ordered from zero")
    for layer in layers:
        if not isinstance(layer.get("keys"), list) or len(layer["keys"]) != 72:
            raise SyncError(
                f"Moonlander layer {layer['position']} must contain exactly 72 keys"
            )
        for key in layer["keys"]:
            unexpected = set(key) - set(KEY_FIELDS)
            if unexpected:
                raise SyncError(
                    f"key contains non-canonical fields: {', '.join(sorted(unexpected))}"
                )


def pretty(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_snapshot(path: Path, snapshot: dict[str, Any]) -> None:
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as output:
            output.write(pretty(snapshot))
            temporary = Path(output.name)
        temporary.replace(path)
    except OSError as error:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise SyncError(f"cannot write {path}: {error}") from error


def snapshot_diff(expected: dict[str, Any], actual: dict[str, Any]) -> str:
    return "".join(
        difflib.unified_diff(
            pretty(actual).splitlines(keepends=True),
            pretty(expected).splitlines(keepends=True),
            fromfile="oryx",
            tofile="repository",
        )
    )


def fetch_snapshot(client: GraphQLClient, expected: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    layout = expected["layout"]
    data = client.execute(
        LAYOUT_QUERY,
        {
            "hashId": layout["hashId"],
            "geometry": layout["geometry"],
            "revisionId": "latest",
        },
        "LayoutSnapshot",
    )
    if data.get("layout") is None:
        raise SyncError(f"Oryx layout {layout['hashId']} was not found")
    raw = data["layout"]
    current = canonical_layout(raw)
    if current["layout"]["hashId"] != layout["hashId"]:
        raise SyncError("Oryx returned a different layout ID")
    return current, raw


def prepare_apply(
    client: GraphQLClient,
    expected: dict[str, Any],
    current: dict[str, Any],
    raw: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Verify ownership and fork an immutable revision when revision data changed."""
    layout_id = expected["layout"]["hashId"]
    revision_id = raw["revision"]["hashId"]
    data = client.execute(MY_LAYOUTS_QUERY, {}, "MyLayouts")
    owned = next(
        (layout for layout in data.get("myLayouts") or [] if layout["hashId"] == layout_id),
        None,
    )
    if owned is None:
        raise SyncError(f"authenticated account does not own Oryx layout {layout_id}")
    owned_revision = next(
        (
            revision
            for revision in owned.get("revisions") or []
            if revision["hashId"] == revision_id
        ),
        None,
    )
    if owned_revision is None:
        raise SyncError(
            f"latest revision {revision_id} is not owned by layout {layout_id}"
        )
    if expected["layout"]["revision"] == current["layout"]["revision"]:
        return expected, None
    if owned_revision.get("qmkVersion") is None:
        return expected, None

    data = client.execute(
        FORK_REVISION_MUTATION,
        {"hashId": revision_id},
        "ForkRevision",
    )
    fork_id = (data.get("forkRevision") or {}).get("hashId")
    if not isinstance(fork_id, str) or not fork_id or fork_id == layout_id:
        raise SyncError("Oryx returned an invalid layout ID while forking the revision")
    prepared = copy.deepcopy(expected)
    prepared["layout"]["hashId"] = fork_id
    print(f"forked compiled layout {layout_id} as editable layout {fork_id}", file=sys.stderr)
    return prepared, fork_id


def delete_layout(client: GraphQLClient, layout_id: str) -> None:
    client.execute(
        DELETE_LAYOUT_MUTATION,
        {"hashId": layout_id},
        "DeleteLayout",
    )


@dataclass(frozen=True)
class Mutation:
    name: str
    query: str
    variables: dict[str, Any]


def mutation(name: str, arguments: str, call: str, variables: dict[str, Any]) -> Mutation:
    query = f"mutation {name}({arguments}) {{ {call} {{ __typename }} }}"
    return Mutation(name, query, variables)


def next_mutation(expected: dict[str, Any], current: dict[str, Any], raw: dict[str, Any]) -> Mutation | None:
    want = expected["layout"]
    have = current["layout"]
    revision_id = raw["revision"]["hashId"]

    if want["title"] != have["title"]:
        return mutation(
            "UpdateLayoutTitle",
            "$hashId: String!, $title: String!",
            "updateLayoutTitle(hashId: $hashId, title: $title)",
            {"hashId": want["hashId"], "title": want["title"]},
        )
    if want["privacy"] != have["privacy"]:
        return mutation(
            "UpdateLayoutPrivacy",
            "$hashId: String!, $privacy: Boolean!",
            "updateLayoutPrivacy(hashId: $hashId, privacy: $privacy)",
            {"hashId": want["hashId"], "privacy": want["privacy"]},
        )
    if want["tags"] != have["tags"]:
        return mutation(
            "UpdateLayoutTags",
            "$hashId: String!, $tagIds: [String!]!",
            "updateLayoutTags(hashId: $hashId, tagIds: $tagIds)",
            {"hashId": want["hashId"], "tagIds": [tag["hashId"] for tag in want["tags"]]},
        )

    want_revision = want["revision"]
    have_revision = have["revision"]
    if want_revision["model"] != have_revision["model"]:
        return mutation(
            "UpdateRevisionModel",
            "$hashId: String!, $model: String!",
            "updateRevisionModel(hashId: $hashId, model: $model)",
            {"hashId": revision_id, "model": want_revision["model"]},
        )
    for field, operation, argument in (
        ("config", "UpdateRevisionConfig", "config"),
        ("swatch", "UpdateRevisionSwatch", "swatch"),
    ):
        if want_revision[field] != have_revision[field]:
            return mutation(
                operation,
                f"$hashId: String!, ${argument}: Json!",
                f"{operation[0].lower() + operation[1:]}(hashId: $hashId, {argument}: ${argument})",
                {"hashId": revision_id, argument: want_revision[field]},
            )
    if want_revision["navigators"] != have_revision["navigators"]:
        return mutation(
            "UpdateNavigators",
            "$revisionHash: String!, $navigators: Json",
            "updateNavigators(revisionHash: $revisionHash, navigators: $navigators)",
            {"revisionHash": revision_id, "navigators": want_revision["navigators"]},
        )

    want_layers = want_revision["layers"]
    have_layers = have_revision["layers"]
    raw_layers = sorted(raw["revision"]["layers"], key=lambda layer: layer["position"])
    if len(have_layers) > len(want_layers):
        layer_id = raw_layers[-1]["hashId"]
        return mutation(
            "DeleteLayer",
            "$hashId: String!",
            "deleteLayer(hashId: $hashId)",
            {"hashId": layer_id},
        )
    if len(have_layers) < len(want_layers):
        layer = want_layers[len(have_layers)]
        return mutation(
            "CreateLayer",
            "$revisionHashId: String!, $keys: Json!, $position: Int!, $title: String, $automouse: Boolean",
            "createLayer(revisionHashId: $revisionHashId, newKeys: $keys, position: $position, title: $title, automouse: $automouse)",
            {
                "revisionHashId": revision_id,
                "keys": layer["keys"],
                "position": layer["position"],
                "title": layer["title"],
                "automouse": layer["automouse"],
            },
        )
    for wanted_layer, current_layer, raw_layer in zip(want_layers, have_layers, raw_layers):
        changed = any(
            wanted_layer[field] != current_layer[field]
            for field in ("title", "color", "keys")
        )
        if changed:
            return mutation(
                "UpdateLayer",
                "$hashId: String!, $keys: Json, $position: Int, $title: String, $color: String",
                "updateLayer(hashId: $hashId, newKeys: $keys, position: $position, title: $title, color: $color)",
                {
                    "hashId": raw_layer["hashId"],
                    "keys": wanted_layer["keys"],
                    "position": wanted_layer["position"],
                    "title": wanted_layer["title"],
                    "color": wanted_layer["color"],
                },
            )
        if wanted_layer["automouse"] != current_layer["automouse"]:
            return mutation(
                "UpdateRevisionAutomouse",
                "$revisionHash: String!, $layerPosition: Int!, $automouse: Boolean!",
                "updateRevisionAutomouse(revisionHash: $revisionHash, layerPosition: $layerPosition, automouse: $automouse)",
                {
                    "revisionHash": revision_id,
                    "layerPosition": wanted_layer["position"],
                    "automouse": wanted_layer["automouse"],
                },
            )

    want_combos = want_revision["combos"]
    have_combos = have_revision["combos"]
    if len(have_combos) > len(want_combos):
        index = len(have_combos) - 1
        return mutation(
            "DeleteCombo",
            "$revisionHashId: String!, $comboIdx: Int!",
            "deleteCombo(revisionHashId: $revisionHashId, comboIdx: $comboIdx)",
            {"revisionHashId": revision_id, "comboIdx": index},
        )
    for index, wanted_combo in enumerate(want_combos):
        if index >= len(have_combos) or wanted_combo != have_combos[index]:
            variables = {"revisionHashId": revision_id, "comboIdx": index, **wanted_combo}
            if index >= len(have_combos):
                variables["comboIdx"] = None
            return mutation(
                "UpsertCombo",
                "$revisionHashId: String!, $comboIdx: Int, $name: String!, $layerIdx: Int!, $keyIndices: [Int!]!, $trigger: Json!",
                "upsertCombo(revisionHashId: $revisionHashId, comboIdx: $comboIdx, name: $name, layerIdx: $layerIdx, keyIndices: $keyIndices, trigger: $trigger)",
                variables,
            )
    return None


def load_snapshot(path: Path) -> dict[str, Any]:
    try:
        snapshot = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise SyncError(f"cannot read {path}: {error}") from error
    validate_snapshot(snapshot)
    return snapshot


def apply(client: GraphQLClient, expected: dict[str, Any]) -> None:
    for _ in range(50):
        current, raw = fetch_snapshot(client, expected)
        pending = next_mutation(expected, current, raw)
        if pending is None:
            if current != expected:
                raise SyncError("Oryx differs, but no supported mutation can reconcile it")
            return
        print(f"applying {pending.name}", file=sys.stderr)
        client.execute(pending.query, pending.variables, pending.name)
    raise SyncError("Oryx did not converge after 50 mutations")


def complete_apply(
    client: GraphQLClient,
    prepared: dict[str, Any],
    fork_id: str | None,
    snapshot_path: Path,
) -> None:
    try:
        apply(client, prepared)
        verified, _ = fetch_snapshot(client, prepared)
        if verified != prepared:
            raise SyncError("post-apply verification did not match the repository snapshot")
        if fork_id is not None:
            write_snapshot(snapshot_path, prepared)
            print(
                f"repository snapshot now tracks forked layout {fork_id}",
                file=sys.stderr,
            )
    except SyncError as apply_error:
        if fork_id is not None:
            try:
                delete_layout(client, fork_id)
                print(f"deleted failed fork {fork_id}", file=sys.stderr)
            except SyncError as cleanup_error:
                raise SyncError(
                    f"{apply_error}; failed to delete fork {fork_id}: {cleanup_error}"
                ) from apply_error
        raise


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument(
        "--layout-id",
        help="layout ID used only to initialize a missing snapshot with --pull",
    )
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--pull", action="store_true", help="replace the snapshot from Oryx")
    action.add_argument("--apply", action="store_true", help="mutate Oryx to match the snapshot")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        if args.pull and not args.snapshot.exists():
            if not args.layout_id:
                raise SyncError("initial --pull requires --layout-id")
            expected = {
                "layout": {"hashId": args.layout_id, "geometry": "moonlander"}
            }
        else:
            expected = load_snapshot(args.snapshot)
            if args.layout_id and args.layout_id != expected["layout"]["hashId"]:
                raise SyncError("--layout-id does not match the repository snapshot")
        token = os.environ.get("ORYX_TOKEN")
        if args.apply and not token:
            raise SyncError("--apply requires ORYX_TOKEN")
        client = GraphQLClient(token=token)
        current, raw = fetch_snapshot(client, expected)
        if args.pull:
            validate_snapshot(current)
            write_snapshot(args.snapshot, current)
            print(f"updated {args.snapshot}")
            return 0
        difference = snapshot_diff(expected, current)
        if not difference:
            print("Oryx matches the repository snapshot")
            return 0
        sys.stdout.write(difference)
        if not args.apply:
            return 1
        prepared, fork_id = prepare_apply(client, expected, current, raw)
        complete_apply(client, prepared, fork_id, args.snapshot)
        print("Oryx now matches the repository snapshot", file=sys.stderr)
        return 0
    except SyncError as error:
        print(f"sync-moonlander: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
