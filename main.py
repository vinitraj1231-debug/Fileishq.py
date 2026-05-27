#!/usr/bin/env python3
"""
Blaze Bot – Community Telegram Bot v2
Features: Force-sub, Referral system, Premium, Owner↔User reply, Broadcast, Ban/Unban
New: Owner notified on referral premium unlock, Premium user list, Remove premium, Updated welcome
"""
import asyncio
import html
import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import ASCENDING
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
    WebAppInfo,
)
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ═══════════════════════════════════════════════════════════════
#  CONFIG  — set all secrets via environment variables
# ═══════════════════════════════════════════════════════════════
BOT_TOKEN      = os.getenv("BOT_TOKEN", "8688366162:AAFrX1Nx3Q1nisUkAl-7Sot2k_jOXoiy-O8").strip()
OWNER_ID       = int(os.getenv("OWNER_ID", "8647666069"))
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "SoulEgoisticVertex").strip().lstrip("@")

MINI_APP_URL = os.getenv("MINI_APP_URL", "http://t.me/ItsBlaze_bot/BLAZE").strip()
START_PHOTO  = os.getenv(
    "START_PHOTO",
    "https://i.ibb.co/r2vdvLdP/43f0c9c7b235.jpg",
).strip()
SUPPORT_URL = os.getenv("SUPPORT_URL", "").strip()
UPDATE_URL  = os.getenv("UPDATE_URL", "").strip()
BOT_NAME    = os.getenv("BOT_NAME", "Blaze Bot").strip()

PREMIUM_TEXT = os.getenv(
    "PREMIUM_TEXT",
    (
        "💎 <b>Premium Plans</b>\n\n"
        "𝖯𝖱𝖨𝖢𝖨𝖭𝖦\n"
        "╭──────────\n"
        "• ₹19 : 3 Days\n"
        "• ₹59 : 1 Week\n"
        "• ₹249 : 1 Month\n"
        "• ₹349 : 2 Months\n"
        "• ₹449 : 3 Months [Best]\n"
        "• ₹599 : 6 Months\n"
        "• ₹899 : 9 Months\n"
        "• ₹1299 : 12 Months\n"
        "• ₹2999 : Lifetime Plan\n"
        "╰──────────\n\n"
        "𝖡𝖤𝖭𝖤𝖥𝖨𝖳𝖲\n"
        "• No Link Shortener – Direct links, no ads\n"
        "• Premium Requests – Request content\n"
        "• One Membership – Access all channels\n"
        "• Quick Access – Instant on click\n"
        "• Faster Uploads – Priority content delivery\n"
        "• Best Value – Totally worth it!\n\n"
        "Use the button below to contact the owner for premium purchase."
    ),
).strip()

MONGO_URI    = os.getenv("MONGO_URI", "").strip()
JSON_DB_PATH = Path(os.getenv("JSON_DB_PATH", "bot_data.json")).resolve()

REFERRAL_THRESHOLD   = int(os.getenv("REFERRAL_THRESHOLD", "20"))
REFERRAL_REWARD_DAYS = int(os.getenv("REFERRAL_REWARD_DAYS", "3"))

if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN env var is required")
if not MINI_APP_URL:
    raise SystemExit("MINI_APP_URL env var is required")

pending_requests: set[int] = set()
storage = None  # assigned in main()


# ═══════════════════════════════════════════════════════════════
#  UTILS
# ═══════════════════════════════════════════════════════════════
def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_owner(user_id) -> bool:
    return bool(user_id) and int(user_id) == OWNER_ID


def owner_link() -> str:
    return f"https://t.me/{OWNER_USERNAME}" if OWNER_USERNAME else f"tg://user?id={OWNER_ID}"


def support_link() -> str:
    return SUPPORT_URL or owner_link()


def update_link() -> str:
    return UPDATE_URL or owner_link()


def parse_text_arg(text: str) -> str:
    parts = text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def split_bar_args(text: str) -> list[str]:
    raw = parse_text_arg(text)
    return [p.strip() for p in raw.split("|") if p.strip()]


def normalize_chat_ref(value: str) -> str:
    value = value.strip()
    if value.startswith("@") or value.startswith("-") or value.isdigit():
        return value
    if value.startswith(("https://t.me/", "http://t.me/")):
        path = value.split("t.me/", 1)[1].split("?", 1)[0].strip("/")
        if path and not path.startswith("+"):
            return "@" + path
        return value  # private invite link – return as-is
    return value


def normalize_url(value: str, chat_ref: str) -> str:
    value = value.strip()
    if value.startswith(("http://", "https://", "tg://")):
        return value
    if chat_ref.startswith("@"):
        return f"https://t.me/{chat_ref.lstrip('@')}"
    return value or chat_ref


def format_user_name(user) -> str:
    name = user.first_name or "User"
    if user.last_name:
        name += f" {user.last_name}"
    return html.escape(name)


# Small-caps Unicode converter
_SC_MAP = str.maketrans(
    "abcdefghijklmnopqrstuvwxyz",
    "ᴀʙᴄᴅᴇꜰɢʜɪᴊᴋʟᴍɴᴏᴘǫʀꜱᴛᴜᴠᴡxʏᴢ",
)

def sc(text: str) -> str:
    """Convert ASCII letters to Unicode small-caps (non-letter chars pass through)."""
    return text.lower().translate(_SC_MAP)


async def _reply_new(
    query,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    reply_markup=None,
    **kwargs,
) -> None:
    """
    Delete the triggering message (which may be a photo/caption) and send
    a clean new text message. Fixes 'There is no text in the message to edit'.
    """
    chat_id = query.message.chat.id
    try:
        await query.message.delete()
    except Exception:
        pass
    await context.bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=reply_markup,
        **kwargs,
    )


def _flexible_match(stored: dict, target: str) -> bool:
    """Case-insensitive flexible match across key/chat/title/url fields."""
    t = target.strip().lower()
    t_bare = re.sub(r"^https?://t\.me/", "", t).lstrip("@")
    for field in ("key", "chat", "title", "url"):
        v = (stored.get(field) or "").strip().lower()
        if not v:
            continue
        if v == t:
            return True
        v_bare = re.sub(r"^https?://t\.me/", "", v).lstrip("@")
        if v_bare and v_bare == t_bare:
            return True
    return False


# ═══════════════════════════════════════════════════════════════
#  BASE STORAGE
# ═══════════════════════════════════════════════════════════════
class BaseStorage:
    async def init(self) -> None: ...
    async def save_user(self, user) -> None: ...
    async def is_banned(self, user_id: int) -> bool: return False
    async def ban_user(self, user_id: int) -> None: ...
    async def unban_user(self, user_id: int) -> bool: return False
    async def add_request(self, user, text: str) -> None: ...
    async def count_users(self) -> int: return 0
    async def count_requests(self) -> int: return 0
    async def count_bans(self) -> int: return 0
    async def list_users(self) -> List[int]: return []
    async def add_force_sub(self, key: str, title: str, chat: str, url: str) -> None: ...
    async def remove_force_sub(self, target: str) -> bool: return False
    async def list_force_subs(self) -> List[Dict[str, Any]]: return []
    async def count_force_subs(self) -> int: return 0
    async def add_channel(self, key: str, title: str, url: str) -> None: ...
    async def remove_channel(self, target: str) -> bool: return False
    async def list_channels(self) -> List[Dict[str, Any]]: return []
    async def count_channels(self) -> int: return 0
    async def add_force_request(self, user_id: int, username: str, first_name: str, link: str) -> None: ...
    async def get_force_requests(self) -> List[Dict[str, Any]]: return []
    async def delete_force_request(self, index: int) -> bool: return False
    # Owner ↔ User reply mapping
    async def save_msg_map(self, msg_id: int, user_id: int) -> None: ...
    async def get_msg_user(self, msg_id: int) -> Optional[int]: return None
    # Referral & Premium
    async def add_referral(self, referrer_id: int, new_user_id: int) -> bool: return False
    async def get_referral_count(self, user_id: int) -> int: return 0
    async def is_premium(self, user_id: int) -> bool: return False
    async def set_premium(self, user_id: int, days: int) -> None: ...
    async def get_premium_until(self, user_id: int) -> Optional[str]: return None
    async def remove_premium(self, user_id: int) -> bool: return False
    async def list_premium_users(self) -> List[Dict[str, Any]]: return []


# ═══════════════════════════════════════════════════════════════
#  JSON STORAGE
# ═══════════════════════════════════════════════════════════════
class JsonStorage(BaseStorage):
    def __init__(self, path: Path):
        self.path = path
        self.lock = asyncio.Lock()
        self.data: Dict[str, Any] = {
            "users": {},
            "requests": [],
            "bans": {},
            "force_subs": {},
            "channels": {},
            "force_requests": [],
            "msg_map": {},       # {msg_id_str: user_id}
            "referrals": {},     # {user_id_str: {count, referred_users, premium_until, referred_by}}
        }

    async def init(self) -> None:
        if self.path.exists():
            try:
                raw = await asyncio.to_thread(self.path.read_text, encoding="utf-8")
                loaded = json.loads(raw)
                if isinstance(loaded, dict):
                    for key in self.data:
                        if key in loaded and isinstance(loaded[key], type(self.data[key])):
                            self.data[key] = loaded[key]
            except Exception as exc:
                print(f"[JsonStorage] Could not load existing DB: {exc}")
        await self._save()

    async def _save(self) -> None:
        async with self.lock:
            payload = json.dumps(self.data, ensure_ascii=False, indent=2)
            await asyncio.to_thread(self.path.write_text, payload, "utf-8")

    # ── users ──────────────────────────────────────────────────
    async def save_user(self, user) -> None:
        async with self.lock:
            self.data["users"][str(user.id)] = {
                "user_id": user.id,
                "first_name": user.first_name or "",
                "last_name": user.last_name or "",
                "username": user.username or "",
                "language_code": getattr(user, "language_code", "") or "",
                "updated_at": now_utc(),
            }
        await self._save()

    async def count_users(self) -> int:
        return len(self.data["users"])

    async def list_users(self) -> List[int]:
        return [int(k) for k in self.data["users"]]

    # ── bans ───────────────────────────────────────────────────
    async def is_banned(self, user_id: int) -> bool:
        return str(user_id) in self.data["bans"]

    async def ban_user(self, user_id: int) -> None:
        async with self.lock:
            self.data["bans"][str(user_id)] = {"user_id": user_id, "banned_at": now_utc()}
        await self._save()

    async def unban_user(self, user_id: int) -> bool:
        async with self.lock:
            existed = str(user_id) in self.data["bans"]
            self.data["bans"].pop(str(user_id), None)
        if existed:
            await self._save()
        return existed

    async def count_bans(self) -> int:
        return len(self.data["bans"])

    # ── requests ───────────────────────────────────────────────
    async def add_request(self, user, text: str) -> None:
        async with self.lock:
            self.data["requests"].append({
                "user_id": user.id,
                "username": user.username or "",
                "first_name": user.first_name or "",
                "text": text,
                "created_at": now_utc(),
            })
        await self._save()

    async def count_requests(self) -> int:
        return len(self.data["requests"])

    # ── force subs ─────────────────────────────────────────────
    async def add_force_sub(self, key: str, title: str, chat: str, url: str) -> None:
        async with self.lock:
            self.data["force_subs"][key] = {
                "key": key, "title": title, "chat": chat,
                "url": url, "created_at": now_utc(),
            }
        await self._save()

    async def remove_force_sub(self, target: str) -> bool:
        remove_key = None
        async with self.lock:
            for k, v in self.data["force_subs"].items():
                if _flexible_match(v, target):
                    remove_key = k
                    break
            if remove_key:
                del self.data["force_subs"][remove_key]
        if remove_key:
            await self._save()
            return True
        return False

    async def list_force_subs(self) -> List[Dict[str, Any]]:
        return list(self.data["force_subs"].values())

    async def count_force_subs(self) -> int:
        return len(self.data["force_subs"])

    # ── channels ───────────────────────────────────────────────
    async def add_channel(self, key: str, title: str, url: str) -> None:
        async with self.lock:
            self.data["channels"][key] = {
                "key": key, "title": title, "url": url, "created_at": now_utc(),
            }
        await self._save()

    async def remove_channel(self, target: str) -> bool:
        remove_key = None
        async with self.lock:
            for k, v in self.data["channels"].items():
                if _flexible_match(v, target):
                    remove_key = k
                    break
            if remove_key:
                del self.data["channels"][remove_key]
        if remove_key:
            await self._save()
            return True
        return False

    async def list_channels(self) -> List[Dict[str, Any]]:
        return list(self.data["channels"].values())

    async def count_channels(self) -> int:
        return len(self.data["channels"])

    # ── force requests ─────────────────────────────────────────
    async def add_force_request(self, user_id: int, username: str, first_name: str, link: str) -> None:
        async with self.lock:
            self.data["force_requests"].append({
                "user_id": user_id, "username": username,
                "first_name": first_name, "link": link, "created_at": now_utc(),
            })
        await self._save()

    async def get_force_requests(self) -> List[Dict[str, Any]]:
        return list(self.data["force_requests"])

    async def delete_force_request(self, index: int) -> bool:
        deleted = False
        async with self.lock:
            if 0 <= index < len(self.data["force_requests"]):
                self.data["force_requests"].pop(index)
                deleted = True
        if deleted:
            await self._save()
        return deleted

    # ── msg map (owner ↔ user reply) ───────────────────────────
    async def save_msg_map(self, msg_id: int, user_id: int) -> None:
        async with self.lock:
            self.data["msg_map"][str(msg_id)] = user_id
            # Trim to 2000 entries to prevent unbounded growth
            if len(self.data["msg_map"]) > 2000:
                for old_key in list(self.data["msg_map"].keys())[:500]:
                    del self.data["msg_map"][old_key]
        await self._save()

    async def get_msg_user(self, msg_id: int) -> Optional[int]:
        val = self.data["msg_map"].get(str(msg_id))
        return int(val) if val is not None else None

    # ── referral & premium ─────────────────────────────────────
    def _ref_entry(self, user_id: int) -> dict:
        """Get-or-create referral entry. Must be called while holding self.lock."""
        key = str(user_id)
        if key not in self.data["referrals"]:
            self.data["referrals"][key] = {
                "count": 0,
                "referred_users": [],
                "premium_until": None,
                "referred_by": None,
            }
        return self.data["referrals"][key]

    async def add_referral(self, referrer_id: int, new_user_id: int) -> bool:
        """Returns True when referral count hits a multiple of REFERRAL_THRESHOLD."""
        hit = False
        async with self.lock:
            rd = self._ref_entry(referrer_id)
            if new_user_id not in rd["referred_users"]:
                rd["referred_users"].append(new_user_id)
                rd["count"] += 1
                if rd["count"] % REFERRAL_THRESHOLD == 0:
                    hit = True
            # Mark the new user's referrer (first-time only)
            nd = self._ref_entry(new_user_id)
            if nd["referred_by"] is None:
                nd["referred_by"] = referrer_id
        await self._save()
        return hit

    async def get_referral_count(self, user_id: int) -> int:
        return self.data["referrals"].get(str(user_id), {}).get("count", 0)

    async def is_premium(self, user_id: int) -> bool:
        pt = self.data["referrals"].get(str(user_id), {}).get("premium_until")
        if not pt:
            return False
        try:
            return datetime.fromisoformat(pt) > datetime.now(timezone.utc)
        except Exception:
            return False

    async def set_premium(self, user_id: int, days: int) -> None:
        async with self.lock:
            rd = self._ref_entry(user_id)
            base = datetime.now(timezone.utc)
            try:
                existing = datetime.fromisoformat(rd.get("premium_until") or "")
                if existing > base:
                    base = existing  # Extend from current expiry
            except Exception:
                pass
            rd["premium_until"] = (base + timedelta(days=days)).isoformat()
        await self._save()

    async def get_premium_until(self, user_id: int) -> Optional[str]:
        return self.data["referrals"].get(str(user_id), {}).get("premium_until")

    async def remove_premium(self, user_id: int) -> bool:
        async with self.lock:
            rd = self.data["referrals"].get(str(user_id))
            if not rd or not rd.get("premium_until"):
                return False
            rd["premium_until"] = None
        await self._save()
        return True

    async def list_premium_users(self) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        results = []
        for uid_str, rd in self.data["referrals"].items():
            pt = rd.get("premium_until")
            if not pt:
                continue
            try:
                if datetime.fromisoformat(pt) > now:
                    results.append({"user_id": int(uid_str), "premium_until": pt})
            except Exception:
                pass
        return results


# ═══════════════════════════════════════════════════════════════
#  MONGO STORAGE
# ═══════════════════════════════════════════════════════════════
class MongoStorage(BaseStorage):
    def __init__(self, uri: str):
        self.client = AsyncIOMotorClient(uri)
        self.db = self.client["blaze_bot"]
        self.users_col          = self.db["users"]
        self.requests_col       = self.db["requests"]
        self.bans_col           = self.db["bans"]
        self.force_subs_col     = self.db["force_subs"]
        self.channels_col       = self.db["channels"]
        self.force_requests_col = self.db["force_requests"]
        self.msg_map_col        = self.db["msg_map"]
        self.referrals_col      = self.db["referrals"]

    async def init(self) -> None:
        await self.client.admin.command("ping")
        await self.users_col.create_index([("user_id", ASCENDING)], unique=True)
        await self.requests_col.create_index([("created_at", ASCENDING)])
        await self.bans_col.create_index([("user_id", ASCENDING)], unique=True)
        await self.force_subs_col.create_index([("key", ASCENDING)], unique=True)
        await self.channels_col.create_index([("key", ASCENDING)], unique=True)
        await self.force_requests_col.create_index([("created_at", ASCENDING)])
        await self.msg_map_col.create_index([("msg_id", ASCENDING)], unique=True)
        await self.msg_map_col.create_index([("created_at", ASCENDING)])
        await self.referrals_col.create_index([("user_id", ASCENDING)], unique=True)

    async def save_user(self, user) -> None:
        await self.users_col.update_one(
            {"user_id": user.id},
            {
                "$set": {
                    "user_id": user.id,
                    "first_name": user.first_name or "",
                    "last_name": user.last_name or "",
                    "username": user.username or "",
                    "language_code": getattr(user, "language_code", "") or "",
                    "updated_at": now_utc(),
                },
                "$setOnInsert": {"joined_at": now_utc()},
            },
            upsert=True,
        )

    async def is_banned(self, user_id: int) -> bool:
        return await self.bans_col.find_one({"user_id": user_id}) is not None

    async def ban_user(self, user_id: int) -> None:
        await self.bans_col.update_one(
            {"user_id": user_id},
            {"$set": {"user_id": user_id, "banned_at": now_utc()}},
            upsert=True,
        )

    async def unban_user(self, user_id: int) -> bool:
        res = await self.bans_col.delete_one({"user_id": user_id})
        return res.deleted_count > 0

    async def add_request(self, user, text: str) -> None:
        await self.requests_col.insert_one({
            "user_id": user.id, "username": user.username or "",
            "first_name": user.first_name or "", "text": text, "created_at": now_utc(),
        })

    async def count_users(self) -> int:
        return await self.users_col.count_documents({})

    async def count_requests(self) -> int:
        return await self.requests_col.count_documents({})

    async def count_bans(self) -> int:
        return await self.bans_col.count_documents({})

    async def list_users(self) -> List[int]:
        rows = await self.users_col.find({}, {"user_id": 1, "_id": 0}).to_list(length=None)
        return [int(r["user_id"]) for r in rows if r.get("user_id") is not None]

    async def add_force_sub(self, key: str, title: str, chat: str, url: str) -> None:
        await self.force_subs_col.update_one(
            {"key": key},
            {"$set": {"key": key, "title": title, "chat": chat, "url": url, "updated_at": now_utc()},
             "$setOnInsert": {"created_at": now_utc()}},
            upsert=True,
        )

    async def remove_force_sub(self, target: str) -> bool:
        t = target.strip()
        t_norm = re.sub(r"^https?://t\.me/", "@", t)
        res = await self.force_subs_col.delete_one({
            "$or": [
                {"key": {"$regex": f"^{re.escape(t)}$", "$options": "i"}},
                {"chat": {"$regex": f"^{re.escape(t)}$", "$options": "i"}},
                {"title": {"$regex": f"^{re.escape(t)}$", "$options": "i"}},
                {"url": {"$regex": f"^{re.escape(t)}$", "$options": "i"}},
                {"key": {"$regex": f"^{re.escape(t_norm)}$", "$options": "i"}},
                {"chat": {"$regex": f"^{re.escape(t_norm)}$", "$options": "i"}},
            ]
        })
        return res.deleted_count > 0

    async def list_force_subs(self) -> List[Dict[str, Any]]:
        return await self.force_subs_col.find({}, {"_id": 0}).to_list(length=None)

    async def count_force_subs(self) -> int:
        return await self.force_subs_col.count_documents({})

    async def add_channel(self, key: str, title: str, url: str) -> None:
        await self.channels_col.update_one(
            {"key": key},
            {"$set": {"key": key, "title": title, "url": url, "updated_at": now_utc()},
             "$setOnInsert": {"created_at": now_utc()}},
            upsert=True,
        )

    async def remove_channel(self, target: str) -> bool:
        t = target.strip()
        t_norm = re.sub(r"^https?://t\.me/", "@", t)
        res = await self.channels_col.delete_one({
            "$or": [
                {"key": {"$regex": f"^{re.escape(t)}$", "$options": "i"}},
                {"title": {"$regex": f"^{re.escape(t)}$", "$options": "i"}},
                {"url": {"$regex": f"^{re.escape(t)}$", "$options": "i"}},
                {"key": {"$regex": f"^{re.escape(t_norm)}$", "$options": "i"}},
                {"url": {"$regex": f"^{re.escape(t_norm)}$", "$options": "i"}},
            ]
        })
        return res.deleted_count > 0

    async def list_channels(self) -> List[Dict[str, Any]]:
        return await self.channels_col.find({}, {"_id": 0}).to_list(length=None)

    async def count_channels(self) -> int:
        return await self.channels_col.count_documents({})

    async def add_force_request(self, user_id: int, username: str, first_name: str, link: str) -> None:
        await self.force_requests_col.insert_one({
            "user_id": user_id, "username": username,
            "first_name": first_name, "link": link, "created_at": now_utc(),
        })

    async def get_force_requests(self) -> List[Dict[str, Any]]:
        return await self.force_requests_col.find({}, {"_id": 0}).sort("created_at", 1).to_list(length=None)

    async def delete_force_request(self, index: int) -> bool:
        all_docs = await self.force_requests_col.find(
            {}, {"_id": 1}
        ).sort("created_at", 1).to_list(length=None)
        if 0 <= index < len(all_docs):
            await self.force_requests_col.delete_one({"_id": all_docs[index]["_id"]})
            return True
        return False

    # ── msg map ────────────────────────────────────────────────
    async def save_msg_map(self, msg_id: int, user_id: int) -> None:
        await self.msg_map_col.update_one(
            {"msg_id": msg_id},
            {"$set": {"msg_id": msg_id, "user_id": user_id, "created_at": now_utc()}},
            upsert=True,
        )
        # Keep only recent 2000 entries
        total = await self.msg_map_col.count_documents({})
        if total > 2000:
            oldest = await self.msg_map_col.find(
                {}, {"_id": 1}
            ).sort("created_at", 1).limit(500).to_list(length=None)
            if oldest:
                await self.msg_map_col.delete_many({"_id": {"$in": [d["_id"] for d in oldest]}})

    async def get_msg_user(self, msg_id: int) -> Optional[int]:
        doc = await self.msg_map_col.find_one({"msg_id": msg_id}, {"user_id": 1})
        return int(doc["user_id"]) if doc else None

    # ── referral & premium ─────────────────────────────────────
    async def add_referral(self, referrer_id: int, new_user_id: int) -> bool:
        # Avoid double-counting the same user
        existing = await self.referrals_col.find_one({"user_id": referrer_id})
        if existing and new_user_id in existing.get("referred_users", []):
            return False

        await self.referrals_col.update_one(
            {"user_id": referrer_id},
            {
                "$inc": {"count": 1},
                "$addToSet": {"referred_users": new_user_id},
                "$setOnInsert": {
                    "premium_until": None, "referred_by": None, "created_at": now_utc(),
                },
            },
            upsert=True,
        )
        # Mark the new user's referrer (first-time only)
        new_doc = await self.referrals_col.find_one({"user_id": new_user_id})
        if new_doc:
            if new_doc.get("referred_by") is None:
                await self.referrals_col.update_one(
                    {"user_id": new_user_id},
                    {"$set": {"referred_by": referrer_id}},
                )
        else:
            await self.referrals_col.insert_one({
                "user_id": new_user_id, "count": 0, "referred_users": [],
                "premium_until": None, "referred_by": referrer_id, "created_at": now_utc(),
            })

        # Get updated count
        updated = await self.referrals_col.find_one({"user_id": referrer_id}, {"count": 1})
        new_count = (updated or {}).get("count", 1)
        return new_count > 0 and new_count % REFERRAL_THRESHOLD == 0

    async def get_referral_count(self, user_id: int) -> int:
        doc = await self.referrals_col.find_one({"user_id": user_id}, {"count": 1})
        return (doc or {}).get("count", 0)

    async def is_premium(self, user_id: int) -> bool:
        doc = await self.referrals_col.find_one({"user_id": user_id}, {"premium_until": 1})
        pt = (doc or {}).get("premium_until")
        if not pt:
            return False
        try:
            return datetime.fromisoformat(pt) > datetime.now(timezone.utc)
        except Exception:
            return False

    async def set_premium(self, user_id: int, days: int) -> None:
        doc = await self.referrals_col.find_one({"user_id": user_id}, {"premium_until": 1})
        base = datetime.now(timezone.utc)
        try:
            existing = datetime.fromisoformat((doc or {}).get("premium_until") or "")
            if existing > base:
                base = existing  # Extend from current expiry
        except Exception:
            pass
        new_until = (base + timedelta(days=days)).isoformat()
        await self.referrals_col.update_one(
            {"user_id": user_id},
            {
                "$set": {"premium_until": new_until},
                "$setOnInsert": {
                    "count": 0, "referred_users": [], "referred_by": None, "created_at": now_utc(),
                },
            },
            upsert=True,
        )

    async def get_premium_until(self, user_id: int) -> Optional[str]:
        doc = await self.referrals_col.find_one({"user_id": user_id}, {"premium_until": 1})
        return (doc or {}).get("premium_until")

    async def remove_premium(self, user_id: int) -> bool:
        doc = await self.referrals_col.find_one({"user_id": user_id}, {"premium_until": 1})
        if not doc or not doc.get("premium_until"):
            return False
        await self.referrals_col.update_one(
            {"user_id": user_id},
            {"$set": {"premium_until": None}},
        )
        return True

    async def list_premium_users(self) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        docs = await self.referrals_col.find(
            {"premium_until": {"$gt": now}},
            {"user_id": 1, "premium_until": 1, "_id": 0},
        ).to_list(length=None)
        return docs


# ─────────────────────────────────────────────────────────────
async def build_storage() -> BaseStorage:
    if MONGO_URI:
        try:
            mongo = MongoStorage(MONGO_URI)
            await mongo.init()
            print("[DB] MongoDB connected.")
            return mongo
        except Exception as exc:
            print(f"[DB] MongoDB failed ({exc}), falling back to JSON.")
    json_store = JsonStorage(JSON_DB_PATH)
    await json_store.init()
    print(f"[DB] JSON storage ready: {JSON_DB_PATH}")
    return json_store


# ═══════════════════════════════════════════════════════════════
#  TELEGRAM UI BUILDERS
# ═══════════════════════════════════════════════════════════════
def build_start_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Open Mini App", web_app=WebAppInfo(url=MINI_APP_URL))],
        [
            InlineKeyboardButton("Support", url=support_link()),
            InlineKeyboardButton("Updates", url=update_link()),
        ],
        [InlineKeyboardButton("Premium", callback_data="premium_info")],
    ])


def build_premium_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Purchase Premium", url=owner_link())],
        [InlineKeyboardButton("Back", callback_data="back_home")],
    ])


def build_fs_keyboard(missing: list[dict]) -> InlineKeyboardMarkup:
    rows: list[list] = []
    current: list = []
    for item in missing:
        url = item.get("url") or item.get("chat") or ""
        title = item.get("title") or str(item.get("chat", "Channel"))
        current.append(InlineKeyboardButton(f"Join {title}", url=url))
        if len(current) == 2:
            rows.append(current)
            current = []
    if current:
        rows.append(current)
    rows.append([InlineKeyboardButton("I Joined – Check Now", callback_data="check_sub")])
    return InlineKeyboardMarkup(rows)


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("Stats", callback_data="admin_stats"),
            InlineKeyboardButton("Broadcast", callback_data="admin_broadcast"),
        ],
        [
            InlineKeyboardButton("Force Sub", callback_data="admin_force_sub"),
            InlineKeyboardButton("Channels", callback_data="admin_channels"),
        ],
        [
            InlineKeyboardButton("FS Requests", callback_data="admin_fs_requests"),
            InlineKeyboardButton("Premium", callback_data="admin_premium"),
        ],
    ])


# ═══════════════════════════════════════════════════════════════
#  FORCE SUB – ADVANCED RESOLUTION
# ═══════════════════════════════════════════════════════════════
async def resolve_invite_link(bot, link: str) -> Optional[int]:
    """Try to join a private invite link and return the numeric chat id."""
    try:
        if "t.me/+" in link:
            invite_hash = link.split("t.me/+")[1].split("?")[0]
        elif "t.me/joinchat/" in link:
            invite_hash = link.split("t.me/joinchat/")[1].split("?")[0]
        else:
            return None
        chat = await bot.join_chat(invite_hash)
        return chat.id
    except TelegramError:
        return None


async def user_in_chat(bot, chat_ref: str, user_id: int) -> bool:
    try:
        if chat_ref.startswith("https://t.me/"):
            return False  # Unresolved invite link – cannot verify
        member = await bot.get_chat_member(chat_ref, user_id)
        return member.status in ("creator", "administrator", "member")
    except TelegramError:
        return False


async def check_force_sub(bot, user_id: int) -> Tuple[bool, list[dict]]:
    subs = await storage.list_force_subs()
    missing = []
    for sub in subs:
        chat = sub.get("chat")
        if not chat:
            continue
        if not await user_in_chat(bot, chat, user_id):
            missing.append(sub)
    return len(missing) == 0, missing


# ═══════════════════════════════════════════════════════════════
#  CORE FLOW
# ═══════════════════════════════════════════════════════════════
async def send_start_card(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caption = (
        "𝗪𝗲𝗹𝗰𝗼𝗺𝗲 𝘁𝗼 𝗕𝗹𝗮𝘇𝗲 𝗕𝗼𝘁\n\n"
        "๏ start the mini app to get the huge library\n"
        f"๏ use /refer command to enjoy {REFERRAL_REWARD_DAYS} days premium\n"
        "➻ premium and large library at one place\n"
        "────────────────────\n"
        "๏ To skip ad click on premium and contact owner"
    )
    chat_id = update.effective_chat.id
    if START_PHOTO:
        await context.bot.send_photo(
            chat_id=chat_id,
            photo=START_PHOTO,
            caption=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=build_start_keyboard(),
        )
    else:
        await context.bot.send_message(
            chat_id=chat_id,
            text=caption,
            parse_mode=ParseMode.HTML,
            reply_markup=build_start_keyboard(),
        )


async def gate_or_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True if user is allowed to proceed."""
    user = update.effective_user
    if not user:
        return False

    if await storage.is_banned(user.id) and not is_owner(user.id):
        msg = update.message or update.effective_message
        if update.callback_query:
            await update.callback_query.answer("You are banned from this bot.", show_alert=True)
        elif msg:
            await msg.reply_text("🚫 You are banned from using this bot.")
        return False

    await storage.save_user(user)

    # Owner and premium users bypass force-sub
    if is_owner(user.id) or await storage.is_premium(user.id):
        return True

    ok, missing = await check_force_sub(context.bot, user.id)
    if not ok:
        text = (
            "<b>📢 Join Required Channels First</b>\n\n"
            "Please join all the channels below, then press the check button."
        )
        msg = update.message or update.effective_message
        if msg:
            await msg.reply_text(
                text,
                parse_mode=ParseMode.HTML,
                reply_markup=build_fs_keyboard(missing),
                disable_web_page_preview=True,
            )
        return False

    return True


def resolve_target(update: Update) -> Optional[int]:
    msg = update.message
    if msg and msg.reply_to_message and msg.reply_to_message.from_user:
        return msg.reply_to_message.from_user.id
    text = parse_text_arg(msg.text or "") if msg else ""
    if text.isdigit():
        return int(text)
    return None


# ═══════════════════════════════════════════════════════════════
#  COMMANDS
# ═══════════════════════════════════════════════════════════════
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not user:
        return

    # ── Handle referral deep link (/start ref_12345) ──────────
    if context.args:
        arg = context.args[0]
        if arg.startswith("ref_"):
            referrer_str = arg[4:]
            if referrer_str.isdigit():
                referrer_id = int(referrer_str)
                if referrer_id != user.id:
                    threshold_hit = await storage.add_referral(referrer_id, user.id)
                    if threshold_hit:
                        await storage.set_premium(referrer_id, REFERRAL_REWARD_DAYS)
                        count = await storage.get_referral_count(referrer_id)

                        # Notify the referrer
                        try:
                            await context.bot.send_message(
                                chat_id=referrer_id,
                                text=(
                                    f"🎉 <b>Congrats! You hit {count} referrals!</b>\n\n"
                                    f"✨ <b>{REFERRAL_REWARD_DAYS} days Premium</b> granted automatically!\n"
                                    "Enjoy all premium benefits 🚀"
                                ),
                                parse_mode=ParseMode.HTML,
                            )
                        except Exception:
                            pass

                        # Notify the owner
                        try:
                            until = await storage.get_premium_until(referrer_id)
                            until_str = ""
                            if until:
                                try:
                                    until_str = datetime.fromisoformat(until).strftime("%d %b %Y, %I:%M %p UTC")
                                except Exception:
                                    until_str = until[:19]
                            await context.bot.send_message(
                                chat_id=OWNER_ID,
                                text=(
                                    f"🎁 <b>Referral Premium Unlocked</b>\n\n"
                                    f"User ID: <code>{referrer_id}</code>\n"
                                    f"Referrals: <b>{count}</b>\n"
                                    f"Reward: <b>{REFERRAL_REWARD_DAYS} days Premium</b>\n"
                                    f"Valid Until: <code>{until_str}</code>"
                                ),
                                parse_mode=ParseMode.HTML,
                            )
                        except Exception:
                            pass

    if await gate_or_start(update, context):
        await send_start_card(update, context)


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate_or_start(update, context):
        return
    text = (
        "<b>📋 Available Commands</b>\n\n"
        "<b>User Commands</b>\n"
        "/start — Welcome &amp; mini app\n"
        "/refer — Get your referral link\n"
        "/mypremium — Check premium status\n"
        "/request — Send a request to owner\n"
        "/requestforce — Request a channel to be added\n"
        "/channels — View community channels\n\n"
        "<b>Owner Commands</b>\n"
        "/admin — Admin panel\n"
        "/stats — Bot statistics\n"
        "/setforcesub title | @ch / -id / link\n"
        "/remforcesub @ch / id / title\n"
        "/forcelist — List force-sub channels\n"
        "/addchannel title | url\n"
        "/remchannel title or url\n"
        "/setpremium user_id days\n"
        "/rempremium user_id — Remove premium\n"
        "/premiumlist — List active premium users\n"
        "/ban user_id or reply\n"
        "/unban user_id or reply\n"
        "/broadcast message or reply"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("Owner only.")
        return
    await update.message.reply_text(
        "<b>⚙️ Owner Panel</b>\n\nUse the buttons below for quick actions.",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_keyboard(),
    )


async def cmd_refer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate_or_start(update, context):
        return
    user = update.effective_user
    if not user:
        return
    count = await storage.get_referral_count(user.id)
    bot_me = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_me.username}?start=ref_{user.id}"
    remaining = REFERRAL_THRESHOLD - (count % REFERRAL_THRESHOLD)
    if remaining == REFERRAL_THRESHOLD:
        remaining = 0  # Just earned a reward

    text = (
        "🔗 <b>Your Referral Link</b>\n\n"
        f"<code>{ref_link}</code>\n\n"
        f"👥 Total referrals: <b>{count}</b>\n"
        f"🎯 <b>{remaining}</b> more for {REFERRAL_REWARD_DAYS} days Premium!\n\n"
        f"Share this link. Every {REFERRAL_THRESHOLD} referrals = {REFERRAL_REWARD_DAYS} days Premium automatically!"
    )
    await update.message.reply_text(
        text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
    )


async def cmd_mypremium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate_or_start(update, context):
        return
    user = update.effective_user
    if not user:
        return
    premium = await storage.is_premium(user.id)
    until = await storage.get_premium_until(user.id)
    if premium and until:
        try:
            until_dt = datetime.fromisoformat(until)
            until_str = until_dt.strftime("%d %b %Y, %I:%M %p UTC")
        except Exception:
            until_str = until[:19]
        await update.message.reply_text(
            f"✨ <b>Premium Active!</b>\n\nExpires: <code>{until_str}</code>",
            parse_mode=ParseMode.HTML,
        )
    else:
        count = await storage.get_referral_count(user.id)
        remaining = REFERRAL_THRESHOLD - (count % REFERRAL_THRESHOLD)
        await update.message.reply_text(
            f"❌ <b>No Premium</b>\n\n"
            f"Earn it free via /refer — {remaining} more referrals needed!\n"
            f"Or purchase via /start → Premium.",
            parse_mode=ParseMode.HTML,
        )


async def cmd_setpremium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("Owner only.")
        return
    parts = (update.message.text or "").split()
    if len(parts) < 3:
        await update.message.reply_text("Usage: /setpremium <user_id> <days>")
        return
    try:
        target_id = int(parts[1])
        days = int(parts[2])
    except ValueError:
        await update.message.reply_text("Invalid args. Use: /setpremium 123456789 30")
        return
    await storage.set_premium(target_id, days)
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"✨ <b>Premium Activated!</b>\n\n"
                f"You've been granted <b>{days} days</b> of premium by the owner.\n"
                "Enjoy all premium benefits! 🎉"
            ),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass
    await update.message.reply_text(
        f"✅ Premium granted: <code>{target_id}</code> → {days} days",
        parse_mode=ParseMode.HTML,
    )


async def cmd_rempremium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("Owner only.")
        return
    parts = (update.message.text or "").split()
    if len(parts) < 2:
        await update.message.reply_text("Usage: /rempremium <user_id>")
        return
    try:
        target_id = int(parts[1])
    except ValueError:
        await update.message.reply_text("Invalid user ID.")
        return
    removed = await storage.remove_premium(target_id)
    if removed:
        await update.message.reply_text(
            f"✅ Premium removed: <code>{target_id}</code>",
            parse_mode=ParseMode.HTML,
        )
        try:
            await context.bot.send_message(
                chat_id=target_id,
                text="❌ <b>Your Premium has been removed by the owner.</b>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
    else:
        await update.message.reply_text(
            f"❌ User <code>{target_id}</code> has no active premium.",
            parse_mode=ParseMode.HTML,
        )


async def cmd_premiumlist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("Owner only.")
        return
    users = await storage.list_premium_users()
    if not users:
        await update.message.reply_text("No active premium users.")
        return
    lines = ["<b>💎 Active Premium Users</b>\n"]
    for i, u in enumerate(users, 1):
        uid = u.get("user_id")
        pt  = u.get("premium_until", "")
        try:
            until_str = datetime.fromisoformat(pt).strftime("%d %b %Y")
        except Exception:
            until_str = pt[:10] if pt else "?"
        lines.append(f"{i}. <code>{uid}</code> — until {until_str}")
    text = "\n".join(lines)
    # Send in chunks to respect Telegram's 4096 char limit
    for i in range(0, len(text), 4000):
        await update.message.reply_text(text[i:i+4000], parse_mode=ParseMode.HTML)


async def cmd_request(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate_or_start(update, context):
        return
    user = update.effective_user
    if not user:
        return

    text = parse_text_arg(update.message.text or "")

    if update.message.reply_to_message:
        # Forward the replied-to message to owner
        result = await context.bot.copy_message(
            chat_id=OWNER_ID,
            from_chat_id=update.effective_chat.id,
            message_id=update.message.reply_to_message.message_id,
        )
        if hasattr(result, "message_id"):
            await storage.save_msg_map(result.message_id, user.id)

        caption_msg = await context.bot.send_message(
            chat_id=OWNER_ID,
            text=(
                "<b>📩 New Request (forwarded)</b>\n"
                f"From: {format_user_name(user)} "
                f"(@{html.escape(user.username or 'no_username')})\n"
                f"User ID: <code>{user.id}</code>\n\n"
                "<i>Reply to this message to respond to the user.</i>"
            ),
            parse_mode=ParseMode.HTML,
        )
        await storage.save_msg_map(caption_msg.message_id, user.id)
        await update.message.reply_text("✅ Your request has been sent to the owner.")
        return

    if text:
        await storage.add_request(user, text)
        sent = await context.bot.send_message(
            chat_id=OWNER_ID,
            text=(
                "<b>📩 New Request</b>\n"
                f"From: {format_user_name(user)} "
                f"(@{html.escape(user.username or 'no_username')})\n"
                f"User ID: <code>{user.id}</code>\n\n"
                f"{html.escape(text)}\n\n"
                "<i>Reply to this message to respond to the user.</i>"
            ),
            parse_mode=ParseMode.HTML,
        )
        await storage.save_msg_map(sent.message_id, user.id)
        await update.message.reply_text("✅ Your request has been sent to the owner.")
        return

    pending_requests.add(user.id)
    await update.message.reply_text(
        "📝 Send your request now. I'll forward it to the owner."
    )


async def cmd_request_force(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate_or_start(update, context):
        return
    user = update.effective_user
    if not user:
        return
    link = parse_text_arg(update.message.text or "").strip()
    if not link:
        await update.message.reply_text(
            "Usage: /requestforce @mychannel\nOr use a channel link / numeric ID."
        )
        return
    if not (link.startswith("@") or link.startswith("https://t.me/") or link.lstrip("-").isdigit()):
        await update.message.reply_text("Invalid format. Use a username, invite link, or numeric ID.")
        return

    await storage.add_force_request(user.id, user.username or "", user.first_name or "", link)
    await update.message.reply_text("✅ Your request has been sent to the owner.")

    # Notify owner via inline buttons
    requests = await storage.get_force_requests()
    idx = len(requests) - 1  # Index of the just-added entry
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("Approve", callback_data=f"approve_force_req_{idx}"),
        InlineKeyboardButton("Deny", callback_data=f"deny_force_req_{idx}"),
    ]])
    await context.bot.send_message(
        chat_id=OWNER_ID,
        text=(
            "<b>Force-sub Channel Request</b>\n"
            f"From: {format_user_name(user)} (@{html.escape(user.username or 'no_username')})\n"
            f"Link: {html.escape(link)}\n"
            f"User ID: <code>{user.id}</code>"
        ),
        parse_mode=ParseMode.HTML,
        reply_markup=kb,
        disable_web_page_preview=True,
    )


async def cmd_setforcesub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("Owner only.")
        return

    parts = split_bar_args(update.message.text or "")
    if not parts:
        await update.message.reply_text(
            "Usage: /setforcesub Title | @channel_or_id_or_invite_link\n"
            "For private channels: add the bot as admin first, then use the invite link."
        )
        return

    title  = parts[0]
    target = parts[1] if len(parts) > 1 else parts[0]
    chat_ref  = normalize_chat_ref(target)
    join_url  = parts[2] if len(parts) > 2 else target
    final_ref = chat_ref

    # Private invite link → try to resolve to numeric id
    if target.startswith("https://t.me/+") or "joinchat" in target:
        resolved = await resolve_invite_link(context.bot, target)
        if resolved:
            final_ref = str(resolved)
            join_url  = target  # Keep original invite link for users to join
        else:
            await update.message.reply_text(
                "⚠️ Could not auto-join the channel.\n\n"
                "Make sure the bot is an admin in that private channel, then use its numeric ID:\n"
                "<code>/setforcesub Title | -1001234567890</code>",
                parse_mode=ParseMode.HTML,
            )
            return

    if not final_ref.startswith("-100"):
        join_url = normalize_url(join_url, final_ref)

    await storage.add_force_sub(final_ref, title or final_ref, final_ref, join_url)
    await update.message.reply_text(
        f"✅ Force-sub added: <b>{html.escape(title or final_ref)}</b>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_remforcesub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("Owner only.")
        return
    target = parse_text_arg(update.message.text or "")
    if not target:
        await update.message.reply_text("Usage: /remforcesub @channel / id / title / link")
        return
    removed = await storage.remove_force_sub(normalize_chat_ref(target))
    if removed:
        await update.message.reply_text("✅ Force-sub removed.")
    else:
        await update.message.reply_text("❌ Not found. Try the exact key, title, or username.")


async def cmd_forcelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("Owner only.")
        return
    items = await storage.list_force_subs()
    if not items:
        await update.message.reply_text("No force-sub channels set.")
        return
    for item in items:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Remove", callback_data=f"remove_force_{item.get('key')}")
        ]])
        await update.message.reply_text(
            f"<b>{html.escape(item.get('title', ''))}</b>\n"
            f"Chat: <code>{item.get('chat')}</code>\n"
            f"Join URL: {item.get('url')}",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
            disable_web_page_preview=True,
        )


async def cmd_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate_or_start(update, context):
        return
    items = await storage.list_channels()
    if not items:
        await update.message.reply_text("No channels added yet.")
        return
    rows = []
    lines = ["<b>📺 Community Channels</b>\n"]
    for item in items:
        title = item.get("title") or "Channel"
        url   = item.get("url") or item.get("key") or ""
        lines.append(f"• {html.escape(title)}")
        if url:
            rows.append([InlineKeyboardButton(title, url=url)])
    await update.message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(rows[:20]),
        disable_web_page_preview=True,
    )


async def cmd_addchannel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("Owner only.")
        return
    parts = split_bar_args(update.message.text or "")
    if not parts:
        await update.message.reply_text("Usage: /addchannel Title | https://t.me/channel")
        return
    title = parts[0]
    url   = parts[1] if len(parts) > 1 else parts[0]
    await storage.add_channel(url, title or url, url)
    await update.message.reply_text(f"✅ Channel added: {html.escape(title or url)}")


async def cmd_remchannel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("Owner only.")
        return
    target = parse_text_arg(update.message.text or "")
    if not target:
        await update.message.reply_text("Usage: /remchannel Title or URL or @username")
        return
    removed = await storage.remove_channel(target)
    if removed:
        await update.message.reply_text("✅ Channel removed.")
    else:
        await update.message.reply_text(
            "❌ Not found. Try the exact title, URL, or @username you used when adding."
        )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("Owner only.")
        return
    await update.message.reply_text(
        "<b>📊 Bot Statistics</b>\n\n"
        f"👥 Users: <code>{await storage.count_users()}</code>\n"
        f"📩 Requests: <code>{await storage.count_requests()}</code>\n"
        f"🚫 Bans: <code>{await storage.count_bans()}</code>\n"
        f"🔒 Force Subs: <code>{await storage.count_force_subs()}</code>\n"
        f"📺 Channels: <code>{await storage.count_channels()}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("Owner only.")
        return
    text  = parse_text_arg(update.message.text or "")
    reply = update.message.reply_to_message
    if not text and not reply:
        await update.message.reply_text(
            "Usage: /broadcast message\nOr reply to a message and use /broadcast"
        )
        return
    users = await storage.list_users()
    sent = failed = 0
    for uid in users:
        try:
            if reply:
                await context.bot.copy_message(
                    chat_id=uid,
                    from_chat_id=update.effective_chat.id,
                    message_id=reply.message_id,
                )
            else:
                await context.bot.send_message(chat_id=uid, text=text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.03)
    await update.message.reply_text(
        f"📣 Broadcast done.\n✅ Sent: {sent}\n❌ Failed: {failed}"
    )


async def cmd_ban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("Owner only.")
        return
    target = resolve_target(update)
    if not target:
        await update.message.reply_text("Usage: /ban 123456789 or reply to user message")
        return
    await storage.ban_user(target)
    await update.message.reply_text(
        f"🚫 Banned: <code>{target}</code>", parse_mode=ParseMode.HTML
    )


async def cmd_unban(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update.effective_user.id if update.effective_user else None):
        await update.message.reply_text("Owner only.")
        return
    target = resolve_target(update)
    if not target:
        await update.message.reply_text("Usage: /unban 123456789 or reply to user message")
        return
    removed = await storage.unban_user(target)
    if removed:
        await update.message.reply_text(
            f"✅ Unbanned: <code>{target}</code>", parse_mode=ParseMode.HTML
        )
    else:
        await update.message.reply_text("User not found in ban list.")


async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await gate_or_start(update, context):
        return
    await update.message.reply_text("🏓 Alive.")


# ═══════════════════════════════════════════════════════════════
#  CALLBACK HANDLERS
# ═══════════════════════════════════════════════════════════════
async def cb_check_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    if not await gate_or_start(update, context):
        return
    try:
        await query.message.delete()
    except Exception:
        pass
    await send_start_card(update, context)


async def cb_premium_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    await _reply_new(
        query, context,
        PREMIUM_TEXT,
        reply_markup=build_premium_keyboard(),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cb_refer_info(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    user = query.from_user
    count = await storage.get_referral_count(user.id)
    bot_me = await context.bot.get_me()
    ref_link = f"https://t.me/{bot_me.username}?start=ref_{user.id}"
    remaining = REFERRAL_THRESHOLD - (count % REFERRAL_THRESHOLD)
    if remaining == REFERRAL_THRESHOLD and count > 0:
        remaining = 0

    text = (
        f"<b>{sc('Refer & Earn Premium')}</b>\n\n"
        f"{sc('your referral link')}:\n<code>{ref_link}</code>\n\n"
        f"{sc('total referrals')}: <b>{count}</b>\n"
        f"<b>{remaining}</b> {sc('more')} → {REFERRAL_REWARD_DAYS} {sc('days premium')}\n\n"
        f"{sc('every')} {REFERRAL_THRESHOLD} {sc('referrals')} = {REFERRAL_REWARD_DAYS} {sc('days premium — automatically!')}"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("Back", callback_data="back_home")]])
    await _reply_new(
        query, context,
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


async def cb_back_home(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()
    try:
        await query.message.delete()
    except Exception:
        pass
    await send_start_card(update, context)


async def cb_admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not is_owner(query.from_user.id):
        return
    await query.answer()
    await query.message.reply_text(
        "<b>📊 Bot Statistics</b>\n\n"
        f"👥 Users: <code>{await storage.count_users()}</code>\n"
        f"📩 Requests: <code>{await storage.count_requests()}</code>\n"
        f"🚫 Bans: <code>{await storage.count_bans()}</code>\n"
        f"🔒 Force Subs: <code>{await storage.count_force_subs()}</code>\n"
        f"📺 Channels: <code>{await storage.count_channels()}</code>",
        parse_mode=ParseMode.HTML,
    )


async def cb_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not is_owner(query.from_user.id):
        return
    await query.answer()
    await query.message.reply_text(
        "Send: /broadcast your message\nOr reply to any message and send /broadcast"
    )


async def cb_admin_force_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not is_owner(query.from_user.id):
        return
    await query.answer()
    await query.message.reply_text(
        "/setforcesub Title | @channel or -id or invite_link\n"
        "/remforcesub @channel or id or title\n"
        "/forcelist — Show all with remove buttons\n\n"
        "<b>Private channel tip:</b> Add the bot as admin in the private channel first.",
        parse_mode=ParseMode.HTML,
    )


async def cb_admin_channels(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not is_owner(query.from_user.id):
        return
    await query.answer()
    await query.message.reply_text(
        "/addchannel Title | https://t.me/channel\n"
        "/remchannel Title or URL\n"
        "/channels — View public list"
    )


async def cb_admin_premium(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not is_owner(query.from_user.id):
        return
    await query.answer()
    await query.message.reply_text(
        "<b>Premium Management</b>\n\n"
        "/setpremium user_id days — Grant premium\n"
        "/rempremium user_id — Remove premium\n"
        "/premiumlist — List active premium users\n"
        "/mypremium — Users check their status\n"
        "/refer — Users earn via referrals\n\n"
        f"Referral threshold: {REFERRAL_THRESHOLD} referrals = {REFERRAL_REWARD_DAYS} days",
        parse_mode=ParseMode.HTML,
    )


async def cb_admin_fs_requests(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not is_owner(query.from_user.id):
        return
    await query.answer()
    requests = await storage.get_force_requests()
    if not requests:
        await query.message.reply_text("No pending force-sub requests.")
        return
    for idx, req in enumerate(requests):
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("Approve", callback_data=f"approve_force_req_{idx}"),
            InlineKeyboardButton("Deny", callback_data=f"deny_force_req_{idx}"),
        ]])
        await query.message.reply_text(
            f"<b>#{idx+1}</b> From: {html.escape(req.get('first_name',''))} "
            f"(@{html.escape(req.get('username',''))})\n"
            f"Link: {html.escape(req.get('link',''))}\n"
            f"User ID: <code>{req.get('user_id')}</code>",
            parse_mode=ParseMode.HTML,
            reply_markup=kb,
            disable_web_page_preview=True,
        )


async def cb_approve_force_req(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not is_owner(query.from_user.id):
        await query.answer("Not authorized.", show_alert=True)
        return
    await query.answer()
    try:
        idx = int(query.data.split("_")[-1])
    except ValueError:
        return

    requests = await storage.get_force_requests()
    if idx < 0 or idx >= len(requests):
        await query.message.edit_text("Request no longer exists.")
        return

    req  = requests[idx]
    link = req.get("link", "")
    if not link:
        await query.message.edit_text("Invalid link in request.")
        return

    title     = link
    chat_ref  = normalize_chat_ref(link)
    final_ref = chat_ref
    join_url  = link

    if link.startswith("https://t.me/+") or "joinchat" in link:
        resolved = await resolve_invite_link(context.bot, link)
        if resolved:
            final_ref = str(resolved)
            join_url  = link
        else:
            await query.message.edit_text(
                "⚠️ Could not auto-join the channel. Ask the owner of that channel to add this bot as admin, "
                "then manually add with /setforcesub."
            )
            return

    if not final_ref.startswith("-100"):
        join_url = normalize_url(join_url, final_ref)

    await storage.add_force_sub(final_ref, title, final_ref, join_url)
    await storage.delete_force_request(idx)
    await query.message.edit_text(f"✅ Approved and added: {html.escape(title)}")


async def cb_deny_force_req(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not is_owner(query.from_user.id):
        await query.answer("Not authorized.", show_alert=True)
        return
    await query.answer()
    try:
        idx = int(query.data.split("_")[-1])
    except ValueError:
        return
    removed = await storage.delete_force_request(idx)
    await query.message.edit_text("❌ Request denied and removed." if removed else "Request not found.")


async def cb_remove_force(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query or not is_owner(query.from_user.id):
        return
    await query.answer()
    key = query.data.replace("remove_force_", "", 1)
    removed = await storage.remove_force_sub(key)
    await query.message.edit_text("✅ Removed." if removed else "❌ Not found.")


# ═══════════════════════════════════════════════════════════════
#  MESSAGE HANDLERS
# ═══════════════════════════════════════════════════════════════
async def handle_owner_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    When owner replies to a tracked request notification, forward the reply to the user.
    Supports any message type (text, photo, sticker, file, etc.) via copy_message.
    """
    msg = update.message
    if not msg or not msg.reply_to_message:
        return

    replied_msg_id = msg.reply_to_message.message_id
    user_id = await storage.get_msg_user(replied_msg_id)
    if not user_id:
        return  # Not a tracked request message – ignore

    try:
        await context.bot.copy_message(
            chat_id=user_id,
            from_chat_id=update.effective_chat.id,
            message_id=msg.message_id,
        )
        await msg.reply_text(
            f"✅ Reply sent to user <code>{user_id}</code>",
            parse_mode=ParseMode.HTML,
        )
    except TelegramError as exc:
        await msg.reply_text(f"❌ Failed to deliver: {exc}")


async def handle_general_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles pending /request continuation from users."""
    user = update.effective_user
    if not user or not update.message:
        return
    if await storage.is_banned(user.id) and not is_owner(user.id):
        return

    if user.id in pending_requests:
        pending_requests.discard(user.id)
        text = update.message.text or ""
        await storage.add_request(user, text)
        sent = await context.bot.send_message(
            chat_id=OWNER_ID,
            text=(
                "<b>📩 New Request</b>\n"
                f"From: {format_user_name(user)} "
                f"(@{html.escape(user.username or 'no_username')})\n"
                f"User ID: <code>{user.id}</code>\n\n"
                f"{html.escape(text)}\n\n"
                "<i>Reply to this message to respond to the user.</i>"
            ),
            parse_mode=ParseMode.HTML,
        )
        await storage.save_msg_map(sent.message_id, user.id)
        await update.message.reply_text("✅ Your request has been sent to the owner.")


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"[Error] Update {update!r} caused: {context.error}")


# ═══════════════════════════════════════════════════════════════
#  BOOT
# ═══════════════════════════════════════════════════════════════
async def init_storage() -> None:
    global storage
    storage = await build_storage()


def main() -> None:
    asyncio.run(init_storage())

    app: Application = ApplicationBuilder().token(BOT_TOKEN).build()

    # ── Commands ───────────────────────────────────────────────
    app.add_handler(CommandHandler("start",        cmd_start))
    app.add_handler(CommandHandler("help",         cmd_help))
    app.add_handler(CommandHandler("admin",        cmd_admin))
    app.add_handler(CommandHandler("ping",         ping))
    app.add_handler(CommandHandler("refer",        cmd_refer))
    app.add_handler(CommandHandler("mypremium",    cmd_mypremium))
    app.add_handler(CommandHandler("setpremium",   cmd_setpremium))
    app.add_handler(CommandHandler("rempremium",   cmd_rempremium))
    app.add_handler(CommandHandler("premiumlist",  cmd_premiumlist))
    app.add_handler(CommandHandler("request",      cmd_request))
    app.add_handler(CommandHandler("requestforce", cmd_request_force))
    app.add_handler(CommandHandler("setforcesub",  cmd_setforcesub))
    app.add_handler(CommandHandler("remforcesub",  cmd_remforcesub))
    app.add_handler(CommandHandler("forcelist",    cmd_forcelist))
    app.add_handler(CommandHandler("stats",        cmd_stats))
    app.add_handler(CommandHandler("broadcast",    cmd_broadcast))
    app.add_handler(CommandHandler("ban",          cmd_ban))
    app.add_handler(CommandHandler("unban",        cmd_unban))
    app.add_handler(CommandHandler("channels",     cmd_channels))
    app.add_handler(CommandHandler("addchannel",   cmd_addchannel))
    app.add_handler(CommandHandler("remchannel",   cmd_remchannel))

    # ── Callbacks ──────────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(cb_check_sub,         pattern="^check_sub$"))
    app.add_handler(CallbackQueryHandler(cb_premium_info,      pattern="^premium_info$"))
    app.add_handler(CallbackQueryHandler(cb_refer_info,        pattern="^refer_info$"))
    app.add_handler(CallbackQueryHandler(cb_back_home,         pattern="^back_home$"))
    app.add_handler(CallbackQueryHandler(cb_admin_stats,       pattern="^admin_stats$"))
    app.add_handler(CallbackQueryHandler(cb_admin_broadcast,   pattern="^admin_broadcast$"))
    app.add_handler(CallbackQueryHandler(cb_admin_force_sub,   pattern="^admin_force_sub$"))
    app.add_handler(CallbackQueryHandler(cb_admin_channels,    pattern="^admin_channels$"))
    app.add_handler(CallbackQueryHandler(cb_admin_fs_requests, pattern="^admin_fs_requests$"))
    app.add_handler(CallbackQueryHandler(cb_admin_premium,     pattern="^admin_premium$"))
    app.add_handler(CallbackQueryHandler(cb_approve_force_req, pattern=r"^approve_force_req_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_deny_force_req,    pattern=r"^deny_force_req_\d+$"))
    app.add_handler(CallbackQueryHandler(cb_remove_force,      pattern="^remove_force_"))

    # ── Message handlers (order matters!) ─────────────────────
    # 1. Owner replying to a tracked request → forward to user
    app.add_handler(MessageHandler(
        filters.User(OWNER_ID) & filters.REPLY & ~filters.COMMAND,
        handle_owner_reply,
    ))
    # 2. General text (pending request continuation for non-owners)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & ~filters.User(OWNER_ID),
        handle_general_text,
    ))

    app.add_error_handler(on_error)

    print(f"[Bot] {BOT_NAME} is running…")
    app.run_polling()


if __name__ == "__main__":
    main()

