#!/usr/bin/env python3
"""
Senkuro Public Trade Assistant v45.0 (Read-Only, Zero Passwords, Zero Alts)
---------------------------------------------------------------------------
1. Автообновляемая база цен банка SenkuTools (addons.mozilla.org -> database.json, комиссия 20% -> x0.80).
2. Мгновенная проверка основы cesium254 с бейджами чистой цены банка на фото карточек.
3. Автоматическое определение свободных дешёвых карт (расходников) на основе cesium254.
4. Поиск и накопление локальной базы целей (.sessions/trade_targets_db.json, обновление раз в 48-72 ч):
   - только дорогие карты (чистыми >= 1.60 / в банке >= 2.00) под твои текущие ранги расходников;
   - проверка, что карта НЕ закреплена (locked == False);
   - проверка, что владелец НЕ состоит в гильдии (гильдейские уходят в чёрный список).
"""

import argparse
import asyncio
import base64
import io
import json
import os
import random
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import BrowserContext, Page, async_playwright

# ==============================================================================
# 1. КОНФИГУРАЦИЯ (БЕЗ ПАРОЛЕЙ И ТВИНКОВ!)
# ==============================================================================

APP_VERSION_TAG = "v45.0"
APP_HEADER_VERSION = "2.2.1"
GRAPHQL_API_URL = "https://api.senkuro.com/graphql"

MAIN_ACCOUNT_SLUG = os.environ.get("SENKURO_MAIN_SLUG", "cesium254").strip() or "cesium254"
MAIN_ACCOUNT_UID = os.environ.get("SENKURO_MAIN_UID", "VVNFUjoxODAxNDM0ODEzOTI0ODE4MDE").strip() or "VVNFUjoxODAxNDM0ODEzOTI0ODE4MDE"
MAIN_ACCOUNT_URL = f"https://senkuro.com/users/{MAIN_ACCOUNT_SLUG}"
MAIN_CARDS_URL = f"https://senkuro.com/users/{MAIN_ACCOUNT_SLUG}/cards"

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

BANK_COMMISSION_MULT = 0.80          # 20% комиссия банка -> 80% чистыми
MIN_BANK_PROFIT_NET = 1.50           # Порог "выгодно слить в банк" на основе (2.00 -> 1.60)
MIN_TARGET_NET_PRICE = 1.60          # Порог для поиска целей под обмен 1-в-1 (в банке >= 2.00)
TARGET_TTL_SECONDS = 72 * 3600       # Обновлять записи старше 72 часов (3 дня)
SEARCHABLE_RANKS = ("F", "D", "C", "B", "A")
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
PREFETCHED_IMAGES: dict[str, bytes] = {}


def log_debug(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        if DEBUG_LOG_FILE.exists() and DEBUG_LOG_FILE.stat().st_size > 200_000:
            DEBUG_LOG_FILE.write_bytes(DEBUG_LOG_FILE.read_bytes()[-120_000:])
        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ==============================================================================
# 2. TELEGRAM API + КОМПАКТНОЕ МЕНЮ
# ==============================================================================

def get_reply_keyboard() -> dict:
    return {
        "keyboard": [
            [{"text": "🃏 Мои карты"}, {"text": "🎯 Найти обмены"}],
            [{"text": "📜 Лог"}],
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
    try:
        with urllib.request.urlopen(req, timeout=35) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log_debug(f"[TG MULTIPART ERR] {method}: {e}")
        return {"ok": False, "error": str(e)}


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
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return bool(json.loads(resp.read().decode("utf-8")).get("ok"))
    except Exception as e:
        log_debug(f"[TG ALBUM ERR] {e}")
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
# 3. АВТООБНОВЛЯЕМАЯ БАЗА ЦЕН БАНКА SENKUTOOLS
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
                log_debug(f"[SENKUTOOLS] Загружаю новую версию v{latest_ver} (была: {cached_ver or 'нет'})...")
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
                        "checked_at": time.strftime("%Y-%m-%d %H:%M:%S"),
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


# ==============================================================================
# 4. ЛОКАЛЬНАЯ БАЗА ЦЕЛЕЙ (БЕЗ ГИЛЬДИИ + НЕ ЗАКРЕПЛЕНЫ + ОБНОВЛЕНИЕ РАЗ В 72 Ч)
# ==============================================================================

def load_trade_db() -> dict[str, Any]:
    default_db: dict[str, Any] = {
        "guild_blacklist": {},   # slug -> {"guild": name, "ts": float}
        "shown_users": {},       # "user_slug|card_slug" -> ts
        "targets": {},           # "user_slug|card_slug" -> {user_slug, card_slug, card_name, rank, net_price, raw_price, verified_at}
        "scanned_cards": {},     # card_slug -> ts
    }
    if TRADE_DB_FILE.exists():
        try:
            loaded = json.loads(TRADE_DB_FILE.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for k, v in default_db.items():
                    if k not in loaded or not isinstance(loaded[k], dict):
                        loaded[k] = v
                return loaded
        except Exception:
            pass
    return default_db


def save_trade_db(db: dict[str, Any]) -> None:
    try:
        # Чистим устаревшие записи старше 72 часов из targets и scanned_cards (чёрный список гильдий держим 14 дней)
        now = time.time()
        db["targets"] = {
            k: v for k, v in db.get("targets", {}).items()
            if now - float(v.get("verified_at") or 0) < TARGET_TTL_SECONDS
        }
        db["scanned_cards"] = {
            k: ts for k, ts in db.get("scanned_cards", {}).items()
            if now - float(ts or 0) < TARGET_TTL_SECONDS
        }
        db["guild_blacklist"] = {
            k: v for k, v in db.get("guild_blacklist", {}).items()
            if now - float(v.get("ts") or 0) < 14 * 86400
        }
        TRADE_DB_FILE.write_text(json.dumps(db, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        log_debug(f"[DB SAVE WARN] {e}")


# ==============================================================================
# 5. ЛЁГКИЙ OPERA VPN ПРОКСИ (ТОЛЬКО ЧТОБЫ НЕ БЛОЧИЛО IP GITHUB НА ПУБЛИЧНЫХ СТРАНИЦАХ)
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
                log_debug(f"[PROXY OK] Поднят публичный туннель {reg} на 127.0.0.1:{port}")
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


# ==============================================================================
# 6. ПУБЛИЧНЫЕ GRAPHQL-ЗАПРОСЫ И РЕНДЕР БЕЙДЖЕЙ ЦЕН НА ФОТО
# ==============================================================================

GQL_FETCH_USER_BY_SLUG = """
query fetchUserBySlug($slug: String!) {
  user(slug: $slug) {
    id
    slug
    name
  }
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
            resp = await page.context.request.post(
                GRAPHQL_API_URL,
                headers=headers,
                data=json.dumps(payload),
                timeout=15000,
            )
            if resp.ok:
                data = await resp.json()
                if isinstance(data, dict) and not data.get("errors"):
                    return data
        except Exception as e:
            if attempt == 2:
                log_debug(f"[GQL WARN] {op_name}: {e}")
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
# 7. СЦЕНАРИЙ 1: МОИ КАРТЫ (CESIUM254) + ОПРЕДЕЛЕНИЕ РАНГОВ РАСХОДНИКОВ
# ==============================================================================

async def inspect_main_account(page: Page) -> dict[str, Any]:
    cards_nodes = await fetch_public_user_cards(page, MAIN_ACCOUNT_UID, modifier_val=0)
    shards_nodes = await fetch_public_user_cards(page, MAIN_ACCOUNT_UID, modifier_val=1)

    cards_info = []
    fodder_by_rank: Counter = Counter()
    profitable_cards = []

    for nd in cards_nodes:
        c = nd.get("card") or {}
        slug = str(c.get("slug") or "")
        rank = str(c.get("rank") or "?").upper()
        qty = int(nd.get("quantity") or 1)
        locked = bool(nd.get("locked"))
        name = extract_card_title(c)
        img_url = str(((c.get("image") or {}).get("original") or {}).get("url") or "")
        net_p = get_net_price(slug)
        item = {
            "slug": slug,
            "rank": rank,
            "qty": qty,
            "locked": locked,
            "name": name,
            "img": img_url,
            "net_price": net_p,
        }
        cards_info.append(item)
        if not locked:
            if net_p is not None and net_p >= MIN_BANK_PROFIT_NET:
                profitable_cards.append(item)
            elif rank in SEARCHABLE_RANKS:
                fodder_by_rank[rank] += qty

    return {
        "cards": cards_info,
        "shards_count": sum(int(n.get("quantity") or 1) for n in shards_nodes),
        "fodder_by_rank": fodder_by_rank,
        "profitable": profitable_cards,
    }


async def run_check_my_cards() -> None:
    st_info = await asyncio.to_thread(ensure_senkutools_db, True)
    proxy_pool = LightweightProxyPool()
    try:
        proxies = await asyncio.to_thread(proxy_pool.start_pool, 1)
        proxy_cfg = {"server": proxies[0]} if proxies else None
        async with async_playwright() as pw:
            browser = await launch_browser(pw)
            ctx = await browser.new_context(proxy=proxy_cfg, viewport={"width": 1280, "height": 800})
            page = await ctx.new_page()
            try:
                data = await inspect_main_account(page)
                cards = data["cards"]
                fodder = data["fodder_by_rank"]
                prof = data["profitable"]

                # Скачиваем фото карточек и рисуем бейджи чистой цены банка
                photo_bytes_list: list[bytes] = []
                for c in cards[:20]:
                    if not c["img"]:
                        continue
                    try:
                        r = await page.context.request.get(
                            c["img"],
                            headers={"Referer": "https://senkuro.com/", "Origin": "https://senkuro.com"},
                            timeout=10000,
                        )
                        if r.ok:
                            jpg = render_card_with_price_badge(await r.body(), c["net_price"])
                            if jpg:
                                photo_bytes_list.append(jpg)
                    except Exception:
                        pass

                cnt_all = Counter()
                for c in cards:
                    cnt_all[c["rank"]] += c["qty"]
                rank_str = " | ".join(f"<b>{cnt_all[r]}</b> {RANK_BADGE.get(r, r)}" for r in RANK_ORDER if cnt_all.get(r)) or "нет"
                fodder_str = ", ".join(f"{RANK_BADGE.get(r, r)} ×<b>{fodder[r]}</b>" for r in SEARCHABLE_RANKS if fodder.get(r)) or "нет свободных дешёвых карт"

                lines = [
                    format_st_header(st_info),
                    "",
                    f"👤 <b><a href='{MAIN_CARDS_URL}'>{MAIN_ACCOUNT_SLUG}</a></b>",
                    f"🃏 <b>Карты ({sum(cnt_all.values())}):</b> {rank_str}",
                    f"🧩 <b>Осколки:</b> {data['shards_count']} шт.",
                    f"🔄 <b>Свободные расходники под обмен 1-в-1:</b> {fodder_str}",
                ]
                if prof:
                    lines.append("")
                    lines.append(f"💎 <b>Выгодно сдать в банк (≥ {MIN_BANK_PROFIT_NET:.2f} чистыми):</b>")
                    for p_it in prof:
                        lines.append(f"  • {RANK_BADGE.get(p_it['rank'], p_it['rank'])} «{p_it['name']}» — <b>{p_it['net_price']:.2f}</b>")

                caption = "\n".join(lines)
                if photo_bytes_list:
                    for i in range(0, len(photo_bytes_list), 10):
                        chunk = photo_bytes_list[i : i + 10]
                        send_tg_media_album(chunk, caption=caption if i == 0 else "")
                        if i + 10 < len(photo_bytes_list):
                            await asyncio.sleep(1.0)
                    send_tg_message("👇 Нажмите <b>«🎯 Найти обмены»</b> — бот сам подберёт цели без гильдии под ваши ранги расходников!", add_keyboard=True)
                else:
                    send_tg_message(caption, add_keyboard=True)
            finally:
                await ctx.close()
                await browser.close()
    finally:
        proxy_pool.stop_all()


# ==============================================================================
# 8. СЦЕНАРИЙ 2 И 3: СКАНЕР ЦЕЛЕЙ (БЕЗ ГИЛЬДИИ + НЕ ЗАКРЕПЛЕНЫ) И НАКОПЛЕНИЕ БАЗЫ
# ==============================================================================

async def check_owner_profile_and_card(
    page: Page,
    owner_slug: str,
    card_slug: str,
    db: dict[str, Any],
) -> tuple[bool, Optional[str]]:
    """
    Проверяет одного публичного владельца карты:
    1) Заходит на https://senkuro.com/users/{owner_slug} — проверяет, состоит ли он в гильдии (ссылка /guilds/).
       Если в гильдии -> добавляет в guild_blacklist и возвращает (False, 'in_guild').
    2) Проверяет через публичный GraphQL, есть ли у него эта карта и locked == False.
    """
    low_slug = owner_slug.strip().lower()
    if not low_slug or low_slug == MAIN_ACCOUNT_SLUG.lower():
        return False, "self"
    if low_slug in db["guild_blacklist"]:
        return False, "blacklisted"

    try:
        await page.goto(f"https://senkuro.com/users/{owner_slug}", wait_until="domcontentloaded", timeout=22000)
        await asyncio.sleep(random.uniform(0.9, 1.5))
        guild_info = await page.evaluate(
            """() => {
                const gLink = document.querySelector('a[href*="/guilds/"], a[href*="/guild/"]');
                if (gLink) return (gLink.textContent || gLink.getAttribute('href') || 'guild').trim().slice(0, 50);
                return '';
            }"""
        )
        if guild_info:
            db["guild_blacklist"][low_slug] = {"guild": str(guild_info), "ts": time.time()}
            log_debug(f"[SCAN SKIP GUILD] {owner_slug} состоит в гильдии ({guild_info}) -> в чёрный список.")
            return False, "in_guild"
    except Exception as e:
        log_debug(f"[SCAN PROFILE WARN] {owner_slug}: {e}")
        return False, "profile_err"

    # Получаем UID и проверяем, что нужная карта не закреплена (locked == False)
    u_res = await gql_public_call(page, GQL_FETCH_USER_BY_SLUG, {"slug": owner_slug}, "fetchUserBySlug")
    uid = ((u_res.get("data") or {}).get("user") or {}).get("id")
    if not uid:
        return False, "no_uid"

    u_cards = await fetch_public_user_cards(page, str(uid), modifier_val=0, max_pages=6)
    target_clean = card_slug.strip().lower()
    for nd in u_cards:
        c_s = str((nd.get("card") or {}).get("slug") or "").strip().lower()
        if c_s == target_clean:
            if bool(nd.get("locked")):
                return False, "locked"
            if int(nd.get("quantity") or 0) > 0:
                return True, "ok"
    return False, "not_found"


async def scan_cards_batch_into_db(
    target_ranks: list[str],
    max_cards_to_scan: int = 10,
    stop_when_found: int = 8,
) -> dict[str, int]:
    """
    Вежливо сканирует публичные страницы дорогих карт (net >= 1.60) выбранных рангов через пул Opera VPN,
    отсеивает владельцев в гильдиях и с закреплённой картой (locked=True) и сохраняет чистые цели в trade_targets_db.json.
    """
    db = load_trade_db()
    now = time.time()
    ranks_set = {r.upper() for r in target_ranks if r.upper() in SEARCHABLE_RANKS}
    if not ranks_set:
        ranks_set = {"F", "D", "C", "B"}

    # Выбираем дорогие карты нужных рангов, которые не сканировались последние 48 часов
    candidates: list[tuple[str, dict[str, Any], float]] = []
    for c_slug, c_info in SENKUTOOLS_DB.items():
        if not isinstance(c_info, dict):
            continue
        r = str(c_info.get("rank") or "").upper()
        if r not in ranks_set:
            continue
        net_p = round(float(c_info.get("price") or 0) * BANK_COMMISSION_MULT, 2)
        if net_p < MIN_TARGET_NET_PRICE:
            continue
        last_sc = float(db["scanned_cards"].get(c_slug) or 0)
        if now - last_sc < 48 * 3600:
            continue
        candidates.append((c_slug, c_info, net_p))

    random.shuffle(candidates)
    # Приоритет более дорогим картам с лёгким рандомом
    candidates.sort(key=lambda x: (x[2] + random.uniform(-0.15, 0.15)), reverse=True)
    batch = candidates[:max_cards_to_scan]

    stats = {"cards_scanned": 0, "owners_checked": 0, "new_targets": 0, "guild_skipped": 0, "locked_skipped": 0}
    if not batch:
        return stats

    proxy_pool = LightweightProxyPool()
    try:
        proxies = await asyncio.to_thread(proxy_pool.start_pool, 3)
        async with async_playwright() as pw:
            browser = await launch_browser(pw)
            contexts: list[BrowserContext] = []
            pages: list[Page] = []
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
                        await asyncio.sleep(random.uniform(1.5, 2.4))
                        owner_slugs = await pg.evaluate(
                            """() => {
                                const out = [];
                                const seen = new Set();
                                document.querySelectorAll('a[href*="/users/"]').forEach(a => {
                                    const href = a.getAttribute('href') || '';
                                    const m = href.match(/\\/users\\/([^/?#]+)/);
                                    if (m && m[1] && !seen.has(m[1].toLowerCase())) {
                                        seen.add(m[1].toLowerCase());
                                        out.push(m[1]);
                                    }
                                });
                                return out.slice(0, 12);
                            }"""
                        )
                    except Exception as nav_e:
                        log_debug(f"[CARD PAGE WARN] {c_slug}: {nav_e}")
                        continue

                    for o_slug in (owner_slugs or []):
                        if STOP_FLAG or stats["new_targets"] >= stop_when_found:
                            break
                        key = f"{o_slug.lower()}|{c_slug.lower()}"
                        if key in db["targets"] or o_slug.lower() in db["guild_blacklist"]:
                            continue
                        stats["owners_checked"] += 1
                        ok, reason = await check_owner_profile_and_card(pg, o_slug, c_slug, db)
                        if ok:
                            db["targets"][key] = {
                                "user_slug": o_slug,
                                "card_slug": c_slug,
                                "card_name": str(c_info.get("name") or c_slug),
                                "rank": str(c_info.get("rank") or "?").upper(),
                                "net_price": net_p,
                                "raw_price": float(c_info.get("price") or 0),
                                "verified_at": time.time(),
                            }
                            stats["new_targets"] += 1
                            log_debug(f"[TARGET FOUND] {o_slug} (без гильдии) владеет {c_info.get('rank')} «{c_info.get('name')}» ({net_p:.2f} чистыми)")
                        elif reason == "in_guild":
                            stats["guild_skipped"] += 1
                        elif reason == "locked":
                            stats["locked_skipped"] += 1
                        await asyncio.sleep(random.uniform(0.7, 1.3))
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


async def run_find_trades_for_my_ranks() -> None:
    st_info = await asyncio.to_thread(ensure_senkutools_db, True)
    send_tg_message(
        f"{format_st_header(st_info)}\n\n"
        f"🎯 Проверяю свободные дешёвые карты на <b>{MAIN_ACCOUNT_SLUG}</b> и подбираю цели без гильдии...",
        add_keyboard=False,
    )

    # 1. Определяем, какие ранги расходников реально есть на cesium254 прямо сейчас!
    proxy_pool = LightweightProxyPool()
    fodder_ranks: list[str] = []
    fodder_counter: Counter = Counter()
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
        send_tg_message(
            f"ℹ️ На <b>{MAIN_ACCOUNT_SLUG}</b> сейчас нет свободных дешёвых карт (F/D/C/B/A) для обмена 1-в-1.",
            add_keyboard=True,
        )
        return

    # 2. Ищем свежие непросмотренные цели в локальной базе под эти ранги
    db = load_trade_db()
    now = time.time()

    def _pick_ready(cur_db: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        out = []
        for k, t in cur_db.get("targets", {}).items():
            if t.get("rank") not in fodder_ranks:
                continue
            if now - float(t.get("verified_at") or 0) > TARGET_TTL_SECONDS:
                continue
            if k in cur_db.get("shown_users", {}):
                continue
            out.append((k, t))
        out.sort(key=lambda x: float(x[1].get("net_price") or 0), reverse=True)
        return out

    ready = _pick_ready(db)
    scan_stats = None
    if len(ready) < 6 and not STOP_FLAG:
        scan_stats = await scan_cards_batch_into_db(fodder_ranks, max_cards_to_scan=12, stop_when_found=8 - len(ready))
        db = load_trade_db()
        ready = _pick_ready(db)

    fodder_desc = ", ".join(f"{RANK_BADGE.get(r, r)} ×<b>{fodder_counter[r]}</b>" for r in fodder_ranks)
    if not ready:
        extra = ""
        if scan_stats:
            extra = f"\n<i>(Проверено карт: {scan_stats['cards_scanned']}, владельцев: {scan_stats['owners_checked']}, отсеяно в гильдиях: {scan_stats['guild_skipped']}, закреплённых: {scan_stats['locked_skipped']})</i>"
        send_tg_message(
            f"🎯 <b>Твои расходники:</b> {fodder_desc}\n\n"
            f"ℹ️ Свежих целей без гильдии с незакреплённой дорогой картой пока не нашлось.{extra}\n"
            "Нажми <b>«🔄 Пополнить базу»</b>, чтобы просканировать ещё партию карт.",
            add_keyboard=True,
        )
        return

    # Группируем по ОДНОМУ случайному рангу (и в приоритете — по ОДНОЙ конкретной карте),
    # чтобы не смешивать в кучу F, D и C за один раз!
    ranks_with_targets = list({t.get("rank") for _, t in ready if t.get("rank")})
    chosen_rank = random.choice(ranks_with_targets)
    rank_items = [(k, t) for k, t in ready if t.get("rank") == chosen_rank]
    random.shuffle(rank_items)

    # Если есть несколько владельцев одной и той же карты — показываем их вместе (до 8 шт.), иначе до 8 случайных целей этого же ранга
    by_card: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for k, t in rank_items:
        by_card.setdefault(t["card_slug"], []).append((k, t))
    best_card_slug = random.choice(list(by_card.keys()))
    if len(by_card[best_card_slug]) >= 2:
        chosen = by_card[best_card_slug][:8]
        single_card_mode = True
    else:
        chosen = rank_items[:8]
        single_card_mode = False

    for k, _ in chosen:
        db["shown_users"][k] = time.time()
    save_trade_db(db)

    r_badge = RANK_BADGE.get(chosen_rank, chosen_rank)
    if single_card_mode:
        t0 = chosen[0][1]
        c_url = f"https://senkuro.com/cards/{t0['card_slug']}"
        lines = [
            f"🎯 <b>Карта ранга {r_badge}:</b> <a href='{c_url}'>{t0['card_name']}</a>",
            f"💎 <b>Чистыми в банке:</b> <b>{t0['net_price']:.2f}</b> (банк {t0['raw_price']:g})",
            f"<i>Владельцы без гильдии с незакреплённой картой ({len(chosen)} чел.):</i>\n",
        ]
        for idx, (_, t) in enumerate(chosen, start=1):
            u_url = f"https://senkuro.com/users/{t['user_slug']}/cards"
            lines.append(f"{idx}. 👤 <a href='{u_url}'>{t['user_slug']}</a>")
    else:
        lines = [
            f"🎯 <b>Случайные цели строго ранга {r_badge} (твоих расходников: {fodder_counter[chosen_rank]} шт.):</b>",
            "<i>(Все игроки проверены: без гильдии + карта не закреплена + цена банка ≥ 2.00)</i>\n",
        ]
        for idx, (_, t) in enumerate(chosen, start=1):
            u_url = f"https://senkuro.com/users/{t['user_slug']}/cards"
            c_url = f"https://senkuro.com/cards/{t['card_slug']}"
            lines.append(
                f"{idx}. <a href='{c_url}'>{t['card_name']}</a> — <b>{t['net_price']:.2f}</b> чистыми (банк {t['raw_price']:g})\n"
                f"   👤 <a href='{u_url}'>{t['user_slug']}</a>"
            )

    inline_more = {"inline_keyboard": [[{"text": "🎲 Ещё цели", "callback_data": "find_trades"}]]}
    send_tg_message("\n".join(lines), add_keyboard=False, inline_markup=inline_more)


async def run_refill_database(max_cards: int = 20, silent: bool = False) -> None:
    st_info = await asyncio.to_thread(ensure_senkutools_db, True)
    if not silent:
        send_tg_message(
            f"{format_st_header(st_info)}\n\n"
            f"🔄 Пополняю базу целей (сканирую до {max_cards} дорогих карт F/D/C/B/A, отсеиваю гильдии и закреплённые)...",
            add_keyboard=False,
        )
    stats = await scan_cards_batch_into_db(["F", "D", "C", "B", "A"], max_cards_to_scan=max_cards, stop_when_found=15)
    db = load_trade_db()
    if not silent:
        send_tg_message(
            f"✅ <b>База пополнена!</b>\n"
            f"• Проверено карт: <b>{stats['cards_scanned']}</b>\n"
            f"• Проверено владельцев: <b>{stats['owners_checked']}</b>\n"
            f"• Новых чистых целей (без гильдии): <b>+{stats['new_targets']}</b>\n"
            f"• Отсеяно (в гильдиях / закреплены): <b>{stats['guild_skipped']}</b> / <b>{stats['locked_skipped']}</b>\n\n"
            f"📦 <b>Всего сейчас в базе:</b> {len(db['targets'])} свежих целей | {len(db['guild_blacklist'])} в чёрном списке гильдий",
            add_keyboard=True,
        )


def send_db_status() -> None:
    st_info = ensure_senkutools_db(force_check=False)
    db = load_trade_db()
    by_rank = Counter(t.get("rank", "?") for t in db.get("targets", {}).values())
    r_str = " | ".join(f"{RANK_BADGE.get(r, r)} <b>{by_rank[r]}</b>" for r in SEARCHABLE_RANKS if by_rank.get(r)) or "пока пусто"
    unshown = sum(1 for k in db.get("targets", {}) if k not in db.get("shown_users", {}))
    send_tg_message(
        f"{format_st_header(st_info)}\n\n"
        f"📊 <b>Статус локальной базы целей (обновление раз в 72 ч):</b>\n"
        f"• Свежих целей без гильдии: <b>{len(db['targets'])}</b> (новых к показу: <b>{unshown}</b>)\n"
        f"• По рангам: {r_str}\n"
        f"• В чёрном списке гильдий: <b>{len(db['guild_blacklist'])}</b> игроков\n"
        f"• Просканировано дорогих карт за 48 ч: <b>{len(db['scanned_cards'])}</b>",
        add_keyboard=True,
    )


# ==============================================================================
# 9. ПРЯМОЙ TELEGRAM LONG POLLING (DAEMON)
# ==============================================================================

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


async def execute_action(act: str) -> None:
    global STOP_FLAG
    STOP_FLAG = False
    if act == "my_cards":
        await run_check_my_cards()
    elif act == "find_trades":
        await run_find_trades_for_my_ranks()
    elif act == "refill_db":
        await run_refill_database(max_cards=20, silent=False)
    elif act == "db_status":
        await asyncio.to_thread(send_db_status)
    elif act == "log":
        await asyncio.to_thread(send_debug_log)


async def handle_update(upd: dict, q: asyncio.Queue) -> None:
    global STOP_FLAG, ACTIVE_JOB_TASK
    cb = upd.get("callback_query")
    if cb:
        cb_id = cb.get("id")
        data = str(cb.get("data") or "").strip()
        if data == "find_trades":
            tg_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": "🎲 Подбираю новую случайную порцию..."})
            if "find_trades" not in QUEUED_KEYS and ACTIVE_JOB_NAME != "find_trades":
                QUEUED_KEYS.add("find_trades")
                await q.put("find_trades")
        return
    msg = upd.get("message")
    if not msg or not msg.get("text"):
        return
    chat_id = str((msg.get("chat") or {}).get("id") or "")
    if TELEGRAM_CHAT_ID and chat_id and chat_id != str(TELEGRAM_CHAT_ID):
        return
    low = str(msg.get("text") or "").strip().lower()

    if low in ("/start", "/menu", "меню"):
        send_tg_message(
            f"🤖 <b>Помощник перепродажи Senkuro {APP_VERSION_TAG} (без твинков и паролей)</b>\n\n"
            "• <b>🃏 Мои карты</b> — показать твои карты <code>cesium254</code> с ценами банка на фото\n"
            "• <b>🎯 Найти обмены</b> — сам проверит твои дешёвые карты и выдаст цели без гильдии\n"
            "• <b>🔄 Пополнить базу</b> — просканировать новую партию дорогих карт в базу",
            add_keyboard=True,
        )
        return

    if low in ("🛑 стоп", "/stop", "стоп"):
        STOP_FLAG = True
        if ACTIVE_JOB_TASK and not ACTIVE_JOB_TASK.done():
            ACTIVE_JOB_TASK.cancel()
        while not q.empty():
            try:
                q.get_nowait()
                q.task_done()
            except Exception:
                break
        QUEUED_KEYS.clear()
        send_tg_message("🛑 Текущая задача остановлена, сервер в режиме ожидания.", add_keyboard=True)
        return

    if low in ("📜 лог", "/log", "лог"):
        await asyncio.to_thread(send_debug_log)
        return

    if low in ("📊 статус базы", "/status", "статус"):
        await asyncio.to_thread(send_db_status)
        return

    btn_map = {
        "🃏 мои карты": "my_cards",
        "/cards": "my_cards",
        "мои карты": "my_cards",
        "🎯 найти обмены": "find_trades",
        "/find": "find_trades",
        "найти обмены": "find_trades",
        "🔄 пополнить базу": "refill_db",
        "/refill": "refill_db",
        "пополнить базу": "refill_db",
    }
    if low in btn_map:
        act = btn_map[low]
        if act in QUEUED_KEYS or (ACTIVE_JOB_NAME == act and ACTIVE_JOB_TASK and not ACTIVE_JOB_TASK.done()):
            send_tg_message("ℹ️ Эта задача уже выполняется.", add_keyboard=True)
            return
        QUEUED_KEYS.add(act)
        await q.put(act)
        return

    send_tg_message("👇 Выберите действие кнопкой ниже:", add_keyboard=True)


async def poller_loop(q: asyncio.Queue, deadline: float) -> None:
    offset = read_tg_offset()
    if offset == 0:
        init_u = await asyncio.to_thread(fetch_tg_updates, -1, 1)
        if init_u:
            offset = int(init_u[-1]["update_id"]) + 1
            write_tg_offset(offset)
    log_debug(f"[DAEMON READY] Senkuro Trade Assistant {APP_VERSION_TAG} запущен (offset={offset}).")
    if os.environ.get("GH_EVENT_NAME") in ("push", "workflow_dispatch"):
        send_tg_message(
            f"🟢 <b>Помощник перепродажи Senkuro {APP_VERSION_TAG} запущен!</b>\n"
            "Работает без паролей и твинков — выбирайте кнопку ниже 👇",
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
            act = await asyncio.wait_for(q.get(), timeout=2.0)
        except asyncio.TimeoutError:
            continue
        QUEUED_KEYS.discard(act)
        ACTIVE_JOB_NAME = act
        STOP_FLAG = False
        try:
            ACTIVE_JOB_TASK = asyncio.create_task(execute_action(act))
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
    parser = argparse.ArgumentParser(description=f"Senkuro Public Trade Assistant {APP_VERSION_TAG}")
    parser.add_argument("--action", default=os.environ.get("SENKURO_ACTION", "daemon").strip().lower() or "daemon")
    args = parser.parse_args()

    q: asyncio.Queue = asyncio.Queue()
    deadline = time.time() + 4.0 * 3600.0

    # При плановом запуске по расписанию (schedule) тихо пополняем локальную базу целей на 15 карт
    if os.environ.get("GH_EVENT_NAME") == "schedule":
        await run_refill_database(max_cards=15, silent=True)

    if args.action != "daemon":
        await execute_action(args.action)
        return

    await asyncio.gather(poller_loop(q, deadline), executor_loop(q, deadline), return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(async_main())