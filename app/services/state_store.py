"""Persist runtime bot state between restarts."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set

from app.core import config


logger = logging.getLogger(__name__)


@dataclass
class BotStateSnapshot:
    """Serializable runtime state used by the Telegram bot."""

    invite_link_expires: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    active_invite_links: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    pending_members: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    sent_notifications: Set[str] = field(default_factory=set)
    last_sync_snapshot: Dict[str, Any] = field(default_factory=dict)


class BotStateStore:
    """Save and restore runtime state using a local JSON file."""

    def __init__(self, path: Optional[Path] = None):
        self.path = path or Path(config.BOT_STATE_FILE)

    def load_state(self) -> BotStateSnapshot:
        """Load state from disk, returning defaults when the file is absent or invalid."""
        if not self.path.exists():
            return BotStateSnapshot()

        try:
            raw_payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to load bot state from %s", self.path)
            return BotStateSnapshot()

        return BotStateSnapshot(
            invite_link_expires=self._deserialize_invite_link_expires(
                raw_payload.get("invite_link_expires", {})
            ),
            active_invite_links=dict(raw_payload.get("active_invite_links", {})),
            pending_members=self._deserialize_pending_members(
                raw_payload.get("pending_members", {})
            ),
            sent_notifications=set(raw_payload.get("sent_notifications", [])),
            last_sync_snapshot=dict(raw_payload.get("last_sync_snapshot", {})),
        )

    def save_state(
        self,
        *,
        invite_link_expires: Dict[str, Dict[str, Any]],
        active_invite_links: Dict[str, Dict[str, Any]],
        pending_members: Dict[str, Dict[str, Any]],
        sent_notifications: Set[str],
        last_sync_snapshot: Dict[str, Any],
    ):
        """Persist the current runtime state to disk atomically."""
        payload = {
            "invite_link_expires": self._serialize_invite_link_expires(invite_link_expires),
            "active_invite_links": active_invite_links,
            "pending_members": self._serialize_pending_members(pending_members),
            "sent_notifications": sorted(sent_notifications),
            "last_sync_snapshot": last_sync_snapshot,
        }

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temp_path.replace(self.path)

    def _serialize_invite_link_expires(
        self,
        invite_link_expires: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        payload = {}
        for invite_link, metadata in invite_link_expires.items():
            serialized_metadata = dict(metadata)
            for field_name in ("created_time", "expire_time"):
                field_value = serialized_metadata.get(field_name)
                if isinstance(field_value, datetime):
                    serialized_metadata[field_name] = field_value.isoformat()
            payload[invite_link] = serialized_metadata
        return payload

    def _deserialize_invite_link_expires(
        self,
        invite_link_expires: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        payload = {}
        for invite_link, metadata in invite_link_expires.items():
            deserialized_metadata = dict(metadata)
            for field_name in ("created_time", "expire_time"):
                field_value = deserialized_metadata.get(field_name)
                if isinstance(field_value, str):
                    try:
                        deserialized_metadata[field_name] = datetime.fromisoformat(field_value)
                    except ValueError:
                        logger.warning(
                            "Skipping invalid datetime for %s.%s: %s",
                            invite_link,
                            field_name,
                            field_value,
                        )
            payload[invite_link] = deserialized_metadata
        return payload

    @staticmethod
    def _serialize_pending_members(
        pending_members: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        payload = {}
        for user_id, member_info in pending_members.items():
            payload[user_id] = {
                "username": member_info.get("username", ""),
                "first_name": member_info.get("first_name", ""),
                "last_name": member_info.get("last_name", ""),
                "join_type": member_info.get("join_type", "default"),
                "expire_date_str": member_info.get("expire_date_str", ""),
                "timestamp": member_info.get("timestamp", ""),
                "chat_id": member_info.get("chat_id"),
                "approval_mode": member_info.get("approval_mode", "member_update"),
            }
        return payload

    @staticmethod
    def _deserialize_pending_members(
        pending_members: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        payload = {}
        for user_id, member_info in pending_members.items():
            normalized_member_info = dict(member_info)
            chat_id = normalized_member_info.get("chat_id")
            if chat_id is not None:
                try:
                    normalized_member_info["chat_id"] = int(chat_id)
                except (TypeError, ValueError):
                    normalized_member_info.pop("chat_id", None)
            payload[str(user_id)] = normalized_member_info
        return payload
