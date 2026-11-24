#!/usr/bin/env python3
"""
Senkuro Smart Auto-Trade & Bank Assistant v61.0
-----------------------------------------------
- Рабочее окно авто-обменов: 09:00–18:00 по Киеву (ZoneInfo("Europe/Kyiv"), авто зимнее/летнее время).
- Ультра-экономный расход украинского резидентского прокси (< 0.5 МБ/день):
  * ВСЁ сканирование целей и 20-минутный мониторинг cesium254 идут через бесплатный Opera VPN (0 байт твоего прокси).
  * Украинский прокси (UKRAINE_PROXY_URL) используется ТОЛЬКО для голых GraphQL-мутаций отправки/отмены трейдов (~5-10 КБ/запрос).
- Вход БЕЗ пароля и БЕЗ браузера для отправки: используется только SENKURO_MAIN_TOKEN (access_token от senkuro.com).
- Ранги: ВСЕ (F, D, C, B, A, S). Закреплённые (locked) и дорогие (>= 1.50 чистыми) карты никогда не тратятся.
- Математика ставок (строго в плюс):
  * net >= 2.60 -> строго 2x того же ранга
  * 2.00 <= net < 2.60 -> 1x того же ранга + 1x младшего ранга (приоритетно) или 1-в-1
  * 1.60 <= net < 2.00 -> строго 1-в-1
- Мониторинг каждые 20 мин: как только залетела дорогая карта (>= 1.50 чистыми), приходит уведомление с кнопкой "🏦 Отправить в банк (goldlotus)".
"""

import argparse
import asyncio
import io
import json
import os
import random
import re
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

from playwright.async_api import BrowserContext, Page, async_playwright

# Принудительно IPv4 для api.telegram.org (убирает Errno 101 на IPv6 в GitHub Actions)
_orig_getaddrinfo = socket.getaddrinfo


def _ipv4_only_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    if host and "telegram.org" in str(host):
        return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
    return _orig_getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = _ipv4_only_getaddrinfo

# ==============================================================================
# 1. КОНФИГУРАЦИЯ
# ==============================================================================

APP_VERSION_TAG = "v61.0"
APP_HEADER_VERSION = "2.2.1"
GRAPHQL_API_URL = "https://api.senkuro.com/graphql"

KYIV_TZ = ZoneInfo("Europe/Kyiv")
WORK_START_HOUR = 9
WORK_END_HOUR = 18
WAVE_INTERVAL_SEC = 61 * 60       # Скользящее окно 61 мин от времени КАЖДОГО трейда (без лишнего простоя)
RATE_LIMIT_RETRY_SEC = 10 * 60    # Если сайт вернул лимит — повторная проверка через 10 мин
MIN_WAVE_COOLDOWN_SEC = 5 * 60    # Минимум 5 мин между авто-прогонами
MONITOR_INTERVAL_SEC = 20 * 60
MAX_TRADES_PER_WAVE = 9           # До 9 обменов в скользящем часе (1 слот держим в запасе под банк)
MAX_ORDERS_PER_BATCH = 5          # До 5 человек на 1 комбинацию (до 9, если комбинация одна)

MAIN_ACCOUNT_SLUG = os.environ.get("SENKURO_MAIN_SLUG", "cesium254").strip() or "cesium254"
MAIN_ACCOUNT_UID = os.environ.get("SENKURO_MAIN_UID", "VVNFUjoxODAxNDM0ODEzOTI0ODE4MDE").strip() or "VVNFUjoxODAxNDM0ODEzOTI0ODE4MDE"
MAIN_ACCOUNT_URL = f"https://senkuro.com/users/{MAIN_ACCOUNT_SLUG}"
MAIN_CARDS_URL = f"https://senkuro.com/users/{MAIN_ACCOUNT_SLUG}/cards"

BANK_ACCOUNT_SLUG = os.environ.get("SENKURO_BANK_SLUG", "goldlotus").strip() or "goldlotus"
BANK_ACCOUNT_URL = f"https://senkuro.com/users/{BANK_ACCOUNT_SLUG}"

SENKURO_MAIN_TOKEN = os.environ.get("SENKURO_MAIN_TOKEN", "").strip()
UKRAINE_PROXY_RAW = os.environ.get("UKRAINE_PROXY_URL", "").strip()

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = (os.environ.get("TELEGRAM_CHAT_ID", "").strip() or "457787014")

SESSIONS_DIR = Path(".sessions")
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
DEBUG_LOG_FILE = Path("/tmp/senkuro_trader_debug.log")
TG_OFFSET_FILE = Path("/tmp/tg_offset.txt")
EARLY_QUEUE_FILE = Path("/tmp/senkuro_early_queue.jsonl")

SENKUTOOLS_AMO_API_URL = "https://addons.mozilla.org/api/v5/addons/addon/senkutools/"
SENKUTOOLS_AMO_PAGE_URL = "https://addons.mozilla.org/ru/firefox/addon/senkutools/"
SENKUTOOLS_PRICES_FILE = SESSIONS_DIR / "senkutools_prices.json"
SENKUTOOLS_META_FILE = SESSIONS_DIR / "senkutools_meta.json"
TRADE_DB_FILE = SESSIONS_DIR / "trade_targets_db.json"
AUTO_STATE_FILE = SESSIONS_DIR / "auto_trade_state.json"

BANK_COMMISSION_MULT = 0.80
MIN_BANK_PROFIT_NET = 1.50
MIN_TARGET_NET_PRICE = 1.60
TARGET_TTL_SECONDS = 72 * 3600

SEARCHABLE_RANKS = ("D", "C", "B", "A", "S")
LOWER_RANK_MAP = {"D": "F", "C": "D", "B": "C", "A": "B", "S": "A"}
LOWER2_RANK_MAP = {"C": "F", "B": "D", "A": "C", "S": "B"}
RANK_ORDER = ("R", "S", "A", "B", "C", "D", "F")
RANK_BADGE = {
    "R": "💠[R]",
    "S": "🔴[S]",
    "A": "🟡[A]",
    "B": "🟣[B]",
    "C": "🔵[C]",
    "D": "🟢[D]",
    "F": "⚪[F]",
}

SENKUTOOLS_DB: dict[str, dict[str, Any]] = {}
SENKUTOOLS_META: dict[str, Any] = {}
STOP_FLAG: bool = False
ACTIVE_JOB_TASK: Optional[asyncio.Task] = None
ACTIVE_JOB_NAME: str = ""
QUEUED_KEYS: set[str] = set()
BANK_PENDING_CARDS: dict[str, dict[str, Any]] = {}


def kyiv_now() -> datetime:
    return datetime.now(KYIV_TZ)


def is_working_hours_kyiv() -> bool:
    h = kyiv_now().hour
    return WORK_START_HOUR <= h < WORK_END_HOUR


def parse_proxy_url(raw: str) -> Optional[str]:
    """Поддерживает оба формата: 'host:port:user:pass' и 'http://user:pass@host:port'."""
    s = (raw or "").strip()
    if not s:
        return None
    if s.startswith("http://") or s.startswith("https://"):
        return s
    parts = s.split(":")
    if len(parts) == 4:
        host, port, user, pwd = parts
        return f"http://{urllib.parse.quote(user, safe='')}:{urllib.parse.quote(pwd, safe='')}@{host}:{port}"
    if len(parts) == 2:
        return f"http://{parts[0]}:{parts[1]}"
    return None


def log_debug(msg: str) -> None:
    ts = kyiv_now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts} Kyiv] {msg}"
    print(line, flush=True)
    try:
        if DEBUG_LOG_FILE.exists() and DEBUG_LOG_FILE.stat().st_size > 220_000:
            DEBUG_LOG_FILE.write_bytes(DEBUG_LOG_FILE.read_bytes()[-130_000:])
        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ==============================================================================
# 2. TELEGRAM API + МЕНЮ
# ==============================================================================

def get_reply_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": "🃏 Мои карты"}, {"text": "🎯 Найти обмены"}],
            [{"text": "⚡ Авто-волна"}, {"text": "📜 Лог"}],
        ],
        "resize_keyboard": True,
        "is_persistent": False,
        "input_field_placeholder": "Выберите действие 🎛 👇",
    }


def tg_request(method: str, payload: dict, max_retries: int = 4) -> dict:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return {"ok": True}
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            if e.code == 429 and attempt < max_retries:
                retry_after = 5
                try:
                    retry_after = int((json.loads(err_body).get("parameters") or {}).get("retry_after") or 5)
                except Exception:
                    pass
                time.sleep(max(2, min(retry_after + 1, 30)))
                continue
            log_debug(f"[TG ERROR] {method} ({e.code}): {err_body[:200]}")
            return {"ok": False, "error_code": e.code, "error": err_body}
        except Exception as e:
            if attempt < max_retries:
                time.sleep(2.0)
                continue
            log_debug(f"[TG ERROR] {method}: {e}")
            return {"ok": False, "error": str(e)}
    return {"ok": False}


def _split_long_text(text: str, limit: int = 3800) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, cur, cur_len = [], [], 0
    for ln in text.splitlines(keepends=True):
        if cur_len + len(ln) > limit and cur:
            parts.append("".join(cur).rstrip())
            cur, cur_len = [ln], len(ln)
        else:
            cur.append(ln)
            cur_len += len(ln)
    if cur:
        parts.append("".join(cur).rstrip())
    return parts or [text[:limit]]


def send_tg_message(text: str, add_keyboard: bool = True, inline_markup: Optional[dict] = None) -> dict:
    chunks = _split_long_text(text)
    last_res: dict[str, Any] = {"ok": False}
    for idx, ch in enumerate(chunks):
        is_last = idx == len(chunks) - 1
        payload: dict[str, Any] = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": ch,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if is_last:
            if inline_markup:
                payload["reply_markup"] = inline_markup
            elif add_keyboard:
                payload["reply_markup"] = get_reply_keyboard()
        res = tg_request("sendMessage", payload)
        if not res.get("ok"):
            plain = dict(payload)
            plain.pop("parse_mode", None)
            res = tg_request("sendMessage", plain)
        last_res = res
        if not is_last:
            time.sleep(0.5)
    return last_res


def send_tg_multipart(method: str, file_field: str, filename: str, file_bytes: bytes, mime_type: str, extra_fields: dict[str, str]) -> dict:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return {"ok": False}
    boundary = f"----SenkuroTrader{int(time.time() * 1000)}"
    body = bytearray()
    for k, v in extra_fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{v}\r\n".encode("utf-8"))
    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode("utf-8"))
    body.extend(f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"))
    body.extend(file_bytes)
    body.extend(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    last_err = ""
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=35) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_err = str(e)
            log_debug(f"[TG MULTIPART ERR #{attempt}/3] {method}: {e}")
            if attempt < 3:
                time.sleep(1.5 * attempt)
    return {"ok": False, "error": last_err}


def send_tg_media_album(images_bytes: list[bytes], caption: str = "") -> bool:
    if not images_bytes or not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    if len(images_bytes) == 1:
        fields = {"chat_id": str(TELEGRAM_CHAT_ID), "parse_mode": "HTML"}
        if caption:
            fields["caption"] = caption[:960]
        res = send_tg_multipart("sendPhoto", "photo", "card.jpg", images_bytes[0], "image/jpeg", fields)
        return bool(res.get("ok"))

    boundary = f"----SenkuroAlbum{int(time.time() * 1000)}"
    media = []
    for i in range(len(images_bytes)):
        item: dict[str, Any] = {"type": "photo", "media": f"attach://p{i}"}
        if i == 0 and caption:
            item["caption"] = caption[:960]
            item["parse_mode"] = "HTML"
        media.append(item)
    body = bytearray()
    for k, v in [("chat_id", str(TELEGRAM_CHAT_ID)), ("media", json.dumps(media, ensure_ascii=False))]:
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{v}\r\n".encode("utf-8"))
    for i, b in enumerate(images_bytes):
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="p{i}"; filename="card_{i}.jpg"\r\n'.encode("utf-8"))
        body.extend(b"Content-Type: image/jpeg\r\n\r\n")
        body.extend(b)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup"
    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                if json.loads(resp.read().decode("utf-8")).get("ok"):
                    return True
        except Exception as e:
            log_debug(f"[TG ALBUM ERR #{attempt}/3] {e}")
            if attempt < 3:
                time.sleep(1.5 * attempt)
    return False


def send_debug_log() -> None:
    if not DEBUG_LOG_FILE.exists():
        send_tg_message("ℹ️ Файл лога пока пуст.", add_keyboard=True)
        return
    raw = DEBUG_LOG_FILE.read_bytes()[-150_000:]
    fields = {
        "chat_id": str(TELEGRAM_CHAT_ID),
        "caption": f"📜 <b>Лог помощника Senkuro {APP_VERSION_TAG}</b> ({max(1, len(raw)//1024)} КБ)",
        "parse_mode": "HTML",
        "reply_markup": json.dumps(get_reply_keyboard(), ensure_ascii=False),
    }
    res = send_tg_multipart("sendDocument", "document", "senkuro_trader_log.txt", raw, "text/plain", fields)
    if not res.get("ok"):
        tail = raw[-2800:].decode("utf-8", errors="ignore").replace("<", "&lt;").replace(">", "&gt;")
        send_tg_message(f"<pre>{tail}</pre>", add_keyboard=True)


# ==============================================================================
# 3. БАЗА ЦЕН SENKUTOOLS (АВТООБНОВЛЕНИЕ) + ЛОКАЛЬНАЯ БАЗА ЦЕЛЕЙ И СОСТОЯНИЯ
# ==============================================================================

def _load_cached_senkutools() -> None:
    global SENKUTOOLS_DB, SENKUTOOLS_META
    if not SENKUTOOLS_DB and SENKUTOOLS_PRICES_FILE.exists():
        try:
            SENKUTOOLS_DB = json.loads(SENKUTOOLS_PRICES_FILE.read_text(encoding="utf-8"))
        except Exception:
            SENKUTOOLS_DB = {}
    if not SENKUTOOLS_META and SENKUTOOLS_META_FILE.exists():
        try:
            SENKUTOOLS_META = json.loads(SENKUTOOLS_META_FILE.read_text(encoding="utf-8"))
        except Exception:
            SENKUTOOLS_META = {}


def ensure_senkutools_db(force_check: bool = True) -> dict[str, Any]:
    global SENKUTOOLS_DB, SENKUTOOLS_META
    _load_cached_senkutools()
    cached_ver = str(SENKUTOOLS_META.get("version") or "")
    note = "из кэша"
    if force_check or not SENKUTOOLS_DB:
        try:
            req = urllib.request.Request(
                SENKUTOOLS_AMO_API_URL,
                headers={"User-Agent": f"Mozilla/5.0 SenkuroTrader/{APP_VERSION_TAG}"},
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                amo = json.loads(resp.read().decode("utf-8"))
            cur_v = amo.get("current_version") or {}
            latest_ver = str(cur_v.get("version") or "").strip()
            xpi_url = str((cur_v.get("file") or {}).get("url") or "").strip()
            last_upd = str(amo.get("last_updated") or "")[:10]

            if latest_ver and xpi_url and (latest_ver != cached_ver or not SENKUTOOLS_DB):
                log_debug(f"[SENKUTOOLS] Загружаю новую версию v{latest_ver}...")
                req_x = urllib.request.Request(xpi_url, headers={"User-Agent": f"Mozilla/5.0 SenkuroTrader/{APP_VERSION_TAG}"})
                with urllib.request.urlopen(req_x, timeout=25) as xr:
                    xpi_bytes = xr.read()
                with zipfile.ZipFile(io.BytesIO(xpi_bytes)) as zf:
                    raw_db = json.loads(zf.read("database.json").decode("utf-8"))
                parsed_db: dict[str, dict[str, Any]] = {}
                if isinstance(raw_db, dict):
                    for slug_k, val in raw_db.items():
                        if isinstance(val, dict) and val.get("price") is not None:
                            try:
                                parsed_db[str(slug_k).strip().lower()] = {
                                    "price": float(val["price"]),
                                    "rank": str(val.get("rank") or "?").upper(),
                                    "name": str(val.get("name") or slug_k),
                                    "manga": str(val.get("manga") or ""),
                                }
                            except Exception:
                                pass
                if parsed_db:
                    SENKUTOOLS_DB = parsed_db
                    SENKUTOOLS_META = {
                        "version": latest_ver,
                        "last_updated": last_upd,
                        "cards_count": len(parsed_db),
                        "checked_at": kyiv_now().strftime("%Y-%m-%d %H:%M:%S"),
                    }
                    SENKUTOOLS_PRICES_FILE.write_text(json.dumps(parsed_db, ensure_ascii=False), encoding="utf-8")
                    SENKUTOOLS_META_FILE.write_text(json.dumps(SENKUTOOLS_META, ensure_ascii=False), encoding="utf-8")
                    note = f"обновлена до {latest_ver}"
                    log_debug(f"[SENKUTOOLS OK] Сохранена база v{latest_ver} ({len(parsed_db)} карт).")
            elif latest_ver:
                SENKUTOOLS_META["version"] = latest_ver
                SENKUTOOLS_META["last_updated"] = last_upd or SENKUTOOLS_META.get("last_updated", "")
                SENKUTOOLS_META["cards_count"] = len(SENKUTOOLS_DB)
                note = "актуальна"
        except Exception as e:
            log_debug(f"[SENKUTOOLS WARN] {e}")
            note = "из кэша" if SENKUTOOLS_DB else "недоступна"

    return {
        "version": str(SENKUTOOLS_META.get("version") or "—"),
        "last_updated": str(SENKUTOOLS_META.get("last_updated") or ""),
        "cards_count": len(SENKUTOOLS_DB),
        "note": note,
    }


def get_net_price(slug: str) -> Optional[float]:
    clean = str(slug or "").strip("/").split("/")[-1].lower()
    entry = SENKUTOOLS_DB.get(clean)
    if not entry:
        return None
    raw_p = entry["price"] if isinstance(entry, dict) else float(entry)
    return round(float(raw_p) * BANK_COMMISSION_MULT, 2)


def format_st_header(st_info: dict[str, Any]) -> str:
    upd = f", от {st_info['last_updated']}" if st_info.get("last_updated") else ""
    return (
        f"🏦 <b><a href='{SENKUTOOLS_AMO_PAGE_URL}'>SenkuTools</a>:</b> "
        f"v<b>{st_info['version']}</b> ({st_info['note']}{upd} | {st_info['cards_count']} карт)"
    )


def load_trade_db() -> dict[str, Any]:
    default_db: dict[str, Any] = {
        "guild_blacklist": {},
        "shown_users": {},
        "sent_trades": {},       # "owner_slug|card_slug" -> ts (не шлём повторно 48 ч)
        "targets": {},
        "scanned_cards": {},
    }
    if TRADE_DB_FILE.exists():
        try:
            loaded = json.loads(TRADE_DB_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for k, v in default_db.items():
                    if k not in loaded or not isinstance(loaded[k], dict):
                        loaded[k] = v
                loaded["guild_blacklist"] = {
                    u_k: u_v for u_k, u_v in loaded.get("guild_blacklist", {}).items()
                    if str((u_v or {}).get("guild") or "").strip().lower() not in ("гильдии", "guilds", "guild", "")
                }
                return loaded
        except Exception:
            pass
    return default_db


def save_trade_db(db: dict[str, Any]) -> None:
    try:
        now = time.time()
        db["targets"] = {k: v for k, v in db.get("targets", {}).items() if now - float(v.get("verified_at") or 0) < TARGET_TTL_SECONDS}
        db["scanned_cards"] = {k: ts for k, ts in db.get("scanned_cards", {}).items() if now - float(ts or 0) < TARGET_TTL_SECONDS}
        db["sent_trades"] = {k: ts for k, ts in db.get("sent_trades", {}).items() if now - float(ts or 0) < 48 * 3600}
        db["guild_blacklist"] = {k: v for k, v in db.get("guild_blacklist", {}).items() if now - float(v.get("ts") or 0) < 14 * 86400}
        TRADE_DB_FILE.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log_debug(f"[DB SAVE WARN] {e}")


def load_auto_state() -> dict[str, Any]:
    default_st: dict[str, Any] = {
        "last_morning_reset_date": "",
        "last_wave_ts": 0.0,
        "last_monitor_ts": 0.0,
        "notified_profitable_ids": [],
        "bank_uid": "",
        "token_warned_ts": 0.0,
    }
    if AUTO_STATE_FILE.exists():
        try:
            d = json.loads(AUTO_STATE_FILE.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                default_st.update(d)
        except Exception:
            pass
    return default_st


def save_auto_state(st: dict[str, Any]) -> None:
    try:
        AUTO_STATE_FILE.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ==============================================================================
# 4. ГОЛЫЕ GRAPHQL-ЗАПРОСЫ ЧЕРЕЗ УКРАИНСКИЙ ПРОКСИ (~5 КБ/ЗАПРОС!)
# ==============================================================================

GQL_FETCH_USER_BY_SLUG = """
query fetchUserBySlug($slug: String!) {
  user(slug: $slug) { id slug name }
}
"""

GQL_FETCH_USER_CARDS = """
query fetchUserCards($userId: ID!, $after: String, $modifier: UserCardModifierFilter) {
  userCards(
    first: 40
    after: $after
    userId: $userId
    modifier: $modifier
    orderBy: { field: CREATED_AT, direction: DESC }
  ) {
    edges {
      node {
        cardId
        quantity
        modifier
        shard
        locked
        card {
          id
          slug
          rank
          titles { lang content }
          image { original { url } }
        }
      }
    }
    pageInfo { hasNextPage endCursor }
  }
}
"""

GQL_FETCH_CARD_TRADES = """
query fetchCardTrades($userId: ID!, $status: CardTradeStatus) {
  cardTrades(first: 40, userId: $userId, status: $status, orderBy: { field: CREATED_AT, direction: DESC }) {
    edges {
      node {
        id
        status
        createdAt
        viewerCanDecline
        source { id slug }
        destination { id slug }
      }
    }
  }
}
"""

GQL_SUGGEST_CARD_TRADE = """
mutation suggestCardTrade($input: SuggestCardTradeInput!) {
  suggestCardTrade(input: $input) { success }
}
"""

GQL_DECLINE_CARD_TRADE = """
mutation declineCardTrade($input: DeclineCardTradeInput!) {
  declineCardTrade(input: $input) { success }
}
"""

GQL_CANCEL_CARD_TRADE = """
mutation cancelCardTrade($input: CancelCardTradeInput!) {
  cancelCardTrade(input: $input) { success }
}
"""


def direct_ua_gql_call(query: str, variables: dict, op_name: str) -> dict:
    """
    Отправляет голый GraphQL-запрос от имени cesium254 строго через украинский резидентский прокси
    (UKRAINE_PROXY_URL) и SENKURO_MAIN_TOKEN. Вес 1 запроса ~5-10 КБ!
    """
    if not SENKURO_MAIN_TOKEN:
        return {"errors": [{"message": "NO_TOKEN"}]}
    proxy_url = parse_proxy_url(UKRAINE_PROXY_RAW)
    if not proxy_url:
        return {"errors": [{"message": "NO_UA_PROXY"}]}

    token_hdr = SENKURO_MAIN_TOKEN if SENKURO_MAIN_TOKEN.startswith("Bearer ") else f"Bearer {SENKURO_MAIN_TOKEN}"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "App-Version": APP_HEADER_VERSION,
        "Origin": "https://senkuro.com",
        "Referer": "https://senkuro.com/",
        "Authorization": token_hdr,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    }
    payload = json.dumps({"query": query, "variables": variables, "operationName": op_name}).encode("utf-8")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}))
    req = urllib.request.Request(GRAPHQL_API_URL, data=payload, headers=headers, method="POST")
    try:
        with opener.open(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
            return json.loads(raw)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        log_debug(f"[UA GQL HTTP {e.code}] op={op_name}: {body[:200]}")
        return {"errors": [{"message": f"HTTP {e.code}: {body[:160]}"}]}
    except Exception as e:
        log_debug(f"[UA GQL ERR] op={op_name}: {e}")
        return {"errors": [{"message": str(e)}]}


def _check_and_alert_token_error(res: dict) -> bool:
    errs = res.get("errors") or []
    err_txt = " ".join(str(e.get("message") or "") for e in errs if isinstance(e, dict)).lower()
    if any(w in err_txt for w in ("unauthorized", "unauthenticated", "401", "invalid token", "expired")):
        st = load_auto_state()
        if time.time() - float(st.get("token_warned_ts") or 0) > 6 * 3600:
            st["token_warned_ts"] = time.time()
            save_auto_state(st)
            send_tg_message(
                "⚠️ <b>Токен авторизации Senkuro устарел!</b>\n"
                "Обновите секрет <code>SENKURO_MAIN_TOKEN</code> на GitHub, чтобы авто-обмены и кнопка банка снова заработали.",
                add_keyboard=True,
            )
        return True
    return False


# ==============================================================================
# 5. БЕСПЛАТНЫЙ OPERA VPN ДЛЯ ПУБЛИЧНОГО СКАНИРОВАНИЯ (0 БАЙТ UA ПРОКСИ)
# ==============================================================================

class LightweightProxyPool:
    def __init__(self) -> None:
        self.procs: list[subprocess.Popen] = []
        self.ports: list[int] = []

    def _port_open(self, port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.4):
                return True
        except Exception:
            return False

    def start_pool(self, count: int = 3) -> list[str]:
        bin_path = Path("bin/opera-proxy")
        if not bin_path.exists():
            return []
        regions = ["EU", "AM", "AS"]
        urls: list[str] = []
        for idx in range(count):
            port = 25410 + idx
            reg = regions[idx % len(regions)]
            if self._port_open(port):
                self.ports.append(port)
                urls.append(f"http://127.0.0.1:{port}")
                continue
            proc = subprocess.Popen(
                [
                    str(bin_path),
                    "-country", reg,
                    "-bind-address", f"127.0.0.1:{port}",
                    "-bootstrap-dns", "https://1.1.1.1/dns-query,https://12.8.8.8/dns-query",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            self.procs.append(proc)
            for _ in range(25):
                if proc.poll() is not None or self._port_open(port):
                    break
                time.sleep(0.2)
            if self._port_open(port):
                self.ports.append(port)
                urls.append(f"http://127.0.0.1:{port}")
        return urls

    def stop_all(self) -> None:
        for proc in self.procs:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self.procs.clear()
        self.ports.clear()


async def gql_public_call(page: Page, query: str, variables: dict, op_name: str) -> dict:
    payload = {"query": query, "variables": variables, "operationName": op_name}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "App-Version": APP_HEADER_VERSION,
        "Origin": "https://senkuro.com",
        "Referer": "https://senkuro.com/",
    }
    for attempt in range(3):
        try:
            resp = await page.context.request.post(GRAPHQL_API_URL, headers=headers, data=json.dumps(payload), timeout=15000)
            if resp.ok:
                data = await resp.json()
                if isinstance(data, dict) and not data.get("errors"):
                    return data
        except Exception:
            pass
        await asyncio.sleep(1.2)
    return {}


async def fetch_public_user_cards(page: Page, user_id: str, modifier_val: int = 0, max_pages: int = 12) -> list[dict]:
    nodes: list[dict] = []
    after: Optional[str] = None
    for _ in range(max_pages):
        vars_d: dict[str, Any] = {"userId": user_id, "modifier": {"include": [modifier_val]}}
        if after:
            vars_d["after"] = after
        res = await gql_public_call(page, GQL_FETCH_USER_CARDS, vars_d, "fetchUserCards")
        uc = (res.get("data") or {}).get("userCards") or {}
        edges = uc.get("edges") or []
        for e in edges:
            nd = e.get("node")
            if nd:
                nodes.append(nd)
        pi = uc.get("pageInfo") or {}
        if not pi.get("hasNextPage") or not pi.get("endCursor"):
            break
        after = pi["endCursor"]
    return nodes


def extract_card_title(card_obj: dict) -> str:
    titles = card_obj.get("titles") or []
    for lang in ("RU", "EN"):
        for t in titles:
            if str(t.get("lang") or "").upper() == lang and t.get("content"):
                return str(t["content"]).strip()
    if titles and titles[0].get("content"):
        return str(titles[0]["content"]).strip()
    return str(card_obj.get("slug") or "Карта")


def render_card_with_price_badge(raw_bytes: bytes, net_price: Optional[float]) -> Optional[bytes]:
    if not raw_bytes or len(raw_bytes) < 64:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont
        with Image.open(io.BytesIO(raw_bytes)) as im:
            if getattr(im, "is_animated", False):
                im.seek(0)
            rgb = im.convert("RGB")
            if rgb.width > 1600 or rgb.height > 1600:
                rgb.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
            if net_price is not None:
                base = rgb.convert("RGBA")
                w, h = base.size
                font_sz = max(18, min(44, int(w * 0.085)))
                font = None
                for fp in (
                    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                ):
                    if Path(fp).exists():
                        try:
                            font = ImageFont.truetype(fp, font_sz)
                            break
                        except Exception:
                            pass
                if font is None:
                    font = ImageFont.load_default()
                label = f"{net_price:.2f}"
                ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
                dr = ImageDraw.Draw(ov)
                bb = dr.textbbox((0, 0), label, font=font)
                tw, th = bb[2] - bb[0], bb[3] - bb[1]
                px, py = max(10, int(font_sz * 0.45)), max(6, int(font_sz * 0.28))
                mg = max(10, int(w * 0.035))
                x1, y1 = max(4, w - mg - tw - px * 2), max(4, h - mg - th - py * 2)
                x2, y2 = w - mg, h - mg
                if net_price >= 2.00:
                    bg, brd = (220, 50, 75, 230), (255, 215, 90, 255)
                elif net_price >= MIN_BANK_PROFIT_NET:
                    bg, brd = (26, 155, 72, 230), (145, 255, 175, 255)
                else:
                    bg, brd = (20, 22, 30, 210), (130, 138, 155, 200)
                dr.rounded_rectangle([x1, y1, x2, y2], radius=max(8, int((y2 - y1) * 0.28)), fill=bg, outline=brd, width=max(2, int(w * 0.005)))
                dr.text((x1 + px - bb[0], y1 + py - bb[1]), label, font=font, fill=(255, 255, 255, 255))
                rgb = Image.alpha_composite(base, ov).convert("RGB")
            out = io.BytesIO()
            rgb.save(out, format="JPEG", quality=94, subsampling=0)
            return out.getvalue()
    except Exception:
        return None


async def launch_browser(pw):
    exe = "/usr/bin/google-chrome-stable" if Path("/usr/bin/google-chrome-stable").exists() else None
    kwargs: dict[str, Any] = {
        "headless": True,
        "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-blink-features=AutomationControlled"],
    }
    if exe:
        kwargs["executable_path"] = exe
    return await pw.chromium.launch(**kwargs)


# ==============================================================================
# 6. ИНСПЕКЦИЯ ОСНОВЫ CESIUM254 + СКАНЕР ЦЕЛЕЙ (БЕЗ ГИЛЬДИИ + НЕ ЗАКРЕПЛЕНЫ)
# ==============================================================================

async def inspect_main_account(page: Page) -> dict[str, Any]:
    cards_nodes = await fetch_public_user_cards(page, MAIN_ACCOUNT_UID, modifier_val=0)
    shards_nodes = await fetch_public_user_cards(page, MAIN_ACCOUNT_UID, modifier_val=1)

    cards_info = []
    fodder_units_by_rank: dict[str, list[dict[str, Any]]] = {r: [] for r in ("F", "D", "C", "B", "A", "S")}
    fodder_by_rank: Counter = Counter()
    profitable_cards = []

    for nd in cards_nodes:
        c = nd.get("card") or {}
        cid = str(c.get("id") or nd.get("cardId") or "")
        slug = str(c.get("slug") or "")
        rank = str(c.get("rank") or "?").upper()
        qty = int(nd.get("quantity") or 1)
        mod = int(nd.get("modifier") or 0)
        locked = bool(nd.get("locked"))
        name = extract_card_title(c)
        img_url = str(((c.get("image") or {}).get("original") or {}).get("url") or "")
        net_p = get_net_price(slug)
        item = {
            "cardId": cid,
            "slug": slug,
            "rank": rank,
            "qty": qty,
            "modifier": mod,
            "locked": locked,
            "name": name,
            "img": img_url,
            "net_price": net_p,
        }
        cards_info.append(item)
        if not locked and cid and qty > 0:
            if net_p is not None and net_p >= MIN_BANK_PROFIT_NET:
                profitable_cards.append(item)
            elif rank in ("F", "D", "C", "B", "A", "S"):
                if rank in SEARCHABLE_RANKS:
                    fodder_by_rank[rank] += qty
                for _ in range(qty):
                    fodder_units_by_rank[rank].append({"cardId": cid, "modifier": mod, "rank": rank, "name": name})

    return {
        "cards": cards_info,
        "shards_count": sum(int(n.get("quantity") or 1) for n in shards_nodes),
        "fodder_by_rank": fodder_by_rank,
        "fodder_units_by_rank": fodder_units_by_rank,
        "profitable": profitable_cards,
    }


async def check_owner_profile_and_card(page: Page, owner_slug: str, card_slug: str, db: dict[str, Any]) -> tuple[bool, Optional[dict[str, str]]]:
    low_slug = owner_slug.strip().lower()
    if not low_slug or low_slug in (MAIN_ACCOUNT_SLUG.lower(), BANK_ACCOUNT_SLUG.lower()):
        return False, None
    if low_slug in db["guild_blacklist"]:
        return False, None

    try:
        await page.goto(f"https://senkuro.com/users/{owner_slug}", wait_until="domcontentloaded", timeout=22000)
        await asyncio.sleep(random.uniform(0.9, 1.5))
        guild_info = await page.evaluate(
            """() => {
                const links = Array.from(document.querySelectorAll('a[href*="/guilds/"], a[href*="/guild/"]'));
                for (const a of links) {
                    if (a.closest('header, nav, footer')) continue;
                    const href = (a.getAttribute('href') || '').trim();
                    const txt = (a.textContent || '').trim();
                    if (/^\\/?guilds?\\/?$/i.test(href) || txt.toLowerCase() === 'гильдии' || txt.toLowerCase() === 'guilds') continue;
                    if (/\\/guilds?\\/[^/?#]{2,}/i.test(href)) {
                        return (txt || href).slice(0, 50);
                    }
                }
                return '';
            }"""
        )
        if guild_info:
            db["guild_blacklist"][low_slug] = {"guild": str(guild_info), "ts": time.time()}
            log_debug(f"[SCAN SKIP GUILD] {owner_slug} ({guild_info}) -> в чёрный список.")
            return False, None
    except Exception:
        return False, None

    u_res = await gql_public_call(page, GQL_FETCH_USER_BY_SLUG, {"slug": owner_slug}, "fetchUserBySlug")
    uid = ((u_res.get("data") or {}).get("user") or {}).get("id")
    if not uid:
        return False, None

    u_cards = await fetch_public_user_cards(page, str(uid), modifier_val=0, max_pages=6)
    target_clean = card_slug.strip().lower()
    for nd in u_cards:
        c_obj = nd.get("card") or {}
        c_s = str(c_obj.get("slug") or "").strip().lower()
        if c_s == target_clean:
            if bool(nd.get("locked")):
                return False, None
            if int(nd.get("quantity") or 0) > 0:
                return True, {"user_id": str(uid), "card_id": str(c_obj.get("id") or nd.get("cardId") or "")}
    return False, None


async def scan_cards_batch_into_db(
    target_ranks: list[str],
    max_cards_to_scan: int = 10,
    stop_when_found: int = 8,
    min_net: float = MIN_TARGET_NET_PRICE,
    max_net: float = 999.0,
) -> dict[str, int]:
    db = load_trade_db()
    now = time.time()
    ranks_set = {r.upper() for r in target_ranks if r.upper() in SEARCHABLE_RANKS} or set(SEARCHABLE_RANKS)

    def _collect_candidates(relaxed: bool = False) -> list[tuple[str, dict[str, Any], float]]:
        out = []
        for c_slug, c_info in SENKUTOOLS_DB.items():
            if not isinstance(c_info, dict):
                continue
            r = str(c_info.get("rank") or "").upper()
            if r not in ranks_set:
                continue
            net_p = round(float(c_info.get("price") or 0) * BANK_COMMISSION_MULT, 2)
            if net_p < min_net or net_p > max_net:
                continue
            cd_sec = (2 * 3600) if relaxed else (8 * 3600 if net_p >= 2.60 else 18 * 3600)
            if now - float(db["scanned_cards"].get(c_slug) or 0) < cd_sec:
                continue
            out.append((c_slug, c_info, net_p))
        return out

    candidates = _collect_candidates(relaxed=False)
    if len(candidates) < 4:
        candidates = _collect_candidates(relaxed=True)

    random.shuffle(candidates)
    candidates.sort(key=lambda x: (x[2] + random.uniform(-0.15, 0.15)), reverse=True)
    batch = candidates[:max_cards_to_scan]
    stats = {"cards_scanned": 0, "owners_checked": 0, "new_targets": 0}
    if not batch:
        return stats

    proxy_pool = LightweightProxyPool()
    try:
        proxies = await asyncio.to_thread(proxy_pool.start_pool, 3)
        async with async_playwright() as pw:
            browser = await launch_browser(pw)
            contexts, pages = [], []
            try:
                for i in range(max(1, len(proxies))):
                    p_cfg = {"server": proxies[i]} if i < len(proxies) else None
                    ctx = await browser.new_context(proxy=p_cfg, viewport={"width": 1280, "height": 800})
                    contexts.append(ctx)
                    pages.append(await ctx.new_page())

                for idx_c, (c_slug, c_info, net_p) in enumerate(batch):
                    if STOP_FLAG or stats["new_targets"] >= stop_when_found:
                        break
                    pg = pages[idx_c % len(pages)]
                    db["scanned_cards"][c_slug] = time.time()
                    stats["cards_scanned"] += 1
                    try:
                        await pg.goto(f"https://senkuro.com/cards/{c_slug}", wait_until="domcontentloaded", timeout=25000)
                        await asyncio.sleep(random.uniform(1.4, 2.2))
                        owner_slugs = await pg.evaluate(
                            """() => {
                                const out = [], seen = new Set();
                                document.querySelectorAll('a[href*="/users/"]').forEach(a => {
                                    const m = (a.getAttribute('href') || '').match(/\\/users\\/([^/?#]+)/);
                                    if (m && m[1] && !seen.has(m[1].toLowerCase())) {
                                        seen.add(m[1].toLowerCase());
                                        out.push(m[1]);
                                    }
                                });
                                return out.slice(0, 12);
                            }"""
                        )
                    except Exception:
                        continue

                    for o_slug in (owner_slugs or []):
                        if STOP_FLAG or stats["new_targets"] >= stop_when_found:
                            break
                        key = f"{o_slug.lower()}|{c_slug.lower()}"
                        if key in db["targets"] or o_slug.lower() in db["guild_blacklist"]:
                            continue
                        stats["owners_checked"] += 1
                        ok, ids_obj = await check_owner_profile_and_card(pg, o_slug, c_slug, db)
                        if ok and ids_obj and ids_obj.get("user_id") and ids_obj.get("card_id"):
                            db["targets"][key] = {
                                "user_slug": o_slug,
                                "user_id": ids_obj["user_id"],
                                "card_slug": c_slug,
                                "card_id": ids_obj["card_id"],
                                "card_name": str(c_info.get("name") or c_slug),
                                "rank": str(c_info.get("rank") or "?").upper(),
                                "net_price": net_p,
                                "raw_price": float(c_info.get("price") or 0),
                                "verified_at": time.time(),
                            }
                            stats["new_targets"] += 1
                            log_debug(f"[TARGET FOUND] {o_slug} (без гильдии) -> {c_info.get('rank')} «{c_info.get('name')}» ({net_p:.2f} чистыми)")
                        await asyncio.sleep(random.uniform(0.7, 1.2))
                    save_trade_db(db)
            finally:
                for ctx in contexts:
                    try:
                        await ctx.close()
                    except Exception:
                        pass
                await browser.close()
    finally:
        proxy_pool.stop_all()
        save_trade_db(db)
    return stats


# ==============================================================================
# 7. АВТО-ВОЛНА ОБМЕНОВ (09:00–18:00 KYIV) + УТРЕННЯЯ ОТМЕНА + КНОПКА В БАНК
# ==============================================================================

def _compress_offer_units(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter = Counter()
    for u in units:
        counts[(str(u["cardId"]), int(u.get("modifier") or 0))] += 1
    return [{"cardId": cid, "modifier": mod, "quantity": q} for (cid, mod), q in counts.items()]


async def cancel_stale_outgoing_trades_morning() -> int:
    if not SENKURO_MAIN_TOKEN or not UKRAINE_PROXY_RAW:
        return 0
    res = await asyncio.to_thread(
        direct_ua_gql_call,
        GQL_FETCH_CARD_TRADES,
        {"userId": MAIN_ACCOUNT_UID, "status": "PENDING"},
        "fetchCardTrades",
    )
    if _check_and_alert_token_error(res):
        return 0
    edges = ((res.get("data") or {}).get("cardTrades") or {}).get("edges") or []
    cancelled = 0
    for e in edges:
        nd = e.get("node") or {}
        src_slug = str((nd.get("source") or {}).get("slug") or "").lower()
        dst_slug = str((nd.get("destination") or {}).get("slug") or "").lower()
        # Отменяем только свои исходящие обмены (и не трогаем обмен в банк goldlotus)
        if src_slug != MAIN_ACCOUNT_SLUG.lower() or dst_slug == BANK_ACCOUNT_SLUG.lower():
            continue
        tid = nd.get("id")
        if not tid:
            continue
        await asyncio.sleep(random.uniform(2.0, 4.0))
        c_res = await asyncio.to_thread(direct_ua_gql_call, GQL_CANCEL_CARD_TRADE, {"input": {"tradeId": tid}}, "cancelCardTrade")
        ok = ((c_res.get("data") or {}).get("cancelCardTrade") or {}).get("success")
        if not ok:
            d_res = await asyncio.to_thread(direct_ua_gql_call, GQL_DECLINE_CARD_TRADE, {"input": {"tradeId": tid}}, "declineCardTrade")
            ok = ((d_res.get("data") or {}).get("declineCardTrade") or {}).get("success")
        if ok:
            cancelled += 1
    if cancelled:
        log_debug(f"[MORNING RESET] Отменено {cancelled} вчерашних непринятых трейдов.")
    return cancelled


async def send_profitable_card_to_bank(card_id: str) -> None:
    if not SENKURO_MAIN_TOKEN or not UKRAINE_PROXY_RAW:
        send_tg_message("⚠️ Для отправки в банк нужно добавить секреты <code>SENKURO_MAIN_TOKEN</code> и <code>UKRAINE_PROXY_URL</code> на GitHub.", add_keyboard=True)
        return

    st = load_auto_state()
    bank_uid = st.get("bank_uid") or ""
    if not bank_uid:
        u_res = await asyncio.to_thread(direct_ua_gql_call, GQL_FETCH_USER_BY_SLUG, {"slug": BANK_ACCOUNT_SLUG}, "fetchUserBySlug")
        bank_uid = str(((u_res.get("data") or {}).get("user") or {}).get("id") or "")
        if bank_uid:
            st["bank_uid"] = bank_uid
            save_auto_state(st)
    if not bank_uid:
        send_tg_message(f"⚠️ Не удалось получить ID банка <b>{BANK_ACCOUNT_SLUG}</b>.", add_keyboard=True)
        return

    # Если нажата кнопка "bank:all" — отправляем ВСЕ выгодные карты ОДНИМ общим трейдом
    if card_id == "all":
        items = list(BANK_PENDING_CARDS.items())
        if not items:
            send_tg_message("ℹ️ Список выгодных карт пуст — нажмите <b>«🃏 Мои карты»</b> для обновления.", add_keyboard=True)
            return
        offer_list = [
            {"cardId": cid, "modifier": 0, "quantity": int(meta.get("qty") or 1)}
            for cid, meta in items
        ]
        labels = [str(meta.get("label") or cid) for cid, meta in items]
    else:
        meta = BANK_PENDING_CARDS.get(card_id) or {}
        offer_list = [{"cardId": card_id, "modifier": 0, "quantity": int(meta.get("qty") or 1)}]
        labels = [str(meta.get("label") or card_id)]

    res = await asyncio.to_thread(
        direct_ua_gql_call,
        GQL_SUGGEST_CARD_TRADE,
        {
            "input": {
                "userId": bank_uid,
                "offer": offer_list,
                "request": [],
                "description": [],
            }
        },
        "suggestCardTrade",
    )
    if _check_and_alert_token_error(res):
        return
    if ((res.get("data") or {}).get("suggestCardTrade") or {}).get("success"):
        if card_id == "all":
            BANK_PENDING_CARDS.clear()
        else:
            BANK_PENDING_CARDS.pop(card_id, None)
        body = "\n".join(f"• {lb}" for lb in labels)
        send_tg_message(
            f"✅ <b>Отправлено в банк <a href='{BANK_ACCOUNT_URL}'>{BANK_ACCOUNT_SLUG}</a> одним трейдом ({len(offer_list)} шт.):</b>\n{body}\n\n"
            "👉 Заходите в банк и подтверждайте начисление баланса!",
            add_keyboard=True,
        )
        log_debug(f"[BANK SENT OK] {len(offer_list)} cards -> {BANK_ACCOUNT_SLUG}")
    else:
        errs = res.get("errors") or []
        msg = errs[0].get("message", "ошибка API") if errs else "неизвестная ошибка"
        send_tg_message(f"⚠️ Не удалось отправить в банк: <code>{str(msg)[:200]}</code>", add_keyboard=True)


async def check_and_notify_new_profitable_cards(my_data: dict[str, Any]) -> None:
    """Тихий режим v61.0: не шлёт пуши в Telegram днём и ночью. Просто обновляет кэш выгодных карт для вечерней кнопки '🃏 Мои карты' -> '🏦 Отправить всё в банк'."""
    BANK_PENDING_CARDS.clear()
    for p_it in my_data["profitable"]:
        cid = p_it["cardId"]
        badge = RANK_BADGE.get(p_it["rank"], p_it["rank"])
        qty = int(p_it.get("qty") or 1)
        q_sfx = f" ×{qty}" if qty > 1 else ""
        lbl = f"{badge} «{p_it['name']}»{q_sfx} (<b>{p_it['net_price']:.2f}</b> чистыми)"
        BANK_PENDING_CARDS[cid] = {"label": lbl, "net_price": p_it["net_price"], "qty": qty}
    st = load_auto_state()
    st["last_monitor_ts"] = time.time()
    save_auto_state(st)


def _build_profitable_combo_blueprints(
    fodder_units: dict[str, list[dict[str, Any]]],
    usage_today: Counter,
) -> list[dict[str, Any]]:
    """
    Математический оптимизатор v61.0:
    Перебирает ВСЕ доступные прибыльные комбинации по всем рангам (S, A, B, C, D)
    с учётом себестоимости (1×ранг=1.25, -1 ранг=0.42, -2 ранга=0.14):
      1) 1×R + 1×(R-1)  [cost=1.67, цели >= 2.00 -> профит +0.33..+1.33]
      2) 2×R            [cost=2.50, цели >= 2.60 -> профит +0.10..+0.50]
      3) 1×R + 1×(R-2)  [cost=1.39, цели >= 1.60 -> профит +0.21..+1.41]
      4) 1×R (1-в-1)    [cost=1.25, цели 1.60..1.99 -> фоллбэк, если нет младших карт]
    Новые карты (usage_today == 0) всегда идут первыми; далее ротация по кругам (круг 2, 3...).
    """
    rank_weight = {"S": 27.0, "A": 9.0, "B": 3.0, "C": 1.6, "D": 1.0}
    blueprints: list[dict[str, Any]] = []

    def _sorted_pool(r_name: str) -> list[dict[str, Any]]:
        units = list(fodder_units.get(r_name) or [])
        # Сортируем: сначала карты с минимальным числом использований сегодня (новые -> 0), затем стабильно по cardId
        units.sort(key=lambda u: (usage_today.get(str(u.get("cardId") or ""), 0), str(u.get("cardId") or "")))
        return units

    for rank in reversed(SEARCHABLE_RANKS):  # S -> A -> B -> C -> D
        p_same = _sorted_pool(rank)
        if not p_same:
            continue
        low1_r = LOWER_RANK_MAP.get(rank)
        low2_r = LOWER2_RANK_MAP.get(rank)
        p_low1 = _sorted_pool(low1_r) if low1_r else []
        p_low2 = _sorted_pool(low2_r) if low2_r else []
        rw = rank_weight.get(rank, 1.0)

        # Комбинация 1: 1×R + 1×(R-1) (самая высокая маржа: +0.33..+1.33)
        if p_low1:
            offer = [p_same[0], p_low1[0]]
            avg_u = sum(usage_today.get(str(u.get("cardId") or ""), 0) for u in offer) / 2.0
            fresh_bonus = 2.2 if avg_u == 0 else (1.0 / (1.0 + 0.45 * avg_u))
            blueprints.append({
                "rank": rank,
                "kind": "1+low1",
                "desc": f"1×{rank}+1×{low1_r}",
                "offer": offer,
                "cost": 1.67,
                "min_net": 2.00,
                "max_net": 999.0,
                "round_num": int(avg_u) + 1,
                "base_score": rw * 1.35 * fresh_bonus,
            })

        # Комбинация 2: 2×R (высокий шанс принятия на 2.60+, формируем до 3 разных пар если карт много)
        if len(p_same) >= 2:
            num_pairs = min(3, len(p_same) // 2)
            for idx_p in range(num_pairs):
                offer = [p_same[idx_p * 2], p_same[idx_p * 2 + 1]]
                avg_u = sum(usage_today.get(str(u.get("cardId") or ""), 0) for u in offer) / 2.0
                fresh_bonus = 2.0 if avg_u == 0 else (1.0 / (1.0 + 0.45 * avg_u))
                blueprints.append({
                    "rank": rank,
                    "kind": "2xsame",
                    "desc": f"2×{rank}",
                    "offer": offer,
                    "cost": 2.50,
                    "min_net": 2.60,
                    "max_net": 999.0,
                    "round_num": int(avg_u) + 1,
                    "base_score": rw * 1.10 * fresh_bonus,
                })

        # Комбинация 3: 1×R + 1×(R-2) (себестоимость 1.39, выгодно на 1.60–2.59 и привлекательнее 1-в-1)
        if p_low2:
            offer = [p_same[0], p_low2[0]]
            avg_u = sum(usage_today.get(str(u.get("cardId") or ""), 0) for u in offer) / 2.0
            fresh_bonus = 1.9 if avg_u == 0 else (1.0 / (1.0 + 0.45 * avg_u))
            blueprints.append({
                "rank": rank,
                "kind": "1+low2",
                "desc": f"1×{rank}+1×{low2_r}",
                "offer": offer,
                "cost": 1.39,
                "min_net": 1.60,
                "max_net": 2.59,
                "round_num": int(avg_u) + 1,
                "base_score": rw * 1.05 * fresh_bonus,
            })

        # Комбинация 4: 1×R (1-в-1, строго 1.60–1.99 — фоллбэк, когда нет ни 2×R, ни младших карт)
        if not p_low1 and not p_low2 and len(p_same) == 1:
            offer = [p_same[0]]
            u0 = usage_today.get(str(p_same[0].get("cardId") or ""), 0)
            fresh_bonus = 1.5 if u0 == 0 else (1.0 / (1.0 + 0.45 * u0))
            blueprints.append({
                "rank": rank,
                "kind": "1for1",
                "desc": f"1×{rank}",
                "offer": offer,
                "cost": 1.25,
                "min_net": 1.60,
                "max_net": 1.99,
                "round_num": int(u0) + 1,
                "base_score": rw * 0.75 * fresh_bonus,
            })

    blueprints.sort(key=lambda b: b["base_score"], reverse=True)
    return blueprints


async def run_auto_trade_wave(manual_trigger: bool = False) -> None:
    if not SENKURO_MAIN_TOKEN or not UKRAINE_PROXY_RAW:
        if manual_trigger:
            send_tg_message(
                "⚠️ <b>Авто-обмены пока не подключены:</b> добавьте секреты <code>SENKURO_MAIN_TOKEN</code> и <code>UKRAINE_PROXY_URL</code> в GitHub Secrets.",
                add_keyboard=True,
            )
        return

    if not manual_trigger and not is_working_hours_kyiv():
        return

    st = load_auto_state()
    now_ts = time.time()

    # 1. Адаптивный скользящий контроль лимита (61 мин от КАЖДОГО трейда + 10 мин после ответа лимита от сайта)
    rl_until = float(st.get("rate_limit_until") or 0)
    if rl_until > now_ts:
        mins_rl = max(1, int((rl_until - now_ts) // 60) + 1)
        if manual_trigger:
            send_tg_message(
                f"⏳ <b>Сайт временно ограничил частоту обменов.</b>\n"
                f"Следующая авто-проверка примерно через <b>{mins_rl} мин</b>.",
                add_keyboard=True,
            )
        return

    recent_ts = [float(x) for x in (st.get("recent_trade_ts") or []) if now_ts - float(x) < WAVE_INTERVAL_SEC]
    remaining_slots = max(0, MAX_TRADES_PER_WAVE - len(recent_ts))
    if remaining_slots <= 0:
        oldest = min(recent_ts) if recent_ts else now_ts
        mins_left = max(1, int((WAVE_INTERVAL_SEC - (now_ts - oldest)) // 60) + 1)
        if manual_trigger:
            send_tg_message(
                f"⏳ <b>Скользящий лимит выбран ({len(recent_ts)}/{MAX_TRADES_PER_WAVE} обменов за последний час).</b>\n"
                f"Первый слот освободится через <b>{mins_left} мин</b> — бот сам продолжит работу.",
                add_keyboard=True,
            )
        return

    # Всегда обновляем базу SenkuTools перед волной
    await asyncio.to_thread(ensure_senkutools_db, True)

    # Всегда сканируем актуальный инвентарь cesium254 (через бесплатный Opera VPN — 0 байт UA прокси)
    proxy_pool = LightweightProxyPool()
    my_data: dict[str, Any] = {}
    try:
        proxies = await asyncio.to_thread(proxy_pool.start_pool, 1)
        p_cfg = {"server": proxies[0]} if proxies else None
        async with async_playwright() as pw:
            browser = await launch_browser(pw)
            ctx = await browser.new_context(proxy=p_cfg)
            page = await ctx.new_page()
            try:
                my_data = await inspect_main_account(page)
            finally:
                await ctx.close()
                await browser.close()
    finally:
        proxy_pool.stop_all()

    if not my_data:
        return

    await check_and_notify_new_profitable_cards(my_data)

    fodder_units = my_data["fodder_units_by_rank"]
    active_ranks = [r for r in SEARCHABLE_RANKS if len(fodder_units.get(r) or []) > 0]
    if not active_ranks:
        if manual_trigger:
            send_tg_message("ℹ️ На основе сейчас нет свободных дешёвых карт рангов D–S для авто-обмена.", add_keyboard=True)
        return

    # 2. Суточный счётчик использований карт (ТОЛЬКО для приоритета новых карт и ротации кругов — НИКОГДА не стопит работу!)
    today_kyiv = kyiv_now().strftime("%Y-%m-%d")
    if st.get("usage_today_date") != today_kyiv:
        st["usage_today_date"] = today_kyiv
        st["card_usage_today"] = {}
    usage_today: Counter = Counter({str(k): int(v) for k, v in (st.get("card_usage_today") or {}).items()})

    blueprints = _build_profitable_combo_blueprints(fodder_units, usage_today)
    if not blueprints:
        if manual_trigger:
            send_tg_message("ℹ️ Под текущие карты пока не собирается прибыльная комбинация.", add_keyboard=True)
        return

    # Если доступна только 1 комбинация — отдаём ей ВСЕ свободные слоты часа (до 9); иначе до 5 на комбинацию (чтобы комбинировать!)
    effective_cap = remaining_slots if len(blueprints) == 1 else MAX_ORDERS_PER_BATCH

    # 3. Проактивно досканируем свежие цели для топ-комбинаций (бесплатный Opera VPN)
    db = load_trade_db()
    now = time.time()

    def _load_fresh(cur_db: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        return [
            (k, t) for k, t in cur_db.get("targets", {}).items()
            if t.get("rank") in active_ranks
            and t.get("user_id")
            and t.get("card_id")
            and now - float(t.get("verified_at") or 0) < TARGET_TTL_SECONDS
            and k not in cur_db.get("sent_trades", {})
        ]

    fresh_targets = _load_fresh(db)
    scanned_any = False
    checked_scan_keys: set[tuple[str, float, float]] = set()
    for bp in blueprints[:4]:
        if STOP_FLAG:
            break
        sk = (bp["rank"], bp["min_net"], bp["max_net"])
        if sk in checked_scan_keys:
            continue
        checked_scan_keys.add(sk)
        cnt_ok = sum(
            1 for _, t in fresh_targets
            if t.get("rank") == bp["rank"] and bp["min_net"] <= float(t.get("net_price") or 0) <= bp["max_net"]
        )
        if cnt_ok < effective_cap:
            log_debug(f"[SCAN NEED] {bp['desc']} ({bp['min_net']:.2f}–{bp['max_net']:.2f}): в базе {cnt_ok}/{effective_cap}, досканирую...")
            await scan_cards_batch_into_db(
                [bp["rank"]],
                max_cards_to_scan=16,
                stop_when_found=effective_cap - cnt_ok,
                min_net=bp["min_net"],
                max_net=bp["max_net"],
            )
            scanned_any = True

    if scanned_any:
        db = load_trade_db()
        fresh_targets = _load_fresh(db)

    if not fresh_targets:
        st["last_wave_ts"] = time.time()
        save_auto_state(st)
        if manual_trigger:
            send_tg_message("ℹ️ Новых непроверенных владельцев пока не нашлось — попробую снова через 5–10 мин.", add_keyboard=True)
        return

    # 4. Безостановочная отправка по лучшим прибыльным комбинациям (Круг 1: новые карты -> Круг 2, 3...: новые цели/люди)
    sent_count = 0
    sent_logs: list[str] = []
    used_user_ids_wave: set[str] = set()
    hit_rate_limit = False

    for bp in blueprints:
        if sent_count >= remaining_slots or STOP_FLAG or hit_rate_limit:
            break

        rank = bp["rank"]
        bp_targets = [
            (k, t) for k, t in fresh_targets
            if t.get("rank") == rank
            and bp["min_net"] <= float(t.get("net_price") or 0) <= bp["max_net"]
            and t.get("user_id") not in used_user_ids_wave
            and k not in db.get("sent_trades", {})
        ]
        if not bp_targets:
            continue

        # Сортируем цели по чистой прибыли (net_price - cost) с лёгким перемешиванием внутри одной цены
        random.shuffle(bp_targets)
        bp_targets.sort(key=lambda x: float(x[1].get("net_price") or 0) - bp["cost"], reverse=True)

        offer_units = bp["offer"]
        offer_payload = _compress_offer_units(offer_units)
        offer_names = " + ".join(u.get("name", "?") for u in offer_units)
        batch_sent = 0

        for t_key, t_obj in bp_targets:
            if sent_count >= remaining_slots or batch_sent >= effective_cap or STOP_FLAG:
                break
            if t_obj["user_id"] in used_user_ids_wave:
                continue

            if sent_count > 0:
                await asyncio.sleep(random.uniform(28.0, 38.0))

            t_res = await asyncio.to_thread(
                direct_ua_gql_call,
                GQL_SUGGEST_CARD_TRADE,
                {
                    "input": {
                        "userId": t_obj["user_id"],
                        "offer": offer_payload,
                        "request": [{"cardId": t_obj["card_id"], "modifier": 0, "quantity": 1}],
                        "description": [],
                    }
                },
                "suggestCardTrade",
            )
            if _check_and_alert_token_error(t_res):
                hit_rate_limit = True
                break
            if ((t_res.get("data") or {}).get("suggestCardTrade") or {}).get("success"):
                sent_count += 1
                batch_sent += 1
                used_user_ids_wave.add(t_obj["user_id"])
                recent_ts.append(time.time())
                db["sent_trades"][t_key] = time.time()
                u_slug = t_obj["user_slug"]
                u_link = f"<a href='https://senkuro.com/users/{u_slug}'>{u_slug}</a>"
                net_p = float(t_obj.get("net_price") or 0)
                est_prof = net_p - bp["cost"]
                sent_logs.append(
                    f"• <b>{bp['desc']}</b> ({offer_names}) ➡️ {RANK_BADGE.get(rank, rank)} «{t_obj['card_name']}» "
                    f"(<b>{net_p:.2f}</b>, +{est_prof:.2f}) у {u_link}"
                )
                log_debug(
                    f"[AUTO TRADE OK] [Круг {bp['round_num']}] {bp['desc']} [{offer_names}] -> "
                    f"{u_slug} ({t_obj['card_name']} {net_p:.2f}, профит +{est_prof:.2f})"
                )
            else:
                errs = t_res.get("errors") or []
                err_m = errs[0].get("message", "") if errs else ""
                log_debug(f"[AUTO TRADE WARN] {t_obj['user_slug']}: {err_m}")
                if any(w in err_m.lower() for w in ("too many", "a lot of trades", "limit", "много", "rate")):
                    st["rate_limit_until"] = time.time() + RATE_LIMIT_RETRY_SEC
                    log_debug("[AUTO TRADE LIMIT] Сайт вернул лимит — повторная проверка через 10 мин.")
                    hit_rate_limit = True
                    break

        if batch_sent > 0:
            for u in offer_units:
                cid = str(u.get("cardId") or "")
                if cid:
                    usage_today[cid] += 1

    save_trade_db(db)
    st["recent_trade_ts"] = recent_ts[-30:]
    st["usage_today_date"] = today_kyiv
    st["card_usage_today"] = dict(usage_today)
    st["last_wave_ts"] = time.time()
    if not hit_rate_limit:
        st["rate_limit_until"] = 0
    save_auto_state(st)

    if manual_trigger:
        if sent_logs:
            rl_note = "\n\n⏳ <i>Достигнут лимит сайта — бот сам продолжит через 10 мин.</i>" if hit_rate_limit else ""
            send_tg_message(
                f"⚡ <b>Авто-волна выполнена ({sent_count} обменов, за час: {len(recent_ts)}/{MAX_TRADES_PER_WAVE}):</b>\n\n"
                + "\n".join(sent_logs)
                + rl_note,
                add_keyboard=True,
            )
        else:
            send_tg_message(
                "ℹ️ Сейчас не удалось отправить новые обмены (возможно, временный лимит сайта — повторю через 10 мин).",
                add_keyboard=True,
            )


# ==============================================================================
# 8. РУЧНЫЕ КНОПКИ: 🃏 МОИ КАРТЫ и 🎯 НАЙТИ ОБМЕНЫ
# ==============================================================================

async def run_check_my_cards() -> None:
    st_info = await asyncio.to_thread(ensure_senkutools_db, True)
    proxy_pool = LightweightProxyPool()
    try:
        proxies = await asyncio.to_thread(proxy_pool.start_pool, 1)
        p_cfg = {"server": proxies[0]} if proxies else None
        async with async_playwright() as pw:
            browser = await launch_browser(pw)
            ctx = await browser.new_context(proxy=p_cfg, viewport={"width": 1280, "height": 800})
            page = await ctx.new_page()
            try:
                data = await inspect_main_account(page)
                cards = data["cards"]
                fodder = data["fodder_by_rank"]
                prof = data["profitable"]

                def _download_card_img_direct(url: str) -> Optional[bytes]:
                    hdrs = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                        "Referer": "https://senkuro.com/",
                        "Origin": "https://senkuro.com",
                        "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                    }
                    for attempt in range(2):
                        try:
                            req = urllib.request.Request(url, headers=hdrs)
                            with urllib.request.urlopen(req, timeout=12) as resp:
                                if resp.status == 200:
                                    return resp.read()
                        except Exception:
                            if attempt == 0:
                                time.sleep(0.5)
                    return None

                photo_bytes_list: list[bytes] = []
                img_failed = 0
                for c in cards[:20]:
                    if not c["img"]:
                        img_failed += 1
                        continue
                    raw_img = await asyncio.to_thread(_download_card_img_direct, c["img"])
                    if not raw_img:
                        # Фоллбэк через браузер/Opera VPN с 2 попытками
                        for _att in range(2):
                            try:
                                r = await page.context.request.get(
                                    c["img"],
                                    headers={"Referer": "https://senkuro.com/", "Origin": "https://senkuro.com"},
                                    timeout=16000,
                                )
                                if r.ok:
                                    raw_img = await r.body()
                                    break
                            except Exception:
                                await asyncio.sleep(0.5)
                    if raw_img:
                        jpg = render_card_with_price_badge(raw_img, c["net_price"])
                        if jpg:
                            photo_bytes_list.append(jpg)
                        else:
                            img_failed += 1
                            log_debug(f"[IMG RENDER ERR] Не удалось отрендерить {c['name']} ({c['img'][:60]})")
                    else:
                        img_failed += 1
                        log_debug(f"[IMG FETCH ERR] Не удалось скачать {c['name']} ({c['img'][:60]})")

                cnt_all = Counter()
                for c in cards:
                    cnt_all[c["rank"]] += c["qty"]
                rank_str = " | ".join(f"<b>{cnt_all[r]}</b> {RANK_BADGE.get(r, r)}" for r in RANK_ORDER if cnt_all.get(r)) or "нет"
                fodder_str = ", ".join(f"{RANK_BADGE.get(r, r)} ×<b>{fodder[r]}</b>" for r in SEARCHABLE_RANKS if fodder.get(r)) or "нет"

                lines = [
                    format_st_header(st_info),
                    "",
                    f"👤 <b><a href='{MAIN_CARDS_URL}'>{MAIN_ACCOUNT_SLUG}</a></b>",
                    f"🃏 <b>Карты ({sum(cnt_all.values())}):</b> {rank_str}",
                    f"🧩 <b>Осколки:</b> {data['shards_count']} шт.",
                    f"🔄 <b>Свободные расходники:</b> {fodder_str}",
                ]
                inline_rows = []
                BANK_PENDING_CARDS.clear()
                if prof:
                    lines.append("")
                    lines.append(f"💎 <b>Выгодно сдать в банк (≥ {MIN_BANK_PROFIT_NET:.2f} чистыми):</b>")
                    total_prof_qty = 0
                    for p_it in prof:
                        qty = int(p_it.get("qty") or 1)
                        total_prof_qty += qty
                        q_sfx = f" ×{qty}" if qty > 1 else ""
                        lbl = f"{RANK_BADGE.get(p_it['rank'], p_it['rank'])} «{p_it['name']}»{q_sfx} — <b>{p_it['net_price']:.2f}</b>"
                        lines.append(f"  • {lbl}")
                        BANK_PENDING_CARDS[p_it["cardId"]] = {"label": lbl, "net_price": p_it["net_price"], "qty": qty}
                    inline_rows.append([{"text": f"🏦 Отправить всё в банк ({total_prof_qty} шт. → {BANK_ACCOUNT_SLUG})", "callback_data": "bank:all"}])

                caption = "\n".join(lines)
                if photo_bytes_list:
                    sent_any = False
                    for i in range(0, len(photo_bytes_list), 10):
                        if send_tg_media_album(photo_bytes_list[i : i + 10], caption=caption if i == 0 else ""):
                            sent_any = True
                        if i + 10 < len(photo_bytes_list):
                            await asyncio.sleep(1.0)
                    if not sent_any:
                        send_tg_message(caption, add_keyboard=True)
                else:
                    send_tg_message(caption, add_keyboard=True)

                if inline_rows:
                    send_tg_message("👇 Нажмите, чтобы отправить все выгодные карты в банк одним трейдом:", add_keyboard=False, inline_markup={"inline_keyboard": inline_rows})
            finally:
                await ctx.close()
                await browser.close()
    finally:
        proxy_pool.stop_all()


async def run_find_trades_for_my_ranks() -> None:
    st_info = await asyncio.to_thread(ensure_senkutools_db, True)
    send_tg_message(f"{format_st_header(st_info)}\n\n🎯 Подбираю цели без гильдии под твои свободные карты...", add_keyboard=False)

    proxy_pool = LightweightProxyPool()
    fodder_ranks, fodder_counter = [], Counter()
    try:
        proxies = await asyncio.to_thread(proxy_pool.start_pool, 1)
        p_cfg = {"server": proxies[0]} if proxies else None
        async with async_playwright() as pw:
            browser = await launch_browser(pw)
            ctx = await browser.new_context(proxy=p_cfg)
            page = await ctx.new_page()
            try:
                my_data = await inspect_main_account(page)
                fodder_counter = my_data["fodder_by_rank"]
                fodder_ranks = [r for r in SEARCHABLE_RANKS if fodder_counter.get(r, 0) > 0]
            finally:
                await ctx.close()
                await browser.close()
    finally:
        proxy_pool.stop_all()

    if not fodder_ranks:
        send_tg_message(f"ℹ️ На <b>{MAIN_ACCOUNT_SLUG}</b> сейчас нет свободных дешёвых карт для обмена.", add_keyboard=True)
        return

    db = load_trade_db()
    now = time.time()

    def _pick_ready(cur_db: dict[str, Any]):
        out = [
            (k, t) for k, t in cur_db.get("targets", {}).items()
            if t.get("rank") in fodder_ranks and now - float(t.get("verified_at") or 0) < TARGET_TTL_SECONDS and k not in cur_db.get("shown_users", {})
        ]
        out.sort(key=lambda x: float(x[1].get("net_price") or 0), reverse=True)
        return out

    ready = _pick_ready(db)
    if len(ready) < 6 and not STOP_FLAG:
        await scan_cards_batch_into_db(fodder_ranks, max_cards_to_scan=10, stop_when_found=8 - len(ready))
        db = load_trade_db()
        ready = _pick_ready(db)

    if not ready:
        send_tg_message("ℹ️ Новых целей без гильдии пока не нашлось — нажми <b>«🎯 Найти обмены»</b> ещё раз.", add_keyboard=True)
        return

    ranks_with_targets = list({t.get("rank") for _, t in ready if t.get("rank")})
    chosen_rank = random.choice(ranks_with_targets)
    rank_items = [(k, t) for k, t in ready if t.get("rank") == chosen_rank]
    random.shuffle(rank_items)
    by_card: dict[str, list] = {}
    for k, t in rank_items:
        by_card.setdefault(t["card_slug"], []).append((k, t))
    best_card = random.choice(list(by_card.keys()))
    single_mode = len(by_card[best_card]) >= 2
    chosen = by_card[best_card][:8] if single_mode else rank_items[:8]

    for k, _ in chosen:
        db["shown_users"][k] = time.time()
    save_trade_db(db)

    r_badge = RANK_BADGE.get(chosen_rank, chosen_rank)
    if single_mode:
        t0 = chosen[0][1]
        c_url = f"https://senkuro.com/cards/{t0['card_slug']}"
        lines = [
            f"🎯 <b>Карта ранга {r_badge}:</b> <a href='{c_url}'>{t0['card_name']}</a>",
            f"💎 <b>Чистыми в банке:</b> <b>{t0['net_price']:.2f}</b> (банк {t0['raw_price']:g})",
            f"<i>Владельцы без гильдии ({len(chosen)} чел.):</i>\n",
        ]
        for idx, (_, t) in enumerate(chosen, start=1):
            lines.append(f"{idx}. 👤 <a href='https://senkuro.com/users/{t['user_slug']}'>{t['user_slug']}</a>")
    else:
        lines = [f"🎯 <b>Случайные цели строго ранга {r_badge}:</b>\n"]
        for idx, (_, t) in enumerate(chosen, start=1):
            lines.append(
                f"{idx}. <a href='https://senkuro.com/cards/{t['card_slug']}'>{t['card_name']}</a> — <b>{t['net_price']:.2f}</b> чистыми\n"
                f"   👤 <a href='https://senkuro.com/users/{t['user_slug']}'>{t['user_slug']}</a>"
            )

    send_tg_message("\n".join(lines), add_keyboard=False, inline_markup={"inline_keyboard": [[{"text": "🎲 Ещё цели", "callback_data": "find_trades"}]]})


# ==============================================================================
# 9. ФОНОВЫЙ ПЛАНИРОВЩИК (МОНИТОРИНГ 20 МИН + ВОЛНЫ 09:00–18:00 KYIV) + POLLER
# ==============================================================================

async def background_scheduler_loop(q: asyncio.Queue, deadline: float) -> None:
    while time.time() < deadline:
        await asyncio.sleep(60.0)
        if STOP_FLAG:
            continue
        st = load_auto_state()
        now = time.time()

        # Адаптивный безостановочный планировщик (09:00–18:00 по Киеву):
        # Не ждёт лишний час после волны — запускает новую волну сразу, как освобождаются слоты в скользящем окне 61 мин
        # (или через 10 мин после ответа лимита от сайта).
        if SENKURO_MAIN_TOKEN and UKRAINE_PROXY_RAW and is_working_hours_kyiv():
            if now < float(st.get("rate_limit_until") or 0):
                continue
            if now - float(st.get("last_wave_ts") or 0) < MIN_WAVE_COOLDOWN_SEC:
                continue
            recent_ts = [float(x) for x in (st.get("recent_trade_ts") or []) if now - float(x) < WAVE_INTERVAL_SEC]
            slots_free = MAX_TRADES_PER_WAVE - len(recent_ts)
            if slots_free >= 1:
                if "auto_wave" not in QUEUED_KEYS and ACTIVE_JOB_NAME != "auto_wave":
                    QUEUED_KEYS.add("auto_wave")
                    await q.put(("auto_wave", ""))
                continue

        # Тихий режим v61.0: 20-минутный мониторинг и пуши отключены — пользователь сам проверяет вечером через '🃏 Мои карты'.


async def run_silent_monitor() -> None:
    await asyncio.to_thread(ensure_senkutools_db, False)
    proxy_pool = LightweightProxyPool()
    try:
        proxies = await asyncio.to_thread(proxy_pool.start_pool, 1)
        p_cfg = {"server": proxies[0]} if proxies else None
        async with async_playwright() as pw:
            browser = await launch_browser(pw)
            ctx = await browser.new_context(proxy=p_cfg)
            page = await ctx.new_page()
            try:
                my_data = await inspect_main_account(page)
                await check_and_notify_new_profitable_cards(my_data)
            finally:
                await ctx.close()
                await browser.close()
    finally:
        proxy_pool.stop_all()


def read_tg_offset() -> int:
    vals = [0]
    for p in (TG_OFFSET_FILE, SESSIONS_DIR / "tg_offset.txt"):
        try:
            if p.exists():
                vals.append(int(p.read_text(encoding="utf-8").strip()))
        except Exception:
            pass
    return max(vals)


def write_tg_offset(val: int) -> None:
    for p in (TG_OFFSET_FILE, SESSIONS_DIR / "tg_offset.txt"):
        try:
            p.write_text(str(val), encoding="utf-8")
        except Exception:
            pass


def fetch_tg_updates(offset: int, timeout_s: int = 4) -> list[dict]:
    if not TELEGRAM_BOT_TOKEN:
        time.sleep(2)
        return []
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset}&timeout={timeout_s}"
    try:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=timeout_s + 5) as resp:
            d = json.loads(resp.read().decode("utf-8"))
            if d.get("ok") and isinstance(d.get("result"), list):
                return d["result"]
            if d.get("error_code") == 409:
                tg_request("deleteWebhook", {"drop_pending_updates": False})
    except Exception:
        time.sleep(1)
    return []


async def execute_action(act: str, param: str = "") -> None:
    global STOP_FLAG
    STOP_FLAG = False
    if act == "my_cards":
        await run_check_my_cards()
    elif act == "find_trades":
        await run_find_trades_for_my_ranks()
    elif act == "auto_wave":
        await run_auto_trade_wave(manual_trigger=False)
    elif act == "auto_wave_manual":
        await run_auto_trade_wave(manual_trigger=True)
    elif act == "monitor_main":
        await run_silent_monitor()
    elif act == "send_bank":
        await send_profitable_card_to_bank(param)
    elif act == "refill_db_silent":
        await asyncio.to_thread(ensure_senkutools_db, True)
        await scan_cards_batch_into_db(list(SEARCHABLE_RANKS), max_cards_to_scan=12, stop_when_found=10)
    elif act == "log":
        await asyncio.to_thread(send_debug_log)


async def handle_update(upd: dict, q: asyncio.Queue) -> None:
    cb = upd.get("callback_query")
    if cb:
        cb_id = cb.get("id")
        data = str(cb.get("data") or "").strip()
        if data == "find_trades":
            tg_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": "🎲 Подбираю новую порцию..."})
            if "find_trades" not in QUEUED_KEYS and ACTIVE_JOB_NAME != "find_trades":
                QUEUED_KEYS.add("find_trades")
                await q.put(("find_trades", ""))
        elif data.startswith("bank:"):
            cid = data.split(":", 1)[1].strip()
            tg_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": "🏦 Отправляю карту в банк..."})
            await q.put(("send_bank", cid))
        return

    msg = upd.get("message")
    if not msg or not msg.get("text"):
        return
    chat_id = str((msg.get("chat") or {}).get("id") or "")
    if TELEGRAM_CHAT_ID and chat_id and chat_id != str(TELEGRAM_CHAT_ID):
        return
    low = str(msg.get("text") or "").strip().lower()

    if low in ("/start", "/menu", "меню"):
        ua_ok = "✅" if (SENKURO_MAIN_TOKEN and UKRAINE_PROXY_RAW) else "⚠️ (добавьте секреты)"
        send_tg_message(
            f"🤖 <b>Senkuro Auto-Trade {APP_VERSION_TAG}</b>\n"
            f"• Рабочее время авто-волн: <b>09:00–18:00 (Киев)</b>\n"
            f"• Авто-отправка (UA-прокси + токен): {ua_ok}\n"
            f"• Банк для слива: <b>{BANK_ACCOUNT_SLUG}</b>",
            add_keyboard=True,
        )
        return

    if low in ("📜 лог", "/log", "лог"):
        await asyncio.to_thread(send_debug_log)
        return

    btn_map = {
        "🃏 мои карты": "my_cards",
        "/cards": "my_cards",
        "🎯 найти обмены": "find_trades",
        "/find": "find_trades",
        "⚡ авто-волна": "auto_wave_manual",
        "/wave": "auto_wave_manual",
    }
    if low in btn_map:
        act = btn_map[low]
        if act in QUEUED_KEYS or (ACTIVE_JOB_NAME == act and ACTIVE_JOB_TASK and not ACTIVE_JOB_TASK.done()):
            send_tg_message("ℹ️ Эта задача уже выполняется.", add_keyboard=True)
            return
        if ACTIVE_JOB_TASK and not ACTIVE_JOB_TASK.done():
            send_tg_message("⏳ Сейчас завершается фоновая задача — ваша команда поставлена следующей!", add_keyboard=True)
        QUEUED_KEYS.add(act)
        await q.put((act, ""))
        return

    send_tg_message("👇 Выберите действие кнопкой ниже:", add_keyboard=True)


async def poller_loop(q: asyncio.Queue, deadline: float) -> None:
    offset = read_tg_offset()
    if offset == 0:
        init_u = await asyncio.to_thread(fetch_tg_updates, -1, 1)
        if init_u:
            offset = int(init_u[-1]["update_id"]) + 1
            write_tg_offset(offset)
    log_debug(f"[DAEMON READY] Senkuro Auto-Trade {APP_VERSION_TAG} запущен (UA_PROXY={'OK' if UKRAINE_PROXY_RAW else 'NO'}, TOKEN={'OK' if SENKURO_MAIN_TOKEN else 'NO'}).")
    if os.environ.get("GH_EVENT_NAME") in ("push", "workflow_dispatch") and os.environ.get("IS_CONTINUATION_JOB") != "true":
        send_tg_message(
            f"🟢 <b>Senkuro Auto-Trade {APP_VERSION_TAG} запущен (24/7 эстафета)!</b>\n"
            f"Рабочие часы авто-волн: <b>09:00–18:00 по Киеву</b> | Авто-отправка: <b>{'✅ Включена' if (SENKURO_MAIN_TOKEN and UKRAINE_PROXY_RAW) else '⚠️ Ждёт секреты'}</b>",
            add_keyboard=True,
        )
    while time.time() < deadline or (ACTIVE_JOB_TASK is not None and not ACTIVE_JOB_TASK.done()):
        updates = await asyncio.to_thread(fetch_tg_updates, offset, 4)
        for upd in updates:
            uid = int(upd.get("update_id") or 0)
            if uid >= offset:
                offset = uid + 1
                write_tg_offset(offset)
            try:
                await handle_update(upd, q)
            except Exception as e:
                log_debug(f"[UPDATE ERR] {e}")
        await asyncio.sleep(0.3)


async def executor_loop(q: asyncio.Queue, deadline: float) -> None:
    global ACTIVE_JOB_TASK, ACTIVE_JOB_NAME, STOP_FLAG
    while time.time() < deadline:
        try:
            act, prm = await asyncio.wait_for(q.get(), timeout=2.0)
        except asyncio.TimeoutError:
            continue
        QUEUED_KEYS.discard(act)
        ACTIVE_JOB_NAME = act
        STOP_FLAG = False
        try:
            ACTIVE_JOB_TASK = asyncio.create_task(execute_action(act, prm))
            await ACTIVE_JOB_TASK
        except asyncio.CancelledError:
            log_debug(f"[CANCELLED] {act}")
        except Exception as e:
            log_debug(f"[EXEC ERR] {act}: {e}")
            send_tg_message(f"⚠️ Ошибка задачи <code>{act}</code>: <code>{str(e)[:250]}</code>", add_keyboard=True)
        finally:
            ACTIVE_JOB_TASK = None
            ACTIVE_JOB_NAME = ""
            q.task_done()


async def async_main() -> None:
    parser = argparse.ArgumentParser(description=f"Senkuro Auto-Trade {APP_VERSION_TAG}")
    parser.add_argument("--action", default=os.environ.get("SENKURO_ACTION", "daemon").strip().lower() or "daemon")
    args = parser.parse_args()

    try:
        Path("/tmp/senkuro_main_ready.flag").write_text("1", encoding="utf-8")
    except Exception:
        pass
    q: asyncio.Queue = asyncio.Queue()
    deadline = time.time() + 4.1 * 3600.0

    if EARLY_QUEUE_FILE.exists():
        try:
            for ln in EARLY_QUEUE_FILE.read_text(encoding="utf-8").splitlines():
                if not ln.strip():
                    continue
                obj = json.loads(ln)
                e_act = str(obj.get("action") or "").strip()
                if e_act and e_act not in QUEUED_KEYS:
                    QUEUED_KEYS.add(e_act)
                    await q.put((e_act, ""))
            EARLY_QUEUE_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    if args.action != "daemon":
        await execute_action(args.action)
        return

    if os.environ.get("GH_EVENT_NAME") == "schedule":
        await q.put(("refill_db_silent", ""))

    await asyncio.gather(
        poller_loop(q, deadline),
        executor_loop(q, deadline),
        background_scheduler_loop(q, deadline),
        return_exceptions=True,
    )


if __name__ == "__main__":
    asyncio.run(async_main())