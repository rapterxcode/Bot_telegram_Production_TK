"""Membership event handlers for the Telegram bot."""

import logging
from datetime import datetime, timedelta

import pytz
from telegram import Update
from telegram.ext import ContextTypes

from app.core import config

logger = logging.getLogger(__name__)


class MembershipEventsMixin:
    """Encapsulate membership updates and join-request flows."""

    @staticmethod
    def _is_member_in_group(chat_member) -> bool:
        """Return True when the Telegram chat member still counts as present."""
        if not chat_member:
            return False

        status = getattr(chat_member, "status", "")
        if status in {"member", "administrator", "creator"}:
            return True
        if status == "restricted":
            return bool(getattr(chat_member, "is_member", False))
        return False

    @staticmethod
    def _format_actor_label(actor_user) -> str:
        """Build a compact actor label for audit fields."""
        if not actor_user:
            return ""
        if getattr(actor_user, "username", None):
            return f"@{actor_user.username}"
        full_name = " ".join(
            part for part in [actor_user.first_name, actor_user.last_name] if part
        ).strip()
        return full_name or f"user_{actor_user.id}"

    def _append_group_audit_log(
        self,
        *,
        user_id: str,
        username: str,
        action: str,
        old_value="",
        new_value="",
        actor: str = "",
        source: str = "",
        note: str = "",
    ):
        """Write a best-effort member audit log entry."""
        self.sheets_manager.append_audit_log(
            user_id=user_id,
            username=username,
            action=action,
            old_value=old_value,
            new_value=new_value,
            actor=actor,
            source=source,
            note=note,
        )

    async def track_chat_member_updates(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        result = await self.handle_chat_member_update(update.chat_member, context)
        if result:
            logger.info("Chat member update handled: %s", result)

    async def handle_chat_member_update(self, chat_member_update, context):
        if not chat_member_update:
            return None

        old_member = chat_member_update.old_chat_member
        new_member = chat_member_update.new_chat_member
        user = new_member.user
        user_id = str(user.id)
        username = f"@{user.username}" if user.username else f"User_{user.id}"
        first_name = user.first_name or ""
        last_name = user.last_name or ""
        actor_user = (
            chat_member_update.from_user
            if hasattr(chat_member_update, "from_user")
            else None
        )
        actor_label = self._format_actor_label(actor_user)

        if (
            not self._is_member_in_group(old_member)
            and self._is_member_in_group(new_member)
        ):
            target_group_id = self.group_chat_id or config.GROUP_CHAT_ID
            if chat_member_update.chat.id == target_group_id:
                existing_member = self.sheets_manager.get_member_record(
                    user_id,
                    include_inactive=True,
                )
                member_exists = bool(
                    existing_member and self.sheets_manager._is_member_active(existing_member)
                )

                if user_id in self.pending_members:
                    logger.info(
                        "User %s (ID: %s) already in pending list, skipping duplicate notification",
                        username,
                        user_id,
                    )
                    return f"User already in pending list: {user_id}"

                if not member_exists:
                    added_by_admin = False
                    if hasattr(chat_member_update, "from_user") and chat_member_update.from_user:
                        added_by_admin = config.is_admin(chat_member_update.from_user.id)

                    if added_by_admin:
                        current_time = datetime.now(pytz.timezone(config.TIMEZONE))
                        expire_days = config.DEFAULT_EXPIRE_DAYS
                        default_expire = current_time + timedelta(days=expire_days)
                        expire_date_str = default_expire.strftime("%Y-%m-%d %H:%M:%S")

                        success = self.sheets_manager.add_member_with_details(
                            username,
                            user_id,
                            expire_date_str,
                            first_name,
                            last_name,
                            metadata={
                                "Role": "admin"
                                if new_member.status in ["administrator", "creator"]
                                else "member",
                                "Telegram Status": new_member.status,
                                "Record Status": "active",
                                "In Group Now": "Yes",
                                "Join Source": "admin_added",
                                "Expire Policy Days": expire_days,
                                "Joined At": current_time.strftime("%Y-%m-%d %H:%M:%S"),
                                "Added By": actor_label,
                                "Last Seen In Group At": current_time.strftime("%Y-%m-%d %H:%M:%S"),
                                "Last Sync Result": "member_joined",
                                "Sync Note": "Added by admin in Telegram",
                                "Sync Source": "chat_member_update",
                            },
                        )

                        if success:
                            self._append_group_audit_log(
                                user_id=user_id,
                                username=username,
                                action="member_joined",
                                new_value={
                                    "Username": username,
                                    "User ID": user_id,
                                    "Join Source": "admin_added",
                                    "Expiredate": expire_date_str,
                                },
                                actor=actor_label,
                                source="chat_member_update",
                                note="Admin added a member directly in Telegram",
                            )
                            admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
                            if admin_group_id:
                                await context.bot.send_message(
                                    chat_id=admin_group_id,
                                    text=(
                                        "แอดมินเพิ่มสมาชิกใหม่แล้ว ระบบจึงบันทึกข้อมูลให้อัตโนมัติ\n"
                                        f"Username: {username}\n"
                                        f"User ID: {user_id}\n"
                                        f"วันหมดอายุ: {expire_date_str}\n"
                                        "วิธีเพิ่ม: เพิ่มโดยแอดมินใน Telegram"
                                    ),
                                )
                            return f"Auto-added to Google Sheet: {username}"

                        admin_group_id = config.GROUP_CHAT_ID_FOR_ADMIN
                        if admin_group_id:
                            await context.bot.send_message(
                                chat_id=admin_group_id,
                                text=(
                                    "แอดมินเพิ่มสมาชิกใหม่แล้ว แต่บันทึกข้อมูลไม่สำเร็จ\n"
                                    f"Username: {username}\n"
                                    f"User ID: {user_id}\n"
                                    "กรุณาใช้คำสั่ง /addmember เพื่อบันทึกข้อมูลด้วยตนเอง"
                                ),
                            )
                    else:
                        current_time = datetime.now(pytz.timezone(config.TIMEZONE))
                        join_type = "default"

                        if self.recent_join_type == "1month":
                            expire_days = config.INVITE_LINK_1MONTH_DAYS
                            default_expire = current_time + timedelta(days=expire_days)
                            expire_date_str = default_expire.strftime("%Y-%m-%d %H:%M:%S")
                            join_type = self.recent_join_type
                        elif self.recent_join_type == "1year":
                            expire_days = config.INVITE_LINK_1YEAR_DAYS
                            default_expire = current_time + timedelta(days=expire_days)
                            expire_date_str = default_expire.strftime("%Y-%m-%d %H:%M:%S")
                            join_type = self.recent_join_type
                        elif self.recent_join_type == "noexpire":
                            expire_date_str = config.INVITE_LINK_NOEXPIRE
                            join_type = self.recent_join_type
                        else:
                            expire_days = config.DEFAULT_EXPIRE_DAYS
                            default_expire = current_time + timedelta(days=expire_days)
                            expire_date_str = default_expire.strftime("%Y-%m-%d %H:%M:%S")

                        logger.info(
                            "Member update - Type: %s, Expire: %s",
                            join_type,
                            expire_date_str,
                        )

                        self.store_pending_member(
                            user_id,
                            {
                                "username": username,
                                "first_name": first_name,
                                "last_name": last_name,
                                "join_type": join_type,
                                "join_source": "member_update",
                                "invite_link_label": "",
                                "expire_policy_days": expire_days if join_type == "default" else (
                                    config.INVITE_LINK_1MONTH_DAYS
                                    if join_type == "1month"
                                    else config.INVITE_LINK_1YEAR_DAYS
                                    if join_type == "1year"
                                    else config.INVITE_LINK_NOEXPIRE
                                ),
                                "expire_date_str": expire_date_str,
                                "timestamp": current_time.strftime("%d/%m/%Y %H:%M:%S"),
                                "approval_mode": "member_update",
                            },
                        )
                        self.recent_join_type = "default"

                        await self.notify_all_admins_with_buttons(
                            context,
                            user_id,
                            username,
                            first_name,
                            last_name,
                            expire_date_str,
                        )
                        self._append_group_audit_log(
                            user_id=user_id,
                            username=username,
                            action="member_joined_pending_review",
                            new_value={
                                "Username": username,
                                "User ID": user_id,
                                "Join Source": "member_update",
                                "Expiredate": expire_date_str,
                            },
                            actor=actor_label,
                            source="chat_member_update",
                            note="Member joined the group and is waiting for approval flow",
                        )

                    logger.info("New member added to pending list: %s (ID: %s)", username, user_id)
                    return f"New member pending approval: {user_id}"

        elif self._is_member_in_group(old_member) and not self._is_member_in_group(new_member):
            target_group_id = self.group_chat_id or config.GROUP_CHAT_ID
            if chat_member_update.chat.id != target_group_id:
                return None

            existing_member = self.sheets_manager.get_member_record(
                user_id,
                include_inactive=True,
            )
            removed_at = datetime.now(pytz.timezone(config.TIMEZONE)).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            new_status = getattr(new_member, "status", "left")
            if new_status == "kicked":
                remove_reason = "Removed from Telegram group"
                audit_action = "member_kicked_from_group"
                note = "Telegram reported that the member was removed from the group"
            else:
                remove_reason = "Left Telegram group"
                audit_action = "member_left_group"
                note = "Telegram reported that the member left the group"

            if existing_member and self.sheets_manager._is_member_active(existing_member):
                self.sheets_manager.remove_member_from_sheet(
                    user_id=user_id,
                    removed_at=removed_at,
                    remove_reason=remove_reason,
                    actor=actor_label,
                    source="chat_member_update",
                    note=note,
                    audit_action=audit_action,
                    last_seen_in_group_at=removed_at,
                )
            else:
                self._append_group_audit_log(
                    user_id=user_id,
                    username=username,
                    action=audit_action,
                    old_value={
                        "Username": username,
                        "User ID": user_id,
                        "Telegram Status": getattr(old_member, "status", ""),
                    },
                    new_value={
                        "Telegram Status": new_status,
                        "Record Status": "removed",
                        "In Group Now": "No",
                        "Last Seen In Group At": removed_at,
                        "Removed At": removed_at,
                        "Remove Reason": remove_reason,
                    },
                    actor=actor_label,
                    source="chat_member_update",
                    note=note,
                )

            return f"Member removed from group: {user_id}"

        elif old_member and new_member and old_member.status == new_member.status:
            old_username = old_member.user.username
            new_username = new_member.user.username

            if old_username != new_username and new_username:
                success = self.sheets_manager.update_username(user_id, f"@{new_username}")
                if success:
                    logger.info(
                        "Updated username for user %s: %s -> @%s",
                        user_id,
                        old_username,
                        new_username,
                    )
                    return f"Username updated: {user_id}"

        return None

    async def handle_chat_join_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        logger.info("Received chat join request")

        if not update.chat_join_request:
            logger.warning("No chat_join_request in update")
            return

        join_request = update.chat_join_request
        user = join_request.from_user
        user_id = str(user.id)
        username = f"@{user.username}" if user.username else f"User_{user.id}"
        first_name = user.first_name or ""
        last_name = user.last_name or ""

        logger.info("Join request from: %s (ID: %s)", username, user_id)
        logger.info("Request for chat ID: %s", join_request.chat.id)

        target_group_id = self.group_chat_id or config.GROUP_CHAT_ID
        logger.info("Target group ID: %s", target_group_id)

        if join_request.chat.id != target_group_id:
            logger.info(
                "Chat ID mismatch. Expected: %s, Got: %s",
                target_group_id,
                join_request.chat.id,
            )
            return

        existing_member = self.sheets_manager.get_member_record(
            user_id,
            include_inactive=True,
        )
        member_exists = bool(
            existing_member and self.sheets_manager._is_member_active(existing_member)
        )
        logger.info("Member exists in sheet: %s", member_exists)

        if member_exists:
            logger.info("User %s (ID: %s) already exists in sheet, skipping", username, user_id)
            return

        current_time = datetime.now(pytz.timezone(config.TIMEZONE))
        invite_link_used = None
        link_info = None
        join_type = "default"

        self._cleanup_expired_invite_links()

        if hasattr(join_request, "invite_link") and join_request.invite_link:
            if hasattr(join_request.invite_link, "invite_link"):
                invite_link_used = join_request.invite_link.invite_link
            else:
                invite_link_used = str(join_request.invite_link)
            logger.info("Invite link found in join_request: %s", invite_link_used)
        else:
            logger.info("No invite_link found in join_request")

        active_links = list(self.active_invite_links.keys())
        logger.info("Available active invite links: %s links", len(active_links))
        for link in active_links:
            logger.info("Active invite link %s: %s", link, self.active_invite_links[link])

        if invite_link_used and invite_link_used in self.active_invite_links:
            link_info = self.active_invite_links[invite_link_used]
            logger.info("Exact match found for %s: %s", invite_link_used, link_info)
        elif invite_link_used and not link_info:
            for stored_link, stored_info in self.active_invite_links.items():
                if invite_link_used in stored_link or stored_link in invite_link_used:
                    link_info = stored_info
                    logger.info(
                        "Partial match found: %s matches %s",
                        stored_link,
                        invite_link_used,
                    )
                    break

        if not link_info and self.invite_link_expires:
            recent_threshold = current_time - timedelta(minutes=5)
            recent_links = []
            for link, info in self.invite_link_expires.items():
                if info.get("created_time", current_time) > recent_threshold:
                    recent_links.append((link, info))

            if recent_links:
                latest_link = max(
                    recent_links,
                    key=lambda item: item[1].get("created_time", current_time),
                )
                link_info = {
                    "type": latest_link[1]["type"],
                    "days": latest_link[1]["days"],
                    "period_name": latest_link[1]["period_name"],
                }
                invite_link_used = latest_link[0]
                logger.info(
                    "Using recent link (within 5 min): %s with info: %s",
                    invite_link_used,
                    link_info,
                )

        if link_info:
            days = link_info["days"]
            join_type = link_info["type"]

            if days == "no_expire":
                expire_date_str = config.INVITE_LINK_NOEXPIRE
            else:
                default_expire = current_time + timedelta(days=days)
                expire_date_str = default_expire.strftime("%Y-%m-%d %H:%M:%S")

            logger.info(
                "Final result - Type: %s, Days: %s, Expire: %s",
                join_type,
                days,
                expire_date_str,
            )
        else:
            expire_days = config.DEFAULT_EXPIRE_DAYS
            default_expire = current_time + timedelta(days=expire_days)
            expire_date_str = default_expire.strftime("%Y-%m-%d %H:%M:%S")
            logger.info(
                "Using default fallback - Type: %s, Days: %s, Expire: %s",
                join_type,
                expire_days,
                expire_date_str,
            )

        self.store_pending_member(
            user_id,
            {
                "username": username,
                "first_name": first_name,
                "last_name": last_name,
                "join_type": join_type,
                "join_source": "join_request",
                "invite_link_label": link_info.get("period_name", "") if link_info else "",
                "expire_policy_days": (
                    link_info.get("days")
                    if link_info
                    else config.DEFAULT_EXPIRE_DAYS
                ),
                "expire_date_str": expire_date_str,
                "timestamp": current_time.strftime("%d/%m/%Y %H:%M:%S"),
                "chat_id": join_request.chat.id,
                "approval_mode": "join_request",
            },
        )
        self.recent_join_type = "default"

        logger.info("Sending notification to admin group for user %s", user_id)
        await self.notify_all_admins_with_join_request_buttons(
            context,
            user_id,
            username,
            first_name,
            last_name,
            expire_date_str,
        )

        logger.info("New join request added to pending list: %s (ID: %s)", username, user_id)
