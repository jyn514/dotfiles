"""Read ChatGPT account exports without extracting archive-controlled paths.

The CLI owns selection and destinations. This adapter produces structured import
messages for the existing Pi writer and publishes each session with its assets.
"""

import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import uuid
import zipfile


CONVERSATIONS = re.compile(r"conversations(?:-\d+)?\.json")


def is_export(path):
    return path.is_dir() or path.suffix.lower() == ".zip" or bool(CONVERSATIONS.fullmatch(path.name))


def iso_time(value, fallback):
    if value is None:
        return fallback
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")


def safe_name(value):
    # Names are labels, not paths, even when an export came from another OS.
    name = re.sub(r"[\x00-\x1f/\\]", "_", str(value))[:180]
    return name if name not in ("", ".", "..") else "attachment"


def image_mime(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class ChatGPTExport:
    def __init__(self, path):
        self.path = path
        self.archive = zipfile.ZipFile(path) if path.suffix.lower() == ".zip" else None
        self.root = (path if path.is_dir() else path.parent).resolve()
        self.warnings = Counter()
        self.missing_attachments = []
        try:
            if self.archive:
                names = self.archive.namelist()
                if len(names) != len(set(names)):
                    raise ValueError("export ZIP contains duplicate member names")
                self.members = set(names)
            else:
                self.members = {p.name for p in self.root.iterdir() if p.is_file()}
            sources = sorted(n for n in self.members if CONVERSATIONS.fullmatch(n))
            if not self.archive and path.is_file():
                sources = [path.name]
            if not sources:
                raise ValueError("export has no conversations.json or conversations-NNN.json files")
            self.conversations = []
            for source in sources:
                conversations = self.read_json(source)
                if not isinstance(conversations, list):
                    raise ValueError(f"{source}: expected a conversation array")
                self.conversations.extend(conversations)
            ids = [c.get("id") or c.get("conversation_id") for c in self.conversations]
            if any(not isinstance(id, str) or not id for id in ids) or len(ids) != len(set(ids)):
                raise ValueError("export contains missing or duplicate conversation IDs")
            self.names = self.read_json("conversation_asset_file_names.json", {})
            self.library = {}
            for file in self.read_json("library_files.json", []):
                id = file.get("id")
                id = id.get("id") if isinstance(id, dict) else id
                if id:
                    self.library[id] = file
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.archive:
            self.archive.close()

    def read(self, member):
        if self.archive:
            return self.archive.read(member)
        path = (self.root / member).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError(f"export file escapes input directory: {member}")
        return path.read_bytes()

    def read_json(self, member, default=None):
        if member not in self.members:
            return default
        return json.loads(self.read(member))

    def select(self, conversation=None):
        if conversation:
            matches = [c for c in self.conversations
                       if conversation in (c.get("id"), c.get("conversation_id"))]
            if not matches:
                raise ValueError(f"conversation not found: {conversation}")
            return matches
        return self.conversations

    def metadata(self, conversation, cwd):
        id = conversation.get("id") or conversation["conversation_id"]
        try:
            session_id = str(uuid.UUID(id))
        except ValueError:
            session_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "chatgpt:" + id))
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return {"session_id": session_id, "title": conversation.get("title") or "ChatGPT conversation",
                "created_at": iso_time(conversation.get("create_time"), now),
                "model": conversation.get("default_model_slug") or "unknown",
                "provider": "openai", "api": "openai-responses", "cwd": str(cwd)}

    def ordered_nodes(self, conversation, branches):
        """Validate parent links and return parents first, independent of JSON key order."""
        mapping = conversation.get("mapping")
        current = conversation.get("current_node")
        if not isinstance(mapping, dict) or current not in mapping:
            raise ValueError("conversation has no valid mapping/current_node")
        ordered, visited = [], set()
        for tip in (mapping if branches else [current]):
            chain, pending = [], set()
            node = tip
            while node is not None and node not in visited:
                if node in pending:
                    raise ValueError("conversation contains a parent cycle")
                if node not in mapping:
                    raise ValueError(f"conversation references missing parent: {node}")
                pending.add(node)
                chain.append(node)
                if "parent" not in mapping[node]:
                    raise ValueError(f"conversation node has no parent field: {node}")
                node = mapping[node]["parent"]
            ordered.extend(reversed(chain))
            visited.update(chain)
        return ordered

    def resolve_asset(self, reference, attachment):
        library = self.library.get(attachment.get("library_file_id"), {})
        ids = [reference, attachment.get("id"), library.get("file_id")]
        for id in ids:
            if not isinstance(id, str):
                continue
            id = re.sub(r"^(?:file-service|sediment)://", "", id)
            for member in (id, id + ".dat"):
                if member in self.members:
                    return member, attachment.get("name") or self.names.get(member) or library.get("file_name") or id
        return None, attachment.get("name") or library.get("file_name") or reference or attachment.get("id") or "attachment"

    def tool_pairs(self, conversation, ordered, session_id):
        """Match parent-linked results to named calls with explicit JSON-object arguments.

        Do not guess argument schemas for code or manufacture calls for orphan results.
        Those messages use the displayed archival representation instead.
        """
        mapping = conversation["mapping"]
        parents, nearest = {}, {}
        for node_id in ordered:
            parents[node_id] = nearest.get(mapping[node_id]["parent"])
            nearest[node_id] = node_id if mapping[node_id].get("message") else parents[node_id]
        calls, results = {}, {}
        for node_id in ordered:
            message = mapping[node_id].get("message")
            if not message or message.get("author", {}).get("role") != "tool":
                continue
            parent = parents[node_id]
            caller = mapping[parent].get("message") if parent is not None else None
            if not caller or caller.get("author", {}).get("role") != "assistant":
                continue
            name = caller.get("recipient")
            if not isinstance(name, str) or not name or name == "all":
                continue
            if message["author"].get("name") not in (None, name):
                continue
            content = caller.get("content", {})
            parts = content.get("parts", [])
            if content.get("content_type") != "text" or len(parts) != 1 or not isinstance(parts[0], str):
                continue
            try:
                arguments = json.loads(parts[0])
                # Python accepts NaN/Infinity, but Pi's JSON reader does not.
                json.dumps(arguments, allow_nan=False)
            except ValueError:
                continue
            if not isinstance(arguments, dict):
                continue
            call_id = "chatgpt_" + uuid.uuid5(uuid.NAMESPACE_URL, f"{session_id}:{parent}:call").hex
            calls[parent] = {"type": "toolCall", "id": call_id, "name": name, "arguments": arguments}
            results[node_id] = calls[parent]
        # One entry may occur on several imported branches. Archive ambiguous calls
        # everywhere rather than leave a native call unanswered on another branch.
        unsafe = {parents[n] for n in ordered if mapping[n].get("message")
                  and parents[n] in calls and n not in results}
        tips = (set(ordered) - {mapping[n]["parent"] for n in ordered}) | {conversation["current_node"]}
        unsafe.update(nearest[n] for n in tips if nearest[n] in calls)
        calls = {n: call for n, call in calls.items() if n not in unsafe}
        call_ids = {call["id"] for call in calls.values()}
        return calls, {n: call for n, call in results.items() if call["id"] in call_ids}

    def import_conversation(self, conversation, destination, convert, cwd, branches=False):
        """Write one new session; leave existing outputs untouched and clean failed staging."""
        destination = destination.resolve()
        asset_dir = destination.with_suffix(".assets")
        if destination.exists() or asset_dir.exists():
            raise ValueError(f"destination already exists: {destination} (or its .assets directory)")
        payload = self.metadata(conversation, cwd)
        ordered = self.ordered_nodes(conversation, branches)
        mapping = conversation["mapping"]
        calls, results = self.tool_pairs(conversation, ordered, payload["session_id"])
        assets, parents, events = {}, {}, []
        for node_id in ordered:
            node = mapping[node_id]
            parent = parents.get(node["parent"])
            message = node.get("message")
            if not message:
                parents[node_id] = parent
                continue
            author = message.get("author", {})
            role = author.get("role")
            context = (f"conversation {json.dumps(payload['title'], ensure_ascii=False)} "
                       f"({json.dumps(conversation.get('id') or conversation['conversation_id'])}), "
                       f"message {json.dumps(node_id)}")
            content = self.content(message, role, asset_dir, assets, context)
            fields = {}
            if node_id in calls:
                content[0] = calls[node_id]
            elif node_id in results:
                call = results[node_id]
                role = "toolResult"
                fields["message_fields"] = {"toolCallId": call["id"], "toolName": call["name"],
                                            "isError": message.get("metadata", {}).get("is_error") is True}
            elif role not in ("user", "assistant") or message.get("recipient") not in (None, "all"):
                # Custom messages retain source roles without turning archived system
                # instructions into active system messages or inventing tool arguments.
                label = f"[Archived ChatGPT {role!r} message"
                if author.get("name"):
                    label += f" from {json.dumps(author['name'], ensure_ascii=False)}"
                if message.get("recipient") not in (None, "all"):
                    label += f" to {json.dumps(message['recipient'], ensure_ascii=False)}"
                content = [{"type": "text", "text": label + "]"}, *[
                    {"type": "text", "text": block["thinking"]} if block["type"] == "thinking" else block
                    for block in content]]
                fields["custom"] = {"source": "chatgpt", "message": message}
            if not content and role != "toolResult":
                parents[node_id] = parent
                continue
            entry_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"chatgpt:{payload['session_id']}:{node_id}"))
            parents[node_id] = entry_id
            model = message.get("metadata", {}).get("model_slug") or payload["model"]
            events.append({"type": "import_message", "role": role, "content": content,
                           "timestamp": iso_time(message.get("create_time"), payload["created_at"]),
                           "entry_id": entry_id, "parent_id": parent, "model": model, **fields})
        payload["selected_tip"] = parents[conversation["current_node"]]
        segments = [[{"type": "session_meta", "payload": payload}, *events]]
        destination.parent.mkdir(parents=True, exist_ok=True)
        published_assets = False
        with tempfile.TemporaryDirectory(prefix=".chatgpt-import-", dir=destination.parent) as temporary:
            staging = Path(temporary)
            for relative, data in assets.values():
                file = staging / "assets" / relative
                file.parent.mkdir(parents=True, exist_ok=True)
                file.write_bytes(data)
            count = convert(segments, staging / "session.jsonl")
            try:
                if assets:
                    # copytree's exclusive mkdir also refuses existing directories or symlinks.
                    asset_dir.mkdir()
                    published_assets = True
                    shutil.copytree(staging / "assets", asset_dir, dirs_exist_ok=True)
                # Hard-link publication is atomic and never replaces an existing session.
                os.link(staging / "session.jsonl", destination)
            except BaseException:
                if published_assets:
                    shutil.rmtree(asset_dir)
                raise
        return count

    def content(self, message, role, asset_dir, assets, context):
        blocks, seen = [], set()
        attachments = message.get("metadata", {}).get("attachments", [])

        def text(value):
            if value:
                blocks.append({"type": "text", "text": value})

        def asset(reference, info):
            member, name = self.resolve_asset(reference, info)
            identity = (member or info.get("library_file_id") or info.get("id")
                        or re.sub(r"^(?:file-service|sediment)://", "", reference or "") or name)
            if identity in seen:
                return
            seen.add(identity)
            if member is None:
                self.missing_attachments.append(f"{context}: attachment {json.dumps(name, ensure_ascii=False)}; "
                                        f"reference: {json.dumps(reference or info, ensure_ascii=False)}")
                text(f"[Missing ChatGPT attachment: {json.dumps(name)}; reference: {json.dumps(reference or info)}]")
                return
            if member not in assets:
                relative = Path(hashlib.sha256(member.encode()).hexdigest()[:16]) / safe_name(name)
                assets[member] = relative, self.read(member)
            relative, data = assets[member]
            mime = image_mime(data)
            if mime and role in ("user", "tool"):
                blocks.append({"type": "image", "data": base64.b64encode(data).decode("ascii"), "mimeType": mime})
            else:
                if info.get("mime_type", "").startswith("image/") and not mime:
                    self.warnings["images not supported by Pi; saved as files"] += 1
                text(f"[ChatGPT attachment: {json.dumps(name)}; saved to: {json.dumps(str(asset_dir / relative))}]")

        def unsupported(value):
            self.warnings["unrecognized content preserved as JSON text"] += 1
            text("[Unrecognized ChatGPT content]\n" + json.dumps(value, ensure_ascii=False))

        content = message.get("content", {})
        kind = content.get("content_type")
        if kind in ("text", "multimodal_text"):
            for part in content.get("parts", []):
                if isinstance(part, str):
                    text(part)
                elif isinstance(part, dict) and part.get("content_type") == "image_asset_pointer":
                    reference = part.get("asset_pointer", "")
                    id = re.sub(r"^(?:file-service|sediment)://", "", reference)
                    info = next((a for a in attachments if a.get("id") == id), {})
                    asset(reference, info)
                elif isinstance(part, dict) and part.get("content_type") == "audio_transcription":
                    text(part.get("text", ""))
                else:
                    unsupported(part)
        elif kind == "code":
            text(content.get("text", ""))
        elif kind in ("thoughts", "reasoning_recap") and role == "assistant":
            if kind == "reasoning_recap":
                thinking = content.get("content", "")
            else:
                thoughts = []
                for thought in content.get("thoughts", []):
                    summary = thought.get("summary", "")
                    body = thought.get("content") or "\n".join(thought.get("chunks", []))
                    thoughts.append("\n\n".join(s for s in (summary, body) if s))
                thinking = "\n\n".join(thoughts)
            if thinking:
                blocks.append({"type": "thinking", "thinking": thinking})
        else:
            unsupported(content)
        for attachment in attachments:
            asset(attachment.get("id"), attachment)
        return blocks
