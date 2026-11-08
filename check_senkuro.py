#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SENKURO FULL AUTOMATION COMBINE v28.0 (8 ФАРМ-АККАУНТОВ + ОСНОВА | ПАРОЛИ В GITHUB SECRETS)
================================================================================
Полный единый комбайн (Kaggle больше НЕ нужен — всё запускается из Telegram!):
1. ▶️ Запустить фарм (8 ч) (--action farm_part1 / farm_part2 / farm):
   - Запускается прямо с кнопки в Telegram на 8 часов (2 этапа по 4 часа в одном
     воркфлоу GitHub Actions с передачей сессий через артефакты).
   - Поднимает виртуальный экран Xvfb (реальный браузер без headless-ограничений),
     8 изолированных туннеля opera-proxy (4 разных IP), входит в 4 аккаунта,
     подключает полный боевой скрипт Senkuro Automation Suite v4.0 (анти-сон через
     Web Worker + AudioContext + WebLocks + requestAnimationFrame, сбор карт в 2 этапа,
     прокрутка закладок в самый низ, автоскролл глав и смена манги в конце).
   - Присылает отчет в Telegram при старте (когда все 8 аккаунтов открыли главы)
     и финальный отчет ровно через 8 часов (без лишних уведомлений за 5 минут).
2. 📊 Проверить статус фарма (--action farm_status):
   - Показывает живую сводку: сколько времени идет фарм, какие IP у 4 аккаунтов,
     читают ли они сейчас главы манги и какие именно тайтлы открыты.
3. 🎟 Ввести промокод (--action promo --promo-code КОД):
   - Заходит на 8 фарм-аккаунтов под их уникальными IP, проверяет баланс ДО,
     вводит промокод, запрашивает свежий баланс с сервера ПОСЛЕ, строго проверяет,
     что монеты реально начислились (after > before), и пишет финальный баланс.
4. 🪙 Баланс монет (4 акка) (--action balance):
   - Прямая кнопка без подменю: заходит на 8 фарм-аккаунтов и показывает точное
     количество сенкоинов и сколько паков «Хардкор» (по 480 монет) доступно.
5. 🎴 Крутить паки Хардкор (--action packs):
   - Прямая кнопка без подменю: крутит пак https://senkuro.com/packs/for-hardcore-gamers
     за 480 монет, выбирает из первых 2 слотов карту выше рангом (S > A > B > C > D > F)
     и пишет статистику по каждому аккаунту: что выпало, что забрал и остаток монет.
6. ⚒️ Переплавка + Трейд (--action forge):
   - Строго вкладка «Переплавка» (UPGRADE: 3 карты одного ранга -> 1 карта выше до S).
   - Перекидывает недостающие карты между 4 аккаунтами, принимает трейды строго из
     белого списка (ber_turtle, ainz, catswat, wolfrice, cesium254), а по завершении
     отправляет все карты и осколки трейдом на основу cesium254.
7. 🔄 Проверить 9 аккаунтов (--action check):
   - Стандартная проверка карт и осколков всех 9 аккаунтов с альбомами фотографий.
================================================================================
"""

import argparse
import asyncio
import json
import os
import platform
import random
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Optional

from playwright.async_api import async_playwright, BrowserContext, Page

# ==============================================================================
# 1. КОНФИГУРАЦИЯ TELEGRAM, АККАУНТОВ И КАНАЛА СИНХРОНИЗАЦИИ СТАТУСА ФАРМА
# ==============================================================================

# Флаг отладки: пока мы тестируем бота = True (включает кнопки «📸 Посмотреть экран» и «📜 Полный лог»,
# авто-загрузку полного лога на GitHub и авто-скриншоты при ошибках).
# Когда всё протестируем, достаточно поменять True на False — и отладка скроется без риска сломать код!
DEBUG_MODE = True

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
if not TELEGRAM_BOT_TOKEN:
    print("❌ [SECURITY ERROR] TELEGRAM_BOT_TOKEN не задан в Secrets GitHub Actions! Добавьте секрет TELEGRAM_BOT_TOKEN в Settings -> Secrets -> Actions.")
TELEGRAM_CHAT_ID = (
    os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    or "457787014"
)
GITHUB_REPO_FULL = os.environ.get("GITHUB_REPOSITORY", "cesium254/senkuro-checker").strip() or "cesium254/senkuro-checker"
GITHUB_PAT_TOKEN = (
    os.environ.get("GITHUB_PAT", "").strip()
    or os.environ.get("GITHUB_TOKEN", "").strip()
    or ""
)

DEBUG_LOG_FILE = Path("/tmp/senkuro_full_debug.log")
ACTIVE_BROWSER_PAGES: dict[str, Page] = {}


def log_debug(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        if DEBUG_LOG_FILE.exists() and DEBUG_LOG_FILE.stat().st_size > 250_000:
            tail_bytes = DEBUG_LOG_FILE.read_bytes()[-140_000:]
            DEBUG_LOG_FILE.write_bytes(tail_bytes)
        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

FARM_STATE_SYNC_TOPIC = "senkuro_cesium254_v8_state_sync"

MAIN_ACCOUNT_SLUG = "cesium254"
MAIN_ACCOUNT_URL = f"https://senkuro.com/users/{MAIN_ACCOUNT_SLUG}"

KNOWN_USER_IDS: dict[str, str] = {
    "ber_turtle": "VVNFUjoyNTM0NjAyNTY0OTM5NDY0MTY",
    "ainz": "VVNFUjoyNTQxMzk3NTk2NjI3NDUxNDk",
    "catswat": "VVNFUjoyNTQxNDA2Mjg1Mzc5ODQ1NzM",
    "wolfrice": "VVNFUjoyNTQxNDQ2NTA5MDkwNzUwMDU",
    "lanar": "VVNFUjoyNTY3ODk1MDgyMTE2MjM0NjQ",
    "canva": "VVNFUjoyNTY3OTA1NTY3ODc2MjM0NjQ",
    "raya": "VVNFUjoyNTY3OTE0MDI4NjI2MjYzNDQ",
    "tnt": "VVNFUjoyNTY3OTIxOTEyMjQwMDYxODQ",
    "cesium254": "VVNFUjoxODAxNDM0ODEzOTI0ODE4MDE",
}


def get_secret_password(idx: int, slug: str, login_email: str) -> str:
    """
    Безопасно загружает пароль аккаунта из Secrets GitHub Actions (никаких паролей в открытом коде!):
    Поддерживает любые варианты имени секрета (SENKURO_PASSWORDS, SENKURO_PASSWORD, SENKURO_PASS, PASSWORDS,
    SENKURO_PASS_1..8) и любые форматы записи (многострочный 1:пароль, 1=пароль, однострочный через пробел,
    список без ключей на 8 или 4 строки).
    """
    for k_env in (f"SENKURO_PASS_{idx}", f"SENKURO_PASSWORD_{idx}", f"PASS_{idx}"):
        direct = os.environ.get(k_env, "").strip()
        if direct:
            return direct

    bulk_sources = [
        os.environ.get("SENKURO_PASSWORDS", "").strip(),
        os.environ.get("SENKURO_PASSWORD", "").strip(),
        os.environ.get("PASSWORDS", "").strip(),
        os.environ.get("PASSWORD", "").strip(),
        os.environ.get("SENKURO_PASS", "").strip(),
    ]
    bulk = next((b for b in bulk_sources if b), "")
    if bulk:
        valid_keys = {
            str(idx),
            f"#{idx}",
            f"№{idx}",
            f"acc_{idx}",
            f"acc{idx}",
            f"account_{idx}",
            f"account{idx}",
            slug.lower(),
            login_email.lower(),
        }
        lines = [ln.strip() for ln in bulk.splitlines() if ln.strip() and not ln.strip().startswith("#")]
        # 1. Построчный разбор вида "1:пароль", "1=пароль", "lanar:пароль"
        for ln in lines:
            for sep in (":", "="):
                if sep in ln:
                    k, v = ln.split(sep, 1)
                    k_clean = k.strip().lower().lstrip("#№")
                    if k.strip().lower() in valid_keys or k_clean in valid_keys:
                        # Если в одной строке записано несколько пар через пробел ("1:pass1 2:pass2")
                        v_clean = v.strip()
                        m_next = re.search(r"\s+(?:#|№|acc_?)?[1-8]\s*[:=]", v_clean)
                        if m_next:
                            v_clean = v_clean[:m_next.start()].strip()
                        if v_clean:
                            return v_clean
        # 2. Если все пары записаны в одну строку через пробел/запятую/точку с запятой
        inline_matches = re.findall(
            r"(?:^|[\s,;]+)(?:#|№|acc_?)?([1-8]|ber_turtle|ainz|catswat|wolfrice|lanar|canva|raya|tnt)\s*[:=]\s*([^\s,;]+)",
            bulk,
            flags=re.IGNORECASE,
        )
        for k_m, v_m in inline_matches:
            if k_m.lower() in valid_keys:
                return v_m.strip()
        # 3. Если просто 8 строк с паролями без номеров
        if len(lines) >= idx:
            cand = lines[idx - 1]
            if not re.match(r"^(?:#|№|acc_?)?[1-8]\s*[:=]", cand):
                return cand
        # 4. Если передано ровно 4 строки (только для новых аккаунтов 5..8)
        if len(lines) == 4 and idx >= 5:
            cand = lines[idx - 5]
            if not re.match(r"^(?:#|№|acc_?)?[1-8]\s*[:=]", cand):
                return cand
        # 5. Если передана ровно 1 строка (единый общий пароль)
        if len(lines) == 1 and not re.match(r"^(?:#|№|acc_?)?[1-8]\s*[:=]", lines[0]):
            return lines[0]

    if idx >= 5:
        shared_new = os.environ.get("SENKURO_PASS_NEW", "").strip()
        if shared_new:
            return shared_new

    return os.environ.get("SENKURO_PASS", "").strip()


FARM_ACCOUNTS = [
    {
        "idx": 1,
        "acc_id": "acc_1",
        "id": "ber_turtle",
        "label": "#1 Ber Turtle (ber_turtle)",
        "login": os.environ.get("SENKURO_LOGIN_1", "").strip() or "zerovillbusiness@gmail.com",
        "password": get_secret_password(1, "ber_turtle", "zerovillbusiness@gmail.com"),
        "pinned_ip": "77.111.244.37",
        "proxy_port": 25341,
        "url": "https://senkuro.com/users/ber_turtle/cards",
        "bookmarks_url": "https://senkuro.com/users/ber_turtle/bookmarks",
    },
    {
        "idx": 2,
        "acc_id": "acc_2",
        "id": "ainz",
        "label": "#2 Ainz (ainz)",
        "login": os.environ.get("SENKURO_LOGIN_2", "").strip() or "dert124689@gmail.com",
        "password": get_secret_password(2, "ainz", "dert124689@gmail.com"),
        "pinned_ip": "77.111.244.209",
        "proxy_port": 25342,
        "url": "https://senkuro.com/users/ainz/cards",
        "bookmarks_url": "https://senkuro.com/users/ainz/bookmarks",
    },
    {
        "idx": 3,
        "acc_id": "acc_3",
        "id": "catswat",
        "label": "#3 Cat Swat (catswat)",
        "login": os.environ.get("SENKURO_LOGIN_3", "").strip() or "gamerecapbusiness@gmail.com",
        "password": get_secret_password(3, "catswat", "gamerecapbusiness@gmail.com"),
        "pinned_ip": "77.111.244.210",
        "proxy_port": 25343,
        "url": "https://senkuro.com/users/catswat/cards",
        "bookmarks_url": "https://senkuro.com/users/catswat/bookmarks",
    },
    {
        "idx": 4,
        "acc_id": "acc_4",
        "id": "wolfrice",
        "label": "#4 Wolf Rice (wolfrice)",
        "login": os.environ.get("SENKURO_LOGIN_4", "").strip() or "gameepicenterbusiness@gmail.com",
        "password": get_secret_password(4, "wolfrice", "gameepicenterbusiness@gmail.com"),
        "pinned_ip": "77.111.246.8",
        "proxy_port": 25344,
        "url": "https://senkuro.com/users/wolfrice/cards",
        "bookmarks_url": "https://senkuro.com/users/wolfrice/bookmarks",
    },
    {
        "idx": 5,
        "acc_id": "acc_5",
        "id": "lanar",
        "label": "#5 Lanar (lanar)",
        "login": os.environ.get("SENKURO_LOGIN_5", "").strip() or "Cesium254@proton.me",
        "password": get_secret_password(5, "lanar", "Cesium254@proton.me"),
        "pinned_ip": "77.111.246.10",
        "proxy_port": 25345,
        "url": "https://senkuro.com/users/lanar/cards",
        "bookmarks_url": "https://senkuro.com/users/lanar/bookmarks",
    },
    {
        "idx": 6,
        "acc_id": "acc_6",
        "id": "canva",
        "label": "#6 Canva (canva)",
        "login": os.environ.get("SENKURO_LOGIN_6", "").strip() or "woodlandcava@gmail.com",
        "password": get_secret_password(6, "canva", "woodlandcava@gmail.com"),
        "pinned_ip": "77.111.246.14",
        "proxy_port": 25346,
        "url": "https://senkuro.com/users/canva/cards",
        "bookmarks_url": "https://senkuro.com/users/canva/bookmarks",
    },
    {
        "idx": 7,
        "acc_id": "acc_7",
        "id": "raya",
        "label": "#7 Raya (raya)",
        "login": os.environ.get("SENKURO_LOGIN_7", "").strip() or "restunger@gmail.com",
        "password": get_secret_password(7, "raya", "restunger@gmail.com"),
        "pinned_ip": "77.111.245.10",
        "proxy_port": 25347,
        "url": "https://senkuro.com/users/raya/cards",
        "bookmarks_url": "https://senkuro.com/users/raya/bookmarks",
    },
    {
        "idx": 8,
        "acc_id": "acc_8",
        "id": "tnt",
        "label": "#8 TNT (tnt)",
        "login": os.environ.get("SENKURO_LOGIN_8", "").strip() or "jekadinamit@gmail.com",
        "password": get_secret_password(8, "tnt", "jekadinamit@gmail.com"),
        "pinned_ip": "77.111.245.14",
        "proxy_port": 25348,
        "url": "https://senkuro.com/users/tnt/cards",
        "bookmarks_url": "https://senkuro.com/users/tnt/bookmarks",
    },
]

ALL_CHECK_ACCOUNTS = FARM_ACCOUNTS + [
    {
        "idx": 9,
        "acc_id": "acc_main",
        "id": "cesium254",
        "label": "Main (Cesium254)",
        "login": "",
        "password": "",
        "pinned_ip": "",
        "proxy_port": 0,
        "url": "https://senkuro.com/users/cesium254/cards",
    }
]

ALLOWED_TRADE_SLUGS = {
    "ber_turtle",
    "ainz",
    "catswat",
    "wolfrice",
    "lanar",
    "canva",
    "raya",
    "tnt",
    "cesium254",
}

HARDCORE_PACK_SLUG = "for-hardcore-gamers"
HARDCORE_PACK_COST = 480
GRAPHQL_API_URL = "https://api.senkuro.com/graphql"
APP_VERSION = "301026"

RANK_ORDER = ["R", "S", "A", "B", "C", "D", "F", "?"]
RANK_PRIORITY = {"F": 1, "D": 2, "C": 3, "B": 4, "A": 5, "S": 6, "R": 7, "X": 8, "?": 0}
FORGE_UPGRADE_CHAIN = ["F", "D", "C", "B", "A"]
NEXT_FORGE_RANK = {"F": "D", "D": "C", "C": "B", "B": "A", "A": "S"}

RANK_BADGE = {
    "R": "💎 R",
    "S": "🟥 S",
    "A": "🟨 A",
    "B": "🟪 B",
    "C": "🟦 C",
    "D": "🟩 D",
    "F": "⬜ F",
}

BASE_DIR = Path(__file__).resolve().parent
SESSIONS_DIR = BASE_DIR / ".sessions"
BIN_DIR = BASE_DIR / "bin"
SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
BIN_DIR.mkdir(parents=True, exist_ok=True)
KNOWN_IDS_CACHE_FILE = SESSIONS_DIR / "known_user_ids.json"
if KNOWN_IDS_CACHE_FILE.exists():
    try:
        _cached_ids = json.loads(KNOWN_IDS_CACHE_FILE.read_text(encoding="utf-8"))
        if isinstance(_cached_ids, dict):
            for _k, _v in _cached_ids.items():
                if isinstance(_v, str) and _v.startswith("VVNFU"):
                    KNOWN_USER_IDS[_k] = _v
    except Exception:
        pass


def save_known_user_id(slug: str, uid: str) -> None:
    if not slug or not isinstance(uid, str) or not uid.startswith("VVNFU"):
        return
    if KNOWN_USER_IDS.get(slug) == uid:
        return
    KNOWN_USER_IDS[slug] = uid
    try:
        KNOWN_IDS_CACHE_FILE.write_text(json.dumps(KNOWN_USER_IDS, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

OPERA_244_CANDIDATE_POOL = [
    "77.111.244.37",
    "77.111.244.209",
    "77.111.244.210",
    "77.111.244.22",
    "77.111.244.42",
    "77.111.244.29",
    "77.111.244.38",
    "77.111.244.28",
    "77.111.244.48",
    "77.111.244.51",
    "77.111.244.52",
    "77.111.244.53",
    "77.111.244.54",
    "77.111.244.72",
    "77.111.244.74",
    "77.111.244.76",
    "77.111.244.77",
    "77.111.244.78",
    "77.111.244.183",
    "77.111.244.185",
    "77.111.244.11",
    "77.111.244.12",
    "77.111.244.21",
    "77.111.244.27",
]


# ==============================================================================
# 2. ЕДИНАЯ БАЗОВАЯ ПАНЕЛЬ КНОПОК TELEGRAM (БЕЗ ПОДПУНКТОВ, 1 КНОПКА = 1 ЗАДАЧА)
# ==============================================================================

def get_collapsible_reply_keyboard() -> dict:
    """
    4-рядная компактная нижняя клавиатура Telegram (помещается на экран целиком БЕЗ прокрутки!).
    Кнопка «🛑 СТОП» вынесена в САМЫЙ ВЕРХНИЙ РЯД справа, чтобы её никогда не нужно было листать вниз,
    а стрелочка [v] справа в поле ввода позволяет сворачивать и разворачивать меню в 1 клик.
    """
    rows = [
        [{"text": "▶️ Фарм (8 ч)"}, {"text": "📊 Статус"}, {"text": "🛑 СТОП"}],
        [{"text": "🪙 Баланс"}, {"text": "🎴 Паки"}, {"text": "🎟 Промокод"}],
        [{"text": "⚒️ Кузня+Трейд"}, {"text": "🔄 Чекать 9"}],
    ]
    if DEBUG_MODE:
        rows.append([{"text": "📸 Экран"}, {"text": "📜 Лог"}])
    return {
        "keyboard": rows,
        "resize_keyboard": True,
        "is_persistent": False,
        "input_field_placeholder": "Промокод или меню 🎛 👇",
    }


def get_main_inline_keyboard() -> dict:
    # Полностью отключено старое верхнее inline-меню, чтобы оно никогда не дублировалось и не сбивало нижнюю панель!
    return get_collapsible_reply_keyboard()


def tg_request(method: str, payload: dict, max_retries: int = 4) -> dict:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[DRY-RUN] {method}: {json.dumps(payload, ensure_ascii=False)[:300]}")
        return {"ok": True}
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")

    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=35) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                print(f"[TG OK] {method}")
                return res_data
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            if e.code == 429 and attempt < max_retries:
                retry_after = 5
                try:
                    err_json = json.loads(err_body)
                    retry_after = int((err_json.get("parameters") or {}).get("retry_after") or 5)
                except Exception:
                    pass
                wait_s = max(2, min(retry_after + 1, 35))
                log_debug(f"[TG 429 WAIT] Лимит Telegram на {method}, жду {wait_s} сек (попытка {attempt}/{max_retries})...")
                time.sleep(wait_s)
                continue
            log_debug(f"[TG ERROR] {method} ({e.code}): {err_body}")
            return {"ok": False, "error_code": e.code, "error": err_body}
        except Exception as e:
            if attempt < max_retries:
                time.sleep(2.0)
                continue
            log_debug(f"[TG ERROR] {method}: {e}")
            return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "max_retries_exceeded"}


def _split_long_tg_text(text: str, limit: int = 3800) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts: list[str] = []
    cur_lines: list[str] = []
    cur_len = 0
    for line in text.splitlines(keepends=True):
        if cur_len + len(line) > limit and cur_lines:
            parts.append("".join(cur_lines).rstrip())
            cur_lines = [line]
            cur_len = len(line)
        else:
            cur_lines.append(line)
            cur_len += len(line)
    if cur_lines:
        parts.append("".join(cur_lines).rstrip())
    return parts or [text[:limit]]


def send_tg_message(text: str, add_keyboard: bool = True, force_reply_kb: bool = False) -> dict:
    chunks = _split_long_tg_text(text, limit=3800)
    last_res: dict[str, Any] = {"ok": False}
    for i, chunk_text in enumerate(chunks):
        is_last = i == len(chunks) - 1
        payload: dict[str, Any] = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": chunk_text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if (add_keyboard or force_reply_kb) and is_last:
            payload["reply_markup"] = get_collapsible_reply_keyboard()
        res = tg_request("sendMessage", payload)
        if not res.get("ok"):
            log_debug(f"[TG WARN] sendMessage HTML failed ({res}), повтор без parse_mode...")
            payload_plain = dict(payload)
            payload_plain.pop("parse_mode", None)
            res = tg_request("sendMessage", payload_plain)
        last_res = res
        if not is_last:
            time.sleep(0.8)
    return last_res


def send_tg_multipart(method: str, file_field: str, filename: str, file_bytes: bytes, mime_type: str, extra_fields: dict[str, str]) -> dict:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return {"ok": False}
    boundary = f"----SenkuroBoundary{int(time.time() * 1000)}"
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
        log_debug(f"[TG MULTIPART ERROR] {method}: {e}")
        return {"ok": False, "error": str(e)}


def send_tg_photo_bytes(png_bytes: bytes, caption: str = "", add_keyboard: bool = False) -> dict:
    fields = {"chat_id": str(TELEGRAM_CHAT_ID), "parse_mode": "HTML"}
    if caption:
        fields["caption"] = caption[:1000]
    if add_keyboard:
        fields["reply_markup"] = json.dumps(get_collapsible_reply_keyboard(), ensure_ascii=False)
    return send_tg_multipart("sendPhoto", "photo", "screen.png", png_bytes, "image/png", fields)


def upload_debug_log_to_github_noop(reason: str = "task") -> Optional[str]:
    """
    Автоматически загружает полный файл лога /tmp/senkuro_full_debug.log в ваш репозиторий
    cesium254/senkuro-checker по пути logs/senkuro_debug.log с тегом [skip ci], чтобы вы или ИИ
    всегда могли открыть полный лог по прямой ссылке!
    """
    if not DEBUG_LOG_FILE.exists() or not GITHUB_PAT_TOKEN:
        return None
    import base64
    try:
        raw_bytes = DEBUG_LOG_FILE.read_bytes()
        # Ограничим последними 450 КБ, если лог огромный
        if len(raw_bytes) > 450_000:
            raw_bytes = raw_bytes[-450_000:]
        b64_content = base64.b64encode(raw_bytes).decode("ascii")
        api_url = f"https://api.github.com/repos/{GITHUB_REPO_FULL}/contents/logs/senkuro_debug.log"
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {GITHUB_PAT_TOKEN}",
            "User-Agent": "SenkuroBot/24.0",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": "application/json",
        }
        sha_val = None
        try:
            get_req = urllib.request.Request(api_url, headers=headers, method="GET")
            with urllib.request.urlopen(get_req, timeout=10) as g_resp:
                g_data = json.loads(g_resp.read().decode("utf-8"))
                sha_val = g_data.get("sha")
        except Exception:
            pass

        put_payload: dict[str, Any] = {
            "message": f"Update full debug log ({reason}) [skip ci]",
            "content": b64_content,
            "branch": "main",
        }
        if sha_val:
            put_payload["sha"] = sha_val

        put_req = urllib.request.Request(
            api_url,
            data=json.dumps(put_payload).encode("utf-8"),
            headers=headers,
            method="PUT",
        )
        with urllib.request.urlopen(put_req, timeout=15) as p_resp:
            if p_resp.status in (200, 201):
                return f"https://github.com/{GITHUB_REPO_FULL}/blob/main/logs/senkuro_debug.log"
    except Exception as e:
        log_debug(f"[GH LOG UPLOAD WARNING] {e}")
    return None


def upload_debug_log_to_github_noop(reason: str = "task") -> None:
    return None


def send_full_debug_log_to_user(reason_title: str = "Полный лог работы") -> None:
    if not DEBUG_LOG_FILE.exists():
        send_tg_message("ℹ️ Файл лога пока пуст.", add_keyboard=True)
        return
    raw_bytes = DEBUG_LOG_FILE.read_bytes()
    caption = (
        f"📜 <b>{reason_title}</b> (размер: {max(1, len(raw_bytes) // 1024)} КБ)\n\n"
        "Откройте этот файл и скопируйте текст (или перешлите его в чат с ИИ) для мгновенной проверки!"
    )
    fields = {
        "chat_id": str(TELEGRAM_CHAT_ID),
        "caption": caption[:1000],
        "parse_mode": "HTML",
        "reply_markup": json.dumps(get_collapsible_reply_keyboard(), ensure_ascii=False),
    }
    send_tg_multipart("sendDocument", "document", "senkuro_debug_log.txt", raw_bytes, "text/plain", fields)


async def capture_page_png_fast(pg: Page) -> Optional[bytes]:
    """
    Мгновенный захват скриншота через Chrome DevTools Protocol (Page.captureScreenshot) за 0.05 сек!
    Не зависает на ожидании шрифтов или анимаций через прокси, в отличие от обычного pg.screenshot().
    """
    import base64
    try:
        cdp = await pg.context.new_cdp_session(pg)
        try:
            res = await asyncio.wait_for(cdp.send("Page.captureScreenshot", {"format": "png"}), timeout=4.0)
            if res and res.get("data"):
                return base64.b64decode(res["data"])
        finally:
            await cdp.detach()
    except Exception as e:
        log_debug(f"[CDP SCREENSHOT FALLBACK] {e}")
    try:
        return await pg.screenshot(full_page=False, animations="disabled", timeout=5000)
    except Exception as e2:
        log_debug(f"[STD SCREENSHOT ERR] {e2}")
        return None


def is_local_port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.25):
            return True
    except Exception:
        return False


is_port_open = is_local_port_open


def _stitch_screens_2x2_png(screens: list[tuple[str, bytes]]) -> Optional[bytes]:
    """
    Склеивает от 2 до 8 скриншотов аккаунтов в ЕДИНУЮ HD-картинку (2x2 для 2..4 экранов или 2x4 для 5..8 экранов),
    чтобы кнопка «📸 Экран» присылала РОВНО 1 СООБЩЕНИЕ со всеми 8 аккаунтами!
    """
    if not screens:
        return None
    if len(screens) == 1:
        return screens[0][1]
    try:
        import io
        from PIL import Image, ImageDraw

        count = min(8, len(screens))
        cols = 2
        rows = 2 if count <= 4 else ((count + 1) // 2)
        tile_w = 1280 if rows <= 2 else 960
        tile_h = 900 if rows <= 2 else 675

        canvas = Image.new("RGB", (tile_w * cols, tile_h * rows), (18, 18, 22))
        draw = ImageDraw.Draw(canvas)

        for idx, (label_txt, png_b) in enumerate(screens[:8]):
            col_i = idx % cols
            row_i = idx // cols
            px = col_i * tile_w
            py = row_i * tile_h
            try:
                im = Image.open(io.BytesIO(png_b)).convert("RGB")
                im = im.resize((tile_w - 4, tile_h - 4))
                canvas.paste(im, (px + 2, py + 2))
                draw.rectangle([px + 8, py + 8, px + 240, py + 34], fill=(0, 0, 0))
                draw.text((px + 14, py + 14), f"#{idx + 1} {label_txt}", fill=(80, 255, 120))
            except Exception:
                pass

        out_buf = io.BytesIO()
        canvas.save(out_buf, format="PNG", optimize=True)
        return out_buf.getvalue()
    except Exception as e:
        log_debug(f"[GRID STITCH FALLBACK] {e}")
        return screens[0][1]


async def send_live_screen_snapshot(custom_caption: str = "") -> None:
    """
    Собирает скриншоты всех открытых вкладок/окон (нативные окна Chrome 26411..26414 + вкладки Playwright),
    объединяет их в ОДНУ общую плитку 2x2 и отправляет ОДНИМ сообщением в Telegram!
    """
    import base64
    collected_screens: list[tuple[str, bytes]] = []
    caption_lines: list[str] = ["📸 <b>Снимок экранов фермы:</b>"]
    seen_labels: set[str] = set()

    # 1. Проверяем открытые нативные окна Chrome (порты 26411..26414)
    for acc_item in FARM_ACCOUNTS:
        c_port = 26410 + int(acc_item["idx"])
        if is_local_port_open(c_port):
            try:
                def _grab_nat(p_num: int):
                    with urllib.request.urlopen(f"http://127.0.0.1:{p_num}/json/list", timeout=1.0) as r:
                        t_list = json.loads(r.read().decode("utf-8", errors="ignore"))
                    p_tabs = [t for t in t_list if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
                    if not p_tabs:
                        return None, "", ""
                    ws_u = p_tabs[0]["webSocketDebuggerUrl"]
                    sc = _cdp_ws_call_sync(ws_u, "Page.captureScreenshot", {"format": "png"}, timeout_sec=3.5)
                    if sc.get("data"):
                        return base64.b64decode(sc["data"]), str(p_tabs[0].get("url") or ""), str(p_tabs[0].get("title") or "")
                    return None, "", ""
                nat_png, nat_url, nat_title = await asyncio.to_thread(_grab_nat, c_port)
                if nat_png:
                    aid = acc_item["id"]
                    seen_labels.add(aid)
                    collected_screens.append((aid, nat_png))
                    caption_lines.append(f"• <b>#{acc_item['idx']} {aid}</b>: <code>{nat_url[:75]}</code>")
            except Exception as e:
                log_debug(f"[NAT SNAPSHOT WARN] {acc_item['id']}: {e}")

    # 2. Проверяем открытые вкладки Playwright
    for label, pg in list(ACTIVE_BROWSER_PAGES.items()):
        if label in seen_labels:
            continue
        try:
            if pg.is_closed():
                ACTIVE_BROWSER_PAGES.pop(label, None)
                continue
            png_data = await capture_page_png_fast(pg)
            if not png_data:
                ACTIVE_BROWSER_PAGES.pop(label, None)
                continue
            seen_labels.add(label)
            collected_screens.append((label, png_data))
            caption_lines.append(f"• <b>{label}</b>: <code>{pg.url[:75]}</code>")
        except Exception as e:
            log_debug(f"[SCREENSHOT WARNING] {label}: {e}")

    if not collected_screens:
        send_tg_message(
            "⚪ <b>Сейчас ни одно окно браузера не открыто</b> (сервер в режиме ожидания).\n\n"
            "Запустите любую задачу (например, «▶️ Фарм (8 ч)», «🎴 Паки» или «⚒️ Кузня+Трейд»), и нажимайте <b>«📸 Экран»</b>!",
            add_keyboard=True,
        )
        return

    combined_png = await asyncio.to_thread(_stitch_screens_2x2_png, collected_screens)
    if combined_png:
        final_cap = (f"{custom_caption}\n\n" if custom_caption else "") + "\n".join(caption_lines)
        await asyncio.to_thread(send_tg_photo_bytes, combined_png, final_cap[:1000], True)


WORKER_PUBLIC_URL = "https://sparkling-meadow-68b3.ev20291.workers.dev/"
INSTANT_CMD_QUEUE_TOPIC = "senkuro_cesium254_v11_cmd_queue"
INSTANT_CMD_ACK_TOPIC = "senkuro_cesium254_v11_cmd_ack"


def configure_telegram_bot_profile() -> None:
    # 1. Полностью отключаем старый вебхук Cloudflare, чтобы Telegram работал напрямую с GitHub без ошибок!
    tg_request(
        "deleteWebhook",
        {
            "drop_pending_updates": False,
        },
    )
    # 2. Автоматически очищаем спам-рекламу ("What can this bot do? Free ChatGPT...") во всех языковых версиях бота!
    clean_desc = "Личный бот автоматизации Senkuro (проверка аккаунтов, паки Хардкор, Переплавка, промокоды и 8-часовой фарм)."
    clean_short = "Автоматизация Senkuro"
    for lang in ("", "ru", "uk", "en", "be", "kk"):
        desc_payload = {"description": clean_desc}
        short_payload = {"short_description": clean_short}
        if lang:
            desc_payload["language_code"] = lang
            short_payload["language_code"] = lang
        tg_request("setMyDescription", desc_payload)
        tg_request("setMyShortDescription", short_payload)

    commands = [
        {"command": "menu", "description": "📋 Открыть панель управления"},
        {"command": "check", "description": "🔄 Проверить карты и осколки (9 аккаунтов)"},
        {"command": "balance", "description": "🪙 Баланс монет на 8 аккаунтах"},
        {"command": "packs", "description": "🎴 Крутить паки Хардкор (480 монет)"},
        {"command": "forge", "description": "⚒️ Переплавка карт до S + трейд на основу"},
        {"command": "farm", "description": "▶️ Запустить 8-часовой фарм манги"},
        {"command": "status", "description": "📊 Статус фарма (читают или нет)"},
        {"command": "screen", "description": "📸 Посмотреть экран браузера (Скриншот)"},
        {"command": "log", "description": "📜 Скачать полный лог (Файл + GitHub)"},
        {"command": "stop", "description": "🛑 Остановить фарм и все задачи"},
    ]
    tg_request("setMyCommands", {"commands": commands})
    tg_request("setChatMenuButton", {"menu_button": {"type": "commands"}})


def ack_instant_command(cmd_id: str) -> None:
    if not cmd_id:
        return
    try:
        req = urllib.request.Request(
            f"https://ntfy.sh/{INSTANT_CMD_ACK_TOPIC}",
            data=cmd_id.encode("utf-8"),
            headers={"Content-Type": "text/plain"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=4)
    except Exception:
        pass


def poll_instant_commands(since_ts: int, seen_ids: set[str]) -> list[dict]:
    cmds: list[dict] = []
    try:
        url = f"https://ntfy.sh/{INSTANT_CMD_QUEUE_TOPIC}/json?poll=1&since={since_ts}"
        req = urllib.request.Request(url, headers={"User-Agent": "SenkuroCombine/11.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw_lines = resp.read().decode("utf-8", errors="ignore").strip().splitlines()
        for line in raw_lines:
            try:
                outer = json.loads(line)
                msg_id = outer.get("id") or ""
                if outer.get("event") != "message" or not outer.get("message"):
                    continue
                inner = json.loads(outer["message"])
                if not isinstance(inner, dict) or "action" not in inner:
                    continue
                cmd_id = str(inner.get("cmd_id") or msg_id)
                if cmd_id in seen_ids or (msg_id and msg_id in seen_ids):
                    continue
                seen_ids.add(cmd_id)
                if msg_id:
                    seen_ids.add(msg_id)
                ack_instant_command(cmd_id)
                cmds.append(inner)
            except Exception:
                continue
    except Exception:
        pass
    return cmds


# ==============================================================================
# 3. СИНХРОНИЗАЦИЯ ЖИВОГО СТАТУСА 8-ЧАСОВОГО ФАРМА ДЛЯ TELEGRAM
# ==============================================================================

def publish_live_farm_status(status_dict: dict) -> None:
    try:
        data = json.dumps(status_dict, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"https://ntfy.sh/{FARM_STATE_SYNC_TOPIC}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass


FARM_CONTROL_SYNC_TOPIC = "senkuro_cesium254_v8_ctrl_sync"


def check_remote_stop_signal(since_ts: int) -> bool:
    """Проверяет, нажал ли пользователь кнопку 🛑 ОСТАНОВИТЬ ФАРМ в Telegram."""
    try:
        url = f"https://ntfy.sh/{FARM_CONTROL_SYNC_TOPIC}/json?poll=1&since={since_ts}"
        req = urllib.request.Request(url, headers={"User-Agent": "SenkuroBot/9.5"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            lines = resp.read().decode("utf-8", errors="ignore").strip().splitlines()
        for line in lines:
            if "STOP_NOW" in line:
                return True
    except Exception:
        pass
    return False


def fetch_latest_farm_status() -> Optional[dict]:
    try:
        url = f"https://ntfy.sh/{FARM_STATE_SYNC_TOPIC}/json?poll=1&since=20m"
        req = urllib.request.Request(url, headers={"User-Agent": "SenkuroBot/9.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            raw_lines = resp.read().decode("utf-8", errors="ignore").strip().splitlines()
        latest_obj = None
        for line in raw_lines:
            try:
                outer = json.loads(line)
                if outer.get("event") == "message" and outer.get("message"):
                    inner = json.loads(outer["message"])
                    if isinstance(inner, dict) and "accounts" in inner:
                        latest_obj = inner
            except Exception:
                continue
        return latest_obj
    except Exception:
        return None


# ==============================================================================
# 4. УПРАВЛЕНИЕ ТУННЕЛЯМИ OPERA-PROXY (УНИКАЛЬНЫЙ IP НА КАЖДЫЙ АККАУНТ)
# ==============================================================================

def is_ipv4_address(ip_str: str) -> bool:
    s = (ip_str or "").strip()
    parts = s.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def ensure_opera_proxy_binary() -> Optional[str]:
    sys_name = platform.system().lower()
    exe_name = "opera-proxy.exe" if "windows" in sys_name else "opera-proxy"
    target_path = BIN_DIR / exe_name
    if target_path.exists() and target_path.stat().st_size > 1_000_000:
        if not sys.platform.startswith("win"):
            try:
                target_path.chmod(0o755)
            except Exception:
                pass
        return str(target_path)

    which_bin = shutil.which("opera-proxy")
    if which_bin:
        return which_bin

    asset = "opera-proxy.windows-amd64.exe" if "windows" in sys_name else "opera-proxy.linux-amd64"
    url = f"https://github.com/Alexey71/opera-proxy/releases/latest/download/{asset}"
    log_debug(f"[VPN] Скачивание {asset} с GitHub...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(target_path, "wb") as out_f:
            shutil.copyfileobj(resp, out_f)
        if not sys.platform.startswith("win"):
            target_path.chmod(0o755)
        return str(target_path)
    except Exception as e:
        print(f"[VPN WARNING] Не удалось скачать opera-proxy: {e}")
        return None


def verify_proxy_exit_ip(local_port: int, timeout: float = 3.0) -> tuple[bool, str]:
    proxy_handler = urllib.request.ProxyHandler(
        {
            "http": f"http://127.0.0.1:{local_port}",
            "https": f"http://127.0.0.1:{local_port}",
        }
    )
    opener = urllib.request.build_opener(proxy_handler)
    for url in ("https://checkip.amazonaws.com", "https://icanhazip.com", "https://api.ipify.org"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8.5.0"})
            with opener.open(req, timeout=timeout) as resp:
                ip = resp.read().decode("utf-8", errors="ignore").strip()
                if is_ipv4_address(ip):
                    return True, ip
        except Exception:
            continue
    return False, ""


class AccountProxyManager:
    """Поднимает и контролирует 8 изолированных VPN-туннеля (строго разные IP на каждый из 4 аккаунтов)."""

    def __init__(self) -> None:
        self.procs: dict[str, subprocess.Popen] = {}
        self.active_ips: dict[str, str] = {}

    def _port_open(self, port: int) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return True
        except Exception:
            return False

    def start_account_proxy(self, acc: dict) -> Optional[str]:
        aid = acc["acc_id"]
        port = acc["proxy_port"]
        pinned_ip = acc["pinned_ip"]
        if not port:
            return None

        if self._port_open(port):
            ok, ip = verify_proxy_exit_ip(port, timeout=3.5)
            if ok:
                self.active_ips[aid] = ip
                log_debug(f"[VPN] {acc['id']}: используется активный туннель 127.0.0.1:{port} -> {ip}")
                return f"http://127.0.0.1:{port}"
            elif aid not in self.procs:
                fallback_ip = acc.get("pinned_ip") or "активный VPN"
                self.active_ips[aid] = fallback_ip
                log_debug(f"[VPN] {acc['id']}: порт 127.0.0.1:{port} уже занят фоновым фармом, переиспользую ({fallback_ip})")
                return f"http://127.0.0.1:{port}"

        exe_path = ensure_opera_proxy_binary()
        if not exe_path:
            return None

        used_ips = set(self.active_ips.values())
        kaggle_eu_gateways = ["77.111.244.37", "77.111.244.209", "77.111.244.210"]
        free_eu_gateways = [ip for ip in kaggle_eu_gateways if ip not in used_ips]

        free_candidates = [ip for ip in OPERA_244_CANDIDATE_POOL if ip not in used_ips]
        if pinned_ip in free_candidates:
            free_candidates.remove(pinned_ip)
            free_candidates.insert(0, pinned_ip)

        if free_eu_gateways and pinned_ip.startswith("77.111.244."):
            target_list = [pinned_ip] if pinned_ip in free_eu_gateways else [free_eu_gateways[0]]
            for cand_list in (target_list, free_candidates):
                self._stop_proc(aid)
                b_path = self._write_blacklist(aid, used_ips)
                csv_path = self._write_discover_csv(aid, cand_list)
                args = [
                    exe_path,
                    "-bind-address", f"127.0.0.1:{port}",
                    "-country", "EU",
                    "-discover-csv", csv_path,
                    "-proxy-blacklist", b_path,
                    "-server-selection", "first",
                    "-bootstrap-dns", "https://1.1.1.1/dns-query,https://8.8.8.8/dns-query",
                ]
                proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.procs[aid] = proc
                for _ in range(25):
                    if proc.poll() is not None or self._port_open(port):
                        break
                    time.sleep(0.2)
                if self._port_open(port):
                    ok, ip = verify_proxy_exit_ip(port, timeout=3.0)
                    if ok and ip not in used_ips and not ip.startswith("77.111.247."):
                        self.active_ips[aid] = ip
                        log_debug(f"[VPN] {acc['id']}: закреплен уникальный IP {ip} (порт {port})")
                        return f"http://127.0.0.1:{port}"
                    elif ok and ip:
                        used_ips.add(ip)

        if pinned_ip.startswith("77.111.245."):
            regions = ["AS", "AM", "EU"]
        elif pinned_ip.startswith("77.111.246."):
            regions = ["AM", "AS", "EU"]
        else:
            regions = ["EU", "AM", "AS"]

        for region in regions:
            for sub_try, sel_mode in enumerate(("first", "random", "random"), start=1):
                self._stop_proc(aid)
                b_path = self._write_blacklist(aid, used_ips)
                args = [
                    exe_path,
                    "-bind-address", f"127.0.0.1:{port}",
                    "-country", region,
                    "-discover-repeat", "5",
                    "-proxy-blacklist", b_path,
                    "-server-selection", sel_mode,
                    "-bootstrap-dns", "https://1.1.1.1/dns-query,https://8.8.8.8/dns-query",
                ]
                proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.procs[aid] = proc
                for _ in range(25):
                    if proc.poll() is not None or self._port_open(port):
                        break
                    time.sleep(0.2)
                if self._port_open(port):
                    ok, ip = verify_proxy_exit_ip(port, timeout=3.0)
                    if ok and ip not in used_ips and not ip.startswith("77.111.247."):
                        self.active_ips[aid] = ip
                        log_debug(f"[VPN] {acc['id']} ({region} #{sub_try}): закреплен уникальный IP {ip} (порт {port})")
                        return f"http://127.0.0.1:{port}"
                    elif ok and ip:
                        used_ips.add(ip)

        self._stop_proc(aid)
        return None

    def _write_blacklist(self, aid: str, used_ips: set[str]) -> str:
        b_path = os.path.join(tempfile.gettempdir(), f"senkuro_bl_{aid}.txt")
        lines = ["eu2.sec-tunnel.com:443", "eu2.sec-tunnel.com"]
        for octet in range(256):
            lines.append(f"77.111.247.{octet}:443")
        for ip in sorted(used_ips):
            if is_ipv4_address(ip):
                lines.append(f"{ip}:443")
                lines.append(ip)
        with open(b_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return b_path

    def _write_discover_csv(self, aid: str, candidate_ips: list[str]) -> str:
        csv_path = os.path.join(tempfile.gettempdir(), f"senkuro_disc_{aid}.csv")
        lines = ["country_code,country_name,host,ip_address,port"]
        for ip in candidate_ips:
            if is_ipv4_address(ip) and ip.startswith("77.111.244."):
                lines.append(f"EU,Netherlands,eu0.sec-tunnel.com,{ip},443")
        with open(csv_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        return csv_path

    def _stop_proc(self, aid: str) -> None:
        proc = self.procs.pop(aid, None)
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    def stop_all(self) -> None:
        for aid in list(self.procs.keys()):
            self._stop_proc(aid)


# ==============================================================================
# 5. ПРЯМЫЕ GRAPHQL ЗАПРОСЫ И АВТОРИЗАЦИЯ В АККАУНТАХ SENKURO
# ==============================================================================

GQL_FETCH_VIEWER = """
query fetchViewer {
  viewer {
    sessionId
    user {
      id
      slug
      name
      points
      credits
      subscriptionTier
    }
  }
}
"""

GQL_FETCH_USER_BY_SLUG = """
query fetchUserBySlug($slug: String!) {
  user(slug: $slug) {
    id
    slug
    name
    points
    credits
  }
}
"""

GQL_REDEEM_PROMO = """
mutation redeemRedemption($input: RedeemRedemptionInput!) {
  redeemRedemption(input: $input) {
    points
    experience
    collectible {
      id
      type
      titles {
        lang
        content
      }
    }
  }
}
"""

GQL_FETCH_PACK_AND_PENDING = """
query fetchPackAndPending($slug: String!) {
  cardPack(slug: $slug) {
    id
    slug
    points
    credits
    pickCount
    pickLimit
    subscriptionPick
    quantity
    maxRolls
    viewerOpens
    viewerFreeOpens
    titles {
      lang
      content
    }
  }
  viewerPendingCardPackOpens {
    id
    completedAt
    pack {
      id
      subscriptionPick
      pickLimit
    }
    resultCards {
      id
      slug
      rank
      animated
      titles {
        lang
        content
      }
    }
  }
}
"""

GQL_OPEN_CARD_PACK = """
mutation openCardPack($input: OpenCardPackInput!) {
  openCardPack(input: $input) {
    opens {
      id
      completedAt
      pack {
        id
        subscriptionPick
        pickLimit
      }
      resultCards {
        id
        slug
        rank
        animated
        titles {
          lang
          content
        }
      }
    }
  }
}
"""

GQL_BULK_CHOOSE_PACK_OPEN = """
mutation bulkChooseCardPackOpen($input: BulkChooseCardPackOpenInput!) {
  bulkChooseCardPackOpen(input: $input) {
    success
  }
}
"""

GQL_FETCH_FORGE_SLOTS = """
query fetchForgeCardsSlots($mode: ForgeCardMode!) {
  forgeCardsSlots(mode: $mode) {
    baseSlots
    subscriptionSlots
    used
    available
    resetAt
  }
}
"""

GQL_FORGE_CARDS = """
mutation forgeCards($input: ForgeCardInput!) {
  forgeCards(input: $input) {
    userId
    newCards {
      quantity
      modifier
      shard
      card {
        id
        slug
        rank
        titles {
          lang
          content
        }
      }
    }
    addUserCards {
      userId
      cardId
      quantity
      modifier
      shard
      locked
      card {
        id
        slug
        rank
        titles {
          lang
          content
        }
      }
    }
    removeUserCards {
      cardId
      modifier
      quantity
      shard
    }
  }
}
"""

GQL_FETCH_USER_CARDS_FULL = """
query fetchUserCards($userId: ID!, $after: String, $modifier: UserCardModifierFilter) {
  userCards(
    first: 20
    after: $after
    userId: $userId
    modifier: $modifier
    orderBy: { field: CREATED_AT, direction: DESC }
  ) {
    edges {
      node {
        userId
        cardId
        quantity
        modifier
        shard
        locked
        card {
          id
          slug
          rank
          animated
          explicit
          titles {
            lang
            content
          }
          image {
            original {
              url
            }
          }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

GQL_FETCH_CARD_TRADES = """
query fetchCardTrades($userId: ID!, $status: CardTradeStatus, $after: String) {
  cardTrades(
    first: 20
    after: $after
    userId: $userId
    status: $status
    orderBy: { field: CREATED_AT, direction: DESC }
  ) {
    edges {
      node {
        id
        status
        createdAt
        viewerCanAccept
        viewerCanDecline
        source {
          id
          slug
          name
        }
        destination {
          id
          slug
          name
        }
        offer {
          cardId
          modifier
          quantity
          shard
          card {
            id
            slug
            rank
            titles {
              lang
              content
            }
          }
        }
        request {
          cardId
          modifier
          quantity
          shard
          card {
            id
            slug
            rank
          }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

GQL_SUGGEST_CARD_TRADE = """
mutation suggestCardTrade($input: SuggestCardTradeInput!) {
  suggestCardTrade(input: $input) {
    success
  }
}
"""

GQL_ACCEPT_CARD_TRADE = """
mutation acceptCardTrade($input: AcceptCardTradeInput!) {
  acceptCardTrade(input: $input) {
    success
  }
}
"""


def _strip_bad_gql_field(query_str: str, bad_field: str) -> str:
    pattern_block = re.compile(r"\b" + re.escape(bad_field) + r"\s*\{")
    m = pattern_block.search(query_str)
    if m:
        start_idx = m.start()
        brace_open = query_str.find("{", m.start())
        depth = 0
        end_idx = brace_open
        for i in range(brace_open, len(query_str)):
            if query_str[i] == "{":
                depth += 1
            elif query_str[i] == "}":
                depth -= 1
                if depth == 0:
                    end_idx = i + 1
                    break
        return query_str[:start_idx] + query_str[end_idx:]
    return re.sub(r"\b" + re.escape(bad_field) + r"\b", "", query_str)


async def gql_call(page: Page, query: str, variables: Optional[dict] = None, operation_name: Optional[str] = None) -> dict:
    cur_query = query
    for attempt in range(6):
        payload: dict[str, Any] = {"query": cur_query, "variables": variables or {}}
        if operation_name:
            payload["operationName"] = operation_name

        result = await page.evaluate(
            """async ({ apiUrl, appVersion, bodyPayload }) => {
                function getCookie(name) {
                    const m = document.cookie.match(new RegExp('(?:^|; )' + name.replace(/([.$?*|{}()\[\]\\/+^])/g, '\\$1') + '=([^;]*)'));
                    return m ? decodeURIComponent(m[1]) : '';
                }
                let token = getCookie('access_token') || getCookie('token') || '';
                if (!token) {
                    try {
                        for (let i = 0; i < localStorage.length; i++) {
                            const k = localStorage.key(i) || '';
                            const v = localStorage.getItem(k) || '';
                            if (k.toLowerCase().includes('token') && v.length > 20 && !v.startsWith('{')) {
                                token = v.replace(/^"|"$/g, '');
                                break;
                            }
                        }
                    } catch (e) {}
                }
                const headers = {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'App-Version': appVersion,
                    'Cache-Control': 'no-cache'
                };
                if (token) {
                    headers['Authorization'] = token.startsWith('Bearer ') ? token : ('Bearer ' + token);
                }
                try {
                    const resp = await fetch(apiUrl + '?_t=' + Date.now(), {
                        method: 'POST',
                        headers: headers,
                        credentials: 'include',
                        cache: 'no-store',
                        body: JSON.stringify(bodyPayload)
                    });
                    const json = await resp.json();
                    return json;
                } catch (err) {
                    return { errors: [{ message: String(err) }] };
                }
            }""",
            {"apiUrl": GRAPHQL_API_URL, "appVersion": APP_VERSION, "bodyPayload": payload},
        )
        res = result or {}
        errs = res.get("errors") or []
        if not errs:
            log_debug(f"[GQL OK] op={operation_name} -> keys={list((res.get('data') or {}).keys())}")
            return res

        err_msgs = " | ".join(str(e.get("message") or "") for e in errs if isinstance(e, dict))
        log_debug(f"[GQL WARN #{attempt+1}] op={operation_name} errors={err_msgs[:300]}")
        m_bad = re.search(r'(?:Cannot query field|Unknown field) "([A-Za-z0-9_]+)"', err_msgs)
        if m_bad:
            bad_f = m_bad.group(1)
            new_q = _strip_bad_gql_field(cur_query, bad_f)
            if new_q != cur_query:
                log_debug(f"[GQL AUTO-HEAL] Удалено неподдерживаемое поле '{bad_f}' из {operation_name}, повтор...")
                cur_query = new_q
                continue
        if any(w in err_msgs for w in ("SyntaxError", "upstream", "Failed to fetch", "NetworkError", "502", "503", "504")) and attempt < 2:
            await asyncio.sleep(1.5)
            continue
        break
    return res


async def launch_senkuro_browser(playwright_obj):
    has_display = bool(os.environ.get("DISPLAY"))
    launch_args = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--test-type",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--password-store=basic",
        "--disable-save-password-bubble",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--window-size=1280,900",
    ]
    # На GitHub Actions (ubuntu-latest) предустановлен настоящий Google Chrome (/usr/bin/google-chrome-stable).
    # Запускаем именно его (как на сервере Kaggle) и убираем --enable-automation, чтобы капча sso.senkuro.org проходила с 1-го раза!
    chrome_bin = None
    for cand in (
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        shutil.which("google-chrome-stable"),
        shutil.which("google-chrome"),
    ):
        if cand and os.path.exists(cand):
            chrome_bin = cand
            break
    if chrome_bin:
        log_debug(f"[BROWSER] Запуск настоящего Google Chrome: {chrome_bin} (headless={not has_display})")
        try:
            b_inst = await playwright_obj.chromium.launch(
                executable_path=chrome_bin,
                headless=not has_display,
                ignore_default_args=["--enable-automation"],
                args=launch_args,
            )
            log_debug("[BROWSER OK] Google Chrome успешно запущен и готов к работе")
            return b_inst
        except Exception as e:
            log_debug(f"[BROWSER WARN] Не удалось запустить {chrome_bin}: {e}, резервный Chromium")
    log_debug(f"[BROWSER] Запуск Chromium без флага автоматизации (headless={not has_display})")
    return await playwright_obj.chromium.launch(
        headless=not has_display,
        ignore_default_args=["--enable-automation"],
        args=launch_args,
    )


async def get_fresh_points_balance(page: Page, slug: str) -> int:
    # 1. Пробуем через GQL_FETCH_VIEWER (с поддержкой как viewer.user.points, так и viewer.points)
    v_res = await gql_call(page, GQL_FETCH_VIEWER, {}, "fetchViewer")
    v_data = (v_res.get("data") or {}).get("viewer") or {}
    v_user = v_data.get("user") if isinstance(v_data.get("user"), dict) else v_data
    if isinstance(v_user, dict) and v_user.get("points") is not None:
        pts = int(v_user["points"])
        log_debug(f"[BALANCE] {slug}: получено через fetchViewer = {pts}")
        return pts

    # 2. Пробуем через fetchUserBySlug
    u_res = await gql_call(page, GQL_FETCH_USER_BY_SLUG, {"slug": slug}, "fetchUserBySlug")
    u_obj = (u_res.get("data") or {}).get("user") or {}
    if isinstance(u_obj, dict) and u_obj.get("points") is not None:
        pts = int(u_obj["points"])
        log_debug(f"[BALANCE] {slug}: получено через fetchUserBySlug = {pts}")
        return pts

    # 3. Открываем страницу пака «Для хардкорщиков», перехватываем реальные ответы GraphQL и проверяем DOM
    intercepted_pts: list[int] = []

    async def on_pack_resp(resp):
        if "graphql" in resp.url and resp.request.method == "POST":
            try:
                j = await resp.json()
                raw_s = json.dumps(j)
                for m_p in re.finditer(r'"points"\s*:\s*(\d+)', raw_s):
                    val = int(m_p.group(1))
                    if val != 480:
                        intercepted_pts.append(val)
            except Exception:
                pass

    page.on("response", on_pack_resp)
    try:
        if "/packs/for-hardcore-gamers" not in page.url:
            await page.goto("https://senkuro.com/packs/for-hardcore-gamers", wait_until="domcontentloaded", timeout=35000)
        for _ in range(12):
            await page.wait_for_timeout(600)
            body_t = await page.evaluate("() => document.body ? (document.body.innerText || '') : ''")
            if "Приготовьтесь к приключениям" not in body_t:
                break
        await page.wait_for_timeout(1500)
        if intercepted_pts:
            log_debug(f"[BALANCE] {slug}: перехвачено из трафика паков = {intercepted_pts[-1]}")
            return intercepted_pts[-1]

        dom_pts = await page.evaluate(
            """() => {
                // Ищем баланс монет в шапке или на странице пака
                const candidates = Array.from(document.querySelectorAll('[class*="point"], [class*="coin"], [class*="balance"], [class*="currency"], header span, header div'));
                for (const el of candidates) {
                    if (el.children.length === 0) {
                        const txt = (el.innerText || el.textContent || '').trim().replace(/\s+/g, '');
                        if (/^\d{1,7}$/.test(txt) && txt !== '480') {
                            return parseInt(txt, 10);
                        }
                    }
                }
                return null;
            }"""
        )
        if dom_pts is not None:
            log_debug(f"[BALANCE] {slug}: считано из DOM = {dom_pts}")
            return int(dom_pts)
    except Exception as e:
        log_debug(f"[BALANCE ERROR] {slug}: {e}")
    finally:
        try:
            page.remove_listener("response", on_pack_resp)
        except Exception:
            pass

    return 0


def get_session_file(acc_id: str) -> Path:
    return SESSIONS_DIR / f"session_{acc_id}.json"


async def create_account_context(playwright_browser, acc: dict, proxy_url: Optional[str]) -> BrowserContext:
    sess_file = get_session_file(acc["id"])
    # ВАЖНО: Никаких add_init_script с Object.defineProperty(navigator, "webdriver")!
    # Флаг --disable-blink-features=AutomationControlled уже делает navigator.webdriver === false нативно в C++ движке Chrome.
    ctx_kwargs: dict[str, Any] = {
        "viewport": {"width": 1280, "height": 900},
        "locale": "ru-RU",
    }
    if proxy_url:
        ctx_kwargs["proxy"] = {"server": proxy_url}
    if sess_file.exists():
        try:
            ctx_kwargs["storage_state"] = str(sess_file)
            log_debug(f"[SESSION] Загружена сохраненная сессия для {acc['id']}")
        except Exception as e:
            log_debug(f"[SESSION WARN] {acc['id']}: {e}")
    ctx = await playwright_browser.new_context(**ctx_kwargs)
    return ctx


async def check_is_authenticated_on_senkuro(page: Page, acc_slug: str, intercepted_user: dict) -> Optional[dict]:
    if intercepted_user.get("id"):
        return intercepted_user

    try:
        dom_state = await page.evaluate(
            """(slug) => {
                const bodyTxt = document.body ? (document.body.innerText || '') : '';
                if (!document.body || bodyTxt.includes('Приготовьтесь к приключениям')) {
                    return { loading: true };
                }
                const loginBtn = Array.from(document.querySelectorAll('a, button')).find(el => {
                    const t = (el.innerText || el.textContent || '').trim();
                    return t === 'Войти' || t === 'Вход';
                });
                const hasTokenCookie = document.cookie.includes('access_token') || document.cookie.includes('refresh_token');
                const profileLink = document.querySelector(`header a[href*="/users/${slug}"], nav a[href*="/users/${slug}"], a[href="/users/${slug}"]`);
                return {
                    loading: false,
                    hasLoginBtn: !!loginBtn,
                    hasTokenCookie,
                    hasProfileLink: !!profileLink,
                    url: window.location.href,
                    title: document.title
                };
            }""",
            acc_slug,
        )
    except Exception as e:
        log_debug(f"[DOM AUTH CHECK WARN] {acc_slug}: {e}")
        dom_state = {"loading": True}

    if dom_state.get("loading"):
        return None

    v_res = await gql_call(page, GQL_FETCH_VIEWER, {}, "fetchViewer")
    v_data = (v_res.get("data") or {}).get("viewer") or {}
    v_user = v_data.get("user") if isinstance(v_data.get("user"), dict) else v_data
    if isinstance(v_user, dict) and v_user.get("id"):
        save_known_user_id(acc_slug, str(v_user["id"]))
        return v_user

    if not dom_state.get("hasLoginBtn") and "senkuro.com" in str(dom_state.get("url", "")) and "/auth/" not in str(dom_state.get("url", "")):
        u_res = await gql_call(page, GQL_FETCH_USER_BY_SLUG, {"slug": acc_slug}, "fetchUserBySlug")
        u_obj = (u_res.get("data") or {}).get("user") or {}
        if isinstance(u_obj, dict) and u_obj.get("id"):
            save_known_user_id(acc_slug, str(u_obj["id"]))
            log_debug(f"[AUTH DOM+SLUG OK] {acc_slug}: вход подтвержден по отсутствию кнопки 'Войти' (id={u_obj['id']})")
            return u_obj
        if dom_state.get("hasTokenCookie") or dom_state.get("hasProfileLink"):
            real_uid = KNOWN_USER_IDS.get(acc_slug, acc_slug)
            log_debug(f"[AUTH DOM OK] {acc_slug}: вход подтвержден по куке/профилю в шапке (id={real_uid})")
            return {"id": real_uid, "slug": acc_slug, "points": 0}

    return None


async def ensure_real_user_id(page: Page, slug: str, candidate_uid: str = "") -> str:
    """
    Гарантирует получение настоящего GraphQL ID (VVNFU...) для любого из 8 аккаунтов
    (включая новые аккаунты lanar, canva, raya, tnt) через fetchUserBySlug / fetchViewer.
    """
    if isinstance(candidate_uid, str) and candidate_uid.startswith("VVNFU"):
        save_known_user_id(slug, candidate_uid)
        return candidate_uid
    cached = KNOWN_USER_IDS.get(slug, "")
    if isinstance(cached, str) and cached.startswith("VVNFU"):
        return cached
    for _ in range(3):
        u_res = await gql_call(page, GQL_FETCH_USER_BY_SLUG, {"slug": slug}, "fetchUserBySlug")
        u_obj = (u_res.get("data") or {}).get("user") or {}
        if isinstance(u_obj, dict) and str(u_obj.get("id") or "").startswith("VVNFU"):
            uid_str = str(u_obj["id"])
            save_known_user_id(slug, uid_str)
            return uid_str
        v_res = await gql_call(page, GQL_FETCH_VIEWER, {}, "fetchViewer")
        v_data = (v_res.get("data") or {}).get("viewer") or {}
        v_user = v_data.get("user") if isinstance(v_data.get("user"), dict) else v_data
        if isinstance(v_user, dict) and str(v_user.get("id") or "").startswith("VVNFU"):
            uid_str = str(v_user["id"])
            save_known_user_id(slug, uid_str)
            return uid_str
        await asyncio.sleep(1.0)
    return candidate_uid or slug


def _cdp_ws_call_sync(ws_url: str, method: str, params: Optional[dict] = None, timeout_sec: float = 4.0) -> dict:
    """
    Выполняет одиночный CDP-запрос по WebSocket (используется ТОЛЬКО после завершения входа
    для чтения кук или финального скриншота, чтобы во время прохождения Turnstile на sso.senkuro.org
    к браузеру НЕ был подключен ни один отладчик CDP!).
    """
    import base64
    import struct
    from urllib.parse import urlparse

    u = urlparse(ws_url)
    host = u.hostname or "127.0.0.1"
    port = u.port or 80
    path = u.path
    try:
        with socket.create_connection((host, port), timeout=timeout_sec) as s:
            s.settimeout(timeout_sec)
            key = base64.b64encode(os.urandom(16)).decode("ascii")
            req = (
                f"GET {path} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                f"Upgrade: websocket\r\n"
                f"Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                f"Sec-WebSocket-Version: 13\r\n\r\n"
            )
            s.sendall(req.encode("ascii"))
            resp = b""
            while b"\r\n\r\n" not in resp:
                chunk = s.recv(4096)
                if not chunk:
                    break
                resp += chunk
            if b"101" not in resp.split(b"\r\n", 1)[0]:
                return {}

            cmd_id = 777
            payload = json.dumps({"id": cmd_id, "method": method, "params": params or {}}, ensure_ascii=False).encode("utf-8")
            length = len(payload)
            mask_key = os.urandom(4)
            header = bytearray([0x81])
            if length < 126:
                header.append(0x80 | length)
            elif length < 65536:
                header.append(0x80 | 126)
                header.extend(struct.pack("!H", length))
            else:
                header.append(0x80 | 127)
                header.extend(struct.pack("!Q", length))
            header.extend(mask_key)
            masked = bytearray(payload[i] ^ mask_key[i % 4] for i in range(length))
            s.sendall(header + masked)

            buf = bytearray(resp.split(b"\r\n\r\n", 1)[1])
            deadline = time.time() + timeout_sec
            while time.time() < deadline:
                while len(buf) < 2:
                    chunk = s.recv(65536)
                    if not chunk:
                        return {}
                    buf.extend(chunk)
                b1 = buf[1]
                plen = b1 & 0x7F
                hlen = 2
                if plen == 126:
                    hlen = 4
                    while len(buf) < hlen:
                        buf.extend(s.recv(65536))
                    plen = struct.unpack("!H", buf[2:4])[0]
                elif plen == 127:
                    hlen = 10
                    while len(buf) < hlen:
                        buf.extend(s.recv(65536))
                    plen = struct.unpack("!Q", buf[2:10])[0]
                if b1 & 0x80:
                    hlen += 4
                while len(buf) < hlen + plen:
                    chunk = s.recv(65536)
                    if not chunk:
                        break
                    buf.extend(chunk)
                frame_data = bytes(buf[hlen : hlen + plen])
                del buf[: hlen + plen]
                try:
                    msg_obj = json.loads(frame_data.decode("utf-8", errors="ignore"))
                    if msg_obj.get("id") == cmd_id:
                        return msg_obj.get("result") or {}
                except Exception:
                    pass
    except Exception as e:
        log_debug(f"[CDP WS WARN] {method}: {e}")
    return {}


def _run_xdotool(args_list: list[str]) -> None:
    if not shutil.which("xdotool"):
        return
    try:
        subprocess.run(["xdotool"] + args_list, timeout=3.0, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


def login_via_native_chrome_sync(acc: dict, proxy_url: Optional[str]) -> tuple[Optional[str], list[dict], Optional[bytes], str]:
    """
    Точная копия рабочего движка входа из Senkuro_Kaggle_Server_v6_5_Ready.ipynb (который успешно входит во все 4/8 аккаунта):
    1) Запускает отдельный изолированный процесс /usr/bin/google-chrome-stable (subprocess.Popen) со своей папкой профиля
       (.sessions/chrome_profile_<id>) и своим индивидуальным VPN-прокси (127.0.0.1:2534X).
    2) Поскольку Google Chrome 156 игнорирует флаг --load-extension, скрипт инжектируется напрямую в главную вкладку
       через одиночный CDP-вызов Runtime.evaluate (БЕЗ включения Runtime.enable и БЕЗ подключения Playwright к фреймам Turnstile!).
    3) Дополнительно при необходимости нажимает на поля, чекбокс Turnstile и кнопку «Войти» системной мышью X11 (xdotool).
    """
    chrome_bin = None
    for cand in (
        "/usr/bin/google-chrome-stable",
        "/usr/bin/google-chrome",
        shutil.which("google-chrome-stable"),
        shutil.which("google-chrome"),
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        shutil.which("chromium"),
    ):
        if cand and os.path.exists(cand):
            chrome_bin = cand
            break
    if not chrome_bin:
        return None, [], None, "Chrome binary not found"

    aid = acc["id"]
    cdp_port = 26410 + int(acc.get("idx", 1))
    prof_dir = SESSIONS_DIR / f"chrome_profile_{aid}"
    cache_dir = Path(tempfile.gettempdir()) / "SenkuroCache" / aid
    prof_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    for lock_name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
        lp = prof_dir / lock_name
        if lp.exists() or lp.is_symlink():
            try:
                lp.unlink()
            except Exception:
                pass

    # Скрипт авто-входа v6.5 (из рабочего ноутбука Kaggle) + диагностика координат для X11 (xdotool)
    sso_eval_js = f"""
    (function() {{
        const LOGIN_STR = {json.dumps(acc["login"])};
        const PASS_STR = {json.dumps(acc["password"])};
        const MY_UNAME = {json.dumps(acc["id"])};
        const TARGET_BM_URL = 'https://senkuro.com/users/' + MY_UNAME + '/bookmarks';

        function getCookie(name) {{
            const m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
            return m ? decodeURIComponent(m[1]) : '';
        }}

        function setNativeVal(el, val) {{
            if (!el) return;
            el.focus();
            const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
            const desc = Object.getOwnPropertyDescriptor(proto, 'value');
            if (desc && desc.set) desc.set.call(el, val);
            else el.value = val;
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
        }}

        function toX11(r, ox, oy) {{
            const cTop = Math.max(0, (window.outerHeight || 900) - (window.innerHeight || 810));
            const cLeft = Math.max(0, Math.round(((window.outerWidth || 1280) - (window.innerWidth || 1280)) / 2));
            return {{
                x: Math.round((window.screenX || 0) + cLeft + r.left + ox),
                y: Math.round((window.screenY || 0) + cTop + r.top + oy),
                w: Math.round(r.width),
                h: Math.round(r.height)
            }};
        }}

        const host = window.location.hostname;
        const path = window.location.pathname;
        const bodyTxt = document.body ? (document.body.innerText || '') : '';

        if (!document.body || bodyTxt.includes('Приготовьтесь к приключениям')) {{
            return JSON.stringify({{ stage: 'SPLASH_LOADING', url: location.href }});
        }}

        // 1. Если мы на основном домене senkuro.com
        if (host.includes('senkuro.com')) {{
            if (path.includes('/auth/')) {{
                let authEnterTs = parseInt(sessionStorage.getItem('senkuro_auth_enter_ts') || '0', 10);
                if (!authEnterTs) {{
                    authEnterTs = Date.now();
                    sessionStorage.setItem('senkuro_auth_enter_ts', String(authEnterTs));
                }}
                if (bodyTxt.includes('Отсутствуют важные данные') || (Date.now() - authEnterTs > 12000)) {{
                    sessionStorage.removeItem('senkuro_auth_enter_ts');
                    sessionStorage.removeItem('senkuro_login_click_ts');
                    window.location.href = 'https://senkuro.com/';
                }}
                return JSON.stringify({{ stage: 'OAUTH_CALLBACK', url: location.href, txt: bodyTxt.slice(0, 120) }});
            }}
            sessionStorage.removeItem('senkuro_auth_enter_ts');

            const tok = getCookie('access_token');
            const loginBtn = Array.from(document.querySelectorAll('a, button')).find(el => {{
                const t = (el.innerText || el.textContent || '').trim();
                return t === 'Войти' || t === 'Вход';
            }});

            if (!loginBtn && tok && tok.length > 15) {{
                return JSON.stringify({{ stage: 'TOKEN_OK', token: tok, url: location.href }});
            }}

            if (loginBtn) {{
                const r = loginBtn.getBoundingClientRect();
                const bBox = toX11(r, r.width / 2, r.height / 2);
                const lastClickTs = parseInt(sessionStorage.getItem('senkuro_login_click_ts') || '0', 10);
                if (Date.now() - lastClickTs > 11000) {{
                    sessionStorage.setItem('senkuro_login_click_ts', String(Date.now()));
                    loginBtn.click();
                }}
                return JSON.stringify({{ stage: 'CLICK_LOGIN_BTN', url: location.href, btnBox: bBox }});
            }}

            if (tok && tok.length > 15) {{
                return JSON.stringify({{ stage: 'TOKEN_OK', token: tok, url: location.href }});
            }}
            return JSON.stringify({{ stage: 'SENKURO_WAIT', url: location.href, txt: bodyTxt.slice(0, 120) }});
        }}

        // 2. Если мы на домене авторизации sso.senkuro.org
        if (host.includes('sso.senkuro.')) {{
            // Перехватываем закрытый Shadow DOM Turnstile на случай интерактивного чекбокса
            if (!window.__skShadowHooked) {{
                window.__skShadowHooked = true;
                window.__tsHosts = window.__tsHosts || [];
                try {{
                    const origAttach = Element.prototype.attachShadow;
                    Element.prototype.attachShadow = function(init) {{
                        const sr = origAttach.call(this, init);
                        try {{ window.__tsHosts.push({{ host: this, shadow: sr }}); }} catch (e) {{}}
                        return sr;
                    }};
                }} catch (e) {{}}
            }}

            if (path.includes('/account') || bodyTxt.includes('Популярные действия') || bodyTxt.includes('Выйти')) {{
                window.location.href = TARGET_BM_URL;
                return JSON.stringify({{ stage: 'SSO_ACCOUNT_REDIRECT', url: location.href }});
            }}

            if (path.includes('/oauth/')) {{
                const allowBtn = Array.from(document.querySelectorAll('button, a')).find(el => {{
                    const t = (el.innerText || '').trim().toLowerCase();
                    return t.includes('разрешить') || t.includes('продолжить') || t.includes('авториз') || t.includes('allow');
                }});
                if (allowBtn) allowBtn.click();
                return JSON.stringify({{ stage: 'SSO_OAUTH_ALLOW', url: location.href }});
            }}

            const passInput = document.querySelector('input[type="password"]');
            if (passInput && passInput.offsetParent !== null) {{
                const allInputs = Array.from(document.querySelectorAll('input:not([type="hidden"]):not([type="password"]):not([type="checkbox"])')).filter(i => i.offsetParent !== null);
                const userInput = allInputs[0];

                if (userInput && userInput.value !== LOGIN_STR) {{
                    setNativeVal(userInput, LOGIN_STR);
                }}
                if (passInput.value !== PASS_STR) {{
                    setNativeVal(passInput, PASS_STR);
                }}

                const submitBtn = Array.from(document.querySelectorAll('button')).find(b => {{
                    const t = (b.innerText || b.textContent || '').trim().toLowerCase();
                    return t === 'войти' || t === 'продолжить' || t === 'вход' || t === 'login' || t.includes('войти');
                }}) || document.querySelector('button[type="submit"]');

                let tsToken = '';
                try {{
                    if (window.turnstile && typeof window.turnstile.getResponse === 'function') {{
                        tsToken = window.turnstile.getResponse() || '';
                    }}
                }} catch (e) {{}}

                const pr = passInput.getBoundingClientRect();
                const br = submitBtn ? submitBtn.getBoundingClientRect() : null;
                let tsBox = null;
                const cand = document.querySelector('.cf-turnstile, [id*="turnstile"], [class*="turnstile"], [class*="captcha"]');
                if (cand && cand.getBoundingClientRect().height > 20) {{
                    const cr = cand.getBoundingClientRect();
                    tsBox = toX11(cr, 28, cr.height / 2);
                }} else if (br && (br.top - pr.bottom) >= 45) {{
                    tsBox = toX11({{ left: pr.left, top: pr.bottom + 8, width: pr.width, height: br.top - pr.bottom - 16 }}, 28, (br.top - pr.bottom - 16) / 2);
                }}

                const lastSub = parseInt(sessionStorage.getItem('senkuro_sso_submit_ts') || '0', 10);
                let clickedSubmitNow = false;
                if (Date.now() - lastSub > 8500) {{
                    sessionStorage.setItem('senkuro_sso_submit_ts', String(Date.now()));
                    clickedSubmitNow = true;
                    setTimeout(() => {{
                        if (userInput && userInput.value !== LOGIN_STR) setNativeVal(userInput, LOGIN_STR);
                        if (passInput && passInput.value !== PASS_STR) setNativeVal(passInput, PASS_STR);
                        if (submitBtn) submitBtn.click();
                    }}, 750);
                }}

                return JSON.stringify({{
                    stage: 'SSO_FORM',
                    url: location.href,
                    uOk: !!(userInput && userInput.value === LOGIN_STR),
                    pOk: !!(passInput && passInput.value === PASS_STR),
                    uBox: userInput ? toX11(userInput.getBoundingClientRect(), 60, 18) : null,
                    pBox: toX11(pr, 60, 18),
                    btnBox: br ? toX11(br, br.width / 2, br.height / 2) : null,
                    tsBox: tsBox,
                    tsLen: (tsToken || '').length,
                    clickedSubmitNow: clickedSubmitNow,
                    hasCaptchaErr: bodyTxt.includes('Ошибка при прохождении капчи') || bodyTxt.includes('Что-то пошло не так'),
                    txt: bodyTxt.replace(/\s+/g, ' ').trim().slice(0, 180)
                }});
            }}
            return JSON.stringify({{ stage: 'SSO_WAIT_INPUTS', url: location.href, txt: bodyTxt.replace(/\s+/g, ' ').trim().slice(0, 140) }});
        }}

        return JSON.stringify({{ stage: 'OTHER', url: location.href }});
    }})();
    """

    target_url = "https://senkuro.com/"
    # Открываем сначала главную https://senkuro.com/ для чистого входа (без экрана 401!)
    # Флаги запуска один в один из рабочего Senkuro_Kaggle_Server_v6_5_Ready.ipynb!
    args = [
        chrome_bin,
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--test-type",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--password-store=basic",
        "--disable-save-password-bubble",
        "--disable-features=PasswordManagerOnboarding,PasswordImport",
        "--disable-SmoothScrolling",
        "--wm-window-animations-disabled",
        "--animation-duration-scale=0",
        f"--user-data-dir={prof_dir}",
        f"--disk-cache-dir={cache_dir}",
        "--disk-cache-size=67108864",
        f"--remote-debugging-port={cdp_port}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--window-position=0,0",
        "--window-size=1280,900",
    ]
    if proxy_url:
        args.extend([f"--proxy-server={proxy_url}", "--proxy-bypass-list=<-loopback>"])
    args.append(target_url)

    log_debug(f"[NATIVE CHROME] {aid}: старт изолированного профиля {prof_dir.name} (CDP=:{cdp_port}, proxy={proxy_url}) -> {target_url}")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    access_token_found: Optional[str] = None
    cdp_cookies: list[dict] = []
    err_png: Optional[bytes] = None
    last_diag_str = ""
    last_ws_url = ""

    clicked_ts_time = 0.0
    clicked_btn_time = 0.0

    try:
        start_t = time.time()
        while time.time() - start_t < 45.0 and not FARM_STOP_FLAG:
            if proc.poll() is not None:
                log_debug(f"[NATIVE CHROME] {aid}: процесс Chrome завершился (код {proc.poll()})")
                break
            time.sleep(1.2)
            if FARM_STOP_FLAG:
                break

            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{cdp_port}/json/list", timeout=1.5) as r:
                    tabs = json.loads(r.read().decode("utf-8", errors="ignore"))
            except Exception:
                continue

            page_tabs = [t for t in tabs if t.get("type") == "page" and "senkuro" in str(t.get("url", ""))]
            if not page_tabs:
                page_tabs = [t for t in tabs if t.get("type") == "page"]
            if not page_tabs:
                continue

            tab = page_tabs[0]
            ws_u = str(tab.get("webSocketDebuggerUrl") or "")
            if not ws_u:
                continue
            last_ws_url = ws_u

            eval_res = _cdp_ws_call_sync(
                ws_u,
                "Runtime.evaluate",
                {"expression": sso_eval_js, "returnByValue": True},
                timeout_sec=3.0,
            )
            val_str = str(((eval_res.get("result") or {}).get("value")) or "")
            if not val_str:
                continue

            if val_str != last_diag_str:
                last_diag_str = val_str
                log_debug(f"[NATIVE STEP] {aid}: {val_str}")

            try:
                st = json.loads(val_str)
            except Exception:
                continue

            stage = st.get("stage")
            if stage == "TOKEN_OK" and st.get("token"):
                access_token_found = str(st["token"]).strip()
                log_debug(f"[NATIVE CHROME SUCCESS] {aid}: вход выполнен, получен access_token (длина={len(access_token_found)})!")
                break

            if stage == "CLICK_LOGIN_BTN" and st.get("btnBox") and (time.time() - clicked_btn_time > 4.5):
                clicked_btn_time = time.time()
                lb = st["btnBox"]
                _run_xdotool(["mousemove", "--sync", str(lb["x"]), str(lb["y"]), "sleep", "0.12", "click", "1"])

            if stage == "SSO_FORM":
                # Если есть бокс капчи Turnstile — дополнительно кликаем системной мышью X11 (xdotool)
                ts_box = st.get("tsBox")
                if ts_box and int(st.get("tsLen") or 0) == 0 and (time.time() - clicked_ts_time > 5.0):
                    clicked_ts_time = time.time()
                    _run_xdotool(["mousemove", "--sync", str(ts_box["x"]), str(ts_box["y"]), "sleep", "0.12", "click", "1"])
                btn_box = st.get("btnBox")
                if btn_box and st.get("uOk") and st.get("pOk") and (time.time() - clicked_btn_time > 8.5):
                    clicked_btn_time = time.time()
                    _run_xdotool(["mousemove", "--sync", str(btn_box["x"]), str(btn_box["y"]), "sleep", "0.12", "click", "1"])

        if last_ws_url and not FARM_STOP_FLAG:
            ck_res = _cdp_ws_call_sync(last_ws_url, "Network.getAllCookies", {}, timeout_sec=3.5)
            cdp_cookies = ck_res.get("cookies") or []
            for c in cdp_cookies:
                if c.get("name") == "access_token" and c.get("value") and len(str(c["value"])) > 15:
                    access_token_found = str(c["value"])
            if not access_token_found:
                import base64
                sc_res = _cdp_ws_call_sync(last_ws_url, "Page.captureScreenshot", {"format": "png"}, timeout_sec=4.0)
                if sc_res.get("data"):
                    err_png = base64.b64decode(sc_res["data"])
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    return access_token_found, cdp_cookies, err_png, last_diag_str


async def ensure_logged_in(context: BrowserContext, acc: dict) -> tuple[Page, Optional[dict]]:
    page = await context.new_page()
    ACTIVE_BROWSER_PAGES[acc["id"]] = page
    intercepted_user: dict[str, Any] = {}

    async def on_gql_or_sso_resp(resp):
        u_str = resp.url
        if "graphql" in u_str and resp.request.method == "POST":
            try:
                j = await resp.json()
                d = j.get("data") or {}
                vw = d.get("viewer") or {}
                u = vw.get("user") if isinstance(vw.get("user"), dict) else (vw if isinstance(vw, dict) and vw.get("id") else None)
                if isinstance(u, dict) and u.get("id"):
                    intercepted_user.update(u)
            except Exception:
                pass

    page.on("response", on_gql_or_sso_resp)

    target_start_url = "https://senkuro.com/"
    log_debug(f"[AUTH START] {acc['id']}: открываю главную {target_start_url} для проверки входа")
    try:
        await page.goto(target_start_url, wait_until="domcontentloaded", timeout=40000)
    except Exception as e:
        log_debug(f"[AUTH GOTO WARN] {acc['id']}: {e}")

    for _ in range(15):
        await page.wait_for_timeout(800)
        try:
            b_txt = await page.evaluate("() => document.body ? (document.body.innerText || '') : ''")
            if b_txt and "Приготовьтесь к приключениям" not in b_txt:
                break
        except Exception:
            pass

    user_obj = await check_is_authenticated_on_senkuro(page, acc["id"], intercepted_user)
    if user_obj:
        log_debug(f"[AUTH ALREADY OK] {acc['id']}: уже авторизован (id={user_obj.get('id')})")
        await context.storage_state(path=str(get_session_file(acc["id"])))
        return page, user_obj

    if not acc.get("password"):
        acc["password"] = get_secret_password(int(acc.get("idx", 1)), str(acc.get("id", "")), str(acc.get("login", "")))
    if not acc.get("login") or not acc.get("password"):
        log_debug(
            f"[AUTH NO SECRET] {acc['id']}: login_present={bool(acc.get('login'))}, pass_present={bool(acc.get('password'))}! Проверьте секрет SENKURO_PASSWORDS."
        )
        return page, None

    proxy_port = 25340 + int(acc.get("idx", 1))
    proxy_url = f"http://127.0.0.1:{proxy_port}" if is_local_port_open(proxy_port) else None
    log_debug(f"[AUTH LOGIN] {acc['id']}: выполняю нативный вход без Playwright ({acc['login']})...")

    token_val, native_cookies, err_png, sso_diag = await asyncio.to_thread(login_via_native_chrome_sync, acc, proxy_url)

    if token_val or native_cookies:
        pw_cookies = []
        if token_val:
            pw_cookies.append(
                {
                    "name": "access_token",
                    "value": token_val,
                    "domain": "senkuro.com",
                    "path": "/",
                    "httpOnly": False,
                    "secure": True,
                    "sameSite": "Lax",
                }
            )
            pw_cookies.append(
                {
                    "name": "access_token",
                    "value": token_val,
                    "domain": ".senkuro.com",
                    "path": "/",
                    "httpOnly": False,
                    "secure": True,
                    "sameSite": "Lax",
                }
            )
        for c in native_cookies:
            if c.get("name") and c.get("value") and c.get("domain"):
                pw_cookies.append(
                    {
                        "name": str(c["name"]),
                        "value": str(c["value"]),
                        "domain": str(c["domain"]),
                        "path": str(c.get("path") or "/"),
                        "httpOnly": bool(c.get("httpOnly", False)),
                        "secure": bool(c.get("secure", True)),
                    }
                )
        try:
            await context.add_cookies(pw_cookies)
        except Exception as e:
            log_debug(f"[ADD COOKIES WARN] {acc['id']}: {e}")

        try:
            await page.goto(target_start_url, wait_until="domcontentloaded", timeout=35000)
            for _ in range(12):
                await page.wait_for_timeout(700)
                b_t = await page.evaluate("() => document.body ? (document.body.innerText || '') : ''")
                if b_t and "Приготовьтесь к приключениям" not in b_t:
                    break
            u_final = await check_is_authenticated_on_senkuro(page, acc["id"], intercepted_user)
            if u_final:
                log_debug(f"[AUTH SUCCESS] {acc['id']}: вход успешно подтверждён (id={u_final.get('id')})!")
                await context.storage_state(path=str(get_session_file(acc["id"])))
                return page, u_final
        except Exception as e:
            log_debug(f"[AUTH VERIFY WARN] {acc['id']}: {e}")

    log_debug(f"[AUTH FAILED DIAG] {acc['id']}: sso_diag={sso_diag}")
    if DEBUG_MODE and err_png:
        try:
            await asyncio.to_thread(
                send_tg_photo_bytes,
                err_png,
                f"⚠️ <b>Скриншот экрана входа SSO ({acc['id']}):</b>\n"
                f"📄 Диагностика: <code>{sso_diag[:260]}</code>",
                False,
            )
        except Exception as e:
            log_debug(f"[AUTH ERR PHOTO WARN] {e}")

    return page, None


def extract_card_title(card_obj: dict) -> str:
    titles = card_obj.get("titles") or []
    for t in titles:
        if t.get("lang") in ("RU", "ru") and (t.get("content") or t.get("text")):
            return (t.get("content") or t.get("text")).strip()
    if titles:
        return (titles[0].get("content") or titles[0].get("text") or "Карта").strip()
    return card_obj.get("slug") or "Карта"


async def fetch_all_user_cards_gql(page: Page, user_id: str, modifier_val: Optional[int] = None) -> list[dict]:
    all_nodes = []
    after_cursor = None
    seen_cursors = set()

    for _ in range(60):
        vars_dict: dict[str, Any] = {"userId": user_id}
        if modifier_val is not None:
            vars_dict["modifier"] = {"include": [modifier_val]}
        if after_cursor:
            vars_dict["after"] = after_cursor

        res = await gql_call(page, GQL_FETCH_USER_CARDS_FULL, vars_dict, "fetchUserCards")
        uc = (res.get("data") or {}).get("userCards")
        if not uc:
            break
        edges = uc.get("edges") or []
        for edge in edges:
            node = edge.get("node")
            if node:
                all_nodes.append(node)

        pinfo = uc.get("pageInfo") or {}
        end_cur = pinfo.get("endCursor")
        if pinfo.get("hasNextPage") and end_cur and end_cur not in seen_cursors:
            seen_cursors.add(end_cur)
            after_cursor = end_cur
        else:
            break

    return all_nodes


# ==============================================================================
# 6. СЦЕНАРИЙ 1: АКТИВАЦИЯ ПРОМОКОДА С ЖЕСТКОЙ ПРОВЕРКОЙ БАЛАНСА ДО И ПОСЛЕ
# ==============================================================================

async def run_promo_code_activation(promo_code: str) -> None:
    global FARM_STOP_FLAG
    FARM_STOP_FLAG = False
    code_clean = (promo_code or "").strip().upper()
    if not code_clean:
        send_tg_message("⚠️ Промокод не указан. Нажмите «🎟 Ввести промокод» и отправьте код ответным сообщением.")
        return

    send_tg_message(
        f"⏳ Запускаю 8 изолированных IP-туннеля, вхожу на 8 аккаунтов и активирую промокод <code>{code_clean}</code>...",
        add_keyboard=False,
    )

    proxy_mgr = AccountProxyManager()
    report_lines = [f"🎟 <b>Отчёт по активации промокода <code>{code_clean}</code>:</b>\n"]
    success_count = 0

    try:
        async with async_playwright() as p:
            browser = await launch_senkuro_browser(p)
            for acc in FARM_ACCOUNTS:
                proxy_url = await asyncio.to_thread(proxy_mgr.start_account_proxy, acc)
                ip_used = proxy_mgr.active_ips.get(acc["acc_id"], "прямой")
                log_debug(f"[BALANCE STEP] #{acc['idx']}/8 {acc['id']} -> IP: {ip_used}")
                send_tg_message(f"⏳ <b>[{acc['idx']}/8] {acc['id']}</b> (IP: <code>{ip_used}</code>): проверяю вход и баланс...", add_keyboard=False)
                context = await create_account_context(browser, acc, proxy_url)
                try:
                    page, user_obj = await ensure_logged_in(context, acc)
                    if not user_obj:
                        report_lines.append(f"❌ <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): не удалось войти в аккаунт\n")
                        continue

                    before_pts = await get_fresh_points_balance(page, acc["id"])

                    res = await gql_call(
                        page,
                        GQL_REDEEM_PROMO,
                        {"input": {"code": code_clean}},
                        "redeemRedemption",
                    )
                    errors = res.get("errors") or []
                    payload = (res.get("data") or {}).get("redeemRedemption")

                    if not payload and errors:
                        try:
                            await page.evaluate(
                                """() => {
                                    const btns = Array.from(document.querySelectorAll('button, a'));
                                    const promoBtn = btns.find(b => (b.innerText || '').includes('Активировать промокод'));
                                    if (promoBtn) promoBtn.click();
                                }"""
                            )
                            await page.wait_for_timeout(1000)
                            inp = page.locator("input[placeholder*='Введите код']").first
                            if await inp.count() > 0:
                                await inp.fill(code_clean)
                                await page.wait_for_timeout(400)
                                ok_btn = page.locator("button:has-text('Окей')").first
                                if await ok_btn.count() > 0:
                                    await ok_btn.click()
                                    await page.wait_for_timeout(1500)
                                    await page.mouse.click(10, 10)
                        except Exception:
                            pass

                    await page.wait_for_timeout(1500)
                    after_pts = await get_fresh_points_balance(page, acc["id"])
                    diff_pts = after_pts - before_pts

                    if diff_pts > 0:
                        success_count += 1
                        report_lines.append(
                            f"✅ <b>{acc['id']}</b> (IP: <code>{ip_used}</code>) — <b>УСПЕШНО НАЧИСЛЕНО!</b>\n"
                            f"   • Было монет: <code>{before_pts}</code> 🪙\n"
                            f"   • Пришло с промокода: <b>+{diff_pts} сенкоинов</b>\n"
                            f"   • 💰 <b>Финальный баланс: {after_pts} 🪙</b>\n"
                        )
                    elif payload and int(payload.get("points") or 0) > 0:
                        pts_claimed = int(payload.get("points"))
                        final_calc = max(after_pts, before_pts + pts_claimed)
                        success_count += 1
                        report_lines.append(
                            f"✅ <b>{acc['id']}</b> (IP: <code>{ip_used}</code>) — <b>УСПЕШНО НАЧИСЛЕНО!</b>\n"
                            f"   • Было монет: <code>{before_pts}</code> 🪙\n"
                            f"   • Пришло с промокода: <b>+{pts_claimed} сенкоинов</b>\n"
                            f"   • 💰 <b>Финальный баланс: {final_calc} 🪙</b>\n"
                        )
                    else:
                        err_reason = errors[0].get("message", "Код уже был активирован или недействителен") if errors else "Баланс монет не увеличился"
                        report_lines.append(
                            f"⚠️ <b>{acc['id']}</b> (IP: <code>{ip_used}</code>) — <b>НЕ НАЧИСЛЕНО</b> ({err_reason})\n"
                            f"   • Баланс не изменился: было <code>{before_pts}</code> 🪙 ➔ осталось <b>{after_pts} 🪙</b>\n"
                        )

                    await context.storage_state(path=str(get_session_file(acc["id"])))
                finally:
                    await context.close()
                await asyncio.sleep(2.5)
            await browser.close()
    finally:
        proxy_mgr.stop_all()

    report_lines.insert(1, f"📊 Итог проверки: монеты реально увеличились на <b>{success_count} из 8</b> аккаунтов.\n")
    send_tg_message("\n".join(report_lines), add_keyboard=True)


# ==============================================================================
# 7. СЦЕНАРИЙ 2: ПРОВЕРКА БАЛАНСА МОНЕТ (4 АККА) И КРУТКА ПАКОВ «ХАРДКОР»
# ==============================================================================

async def run_check_coins_balance() -> None:
    global FARM_STOP_FLAG
    FARM_STOP_FLAG = False
    """Проверяет баланс сенкоинов на всех 8 фарм-аккаунтах и возвращает базовую панель кнопок."""
    send_tg_message("🪙 Вхожу на 8 фарм-аккаунтов под своими IP и проверяю баланс сенкоинов...", add_keyboard=False)
    proxy_mgr = AccountProxyManager()
    lines = ["🪙 <b>Баланс сенкоинов на 8 фарм-аккаунтах:</b>\n"]
    total_coins = 0
    total_packs_possible = 0

    try:
        async with async_playwright() as p:
            browser = await launch_senkuro_browser(p)
            for acc in FARM_ACCOUNTS:
                proxy_url = await asyncio.to_thread(proxy_mgr.start_account_proxy, acc)
                ip_used = proxy_mgr.active_ips.get(acc["acc_id"], "прямой")
                if FARM_STOP_FLAG:
                    break
                log_debug(f"[BALANCE STEP] #{acc['idx']}/8 {acc['id']} -> IP: {ip_used}")
                send_tg_message(f"⏳ <b>[{acc['idx']}/8] {acc['id']}</b> (IP: <code>{ip_used}</code> ✅): вхожу в изолированный профиль Chrome и проверяю баланс...", add_keyboard=False)
                context = await create_account_context(browser, acc, proxy_url)
                try:
                    page, user_obj = await ensure_logged_in(context, acc)
                    if not user_obj:
                        lines.append(f"❌ <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): не удалось войти")
                        continue
                    pts = await get_fresh_points_balance(page, acc["id"])
                    packs_avail = pts // HARDCORE_PACK_COST
                    total_coins += pts
                    total_packs_possible += packs_avail
                    pack_str = f"✅ хватает на <b>{packs_avail}</b> пак(ов) Хардкор" if packs_avail > 0 else f"⏳ не хватает {HARDCORE_PACK_COST - pts} 🪙 до пака (нужно 480)"
                    lines.append(f"👤 <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): <b>{pts} 🪙</b> — {pack_str}")
                    await context.storage_state(path=str(get_session_file(acc["id"])))
                finally:
                    await context.close()
                await asyncio.sleep(2.5)
            await browser.close()
    finally:
        proxy_mgr.stop_all()

    lines.append(f"\n💰 <b>Всего монет на 8 аккаунтах:</b> {total_coins} 🪙 (доступно прокруток Хардкор: <b>{total_packs_possible}</b>)")
    full_msg = "\n".join(lines)
    send_tg_message(full_msg, add_keyboard=True)
    if DEBUG_MODE:
        upload_debug_log_to_github_noop("balance_check")
        if "не удалось войти" in full_msg:
            send_full_debug_log_to_user("Авто-лог диагностики входа (Баланс)")


def choose_best_unlocked_card_index(result_cards: list[dict], has_premium: bool = False) -> tuple[int, dict]:
    unlocked_limit = len(result_cards) if has_premium else min(2, len(result_cards))
    candidates = []
    for idx in range(unlocked_limit):
        c = result_cards[idx]
        rank_str = str(c.get("rank") or "F").upper()
        score = RANK_PRIORITY.get(rank_str, 1)
        anim_bonus = 1 if c.get("animated") else 0
        candidates.append((score, anim_bonus, -idx, idx, c))

    if not candidates:
        return 0, (result_cards[0] if result_cards else {})

    candidates.sort(reverse=True)
    _, _, _, best_idx, best_card = candidates[0]
    return best_idx, best_card


async def roll_hardcore_packs_for_account(page: Page, acc: dict, user_obj: dict) -> list[str]:
    logs: list[str] = []
    user_id = await ensure_real_user_id(page, acc["id"], str(user_obj.get("id") or ""))
    try:
        await page.goto("https://senkuro.com/packs/for-hardcore-gamers", wait_until="domcontentloaded", timeout=35000)
    except Exception:
        pass
    await asyncio.sleep(random.uniform(2.5, 4.0))

    before_points = await get_fresh_points_balance(page, acc["id"])
    has_premium = int(user_obj.get("subscriptionTier") or 0) > 0

    pack_res = await gql_call(page, GQL_FETCH_PACK_AND_PENDING, {"slug": HARDCORE_PACK_SLUG}, "fetchPackAndPending")
    data = pack_res.get("data") or {}
    pack = data.get("cardPack")
    if not pack:
        logs.append("⚠️ Пак «Для хардкорщиков» не найден на сайте")
        return logs

    pack_id = pack["id"]
    pack_cost = int(pack.get("points") or HARDCORE_PACK_COST)
    pending_opens = list(data.get("viewerPendingCardPackOpens") or [])

    chosen_cards_summary: list[str] = []

    if pending_opens:
        opens_input = []
        for op in pending_opens:
            rcards = op.get("resultCards") or []
            if not rcards:
                continue
            best_idx, best_card = choose_best_unlocked_card_index(rcards, has_premium=has_premium)
            opens_input.append(
                {
                    "openId": op["id"],
                    "packId": (op.get("pack") or {}).get("id") or pack_id,
                    "indexes": [best_idx],
                }
            )
            r_badge = RANK_BADGE.get(str(best_card.get("rank", "F")).upper(), best_card.get("rank", "F"))
            c_title = extract_card_title(best_card)
            chosen_cards_summary.append(f"Забрал: <b>{r_badge} «{c_title}»</b> (из незавершенного открытия, слот #{best_idx + 1})")

        if opens_input:
            await asyncio.sleep(random.uniform(2.2, 3.6))
            await gql_call(
                page,
                GQL_BULK_CHOOSE_PACK_OPEN,
                {"input": {"opens": opens_input}},
                "bulkChooseCardPackOpen",
            )
            await asyncio.sleep(random.uniform(2.0, 3.2))

    rolls_available = before_points // pack_cost
    if rolls_available <= 0 and not chosen_cards_summary:
        logs.append(f"недостаточно монет для прокрутки (сейчас <b>{before_points} 🪙</b>, нужно <b>{pack_cost} 🪙</b>)")
        return logs

    for roll_num in range(1, rolls_available + 1):
        if FARM_STOP_FLAG:
            logs.append("🛑 Прокрутка остановлена пользователем")
            break

        # Человеческая пауза перед нажатием кнопки «Открыть пак за 480»
        await asyncio.sleep(random.uniform(2.5, 4.2))
        open_res = await gql_call(
            page,
            GQL_OPEN_CARD_PACK,
            {
                "input": {
                    "packId": pack_id,
                    "userId": user_id,
                    "currency": "POINTS",
                    "rolls": 1,
                }
            },
            "openCardPack",
        )
        errs = open_res.get("errors") or []
        opens_list = ((open_res.get("data") or {}).get("openCardPack") or {}).get("opens") or []
        if not opens_list:
            if errs:
                logs.append(f"остановка на крутке #{roll_num}: {errs[0].get('message')}")
            break

        # Человеческая задержка (3.8–5.8 сек) на анимацию открытия пака и осмотр выпавших карт перед выбором!
        await asyncio.sleep(random.uniform(3.8, 5.8))

        choose_payload = []
        for op in opens_list:
            rcards = op.get("resultCards") or []
            if not rcards:
                continue
            best_idx, best_card = choose_best_unlocked_card_index(rcards, has_premium=has_premium)
            choose_payload.append(
                {
                    "openId": op["id"],
                    "packId": pack_id,
                    "indexes": [best_idx],
                }
            )
            slot1_desc = f"1-я: {rcards[0].get('rank')} «{extract_card_title(rcards[0])}»" if len(rcards) > 0 else "-"
            slot2_desc = f"2-я: {rcards[1].get('rank')} «{extract_card_title(rcards[1])}»" if len(rcards) > 1 else "-"
            slot3_desc = f"3-я (🔒): {rcards[2].get('rank')}" if len(rcards) > 2 else ""

            r_badge = RANK_BADGE.get(str(best_card.get("rank", "F")).upper(), best_card.get("rank", "F"))
            c_title = extract_card_title(best_card)
            chosen_cards_summary.append(
                f"Крутка #{roll_num}: выпало [{slot1_desc} | {slot2_desc} | {slot3_desc}] ➔ "
                f"✅ <b>Забрал: {r_badge} «{c_title}»</b> (слот #{best_idx + 1})"
            )

        if choose_payload:
            await gql_call(
                page,
                GQL_BULK_CHOOSE_PACK_OPEN,
                {"input": {"opens": choose_payload}},
                "bulkChooseCardPackOpen",
            )
            # Пауза после выбора карты, как у живого человека
            await asyncio.sleep(random.uniform(2.2, 3.8))

    await page.wait_for_timeout(1200)
    after_points = await get_fresh_points_balance(page, acc["id"])

    if chosen_cards_summary:
        logs.append(
            f"было <code>{before_points}</code> 🪙 ➔ прокручено паков: <b>{len(chosen_cards_summary)}</b> ➔ "
            f"💰 <b>Осталось монет: {after_points} 🪙</b>"
        )
        for item in chosen_cards_summary:
            logs.append(f"   • {item}")
    return logs


async def run_all_packs_opening() -> None:
    global FARM_STOP_FLAG
    FARM_STOP_FLAG = False
    send_tg_message(
        "🎰 Открываю 8 изолированных профиля Chrome под своими IP и кручу паки «Хардкор» (480 🪙) с человеческими паузами...",
        add_keyboard=False,
    )
    proxy_mgr = AccountProxyManager()
    report_lines = ["🎴 <b>Статистика прокрутки паков «Для хардкорщиков» (480 🪙):</b>\n"]

    try:
        async with async_playwright() as p:
            browser = await launch_senkuro_browser(p)
            open_contexts: list[tuple[dict, BrowserContext, Page, Optional[dict], str]] = []
            try:
                for acc in FARM_ACCOUNTS:
                    if FARM_STOP_FLAG:
                        break
                    proxy_url = await asyncio.to_thread(proxy_mgr.start_account_proxy, acc)
                    ip_used = proxy_mgr.active_ips.get(acc["acc_id"], "прямой")
                    log_debug(f"[PACKS STEP] #{acc['idx']}/8 {acc['id']} -> IP: {ip_used}")
                    context = await create_account_context(browser, acc, proxy_url)
                    page, user_obj = await ensure_logged_in(context, acc)
                    open_contexts.append((acc, context, page, user_obj, ip_used))

                for acc, context, page, user_obj, ip_used in open_contexts:
                    if FARM_STOP_FLAG:
                        break
                    if not user_obj:
                        report_lines.append(f"❌ <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): ошибка входа\n")
                        continue
                    send_tg_message(f"🎴 <b>[{acc['idx']}/8] {acc['id']}</b> (IP: <code>{ip_used}</code> ✅): кручу паки «Хардкор»...", add_keyboard=False)
                    acc_logs = await roll_hardcore_packs_for_account(page, acc, user_obj)
                    report_lines.append(f"👤 <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): " + "\n".join(acc_logs) + "\n")
                    await context.storage_state(path=str(get_session_file(acc["id"])))
                    await asyncio.sleep(random.uniform(3.0, 4.8))
            finally:
                ACTIVE_BROWSER_PAGES.clear()
                for _, context, _, _, _ in open_contexts:
                    try:
                        await context.close()
                    except Exception:
                        pass
            await browser.close()
    finally:
        proxy_mgr.stop_all()

    send_tg_message("\n".join(report_lines), add_keyboard=True)


# ==============================================================================
# 8. СЦЕНАРИЙ 3: УМНАЯ ПЕРЕПЛАВКА (КУЗНЯ) + МЕЖАККАУНТНЫЙ ТРЕЙД + СБОР НА ОСНОВУ
# ==============================================================================

TRADE_RANDOM_MESSAGES = [
    "gl hf",
    "nice cards",
    "thanks",
    "for craft",
    "gg wp",
    "trade",
    "ty bro",
    "good luck",
]


def format_reset_at_human(reset_at_val: Any) -> str:
    if not reset_at_val:
        return "неизвестно"
    try:
        from datetime import datetime, timezone
        s = str(reset_at_val).strip()
        if s.isdigit():
            ts = int(s)
            if ts > 10_000_000_000:
                ts = ts // 1000
            diff_sec = max(0, int(ts - time.time()))
        else:
            s_iso = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(s_iso)
            diff_sec = max(0, int(dt.timestamp() - time.time()))
        h = diff_sec // 3600
        m = (diff_sec % 3600) // 60
        if h > 0:
            return f"через {h} ч. {m} мин."
        return f"через {max(1, m)} мин."
    except Exception:
        return str(reset_at_val)[:19]


async def accept_whitelisted_incoming_trades(page: Page, acc_slug: str, user_id: str) -> list[str]:
    accepted_logs: list[str] = []
    res = await gql_call(
        page,
        GQL_FETCH_CARD_TRADES,
        {"userId": user_id, "status": "PENDING"},
        "fetchCardTrades",
    )
    edges = ((res.get("data") or {}).get("cardTrades") or {}).get("edges") or []
    for edge in edges:
        if FARM_STOP_FLAG:
            break
        node = edge.get("node") or {}
        if node.get("status") != "PENDING" or not node.get("viewerCanAccept"):
            continue

        trade_id = node.get("id")
        source_user = node.get("source") or {}
        source_slug = str(source_user.get("slug") or "").strip().lower()
        req_items = node.get("request") or []
        offer_items = node.get("offer") or []

        if source_slug not in ALLOWED_TRADE_SLUGS:
            log_debug(f"[SECURITY BLOCK] {acc_slug}: проигнорирован входящий трейд {trade_id} от ЧУЖОГО игрока '{source_slug}'!")
            continue

        if req_items and source_slug not in ALLOWED_TRADE_SLUGS:
            continue

        # Человеческая пауза перед принятием трейда
        await asyncio.sleep(random.uniform(3.2, 5.2))
        acc_res = await gql_call(
            page,
            GQL_ACCEPT_CARD_TRADE,
            {"input": {"tradeId": trade_id}},
            "acceptCardTrade",
        )
        ok = ((acc_res.get("data") or {}).get("acceptCardTrade") or {}).get("success")
        if ok:
            total_qty = sum(int(x.get("quantity") or 1) for x in offer_items)
            accepted_logs.append(f"принят трейд от <b>{source_slug}</b> ({total_qty} шт.)")
    return accepted_logs


def expand_craftable_cards_by_rank(user_cards_nodes: list[dict]) -> dict[str, list[dict]]:
    by_rank: dict[str, list[dict]] = defaultdict(list)
    for node in user_cards_nodes:
        if node.get("shard") or int(node.get("modifier") or 0) != 0:
            continue
        if node.get("locked"):
            continue
        card = node.get("card") or {}
        if card.get("animated"):
            continue
        rank = str(card.get("rank") or "").upper()
        if rank not in FORGE_UPGRADE_CHAIN:
            continue
        qty = int(node.get("quantity") or 1)
        for _ in range(qty):
            by_rank[rank].append(
                {
                    "cardId": card.get("id") or node.get("cardId"),
                    "modifier": int(node.get("modifier") or 0),
                    "rank": rank,
                    "title": extract_card_title(card),
                    "slug": card.get("slug") or "",
                }
            )
    return by_rank


def compress_card_units_for_gql(units: list[dict]) -> list[dict]:
    counts: dict[tuple[str, int], int] = Counter()
    for u in units:
        counts[(str(u["cardId"]), int(u.get("modifier") or 0))] += 1
    return [
        {"cardId": cid, "modifier": mod, "quantity": qty}
        for (cid, mod), qty in counts.items()
    ]


def format_text_only_inventory_summary(cards_nodes: list[dict], shards_nodes: list[dict]) -> str:
    card_counts: Counter = Counter()
    for n in cards_nodes:
        if n.get("locked"):
            continue
        r = str((n.get("card") or {}).get("rank") or "?").upper()
        card_counts[r] += int(n.get("quantity") or 1)

    shard_counts: Counter = Counter()
    for n in shards_nodes:
        if n.get("locked"):
            continue
        r = str((n.get("card") or {}).get("rank") or "?").upper()
        shard_counts[r] += int(n.get("quantity") or 1)

    c_parts = [f"<b>{card_counts[r]}</b> {RANK_BADGE.get(r, r)}" for r in RANK_ORDER if card_counts.get(r, 0) > 0]
    s_parts = [f"<b>{shard_counts[r]}</b> {RANK_BADGE.get(r, r)}" for r in RANK_ORDER if shard_counts.get(r, 0) > 0]

    c_str = ", ".join(c_parts) if c_parts else "нет"
    s_str = ", ".join(s_parts) if s_parts else "нет"
    return f"Карты: {c_str} | Осколки: {s_str}"


async def refresh_farm_state(state_map: dict[str, dict]) -> None:
    for aid, st in state_map.items():
        if FARM_STOP_FLAG:
            break
        page: Page = st["page"]
        uid: str = st["user_id"]

        acc_trades = await accept_whitelisted_incoming_trades(page, aid, uid)
        if acc_trades:
            st["logs"].extend(acc_trades)

        slots_res = await gql_call(page, GQL_FETCH_FORGE_SLOTS, {"mode": "UPGRADE"}, "fetchForgeCardsSlots")
        slots_obj = (slots_res.get("data") or {}).get("forgeCardsSlots") or {}
        st["available_slots"] = int(slots_obj.get("available") or 0)
        st["used_slots"] = int(slots_obj.get("used") or 0)
        st["reset_at"] = slots_obj.get("resetAt")

        st["cards_nodes"] = await fetch_all_user_cards_gql(page, uid, modifier_val=0)
        st["shards_nodes"] = await fetch_all_user_cards_gql(page, uid, modifier_val=1)
        st["craftable_by_rank"] = expand_craftable_cards_by_rank(st["cards_nodes"])


async def forge_local_triples_on_account(st: dict) -> int:
    page: Page = st["page"]
    forged_count = 0

    while st["available_slots"] > 0 and not FARM_STOP_FLAG:
        did_forge_in_pass = False
        for r in FORGE_UPGRADE_CHAIN:
            pool = st["craftable_by_rank"].get(r, [])
            if len(pool) >= 3 and st["available_slots"] > 0:
                triple = pool[:3]
                gql_cards = compress_card_units_for_gql(triple)
                # Человеческая задержка (3.5–5.5 сек) на выбор 3 карт и переплавку в Кузне!
                await asyncio.sleep(random.uniform(3.5, 5.5))
                res = await gql_call(
                    page,
                    GQL_FORGE_CARDS,
                    {"input": {"mode": "UPGRADE", "cards": gql_cards}},
                    "forgeCards",
                )
                forge_data = (res.get("data") or {}).get("forgeCards")
                if not forge_data:
                    errs = res.get("errors") or []
                    err_txt = errs[0].get("message", "ошибка кузни") if errs else "ошибка кузни"
                    st["logs"].append(f"⚠️ Ошибка переплавки 3×{r}: {err_txt}")
                    st["available_slots"] = 0
                    break

                st["available_slots"] -= 1
                st["used_slots"] += 1
                forged_count += 1
                did_forge_in_pass = True

                new_cards = forge_data.get("newCards") or forge_data.get("addUserCards") or []
                if new_cards:
                    nc = (new_cards[0].get("card") or {})
                    new_rank = str(nc.get("rank") or NEXT_FORGE_RANK[r]).upper()
                    new_title = extract_card_title(nc)
                    st["logs"].append(f"⚒️ Переплавлено 3×{r} ➡️ <b>{RANK_BADGE.get(new_rank, new_rank)} «{new_title}»</b>")
                else:
                    nxt = NEXT_FORGE_RANK[r]
                    st["logs"].append(f"⚒️ Переплавлено 3×{r} ➡️ <b>1×{nxt}</b>")

                await asyncio.sleep(random.uniform(2.0, 3.2))
                st["cards_nodes"] = await fetch_all_user_cards_gql(page, st["user_id"], modifier_val=0)
                st["craftable_by_rank"] = expand_craftable_cards_by_rank(st["cards_nodes"])
                break

        if not did_forge_in_pass:
            break

    return forged_count


async def run_smart_forge_and_trade_pipeline() -> None:
    global FARM_STOP_FLAG
    FARM_STOP_FLAG = False
    send_tg_message(
        "⚒️ Запускаю умную Кузницу («Переплавка» 3 в 1) и межаккаунтный обмен на 8 аккаунтах с человеческими задержками...",
        add_keyboard=False,
    )

    proxy_mgr = AccountProxyManager()
    state_map: dict[str, dict] = {}

    try:
        async with async_playwright() as p:
            browser = await launch_senkuro_browser(p)
            contexts: list[BrowserContext] = []

            try:
                for acc in FARM_ACCOUNTS:
                    if FARM_STOP_FLAG:
                        break
                    proxy_url = await asyncio.to_thread(proxy_mgr.start_account_proxy, acc)
                    ip_used = proxy_mgr.active_ips.get(acc["acc_id"], "прямой")
                    log_debug(f"[FORGE STEP] #{acc['idx']}/8 {acc['id']} -> IP: {ip_used}")
                    send_tg_message(f"⚒️ <b>[{acc['idx']}/8] {acc['id']}</b> (IP: <code>{ip_used}</code> ✅): подключаю кузню и проверяю карты...", add_keyboard=False)
                    ctx = await create_account_context(browser, acc, proxy_url)
                    contexts.append(ctx)
                    page, user_obj = await ensure_logged_in(ctx, acc)
                    if not user_obj:
                        continue
                    try:
                        await page.goto("https://senkuro.com/forge", wait_until="domcontentloaded", timeout=35000)
                        await asyncio.sleep(random.uniform(1.8, 3.0))
                    except Exception:
                        pass
                    real_acc_uid = await ensure_real_user_id(page, acc["id"], str(user_obj.get("id") or ""))
                    state_map[acc["id"]] = {
                        "acc": acc,
                        "context": ctx,
                        "page": page,
                        "user_id": real_acc_uid,
                        "ip": ip_used,
                        "available_slots": 0,
                        "used_slots": 0,
                        "reset_at": None,
                        "cards_nodes": [],
                        "shards_nodes": [],
                        "craftable_by_rank": defaultdict(list),
                        "logs": [],
                    }

                if not state_map:
                    send_tg_message("❌ Не удалось авторизоваться ни в одном из 4 фарм-аккаунтов.")
                    return

                await refresh_farm_state(state_map)

                # Если на всех 8 аккаунтах слоты кузни = 0/5, сразу сообщаем точное время до сброса!
                initial_free_slots = sum(st["available_slots"] for st in state_map.values())
                if initial_free_slots <= 0:
                    reset_lines = ["⏳ <b>На всех 8 фарм-аккаунтах сейчас 0 из 5 доступных попыток переплавки в Кузне:</b>\n"]
                    for aid, st in state_map.items():
                        rst_str = format_reset_at_human(st.get("reset_at"))
                        inv_str = format_text_only_inventory_summary(st["cards_nodes"], st["shards_nodes"])
                        reset_lines.append(
                            f"👤 <b>{aid}</b> (Слоты: 0/5) — сброс счётчика: <b>{rst_str}</b>\n"
                            f"   📦 На аккаунте: {inv_str}\n"
                        )
                    reset_lines.append("💡 <i>Карты оставлены на аккаунтах до сброса попыток Кузни.</i>")
                    send_tg_message("\n".join(reset_lines), add_keyboard=True)
                    return

                # 1. ПЕРВЫМ ДЕЛОМ проверяем основной аккаунт cesium254 и забираем оттуда ВСЮ мелочь младше A-ранга (F, D, C, B),
                #    чтобы на основе оставались только A/S/R, а все F/D/C/B сразу участвовали в общем расчёте крафтов на ферме!
                first_page = next(iter(state_map.values()))["page"]
                main_res = await gql_call(first_page, GQL_FETCH_USER_BY_SLUG, {"slug": MAIN_ACCOUNT_SLUG}, "fetchUserBySlug")
                main_user = (main_res.get("data") or {}).get("user")
                main_uid = (main_user.get("id") if isinstance(main_user, dict) and main_user.get("id") else None) or KNOWN_USER_IDS.get(MAIN_ACCOUNT_SLUG)

                if main_uid and not FARM_STOP_FLAG:
                    main_cards_nodes = await fetch_all_user_cards_gql(first_page, main_uid, modifier_val=0)
                    main_by_rank = expand_craftable_cards_by_rank(main_cards_nodes)
                    borrow_units: list[dict] = []
                    borrow_desc_parts: list[str] = []
                    for low_r in ("F", "D", "C", "B"):
                        m_pool = main_by_rank.get(low_r, [])
                        if m_pool:
                            take_m = m_pool[:50 - len(borrow_units)]
                            if take_m:
                                borrow_units.extend(take_m)
                                borrow_desc_parts.append(f"{len(take_m)}×{RANK_BADGE.get(low_r, low_r)}")
                    if borrow_units:
                        best_rec = max(state_map.values(), key=lambda s: s["available_slots"])
                        req_payload = compress_card_units_for_gql(borrow_units)
                        await asyncio.sleep(random.uniform(3.0, 5.0))
                        b_res = await gql_call(
                            best_rec["page"],
                            GQL_SUGGEST_CARD_TRADE,
                            {
                                "input": {
                                    "userId": main_uid,
                                    "offer": [],
                                    "request": req_payload,
                                    "description": [],
                                }
                            },
                            "suggestCardTrade",
                        )
                        trade_created_obj = (b_res.get("data") or {}).get("suggestCardTrade") or {}
                        if trade_created_obj.get("success"):
                            b_summary = ", ".join(borrow_desc_parts)
                            send_tg_message(
                                f"🤝 <b>Запрос карт B-ранга и ниже с основы <a href='{MAIN_ACCOUNT_URL}'>{MAIN_ACCOUNT_SLUG}</a>!</b>\n\n"
                                f"Аккаунт <b>{best_rec['acc']['id']}</b> (свободно слотов кузни: {best_rec['available_slots']}/5) "
                                f"запросил с вашей основы все карты младше A-ранга ({b_summary}).\n"
                                "👉 <b>Пожалуйста, подтвердите входящий обмен на сайте (проверяю каждые 10 сек., жду до 2.5 минут)...</b>",
                                add_keyboard=False,
                            )
                            prev_total_cards = sum(int(n.get("quantity") or 1) for n in best_rec["cards_nodes"])
                            for _ in range(15):
                                if FARM_STOP_FLAG:
                                    break
                                await asyncio.sleep(10.0)
                                cur_nodes = await fetch_all_user_cards_gql(best_rec["page"], best_rec["user_id"], modifier_val=0)
                                cur_total = sum(int(n.get("quantity") or 1) for n in cur_nodes)
                                # Также проверяем, исчез ли PENDING трейд к основе (если обмен уже принят)
                                tr_chk = await gql_call(
                                    best_rec["page"],
                                    GQL_FETCH_CARD_TRADES,
                                    {"userId": best_rec["user_id"], "status": "PENDING"},
                                    "fetchCardTrades",
                                )
                                pend_edges = ((tr_chk.get("data") or {}).get("cardTrades") or {}).get("edges") or []
                                still_pending_to_main = any(
                                    str(((e.get("node") or {}).get("target") or {}).get("slug") or "").lower() == MAIN_ACCOUNT_SLUG.lower()
                                    or str(((e.get("node") or {}).get("recipient") or {}).get("slug") or "").lower() == MAIN_ACCOUNT_SLUG.lower()
                                    for e in pend_edges
                                )
                                if cur_total > prev_total_cards or (not still_pending_to_main and len(cur_nodes) > 0 and cur_total != prev_total_cards):
                                    best_rec["logs"].append(f"📥 Получены карты с основы {MAIN_ACCOUNT_SLUG} ({b_summary})")
                                    send_tg_message(
                                        f"✅ <b>Обмен с основы подтверждён!</b> Карты ({b_summary}) получены на <b>{best_rec['acc']['id']}</b> — начинаю распределение и переплавку...",
                                        add_keyboard=False,
                                    )
                                    break
                        else:
                            b_errs = b_res.get("errors") or []
                            if b_errs:
                                best_rec["logs"].append(f"⚠️ Не удалось запросить карты с основы: {b_errs[0].get('message')}")

                # 2. Обновляем состояние всех 4 аккаунтов (уже вместе с полученными картами с основы!) и варим локальные тройки
                await refresh_farm_state(state_map)
                for aid, st in state_map.items():
                    if FARM_STOP_FLAG:
                        break
                    await forge_local_triples_on_account(st)

                # 3. Межаккаунтный обмен и переплавка между 8 фарм-аккаунтами (с человеческими паузами!)
                for _ in range(30):
                    if FARM_STOP_FLAG:
                        break
                    await refresh_farm_state(state_map)
                    total_free_slots = sum(st["available_slots"] for st in state_map.values())
                    if total_free_slots <= 0:
                        break

                    target_rank = None
                    for r in FORGE_UPGRADE_CHAIN:
                        total_r = sum(len(st["craftable_by_rank"].get(r, [])) for st in state_map.values())
                        if total_r >= 3:
                            target_rank = r
                            break

                    if not target_rank:
                        break

                    receiver_candidates = [st for st in state_map.values() if st["available_slots"] > 0]
                    if not receiver_candidates:
                        break
                    receiver_candidates.sort(
                        key=lambda s: (len(s["craftable_by_rank"].get(target_rank, [])), s["available_slots"]),
                        reverse=True,
                    )
                    receiver = receiver_candidates[0]
                    rec_id = receiver["acc"]["id"]
                    rec_uid = receiver["user_id"]

                    have_on_receiver = len(receiver["craftable_by_rank"].get(target_rank, []))
                    need_count = max(0, 3 - have_on_receiver)

                    if need_count == 0:
                        await forge_local_triples_on_account(receiver)
                        continue

                    transferred_any = False
                    for donor_id, donor in state_map.items():
                        if donor_id == rec_id or need_count <= 0 or FARM_STOP_FLAG:
                            continue
                        donor_pool = donor["craftable_by_rank"].get(target_rank, [])
                        if not donor_pool:
                            continue

                        take_units = donor_pool[:need_count]
                        offer_payload = compress_card_units_for_gql(take_units)
                        # Человеческая пауза перед отправкой межаккаунтного трейда
                        await asyncio.sleep(random.uniform(4.0, 6.2))
                        tr_res = await gql_call(
                            donor["page"],
                            GQL_SUGGEST_CARD_TRADE,
                            {
                                "input": {
                                    "userId": rec_uid,
                                    "offer": offer_payload,
                                    "request": [],
                                    "description": [],
                                }
                            },
                            "suggestCardTrade",
                        )
                        if ((tr_res.get("data") or {}).get("suggestCardTrade") or {}).get("success"):
                            need_count -= len(take_units)
                            transferred_any = True
                            donor["logs"].append(
                                f"📤 Отправлен трейд ({len(take_units)}×{target_rank}) ➡️ <b>{rec_id}</b> для переплавки"
                            )
                            await asyncio.sleep(random.uniform(2.5, 4.0))
                            acc_logs = await accept_whitelisted_incoming_trades(receiver["page"], rec_id, rec_uid)
                            receiver["logs"].extend(acc_logs)
                        else:
                            t_errs = tr_res.get("errors") or []
                            if t_errs:
                                donor["logs"].append(f"⚠️ Ошибка отправки трейда на {rec_id}: {t_errs[0].get('message')}")

                    if not transferred_any:
                        break

                    await refresh_farm_state(state_map)
                    await forge_local_triples_on_account(receiver)

                await refresh_farm_state(state_map)

                report_lines = ["⚒️ <b>Отчёт работы Кузницы (Переплавка):</b>\n"]
                for aid, st in state_map.items():
                    inv_str = format_text_only_inventory_summary(st["cards_nodes"], st["shards_nodes"])
                    rst_info = f", сброс {format_reset_at_human(st.get('reset_at'))}" if st["available_slots"] < 5 and st.get("reset_at") else ""
                    report_lines.append(
                        f"👤 <b>{aid}</b> (IP: <code>{st['ip']}</code> | Слоты кузни: <b>{st['available_slots']}/5</b> свободно{rst_info}):"
                    )
                    if st["logs"]:
                        for lg in st["logs"]:
                            report_lines.append(f"   • {lg}")
                    else:
                        report_lines.append("   • Переплавок не требовалось")
                    report_lines.append(f"   📦 Сейчас на аккаунте: {inv_str}\n")

                # 4. Отправка готовых карт НА ОСНОВУ cesium254 по новым правилам:
                #    - На основу отправляются ТОЛЬКО карты ранга A и выше (A, S, R)!
                #    - Карты B, C, D, F остаются лежать на фарм-аккаунтах для следующих переплавок!
                #    - Осколки отправляются на основу ТОЛЬКО попутно вместе с картой A/S/R (отдельно осколки не шлются, а копятся!).
                if not main_uid:
                    report_lines.append(f"⚠️ Не удалось получить ID основного аккаунта {MAIN_ACCOUNT_SLUG}.")
                else:
                    total_sent_cards: Counter = Counter()
                    total_sent_shards: Counter = Counter()
                    accounts_that_sent: list[str] = []

                    # Проверяем, появилась ли хотя бы на одном из 4 фарм-аккаунтов карта ранга A и выше (A, S, R)
                    has_any_high_rank_on_farm = any(
                        not node.get("locked")
                        and int(node.get("quantity") or 1) > 0
                        and str((node.get("card") or {}).get("rank") or "").upper() in ("A", "S", "R")
                        for st_chk in state_map.values()
                        for node in st_chk["cards_nodes"]
                    )

                    for aid, st in state_map.items():
                        if FARM_STOP_FLAG or not has_any_high_rank_on_farm:
                            break
                        high_rank_offers = []
                        acc_cards_cnt: Counter = Counter()
                        for node in st["cards_nodes"]:
                            if node.get("locked"):
                                continue
                            cid = (node.get("card") or {}).get("id") or node.get("cardId")
                            qty = int(node.get("quantity") or 1)
                            mod = int(node.get("modifier") or 0)
                            rank = str((node.get("card") or {}).get("rank") or "?").upper()
                            # Фильтр: отправляем на основу ТОЛЬКО ранг A и выше (A, S, R)!
                            if cid and qty > 0 and rank in ("A", "S", "R"):
                                high_rank_offers.append({"cardId": cid, "modifier": mod, "quantity": qty})
                                acc_cards_cnt[rank] += qty

                        # Когда отправляется карта A/S/R хотя бы с одного аккаунта — со ВСЕХ 4 аккаунтов также скидываем осколки напрямую на основу!
                        all_offer_entries = list(high_rank_offers)
                        acc_shards_cnt: Counter = Counter()
                        for node in st["shards_nodes"]:
                            if node.get("locked"):
                                continue
                            cid = (node.get("card") or {}).get("id") or node.get("cardId")
                            qty = int(node.get("quantity") or 1)
                            mod = int(node.get("modifier") or 1)
                            rank = str((node.get("card") or {}).get("rank") or "?").upper()
                            if cid and qty > 0:
                                all_offer_entries.append({"cardId": cid, "modifier": mod, "quantity": qty})
                                acc_shards_cnt[rank] += qty

                        if not all_offer_entries:
                            continue

                        sent_ok_any = False
                        for i in range(0, len(all_offer_entries), 50):
                            chunk = all_offer_entries[i : i + 50]
                            await asyncio.sleep(random.uniform(4.0, 6.2))
                            s_res = await gql_call(
                                st["page"],
                                GQL_SUGGEST_CARD_TRADE,
                                {
                                    "input": {
                                        "userId": main_uid,
                                        "offer": chunk,
                                        "request": [],
                                        "description": [],
                                    }
                                },
                                "suggestCardTrade",
                            )
                            if ((s_res.get("data") or {}).get("suggestCardTrade") or {}).get("success"):
                                sent_ok_any = True

                        if sent_ok_any:
                            accounts_that_sent.append(aid)
                            for r_k, q_v in acc_cards_cnt.items():
                                total_sent_cards[r_k] += q_v
                            for r_k, q_v in acc_shards_cnt.items():
                                total_sent_shards[r_k] += q_v

                    if accounts_that_sent:
                        c_summary = ", ".join(
                            f"<b>{total_sent_cards[r]}</b> {RANK_BADGE.get(r, r)}"
                            for r in RANK_ORDER
                            if total_sent_cards.get(r, 0) > 0
                        ) or "нет"
                        s_summary = ", ".join(
                            f"<b>{total_sent_shards[r]}</b> {RANK_BADGE.get(r, r)}"
                            for r in RANK_ORDER
                            if total_sent_shards.get(r, 0) > 0
                        ) or "нет"
                        report_lines.append(
                            f"🎁 <b>Отправлены трейды (ранг A и выше + попутные осколки) на основу <a href='{MAIN_ACCOUNT_URL}'>{MAIN_ACCOUNT_SLUG}</a> (от: {', '.join(accounts_that_sent)}):</b>\n"
                            f"🃏 <b>Карты ({sum(total_sent_cards.values())} шт.):</b> {c_summary}\n"
                            f"🧩 <b>Попутные осколки ({sum(total_sent_shards.values())} шт.):</b> {s_summary}"
                        )
                    else:
                        report_lines.append(
                            "ℹ️ <b>Карт ранга A и выше сейчас нет</b> — все карты B/C/D/F и осколки оставлены на фарм-аккаунтах для накопления и следующих переплавок."
                        )

                for aid, st in state_map.items():
                    await st["context"].storage_state(path=str(get_session_file(aid)))
            finally:
                ACTIVE_BROWSER_PAGES.clear()
                for ctx in contexts:
                    try:
                        await ctx.close()
                    except Exception:
                        pass
            await browser.close()
    finally:
        proxy_mgr.stop_all()

    send_tg_message("\n".join(report_lines), add_keyboard=True)


# ==============================================================================
# 9. СЦЕНАРИЙ 4: ПОЛНЫЙ БОЕВОЙ 8-ЧАСОВОЙ ФАРМ МАНГИ И КАРТ НА GITHUB ACTIONS
#    (БЕЗ KAGGLE — ПОЛНЫЙ ДВИЖОК v6.5: Xvfb + WebWorker + Audio + Сбор Карт)
# ==============================================================================

FULL_FARM_USERSCRIPT_V9 = r"""
(() => {
    if (window.__senkuroSuiteV9Loaded) return;
    window.__senkuroSuiteV9Loaded = true;

    const TAB_ID = 'tab_' + Math.random().toString(36).slice(2, 9) + '_' + Date.now();

    // 1. АНТИ-СОН И ИМИТАЦИЯ АКТИВНОЙ ВКЛАДКИ (requestAnimationFrame + WebLocks + AudioContext)
    try {
        const hiddenDesc = { get: () => false, configurable: true };
        const visDesc = { get: () => 'visible', configurable: true };
        Object.defineProperty(document, 'hidden', hiddenDesc);
        Object.defineProperty(document, 'visibilityState', visDesc);
        Object.defineProperty(document, 'webkitHidden', hiddenDesc);
        if (window.Document && window.Document.prototype) {
            Object.defineProperty(window.Document.prototype, 'hidden', hiddenDesc);
            Object.defineProperty(window.Document.prototype, 'visibilityState', visDesc);
            window.Document.prototype.hasFocus = () => true;
        }
        document.hasFocus = () => true;

        const stopEvt = (e) => { e.stopImmediatePropagation(); e.stopPropagation(); };
        ['visibilitychange', 'webkitvisibilitychange', 'blur', 'focusout', 'freeze', 'pagehide'].forEach(evtName => {
            window.addEventListener(evtName, stopEvt, true);
            document.addEventListener(evtName, stopEvt, true);
        });

        if (window.requestAnimationFrame) {
            const origRAF = window.requestAnimationFrame.bind(window);
            window.requestAnimationFrame = function(callback) {
                let executed = false;
                const rafId = origRAF((ts) => {
                    if (!executed) { executed = true; callback(ts); }
                });
                window.setTimeout(() => {
                    if (!executed) {
                        executed = true;
                        try { callback(window.performance ? window.performance.now() : Date.now()); } catch (e) {}
                    }
                }, 30);
                return rafId;
            };
        }
    } catch (e) {}

    let webLockHeld = false;
    let silentAudioStarted = false;
    function ensureKeepAlive() {
        if (!webLockHeld && navigator.locks && navigator.locks.request) {
            webLockHeld = true;
            navigator.locks.request('senkuro_keep_alive_' + TAB_ID, () => new Promise(() => {})).catch(() => {});
        }
        if (!silentAudioStarted) {
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (AudioCtx) {
                    const ctx = new AudioCtx();
                    if (ctx.state === 'suspended') ctx.resume().catch(() => {});
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    gain.gain.value = 0.00001;
                    osc.connect(gain);
                    gain.connect(ctx.destination);
                    osc.start();
                    silentAudioStarted = true;
                }
            } catch (e) {}
        }
    }

    function isElementVisible(el) {
        if (!el || !el.isConnected) return false;
        try {
            const style = window.getComputedStyle(el);
            if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) return false;
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0;
        } catch (e) { return true; }
    }

    function triggerClick(el) {
        if (!el) return;
        try { if (typeof el.click === 'function') { el.click(); return; } } catch (e) {}
        try { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); } catch (e) {}
    }

    function findVisibleContinueModal() {
        const directNodes = document.querySelectorAll('.modal-drop__info, [class*="modal-drop__info"]');
        for (const node of directNodes) {
            if (isElementVisible(node)) return node;
        }
        for (const el of document.querySelectorAll('div, button, span')) {
            if (el.children.length > 2) continue;
            if (el.textContent && el.textContent.includes('Нажми, чтобы продолжить') && isElementVisible(el)) {
                return el;
            }
        }
        return null;
    }

    function findVisibleCardDrop() {
        const drops = document.querySelectorAll('.cards-drop, [class*="cards-drop"], img[alt="card-drop"], img[src*="card-back"]');
        for (const el of drops) {
            if (isElementVisible(el)) return el;
        }
        return null;
    }

    function getAutoscrollButton() {
        const path = document.querySelector('svg path[d^="M380-337"]');
        return path ? (path.closest('button') || path.parentElement) : null;
    }

    function runFarmTick() {
        ensureKeepAlive();
        const path = window.location.pathname;
        if (path.includes('/auth/')) return;
        const bodyTxt = document.body ? (document.body.innerText || '') : '';
        if (bodyTxt.includes('Приготовьтесь к приключениям')) return;

        // ЭТАП 2 СБОРА КАРТЫ: закрываем полноэкранную модалку полученной карты
        const continueDrop = findVisibleContinueModal();
        if (continueDrop) {
            triggerClick(continueDrop);
            return;
        }

        // ЭТАП 1 СБОРА КАРТЫ: открываем выпавшую рубашку карты справа снизу
        const cardDrop = findVisibleCardDrop();
        if (cardDrop) {
            triggerClick(cardDrop);
            if (cardDrop.parentElement && cardDrop.parentElement !== document.body) {
                triggerClick(cardDrop.parentElement);
            }
            setTimeout(() => {
                const modalNow = findVisibleContinueModal();
                if (modalNow) triggerClick(modalNow);
            }, 650);
            return;
        }

        // ЭТАП 3: В читалке (/chapters/) держим включенной автопрокрутку + проверяем конец манги
        if (path.includes('/chapters/')) {
            const slugM = path.match(/\/manga\/([^/]+)/);
            const curSlug = slugM ? slugM[1] : '';
            if (curSlug && sessionStorage.getItem('senkuro_active_slug') !== curSlug) {
                sessionStorage.setItem('senkuro_active_slug', curSlug);
                sessionStorage.setItem('senkuro_slug_start_ts', String(Date.now()));
            }

            const atBottom = (window.innerHeight + window.scrollY) >= (document.documentElement.scrollHeight - 220);
            if (atBottom) {
                const goToTitleBtn = Array.from(document.querySelectorAll('a, button')).find(el => {
                    const t = (el.innerText || el.textContent || '').trim();
                    return t.includes('Перейти к тайтлу') || t.includes('К тайтлу');
                });
                const nextChapBtn = Array.from(document.querySelectorAll('a, button')).find(el => {
                    const t = (el.innerText || el.textContent || '').trim();
                    return t.includes('Следующая глава') || t.includes('След. глава');
                });
                if (goToTitleBtn && !nextChapBtn && isElementVisible(goToTitleBtn)) {
                    if (curSlug) {
                        try {
                            const cdMap = JSON.parse(localStorage.getItem('senkuro_cooldown_mangas_v4') || '{}');
                            cdMap[curSlug] = Date.now() + 12 * 3600 * 1000;
                            localStorage.setItem('senkuro_cooldown_mangas_v4', JSON.stringify(cdMap));
                        } catch (e) {}
                    }
                    sessionStorage.setItem('senkuro_return_to_bookmarks', '1');
                    triggerClick(goToTitleBtn);
                    return;
                }
            }

            const autoscrollBtn = getAutoscrollButton();
            if (autoscrollBtn) {
                const isActive = autoscrollBtn.classList.contains('button--accent') ||
                                 autoscrollBtn.classList.contains('active') ||
                                 autoscrollBtn.getAttribute('aria-pressed') === 'true';
                if (!isActive) triggerClick(autoscrollBtn);
            } else {
                window.scrollBy({ top: 180, behavior: 'smooth' });
            }
            return;
        }

        // ЭТАП 4: На странице описания тайтла (/manga/...)
        if (path.startsWith('/manga/') && !path.includes('/chapters/')) {
            if (sessionStorage.getItem('senkuro_return_to_bookmarks') === '1') {
                sessionStorage.removeItem('senkuro_return_to_bookmarks');
                const savedBmUrl = localStorage.getItem('senkuro_my_bookmarks_url');
                if (savedBmUrl) {
                    window.location.href = savedBmUrl;
                    return;
                }
            }
            const startOrContinueBtn = Array.from(document.querySelectorAll('button.button--accent, a.button--accent, a[href*="/chapters/"]')).find(btn => {
                const txt = (btn.innerText || btn.textContent || '').trim();
                return txt.includes('Продолжить') || txt === 'Читать' || txt.startsWith('Читать') || txt.includes('Начать');
            });
            if (startOrContinueBtn) {
                triggerClick(startOrContinueBtn);
            }
            return;
        }

        // ЭТАП 5: В закладках (/users/.../bookmarks) прокручиваем вниз и берем самую нижнюю мангу
        if (path.startsWith('/users/') && path.includes('/bookmarks')) {
            try { localStorage.setItem('senkuro_my_bookmarks_url', window.location.href); } catch (e) {}
            const step = parseInt(sessionStorage.getItem('senkuro_bm_scroll_step') || '0', 10);
            const prevH = parseInt(sessionStorage.getItem('senkuro_bm_prev_h') || '0', 10);
            const curH = document.documentElement.scrollHeight || 0;
            const sameHCount = parseInt(sessionStorage.getItem('senkuro_bm_same_h') || '0', 10);
            if (step < 4 || (step < 15 && (curH > prevH + 50 || sameHCount < 1))) {
                sessionStorage.setItem('senkuro_bm_scroll_step', String(step + 1));
                sessionStorage.setItem('senkuro_bm_prev_h', String(curH));
                sessionStorage.setItem('senkuro_bm_same_h', curH <= prevH + 50 ? String(sameHCount + 1) : '0');
                window.scrollTo({ top: Math.max(0, curH - 350), behavior: 'smooth' });
                return;
            }
            sessionStorage.setItem('senkuro_bm_scroll_step', '0');
            sessionStorage.setItem('senkuro_bm_prev_h', '0');
            sessionStorage.setItem('senkuro_bm_same_h', '0');

            const nowTs = Date.now();
            let cdMap = {};
            try {
                cdMap = JSON.parse(localStorage.getItem('senkuro_cooldown_mangas_v4') || '{}');
                Object.keys(cdMap).forEach(k => { if (cdMap[k] <= nowTs) delete cdMap[k]; });
                localStorage.setItem('senkuro_cooldown_mangas_v4', JSON.stringify(cdMap));
            } catch (e) {}

            const allMangaLinks = Array.from(document.querySelectorAll('a[href*="/manga/"]')).filter(a => {
                if (a.closest('footer')) return false;
                const href = a.getAttribute('href') || '';
                if (!href.startsWith('/manga/') && !href.includes('senkuro.com/manga/')) return false;
                if (href.includes('/chapters/')) return false;
                const rect = a.getBoundingClientRect();
                return rect.width > 30 && rect.height > 30;
            });

            const uniqueLinks = [];
            const seenSlugs = new Set();
            for (const a of allMangaLinks) {
                const m = (a.getAttribute('href') || '').match(/\/manga\/([^/?#]+)/);
                if (m && !seenSlugs.has(m[1])) {
                    seenSlugs.add(m[1]);
                    uniqueLinks.push({ slug: m[1], el: a, href: a.href });
                }
            }

            const candidates = uniqueLinks.filter(item => !cdMap[item.slug]);
            if (uniqueLinks.length > 0 && candidates.length === 0) {
                localStorage.setItem('senkuro_cooldown_mangas_v4', '{}');
            }
            const chosen = candidates.length > 0 ? candidates[candidates.length - 1] : (uniqueLinks.length > 0 ? uniqueLinks[uniqueLinks.length - 1] : null);
            if (chosen) {
                try {
                    cdMap[chosen.slug] = Date.now() + 12 * 3600 * 1000;
                    localStorage.setItem('senkuro_cooldown_mangas_v4', JSON.stringify(cdMap));
                } catch (e) {}
                triggerClick(chosen.el);
                setTimeout(() => {
                    if (window.location.pathname.includes('/bookmarks')) window.location.href = chosen.href;
                }, 1200);
            }
        }
    }

    try {
        const blob = new Blob(['setInterval(() => postMessage("tick"), 2000);'], { type: 'application/javascript' });
        const worker = new Worker(URL.createObjectURL(blob));
        worker.onmessage = () => runFarmTick();
    } catch (e) {
        setInterval(runFarmTick, 2000);
    }
})();
"""


def format_farm_status_message(status_obj: dict) -> str:
    elapsed_min = int(status_obj.get("elapsed_minutes") or 0)
    total_hours = float(status_obj.get("target_hours") or 8.0)
    reading_cnt = int(status_obj.get("reading_count") or 0)
    unique_ips = int(status_obj.get("unique_ips") or 0)
    updated_str = status_obj.get("updated_at", "")

    hh = elapsed_min // 60
    mm = elapsed_min % 60
    lines = [
        "📊 <b>Статус 8-часового фарма манги:</b>",
        f"⏱ <b>Отработано:</b> {hh} ч {mm} мин из {total_hours:g} ч",
        f"📖 <b>Читают главы сейчас:</b> <b>{reading_cnt}/8</b> аккаунтов | 🌐 <b>Уникальных IP:</b> <b>{unique_ips}/8</b>\n",
    ]
    for acc_info in status_obj.get("accounts", []):
        is_rd = acc_info.get("is_reading", False)
        icon = "🟢" if is_rd else "🟡"
        st_label = "ЧИТАЕТ ГЛАВУ" if is_rd else "Навигация / В закладках"
        lines.append(
            f"{icon} <b>#{acc_info['idx']} {acc_info['id']}</b> (IP: <code>{acc_info['ip']}</code>)\n"
            f"   └ {st_label}: <i>{acc_info.get('title', 'Загрузка...')}</i>"
        )
    if updated_str:
        lines.append(f"\n🕒 Обновлено: <code>{updated_str}</code>")
    return "\n".join(lines)


async def run_check_farm_status() -> None:
    st = fetch_latest_farm_status()
    if st and st.get("active"):
        send_tg_message(format_farm_status_message(st), add_keyboard=True)
    else:
        send_tg_message(
            "⚪ <b>Сейчас 8-часовой фарм манги не активен</b> (или уже завершил 8-часовой таймер).\n\n"
            "Нажмите кнопку <b>«▶️ Запустить фарм (8 ч)»</b> ниже, чтобы запустить чтение манги на всех 8 аккаунтах!",
            add_keyboard=True,
        )


async def run_farm_segment(part_mode: str = "farm_part1") -> None:
    """
    Выполняет 8-часовой фарм манги на GitHub Actions в 2 бесшовных этапа по 4 часа
    (farm_part1: часы 0..4 -> farm_part2: часы 4..8) в рамках одного запуска воркфлоу!
    - При старте farm_part1 отправляет сообщение о начале работы в Telegram.
    - Каждые 45 сек публикует живую сводку для кнопки «📊 Проверить статус фарма».
    - По окончании farm_part2 (ровно через 8 часов, без 5-минутного спама!) отправляет
      итоговое сообщение в Telegram с базовой панелью кнопок.
    """
    is_part1 = part_mode in ("farm_part1", "farm")
    is_part2 = part_mode == "farm_part2"
    segment_hours = 4.0
    base_elapsed_minutes = 0 if is_part1 else 240

    if is_part1:
        send_tg_message(
            "🚀 <b>Запускаю 8-часовой фарм манги на всех 8 аккаунтах!</b>\n"
            "Поднимаю виртуальный экран, 8 уникальных IP, вхожу в аккаунты, выбираю мангу снизу закладок и пришлю сводку через ~45 сек...",
            add_keyboard=False,
        )

    proxy_mgr = AccountProxyManager()
    farm_sessions = []
    start_ts = time.time()

    # Если доступен виртуальный экран Xvfb (DISPLAY), запускаем полноценный браузер headless=False (как в Kaggle v6.5)
    has_display = bool(os.environ.get("DISPLAY"))

    try:
        async with async_playwright() as p:
            browser = await launch_senkuro_browser(p)
            for acc in FARM_ACCOUNTS:
                proxy_url = await asyncio.to_thread(proxy_mgr.start_account_proxy, acc)
                ip_used = proxy_mgr.active_ips.get(acc["acc_id"], acc["pinned_ip"])
                ctx = await create_account_context(browser, acc, proxy_url)
                await ctx.add_init_script(FULL_FARM_USERSCRIPT_V9)
                page, user_obj = await ensure_logged_in(ctx, acc)
                await page.goto(acc["bookmarks_url"], wait_until="domcontentloaded", timeout=40000)
                await page.evaluate(FULL_FARM_USERSCRIPT_V9)
                farm_sessions.append(
                    {
                        "acc": acc,
                        "context": ctx,
                        "page": page,
                        "ip": ip_used,
                    }
                )

            # Ждем до 60 сек, пока все 8 аккаунтов откроют чтение главы (/chapters/)
            for _ in range(12):
                await asyncio.sleep(5)
                for s in farm_sessions:
                    try:
                        await s["page"].evaluate(FULL_FARM_USERSCRIPT_V9)
                    except Exception:
                        pass
                if sum(1 for s in farm_sessions if "/chapters/" in s["page"].url) == len(FARM_ACCOUNTS):
                    break

            def collect_snapshot(active_flag: bool = True) -> dict:
                elapsed_m = base_elapsed_minutes + int((time.time() - start_ts) // 60)
                acc_list = []
                rd_cnt = 0
                ips_set = set()
                for s in farm_sessions:
                    pg: Page = s["page"]
                    u = pg.url
                    is_rd = "/chapters/" in u
                    if is_rd:
                        rd_cnt += 1
                    if s["ip"]:
                        ips_set.add(s["ip"])
                    acc_list.append(
                        {
                            "idx": s["acc"]["idx"],
                            "id": s["acc"]["id"],
                            "ip": s["ip"],
                            "url": u,
                            "is_reading": is_rd,
                            "title": "",
                        }
                    )
                return {
                    "active": active_flag,
                    "elapsed_minutes": elapsed_m,
                    "target_hours": 8.0,
                    "reading_count": rd_cnt,
                    "unique_ips": len(ips_set),
                    "updated_at": time.strftime("%H:%M:%S"),
                    "accounts": acc_list,
                }

            async def enrich_titles(snap: dict) -> dict:
                for idx_s, s in enumerate(farm_sessions):
                    try:
                        t = (await s["page"].title()).replace(" - Senkuro", "").strip()
                    except Exception:
                        t = s["page"].url
                    snap["accounts"][idx_s]["title"] = t[:48]
                return snap

            initial_snap = await enrich_titles(collect_snapshot(True))
            publish_live_farm_status(initial_snap)

            if is_part1:
                send_tg_message(
                    "✅ <b>8-часовой фарм манги успешно запущен!</b>\n\n" + format_farm_status_message(initial_snap),
                    add_keyboard=True,
                )

            end_ts = start_ts + segment_hours * 3600.0
            last_sync_ts = time.time()
            last_save_ts = time.time()

            stopped_by_user = False
            farm_seen_cmds: set[str] = set()
            farm_cmd_Poll_ts = int(time.time())

            while time.time() < end_ts:
                await asyncio.sleep(6)
                for s in farm_sessions:
                    try:
                        await s["page"].evaluate(FULL_FARM_USERSCRIPT_V9)
                    except Exception:
                        pass

                # Мгновенная проверка команд из Telegram прямо во время фарма!
                new_cmds = poll_instant_commands(farm_cmd_Poll_ts - 2, farm_seen_cmds)
                farm_cmd_Poll_ts = int(time.time())
                for c_item in new_cmds:
                    c_act = str(c_item.get("action") or "").strip().lower()
                    c_promo = str(c_item.get("promo_code") or "").strip()
                    if c_act == "stop":
                        stopped_by_user = True
                        break
                    elif c_act == "check":
                        await run_check_all_5_accounts()
                    elif c_act == "balance":
                        await run_check_coins_balance()
                    elif c_act == "promo" and c_promo:
                        await run_promo_code_activation(c_promo)
                    elif c_act == "packs":
                        await run_all_packs_opening()
                    elif c_act == "forge":
                        await run_smart_forge_and_trade_pipeline()
                    elif c_act == "all":
                        await run_all_packs_opening()
                        await run_smart_forge_and_trade_pipeline()

                if stopped_by_user:
                    print("[FARM STOP] Получен мгновенный сигнал остановки из очереди! Сохраняем сессии и выходим...")
                    stopped_snap = await enrich_titles(collect_snapshot(False))
                    publish_live_farm_status(stopped_snap)
                    break

                now = time.time()
                if now - last_sync_ts >= 25:
                    last_sync_ts = now
                    if check_remote_stop_signal(int(start_ts)):
                        print("[FARM STOP] Получен сигнал остановки из Telegram! Сохраняем сессии и выходим...")
                        stopped_by_user = True
                        stopped_snap = await enrich_titles(collect_snapshot(False))
                        publish_live_farm_status(stopped_snap)
                        break
                    snap = await enrich_titles(collect_snapshot(True))
                    publish_live_farm_status(snap)

                if now - last_save_ts >= 600:
                    last_save_ts = now
                    for s in farm_sessions:
                        try:
                            await s["context"].storage_state(path=str(get_session_file(s["acc"]["id"])))
                        except Exception:
                            pass

            for s in farm_sessions:
                try:
                    await s["context"].storage_state(path=str(get_session_file(s["acc"]["id"])))
                except Exception:
                    pass

            if is_part2:
                final_snap = await enrich_titles(collect_snapshot(False))
                publish_live_farm_status(final_snap)
                send_tg_message(
                    "🏁 <b>8 часов фарма манги полностью завершены!</b>\n"
                    "Все 8 аккаунтов остановлены, прогресс чтения и сессии сохранены.\n\n"
                    + format_farm_status_message(final_snap),
                    add_keyboard=True,
                )

            if is_part1 and not stopped_by_user:
                gh_out = os.environ.get("GITHUB_OUTPUT", "")
                if gh_out:
                    try:
                        with open(gh_out, "a", encoding="utf-8") as f_out:
                            f_out.write("continue_farm=true\n")
                    except Exception:
                        pass

            for s in farm_sessions:
                await s["context"].close()
            await browser.close()
    finally:
        proxy_mgr.stop_all()


# ==============================================================================
# 10. СЦЕНАРИЙ 5: КЛАССИЧЕСКИЙ ЧЕКЕР КАРТ И ОСКОЛКОВ ПО ВСЕМ 5 АККАУНТАМ (С ФОТО)
# ==============================================================================

CACHED_FETCH_USER_CARDS_TEMPLATE: dict[str, Any] = {}


def parse_graphql_edges(edges: list[dict]) -> list[dict]:
    parsed = []
    for edge in edges:
        node = edge.get("node") or edge
        if not isinstance(node, dict):
            continue
        card = node.get("card") or {}
        qty = int(node.get("quantity") or 1)
        rank = str(card.get("rank") or "?").upper()
        slug = card.get("slug") or ""
        url = f"https://senkuro.com/cards/{slug}" if slug else "https://senkuro.com"

        name = extract_card_title(card)
        image_obj = card.get("image") or {}
        preview_url = (image_obj.get("preview") or {}).get("url") or (image_obj.get("original") or {}).get("url") or ""

        for _ in range(max(1, qty)):
            parsed.append(
                {
                    "slug": slug,
                    "url": url,
                    "name": name,
                    "rank": rank if rank in RANK_ORDER else "?",
                    "img": preview_url,
                }
            )

    rank_idx = {r: i for i, r in enumerate(RANK_ORDER)}
    parsed.sort(key=lambda x: (rank_idx.get(x["rank"], 9), x["name"]))
    return parsed


def extract_rank_dom(slug: str, style_attr: str, text_content: str) -> str:
    if style_attr:
        m = re.search(r"#rank-([RSABCDF])", style_attr, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    if slug:
        m = re.search(r"-([rsabcdf])$", slug.strip("/"), re.IGNORECASE)
        if m:
            return m.group(1).upper()
    if text_content:
        for r in ["R", "S", "A", "B", "C", "D", "F"]:
            if re.search(rf"\b{r}\b", text_content):
                return r
    return "?"


async def extract_items_from_dom(page: Page) -> list[dict]:
    """Надёжное резервное извлечение карточек прямо из DOM страницы (как в оригинальном чекере)."""
    raw_items = await page.evaluate(
        """() => {
        const results = [];
        let elements = Array.from(document.querySelectorAll('.card-collect-preview'));
        if (elements.length === 0) {
            elements = Array.from(document.querySelectorAll('a.card-collect, a[href*="/cards/"]'));
        }
        elements.forEach(el => {
            const linkEl = el.tagName === 'A' ? el : el.querySelector('a.card-collect, a[href*="/cards/"]');
            const href = linkEl ? (linkEl.getAttribute('href') || '') : '';
            if (!href || !href.includes('/cards/')) return;
            const style = linkEl ? (linkEl.getAttribute('style') || '') : '';
            const imgEl = el.querySelector('img.card-collect__img, img');
            const name = imgEl ? (imgEl.getAttribute('alt') || '').trim() : '';
            const img = imgEl ? (imgEl.getAttribute('src') || '').trim() : '';
            const infoEl = el.querySelector('.card-collect-preview__info, .card-collect-preview__title');
            const titleText = infoEl ? infoEl.innerText.trim() : (el.innerText || '').trim();
            results.push({ href, style, name: name || 'Карта', img, titleText });
        });
        return results;
    }"""
    )
    parsed = []
    for item in raw_items or []:
        href = item["href"]
        full_url = f"https://senkuro.com{href}" if href.startswith("/") else href
        rank = extract_rank_dom(href, item["style"], item["titleText"])
        parsed.append({"slug": href, "url": full_url, "name": item["name"], "rank": rank, "img": item["img"]})
    rank_idx = {r: i for i, r in enumerate(RANK_ORDER)}
    parsed.sort(key=lambda x: (rank_idx.get(x["rank"], 9), x["name"]))
    return parsed


async def fetch_all_pages_via_graphql(page: Page, captured_req: dict, modifier_val: int, override_user_id: Optional[str] = None) -> list[dict]:
    raw_edges = await page.evaluate(
        """async ({ reqInfo, modifierVal, overrideUserId }) => {
        const allEdges = [];
        let afterCursor = null;
        const seenCursors = new Set();

        const headers = {};
        for (const [k, v] of Object.entries(reqInfo.headers || {})) {
            const lk = k.toLowerCase();
            if (lk === 'content-type' || lk === 'accept' || lk.startsWith('app-') || lk === 'authorization') {
                headers[k] = v;
            }
        }
        headers['Content-Type'] = 'application/json';

        for (let pageNum = 0; pageNum < 50; pageNum++) {
            const bodyObj = JSON.parse(JSON.stringify(reqInfo.postData));
            bodyObj.variables = bodyObj.variables || {};
            if (overrideUserId) {
                bodyObj.variables.userId = overrideUserId;
            }
            bodyObj.variables.modifier = { include: [modifierVal] };
            if (afterCursor) {
                bodyObj.variables.after = afterCursor;
            } else {
                delete bodyObj.variables.after;
            }

            const resp = await fetch(reqInfo.url, {
                method: 'POST',
                headers: headers,
                body: JSON.stringify(bodyObj)
            });
            if (!resp.ok) break;
            const json = await resp.json();
            const userCards = json?.data?.userCards;
            if (!userCards) break;

            const edges = userCards.edges || [];
            allEdges.push(...edges);

            const pageInfo = userCards.pageInfo || {};
            if (pageInfo.hasNextPage && pageInfo.endCursor && !seenCursors.has(pageInfo.endCursor)) {
                seenCursors.add(pageInfo.endCursor);
                afterCursor = pageInfo.endCursor;
            } else {
                break;
            }
        }
        return allEdges;
    }""",
        {"reqInfo": captured_req, "modifierVal": modifier_val, "overrideUserId": override_user_id},
    )
    return parse_graphql_edges(raw_edges or [])


async def scrape_account_cards_public(browser, account: dict) -> dict:
    """
    Для КАЖДОГО из 9 аккаунтов создаёт свежий изолированный BrowserContext с service_workers='block',
    чтобы Service Worker от 1-го аккаунта НИКОГДА не блокировал перехват запросов на 2..5 аккаунтах!
    """
    context = await browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        viewport={"width": 1280, "height": 900},
        locale="ru-RU",
        service_workers="block",
    )
    page = await context.new_page()
    ACTIVE_BROWSER_PAGES[f"check_{account['id']}"] = page
    log_debug(f"[CHECK 5] Проверка {account['label']} -> {account['url']}")
    captured_req: dict[str, Any] = {}
    intercepted_user_id: list[str] = []

    def on_request(request):
        if "graphql" in request.url and request.method == "POST":
            try:
                post_json = request.post_data_json
                items = post_json if isinstance(post_json, list) else [post_json]
                for item in items:
                    if isinstance(item, dict) and item.get("operationName") == "fetchUserCards":
                        if not captured_req:
                            captured_req["url"] = request.url
                            captured_req["headers"] = request.headers
                            captured_req["postData"] = item
                            CACHED_FETCH_USER_CARDS_TEMPLATE.update(captured_req)
                            uid_v = (item.get("variables") or {}).get("userId")
                            if uid_v:
                                intercepted_user_id.append(str(uid_v))
            except Exception:
                pass

    page.on("request", on_request)

    try:
        await page.goto(account["url"], wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(1500)

        # Способ 1 (Самый быстрый — 1 сек): прямой GraphQL запрос всех страниц карт и осколков по userId
        u_res = await gql_call(page, GQL_FETCH_USER_BY_SLUG, {"slug": account["id"]}, "fetchUserBySlug")
        uid = ((u_res.get("data") or {}).get("user") or {}).get("id") or (intercepted_user_id[0] if intercepted_user_id else None)
        log_debug(f"[CHECK 5 UID] {account['id']}: uid={uid}")

        if uid:
            c_nodes = await fetch_all_user_cards_gql(page, uid, modifier_val=0)
            s_nodes = await fetch_all_user_cards_gql(page, uid, modifier_val=1)
            cards = parse_graphql_edges(c_nodes)
            shards = parse_graphql_edges(s_nodes)
            log_debug(f"[CHECK 5 DIRECT GQL] {account['id']}: карт={len(cards)}, осколков={len(shards)}")
            if cards or shards:
                return {"cards": cards, "shards": shards, "error": None}

        # Способ 2: перехваченный запрос fetchUserCards от самой страницы
        for _ in range(10):
            if captured_req:
                break
            await page.wait_for_timeout(500)

        if captured_req:
            cards = await fetch_all_pages_via_graphql(page, captured_req, modifier_val=0)
            shards = await fetch_all_pages_via_graphql(page, captured_req, modifier_val=1)
            log_debug(f"[CHECK 5 GQL CAPTURED] {account['id']}: карт={len(cards)}, осколков={len(shards)}")
            if cards or shards:
                return {"cards": cards, "shards": shards, "error": None}

        # Резерв 2 (из оригинального рабочего check_orig.py): прямое считывание карточек и вкладки «Осколки» из DOM!
        await page.wait_for_timeout(2500)
        cards = await extract_items_from_dom(page)
        shards = []
        shard_tab = page.locator("text=/Осколки/i").first
        if await shard_tab.count() > 0:
            await shard_tab.click()
            await page.wait_for_timeout(2000)
            shards = await extract_items_from_dom(page)
        log_debug(f"[CHECK 5 DOM FALLBACK] {account['id']}: карт={len(cards)}, осколков={len(shards)}")
        return {"cards": cards, "shards": shards, "error": None}
    except Exception as e:
        log_debug(f"[CHECK 5 ERROR] {account['id']}: {e}")
        return {"cards": [], "shards": [], "error": str(e)}
    finally:
        ACTIVE_BROWSER_PAGES.pop(f"check_{account['id']}", None)
        await page.close()
        await context.close()


def format_rank_breakdown(items: list[dict]) -> str:
    if not items:
        return "нет"
    counts = Counter(x["rank"] for x in items)
    parts = []
    for r in RANK_ORDER:
        cnt = counts.get(r, 0)
        if cnt > 0:
            badge = RANK_BADGE.get(r, r)
            parts.append(f"<b>{cnt}</b> {badge}")
    return "  |  ".join(parts)


def build_account_message(account: dict, current: dict) -> tuple[str, list[str]]:
    cards = current["cards"]
    shards = current["shards"]
    cards_summary = format_rank_breakdown(cards)
    shards_summary = format_rank_breakdown(shards)
    lines = [
        f"👤 <b><a href=\"{account['url']}\">{account['label']}</a></b>",
        "",
        f"🃏 <b>Карты ({len(cards)}):</b> {cards_summary}",
        f"🧩 <b>Осколки ({len(shards)}):</b> {shards_summary}",
    ]
    card_photos = [c["img"] for c in cards if c.get("img", "").startswith("http")]
    return "\n".join(lines), card_photos


def _download_and_normalize_card_photo(url: str) -> Optional[bytes]:
    """Скачивает картинку карты с CDN Senkuro (с 3 попытками) и конвертирует в чистый JPEG для 100% приёма Telegram."""
    import io
    raw_bytes = None
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
                    "Referer": "https://senkuro.com/",
                    "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                },
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw_bytes = resp.read()
            if raw_bytes:
                break
        except Exception as e:
            if attempt == 3:
                log_debug(f"[CARD IMG DL WARN] Не удалось скачать {url} (попытка {attempt}/3): {e}")
            else:
                time.sleep(1.0)
    if not raw_bytes:
        return None
    try:
        from PIL import Image
        with Image.open(io.BytesIO(raw_bytes)) as im:
            if getattr(im, "is_animated", False):
                im.seek(0)
            rgb = im.convert("RGB")
            if rgb.width > 1200 or rgb.height > 1200:
                rgb.thumbnail((1200, 1200))
            out = io.BytesIO()
            rgb.save(out, format="JPEG", quality=88)
            return out.getvalue()
    except Exception:
        return raw_bytes


def _send_media_chunk_binary_fallback(chunk_urls: list[str], caption: str = "") -> bool:
    """Резервная отправка альбома карт бинарными файлами (multipart), если Telegram не смог скачать URL с CDN Senkuro."""
    from concurrent.futures import ThreadPoolExecutor
    files_to_send: list[tuple[str, bytes]] = []
    with ThreadPoolExecutor(max_workers=min(5, max(1, len(chunk_urls)))) as pool:
        results = list(pool.map(_download_and_normalize_card_photo, chunk_urls))
    for idx, img_bytes in enumerate(results):
        if img_bytes:
            files_to_send.append((f"photo_{idx}", img_bytes))

    if not files_to_send:
        return False

    if len(files_to_send) == 1:
        extra = {"chat_id": str(TELEGRAM_CHAT_ID)}
        if caption:
            extra["caption"] = caption
            extra["parse_mode"] = "HTML"
        res = send_tg_multipart("sendPhoto", "photo", "card_0.jpg", files_to_send[0][1], "image/jpeg", extra)
        return bool(res.get("ok"))

    boundary = f"----SenkuroMediaGroup{int(time.time() * 1000)}"
    media_manifest = []
    for idx, (field_name, _) in enumerate(files_to_send):
        item: dict[str, Any] = {"type": "photo", "media": f"attach://{field_name}"}
        if idx == 0 and caption:
            item["caption"] = caption
            item["parse_mode"] = "HTML"
        media_manifest.append(item)

    body = bytearray()
    for k, v in (("chat_id", str(TELEGRAM_CHAT_ID)), ("media", json.dumps(media_manifest, ensure_ascii=False))):
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{v}\r\n".encode("utf-8"))

    for idx, (field_name, img_bytes) in enumerate(files_to_send):
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{field_name}"; filename="card_{idx}.jpg"\r\n'.encode("utf-8"))
        body.extend(b"Content-Type: image/jpeg\r\n\r\n")
        body.extend(img_bytes)
        body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMediaGroup"
    for attempt in range(1, 4):
        req = urllib.request.Request(
            url,
            data=bytes(body),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                if res_data.get("ok"):
                    log_debug(f"[CHECK 5 ALBUM FALLBACK OK] Отправлено {len(files_to_send)} фото через прямую загрузку")
                    return True
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            if e.code == 429 and attempt < 3:
                retry_after = 5
                try:
                    retry_after = int((json.loads(err_body).get("parameters") or {}).get("retry_after") or 5)
                except Exception:
                    pass
                time.sleep(max(2, min(retry_after + 1, 35)))
                continue
            log_debug(f"[CHECK 5 ALBUM FALLBACK ERR] ({e.code}): {err_body}")
            break
        except Exception as e:
            log_debug(f"[CHECK 5 ALBUM FALLBACK ERR] {e}")
            break
    return False


def _send_single_photo_chunk(chunk: list[str], caption: str = "") -> bool:
    if len(chunk) == 1:
        payload: dict[str, Any] = {"chat_id": TELEGRAM_CHAT_ID, "photo": chunk[0]}
        if caption:
            payload["caption"] = caption
            payload["parse_mode"] = "HTML"
        res = tg_request("sendPhoto", payload)
        if res.get("ok"):
            return True
        log_debug(f"[CHECK 5 PHOTO FALLBACK] Прямой URL не прошёл, качаю фото напрямую...")
        return _send_media_chunk_binary_fallback(chunk, caption=caption)
    else:
        media = []
        for idx, url in enumerate(chunk):
            item: dict[str, Any] = {"type": "photo", "media": url}
            if idx == 0 and caption:
                item["caption"] = caption
                item["parse_mode"] = "HTML"
            media.append(item)
        res = tg_request("sendMediaGroup", {"chat_id": TELEGRAM_CHAT_ID, "media": media})
        if res.get("ok"):
            return True
        log_debug(f"[CHECK 5 ALBUM FALLBACK] sendMediaGroup по URL не прошёл ({res.get('error', '')[:120]}), загружаю {len(chunk)} фото напрямую...")
        return _send_media_chunk_binary_fallback(chunk, caption=caption)


def send_account_report(text: str, photo_urls: list[str], add_reply_button: bool = False) -> None:
    chunks = [photo_urls[i : i + 10] for i in range(0, len(photo_urls), 10)]

    if chunks and not add_reply_button and len(chunks) == 1:
        if _send_single_photo_chunk(chunks[0], caption=text):
            return

    for c_idx, chunk in enumerate(chunks):
        _send_single_photo_chunk(chunk, caption="")
        if c_idx < len(chunks) - 1:
            time.sleep(1.5)

    msg_payload: dict[str, Any] = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if add_reply_button:
        msg_payload["reply_markup"] = get_main_inline_keyboard()
    tg_request("sendMessage", msg_payload)


async def run_check_all_5_accounts() -> None:
    log_debug("[TASK START] Запуск проверки всех 9 аккаунтов (поочерёдно с изолированными контекстами)...")
    async with async_playwright() as p:
        browser = await launch_senkuro_browser(p)
        for idx, acc in enumerate(ALL_CHECK_ACCOUNTS):
            acc_data = await scrape_account_cards_public(browser, acc)
            is_last = idx == len(ALL_CHECK_ACCOUNTS) - 1
            if acc_data["error"]:
                err_msg = f"⚠️ <b><a href=\"{acc['url']}\">{acc['label']}</a></b>: ошибка загрузки ({acc_data['error']})"
                send_account_report(err_msg, [], add_reply_button=is_last)
                continue
            text, card_photos = build_account_message(acc, acc_data)
            send_account_report(text, card_photos, add_reply_button=is_last)
            await asyncio.sleep(2.0)
        await browser.close()
    if DEBUG_MODE:
        upload_debug_log_to_github_noop("check_9_accounts")


# ==============================================================================
# 11. ПРЯМОЙ ДВИЖОК TELEGRAM LONG POLLING (v28.0 — БЕЗ CLOUDFLARE WORKER!)
# ==============================================================================

CURRENT_FARM_STATUS: dict[str, Any] = {"active": False, "accounts": []}
FARM_STOP_FLAG: bool = False
GLOBAL_DEADLINE_TS: float = 0.0
ACTIVE_FARM_TASK: Optional[asyncio.Task] = None
ACTIVE_JOB_TASK: Optional[asyncio.Task] = None
PENDING_TASKS: Optional[asyncio.Queue] = None

TG_OFFSET_FILE = Path("/tmp/tg_offset.txt")
EARLY_QUEUE_FILE = Path("/tmp/senkuro_early_queue.jsonl")
FARM_RESUME_FILE = SESSIONS_DIR / "farm_resume.json"


def read_saved_tg_offset() -> int:
    vals = [0]
    for candidate in (TG_OFFSET_FILE, SESSIONS_DIR / "tg_offset.txt"):
        try:
            if candidate.exists():
                vals.append(int(candidate.read_text(encoding="utf-8").strip()))
        except Exception:
            pass
    return max(vals)


def write_saved_tg_offset(offset_val: int) -> None:
    for candidate in (TG_OFFSET_FILE, SESSIONS_DIR / "tg_offset.txt"):
        try:
            candidate.write_text(str(offset_val), encoding="utf-8")
        except Exception:
            pass


def fetch_tg_updates_sync(offset_val: int, timeout_sec: int = 4) -> list[dict]:
    if not TELEGRAM_BOT_TOKEN:
        time.sleep(2)
        return []
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset_val}&timeout={timeout_sec}"
    req = urllib.request.Request(url, headers={"User-Agent": "SenkuroDirectBot/24.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec + 6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok") and isinstance(data.get("result"), list):
                return data["result"]
            if not data.get("ok") and data.get("error_code") == 409:
                # Если вдруг старый вебхук был установлен, сбрасываем его
                tg_request("deleteWebhook", {"drop_pending_updates": False})
    except urllib.error.HTTPError as e:
        if e.code == 409:
            tg_request("deleteWebhook", {"drop_pending_updates": False})
        time.sleep(1)
    except Exception:
        time.sleep(1)
    return []


async def run_background_8h_farm(base_elapsed_minutes: int = 0, segment_hours: float = 4.0) -> None:
    global CURRENT_FARM_STATUS, FARM_STOP_FLAG
    FARM_STOP_FLAG = False

    if base_elapsed_minutes == 0:
        send_tg_message(
            "🚀 <b>Запускаю 8-часовой фарм манги на всех 8 аккаунтах!</b>\n"
            "Поднимаю виртуальный экран, 8 уникальных IP, вхожу в аккаунты, выбираю мангу снизу закладок и пришлю сводку через ~40 сек...",
            add_keyboard=True,
        )
    else:
        send_tg_message(
            f"🔄 <b>Продолжаю второй этап 8-часового фарма манги (уже отработано {base_elapsed_minutes // 60} ч)!</b>",
            add_keyboard=True,
        )

    proxy_mgr = AccountProxyManager()
    farm_sessions = []
    start_ts = time.time()
    has_display = bool(os.environ.get("DISPLAY"))

    try:
        async with async_playwright() as p:
            browser = await launch_senkuro_browser(p)
            for acc in FARM_ACCOUNTS:
                if FARM_STOP_FLAG:
                    break
                proxy_url = await asyncio.to_thread(proxy_mgr.start_account_proxy, acc)
                ip_used = proxy_mgr.active_ips.get(acc["acc_id"], acc["pinned_ip"])
                log_debug(f"[FARM STEP] #{acc['idx']}/8 {acc['id']} -> IP: {ip_used}")
                send_tg_message(
                    f"⏳ <b>[Фарм {acc['idx']}/8] {acc['id']}</b> (IP: <code>{ip_used}</code> ✅): вхожу в профиль, открываю закладки и листаю в самый низ...",
                    add_keyboard=False,
                )
                ctx = await create_account_context(browser, acc, proxy_url)
                await ctx.add_init_script(FULL_FARM_USERSCRIPT_V9)
                page, user_obj = await ensure_logged_in(ctx, acc)
                await page.goto(acc["bookmarks_url"], wait_until="domcontentloaded", timeout=40000)
                await page.evaluate(FULL_FARM_USERSCRIPT_V9)
                farm_sessions.append(
                    {
                        "acc": acc,
                        "context": ctx,
                        "page": page,
                        "ip": ip_used,
                    }
                )

            for _ in range(12):
                if FARM_STOP_FLAG:
                    break
                await asyncio.sleep(5)
                for s in farm_sessions:
                    try:
                        await s["page"].evaluate(FULL_FARM_USERSCRIPT_V9)
                    except Exception:
                        pass
                if sum(1 for s in farm_sessions if "/chapters/" in s["page"].url) == len(FARM_ACCOUNTS):
                    break

            def collect_snapshot(active_flag: bool = True) -> dict:
                elapsed_m = base_elapsed_minutes + int((time.time() - start_ts) // 60)
                acc_list = []
                rd_cnt = 0
                ips_set = set()
                for s in farm_sessions:
                    pg: Page = s["page"]
                    u = pg.url
                    is_rd = "/chapters/" in u
                    if is_rd:
                        rd_cnt += 1
                    if s["ip"]:
                        ips_set.add(s["ip"])
                    acc_list.append(
                        {
                            "idx": s["acc"]["idx"],
                            "id": s["acc"]["id"],
                            "ip": s["ip"],
                            "url": u,
                            "is_reading": is_rd,
                            "title": "",
                        }
                    )
                return {
                    "active": active_flag,
                    "elapsed_minutes": elapsed_m,
                    "target_hours": 8.0,
                    "reading_count": rd_cnt,
                    "unique_ips": len(ips_set),
                    "updated_at": time.strftime("%H:%M:%S"),
                    "accounts": acc_list,
                }

            async def enrich_titles(snap: dict) -> dict:
                for idx_s, s in enumerate(farm_sessions):
                    try:
                        t = (await s["page"].title()).replace(" - Senkuro", "").strip()
                    except Exception:
                        t = s["page"].url
                    snap["accounts"][idx_s]["title"] = t[:48]
                return snap

            if not FARM_STOP_FLAG and farm_sessions:
                initial_snap = await enrich_titles(collect_snapshot(True))
                CURRENT_FARM_STATUS = initial_snap
                publish_live_farm_status(initial_snap)
                # Сразу сохраняем файл резюме фарма на диск, чтобы при любом переходе между этапами прогресс не терялся!
                try:
                    FARM_RESUME_FILE.write_text(
                        json.dumps({"active": True, "elapsed_minutes": max(1, initial_snap["elapsed_minutes"]), "saved_at": time.time(), "run_id": os.environ.get("GITHUB_RUN_ID", "")}),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
                if base_elapsed_minutes == 0:
                    send_tg_message(
                        "✅ <b>8-часовой фарм манги успешно запущен!</b>\n\n" + format_farm_status_message(initial_snap),
                        add_keyboard=True,
                    )
                else:
                    log_debug(f"[FARM RESUME OK] Этап 8-часового фарма продолжен с {base_elapsed_minutes}-й минуты!")

            job_limit_ts = (GLOBAL_DEADLINE_TS - 45.0) if GLOBAL_DEADLINE_TS > time.time() + 120 else (start_ts + segment_hours * 3600.0)
            end_ts = min(start_ts + segment_hours * 3600.0, job_limit_ts)
            last_sync_ts = time.time()
            last_save_ts = time.time()

            while time.time() < end_ts and not FARM_STOP_FLAG:
                await asyncio.sleep(5)
                if FARM_STOP_FLAG:
                    break
                for s in farm_sessions:
                    try:
                        await s["page"].evaluate(FULL_FARM_USERSCRIPT_V9)
                    except Exception:
                        pass

                now = time.time()
                if now - last_sync_ts >= 20:
                    last_sync_ts = now
                    snap = await enrich_titles(collect_snapshot(True))
                    CURRENT_FARM_STATUS = snap
                    publish_live_farm_status(snap)
                    try:
                        FARM_RESUME_FILE.write_text(
                            json.dumps({"active": True, "elapsed_minutes": max(1, snap["elapsed_minutes"]), "saved_at": time.time(), "run_id": os.environ.get("GITHUB_RUN_ID", "")}),
                            encoding="utf-8",
                        )
                    except Exception:
                        pass
                    if snap["elapsed_minutes"] >= 480:
                        # Полные 8 часов (480 минут) отработаны!
                        break

                if now - last_save_ts >= 300:
                    last_save_ts = now
                    for s in farm_sessions:
                        try:
                            await s["context"].storage_state(path=str(get_session_file(s["acc"]["id"])))
                        except Exception:
                            pass

            for s in farm_sessions:
                try:
                    await s["context"].storage_state(path=str(get_session_file(s["acc"]["id"])))
                except Exception:
                    pass

            final_elapsed = base_elapsed_minutes + int((time.time() - start_ts) // 60)
            final_snap = await enrich_titles(collect_snapshot(False))
            CURRENT_FARM_STATUS = final_snap
            publish_live_farm_status(final_snap)

            if FARM_STOP_FLAG:
                if FARM_RESUME_FILE.exists():
                    FARM_RESUME_FILE.unlink(missing_ok=True)
            elif final_elapsed >= 475:
                if FARM_RESUME_FILE.exists():
                    FARM_RESUME_FILE.unlink(missing_ok=True)
                log_debug(f"[FARM COMPLETE] 8 часов фарма ({final_elapsed} мин) полностью отработаны!")
                send_tg_message(
                    "🏁 <b>8 часов фарма манги полностью завершены!</b>\n"
                    "Все 8 аккаунтов остановлены, прогресс чтения и сессии сохранены.\n\n"
                    + format_farm_status_message(final_snap),
                    add_keyboard=True,
                )
            else:
                # Сохраняем точное количество отработанных минут для бесшовного продолжения в следующем этапе воркфлоу!
                saved_min = max(1, final_elapsed)
                log_debug(f"[FARM HANDOFF] Этап завершён на {saved_min}/480 мин — сохраняю farm_resume.json для следующего этапа!")
                FARM_RESUME_FILE.write_text(
                    json.dumps({"active": True, "elapsed_minutes": saved_min, "saved_at": time.time(), "run_id": os.environ.get("GITHUB_RUN_ID", "")}),
                    encoding="utf-8",
                )

            for s in farm_sessions:
                await s["context"].close()
            await browser.close()
    except asyncio.CancelledError:
        CURRENT_FARM_STATUS = {"active": False, "accounts": []}
        if FARM_STOP_FLAG:
            if FARM_RESUME_FILE.exists():
                FARM_RESUME_FILE.unlink(missing_ok=True)
        else:
            # Отмена из-за завершения 4-часового джоба GitHub Actions — сохраняем точный прогресс для следующего джоба!
            saved_min = max(1, base_elapsed_minutes + int((time.time() - start_ts) // 60))
            log_debug(f"[FARM CANCEL HANDOFF] Джоб завершается на {saved_min}/480 мин — сохраняю farm_resume.json!")
            try:
                FARM_RESUME_FILE.write_text(
                    json.dumps({"active": True, "elapsed_minutes": saved_min, "saved_at": time.time(), "run_id": os.environ.get("GITHUB_RUN_ID", "")}),
                    encoding="utf-8",
                )
            except Exception:
                pass
    except Exception as e:
        log_debug(f"[FARM FATAL ERROR] {e}")
        send_tg_message(f"⚠️ Ошибка при запуске фарма: <code>{str(e).replace('<', '&lt;').replace('>', '&gt;')[:400]}</code>", add_keyboard=True)
    finally:
        ACTIVE_BROWSER_PAGES.clear()
        proxy_mgr.stop_all()


async def execute_single_action(action: str, promo_code: str = "") -> None:
    global ACTIVE_FARM_TASK, FARM_STOP_FLAG
    FARM_STOP_FLAG = False
    if action == "menu":
        send_tg_message(
            "✅ <b>Единый комбайн Senkuro v28.0 готов к работе (Прямая связь с GitHub)!</b>\n\n"
            "Выберите любую задачу кнопкой ниже (или просто отправьте промокод одним словом в чат):",
            add_keyboard=True,
        )
    elif action == "promo":
        await run_promo_code_activation(promo_code)
    elif action == "balance":
        await run_check_coins_balance()
    elif action == "packs":
        await run_all_packs_opening()
    elif action == "forge":
        await run_smart_forge_and_trade_pipeline()
    elif action in ("farm", "farm_part1"):
        if ACTIVE_FARM_TASK and not ACTIVE_FARM_TASK.done():
            send_tg_message(
                "🟢 <b>8-часовой фарм манги УЖЕ запущен и работает!</b>\n\n"
                + format_farm_status_message(CURRENT_FARM_STATUS),
                add_keyboard=True,
            )
        else:
            FARM_STOP_FLAG = False
            ACTIVE_FARM_TASK = asyncio.create_task(run_background_8h_farm(0, 4.0))
    elif action == "farm_part2":
        FARM_STOP_FLAG = False
        ACTIVE_FARM_TASK = asyncio.create_task(run_background_8h_farm(240, 4.0))
    elif action == "farm_status":
        if CURRENT_FARM_STATUS.get("active"):
            send_tg_message(format_farm_status_message(CURRENT_FARM_STATUS), add_keyboard=True)
        else:
            await run_check_farm_status()
    elif action == "all":
        if promo_code:
            await run_promo_code_activation(promo_code)
        await run_all_packs_opening()
        await run_smart_forge_and_trade_pipeline()
    elif action == "check":
        await run_check_all_5_accounts()


async def handle_telegram_update(upd: dict, task_queue: asyncio.Queue) -> None:
    global FARM_STOP_FLAG, ACTIVE_FARM_TASK, ACTIVE_JOB_TASK, CURRENT_FARM_STATUS

    cb = upd.get("callback_query")
    if cb:
        cb_id = cb.get("id")
        msg = cb.get("message") or {}
        chat_id = str((msg.get("chat") or {}).get("id") or "")
        data = str(cb.get("data") or "").strip()

        if TELEGRAM_CHAT_ID and chat_id and chat_id != str(TELEGRAM_CHAT_ID):
            tg_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": "⛔ Доступ запрещён", "show_alert": True})
            return

        if data == "stop_all_farm":
            tg_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": "🛑 Останавливаю фарм и все задачи..."})
            FARM_STOP_FLAG = True
            if FARM_RESUME_FILE.exists():
                FARM_RESUME_FILE.unlink(missing_ok=True)
            while not task_queue.empty():
                try:
                    task_queue.get_nowait()
                    task_queue.task_done()
                except Exception:
                    break
            if ACTIVE_JOB_TASK and not ACTIVE_JOB_TASK.done():
                ACTIVE_JOB_TASK.cancel()
            if ACTIVE_FARM_TASK and not ACTIVE_FARM_TASK.done():
                ACTIVE_FARM_TASK.cancel()
            CURRENT_FARM_STATUS = {"active": False, "accounts": []}
            publish_live_farm_status(CURRENT_FARM_STATUS)
            send_tg_message(
                "🛑 <b>Фарм и все активные задачи полностью остановлены!</b>\n\n"
                "Сессии сохранены. Сервер остаётся на связи — можете сразу запускать любую задачу кнопкой ниже:",
                add_keyboard=True,
            )
            return

        if data == "view_screen":
            tg_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": "📸 Делаю снимок экрана..."})
            await send_live_screen_snapshot()
            return

        if data == "dump_full_log":
            tg_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": "📜 Выгружаю полный лог..."})
            send_full_debug_log_to_user("Полный лог работы комбайна v28.0")
            return

        if data == "check_farm_status":
            tg_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Проверяю статус фарма..."})
            if CURRENT_FARM_STATUS.get("active"):
                send_tg_message(format_farm_status_message(CURRENT_FARM_STATUS), add_keyboard=True)
            else:
                await run_check_farm_status()
            return

        if data == "prompt_promo":
            tg_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": "Введите промокод в чат 👇"})
            send_tg_message(
                "🎟 <b>Просто напишите и отправьте промокод одним словом в этот чат:</b>\n\n"
                "Сервер откроет 8 уникальных IP, зайдёт на каждый из 4 аккаунтов, введёт промокод, "
                "<b>реально проверит увеличение баланса монет</b> и пришлёт результат!",
                add_keyboard=True,
            )
            return

        action_map = {
            "start_farm_8h": ("farm", "▶️ Запускаю 8-часовой фарм манги на 8 аккаунтах!"),
            "check_balance": ("balance", "🪙 Проверяю баланс сенкоинов на 8 фарм-аккаунтах..."),
            "roll_packs": ("packs", "🎴 Запускаю прокрутку паков «Хардкор» (480 🪙)..."),
            "run_forge": ("forge", "⚒️ Запускаю Переплавку (Кузня) + Трейд на основу..."),
            "check_senkuro": ("check", "🔄 Проверяю карты и осколки всех 9 аккаунтов..."),
            "run_all": ("all", "🚀 Запускаю полный цикл (Паки + Переплавка + Трейд)..."),
        }
        act_code, act_label = action_map.get(data, ("check", "🔄 Проверяю карты и осколки всех 9 аккаунтов..."))
        tg_request("answerCallbackQuery", {"callback_query_id": cb_id, "text": act_label})

        if act_code == "farm":
            await execute_single_action("farm", "")
        else:
            send_tg_message(f"⏳ <b>{act_label}</b>\nВыполняю задачу — отчёт придёт через несколько секунд!", add_keyboard=True)
            await task_queue.put((act_code, ""))
        return

    msg = upd.get("message")
    if msg and msg.get("text"):
        chat_id = str((msg.get("chat") or {}).get("id") or "")
        if TELEGRAM_CHAT_ID and chat_id and chat_id != str(TELEGRAM_CHAT_ID):
            return
        raw_text = str(msg.get("text") or "").strip()
        lower = raw_text.lower()

        if lower in ("/start", "/menu", "/help", "меню"):
            send_tg_message(
                "🤖 <b>Панель управления фермой Senkuro v28.0</b>\n\n"
                "Выберите задачу кнопкой в нижнем меню 🎛 (его можно сворачивать и разворачивать значком справа в поле ввода) "
                "или просто напишите промокод одним словом в чат:",
                add_keyboard=True,
                force_reply_kb=True,
            )
            return

        if lower in ("/screen", "📸 экран", "📸 посмотреть экран", "экран", "скрин"):
            await send_live_screen_snapshot()
            return

        if lower in ("/log", "📜 лог", "📜 полный лог", "лог", "логи"):
            send_full_debug_log_to_user("Полный лог работы комбайна v28.0")
            return

        if lower in ("/stop", "🛑 стоп", "стоп", "🛑 остановить фарм / все задачи"):
            FARM_STOP_FLAG = True
            if FARM_RESUME_FILE.exists():
                FARM_RESUME_FILE.unlink(missing_ok=True)
            while not task_queue.empty():
                try:
                    task_queue.get_nowait()
                    task_queue.task_done()
                except Exception:
                    break
            if ACTIVE_JOB_TASK and not ACTIVE_JOB_TASK.done():
                ACTIVE_JOB_TASK.cancel()
            if ACTIVE_FARM_TASK and not ACTIVE_FARM_TASK.done():
                ACTIVE_FARM_TASK.cancel()
            CURRENT_FARM_STATUS = {"active": False, "accounts": []}
            send_tg_message("🛑 <b>Все активные задачи и очередь полностью остановлены!</b>", add_keyboard=True)
            return

        if lower in ("/status", "📊 статус", "📊 статус фарма", "📊 проверить статус фарма"):
            if CURRENT_FARM_STATUS.get("active"):
                send_tg_message(format_farm_status_message(CURRENT_FARM_STATUS), add_keyboard=True)
            else:
                await run_check_farm_status()
            return

        if lower in ("/farm", "▶️ фарм (8 ч)", "▶️ запустить фарм (8 ч)"):
            await execute_single_action("farm", "")
            return

        if lower in ("🎟 промокод", "🎟 ввести промокод"):
            send_tg_message(
                "🎟 <b>Просто напишите и отправьте промокод одним словом в этот чат:</b>\n"
                "(окошко принудительного ответа убрано, чтобы ничего не залипало!)",
                add_keyboard=True,
            )
            return

        text_btn_map = {
            "/balance": "balance",
            "/relogin": "balance",
            "relogin": "balance",
            "🪙 баланс": "balance",
            "🪙 баланс монет": "balance",
            "🪙 баланс монет (4 акка)": "balance",
            "/packs": "packs",
            "🎴 паки": "packs",
            "🎴 паки хардкор": "packs",
            "🎴 крутить паки хардкор": "packs",
            "/forge": "forge",
            "⚒️ кузня+трейд": "forge",
            "⚒️ кузня + трейд": "forge",
            "⚒️ переплавка + трейд": "forge",
            "/check": "check",
            "🔄 чекать 9": "check",
            "🔄 чекать 9 акков": "check",
            "🔄 чекать 5": "check",
            "🔄 чекать 5 акков": "check",
            "🔄 проверить 9 аккаунтов": "check",
            "🔄 проверить 5 аккаунтов": "check",
            "🚀 всё": "all",
            "🚀 сделать всё": "all",
            "🚀 сделать всё (паки+кузня)": "all",
        }
        if lower in text_btn_map:
            act_c = text_btn_map[lower]
            send_tg_message(f"⏳ Запускаю задачу <code>{act_c}</code>...", add_keyboard=True)
            await task_queue.put((act_c, ""))
            return

        promo_code = ""
        if lower.startswith("/promo "):
            promo_code = raw_text[7:].strip().upper()
        elif not raw_text.startswith("/") and re.match(r"^[A-Za-z0-9_-]{4,32}$", raw_text):
            promo_code = raw_text.upper()

        if promo_code:
            send_tg_message(
                f"🎟 Принят промокод <code>{promo_code}</code>!\n"
                "⏳ Открываю 8 уникальных IP, захожу на 8 аккаунтов, ввожу промокод и проверяю реальное увеличение баланса монет (~40 сек)...",
                add_keyboard=True,
            )
            await task_queue.put(("promo", promo_code))
            return

        send_tg_message(
            "👇 Выберите задачу кнопкой ниже (или просто отправьте промокод одним словом):",
            add_keyboard=True,
        )


async def telegram_direct_poller_loop(task_queue: asyncio.Queue, deadline_ts: float) -> None:
    offset = read_saved_tg_offset()
    if offset == 0:
        initial_upds = await asyncio.to_thread(fetch_tg_updates_sync, -1, 1)
        if initial_upds:
            offset = int(initial_upds[-1]["update_id"]) + 1
            write_saved_tg_offset(offset)

    yml_ver = os.environ.get("WORKFLOW_YML_VERSION", "OLD_v24_NO_SECRETS")
    loaded_idxs = [str(a["idx"]) for a in FARM_ACCOUNTS if a.get("password")]
    log_debug(
        f"[DAEMON READY] Прямой Telegram Long Polling запущен (offset={offset}, workflow={yml_ver}, "
        f"пароли загружены для {len(loaded_idxs)}/8 акков: {loaded_idxs or 'НЕТ (обновите .github/workflows/check_senkuro.yml!)'}) — сервер 100% готов!"
    )
    if os.environ.get("GH_EVENT_NAME") == "push":
        send_tg_message(
            "🟢 <b>Сервер полностью запущен и готов к работе (v28.0)!</b>\n\n"
            "Браузер Google Chrome и виртуальный экран готовы — теперь любая кнопка сработает сразу 👇:",
            add_keyboard=True,
        )
    while time.time() < deadline_ts:
        updates = await asyncio.to_thread(fetch_tg_updates_sync, offset, 4)
        for upd in updates:
            uid = int(upd.get("update_id") or 0)
            if uid >= offset:
                offset = uid + 1
                write_saved_tg_offset(offset)
            try:
                await handle_telegram_update(upd, task_queue)
            except Exception as e:
                print(f"[TG UPDATE ERROR] {e}")
        await asyncio.sleep(0.3)


async def task_executor_loop(task_queue: asyncio.Queue, deadline_ts: float) -> None:
    global ACTIVE_JOB_TASK, FARM_STOP_FLAG
    while time.time() < deadline_ts:
        try:
            item = await asyncio.wait_for(task_queue.get(), timeout=2.0)
        except asyncio.TimeoutError:
            continue
        act_code, p_code = item
        FARM_STOP_FLAG = False
        log_debug(f"[EXECUTOR] Запуск задачи: action={act_code}, promo={p_code or '-'}")
        try:
            ACTIVE_JOB_TASK = asyncio.create_task(execute_single_action(act_code, p_code))
            await ACTIVE_JOB_TASK
        except asyncio.CancelledError:
            log_debug(f"[EXECUTOR CANCELLED] Задача {act_code} остановлена пользователем (СТОП).")
        except Exception as e:
            log_debug(f"[EXECUTOR ERROR] {act_code}: {e}")
            send_tg_message(f"⚠️ Ошибка при выполнении задачи <code>{act_code}</code>: {str(e).replace('<', '&lt;').replace('>', '&gt;')[:400]}", add_keyboard=True)
        finally:
            for _k, _pg in list(ACTIVE_BROWSER_PAGES.items()):
                try:
                    if _pg.is_closed():
                        ACTIVE_BROWSER_PAGES.pop(_k, None)
                except Exception:
                    ACTIVE_BROWSER_PAGES.pop(_k, None)
            ACTIVE_JOB_TASK = None
            task_queue.task_done()


async def async_main() -> None:
    global PENDING_TASKS, ACTIVE_FARM_TASK
    parser = argparse.ArgumentParser(description="Senkuro Full Automation Combine v28.0")
    parser.add_argument(
        "--action",
        default=os.environ.get("SENKURO_ACTION", "daemon").strip().lower() or "daemon",
        choices=["check", "menu", "daemon", "promo", "balance", "packs", "forge", "farm", "farm_part1", "farm_part2", "farm_status", "all"],
    )
    parser.add_argument(
        "--promo-code",
        default=os.environ.get("SENKURO_PROMO_CODE", "").strip(),
    )
    args = parser.parse_args()

    configure_telegram_bot_profile()

    global GLOBAL_DEADLINE_TS
    PENDING_TASKS = asyncio.Queue()
    deadline_ts = time.time() + 4.1 * 3600.0
    GLOBAL_DEADLINE_TS = deadline_ts

    # 1. Загружаем все команды, которые пользователь успел нажать за 40 секунд установки браузера!
    if EARLY_QUEUE_FILE.exists():
        try:
            lines = EARLY_QUEUE_FILE.read_text(encoding="utf-8").strip().splitlines()
            EARLY_QUEUE_FILE.unlink(missing_ok=True)
            for ln in lines:
                if not ln.strip():
                    continue
                obj = json.loads(ln)
                e_act = str(obj.get("action") or "").strip().lower()
                e_prm = str(obj.get("promo_code") or "").strip()
                if e_act == "farm":
                    await execute_single_action("farm", "")
                elif e_act:
                    await PENDING_TASKS.put((e_act, e_prm))
        except Exception as e:
            print(f"[EARLY QUEUE WARNING] {e}")

    # 2. Проверяем, нужно ли автоматически продолжить 8-часовой фарм с сохраненной минуты.
    # ВАЖНО: продолжаем фарм ТОЛЬКО во 2-м и 3-м джобах одного и того же запуска (IS_CONTINUATION_JOB=true или farm_part2),
    # а при обычном старте (push / расписание / первый джоб) удаляем старый farm_resume.json из кэша GitHub Actions,
    # чтобы давно остановленный фарм НИКОГДА сам не воскресал из старого кэша!
    is_continuation = (args.action == "farm_part2") or (os.environ.get("IS_CONTINUATION_JOB", "").strip().lower() == "true")
    should_resume_farm = False
    elapsed_prev = 240
    if FARM_RESUME_FILE.exists():
        if is_continuation:
            try:
                st_data = json.loads(FARM_RESUME_FILE.read_text(encoding="utf-8"))
                saved_at = float(st_data.get("saved_at") or 0)
                cur_run_id = os.environ.get("GITHUB_RUN_ID", "").strip()
                file_run_id = str(st_data.get("run_id") or "").strip()
                # Проверяем, что файл создан в текущем workflow run (или не старше 20 минут)
                if st_data.get("active") and (not cur_run_id or not file_run_id or cur_run_id == file_run_id) and (saved_at == 0 or (time.time() - saved_at) < 1800):
                    elapsed_prev = int(st_data.get("elapsed_minutes") or 240)
                    should_resume_farm = True
                else:
                    log_debug("[FARM CACHE CLEAN] Удалён устаревший farm_resume.json из прошлого запуска.")
                    FARM_RESUME_FILE.unlink(missing_ok=True)
            except Exception:
                FARM_RESUME_FILE.unlink(missing_ok=True)
        else:
            log_debug("[FARM CACHE CLEAN] Очищен старый farm_resume.json из кэша GitHub Actions при новом запуске сервера.")
            FARM_RESUME_FILE.unlink(missing_ok=True)

    if should_resume_farm:
        rem_hours = max(0.25, (480 - elapsed_prev) / 60.0)
        log_debug(f"[FARM AUTO-RESUME] Продолжаю 8ч фарм во 2/3 этапе (уже прошло {elapsed_prev} мин из 480, осталось {rem_hours:.2f} ч)!")
        ACTIVE_FARM_TASK = asyncio.create_task(run_background_8h_farm(elapsed_prev, min(4.0, rem_hours)))
    elif args.action not in ("daemon", "menu"):
        if args.action in ("farm", "farm_part1"):
            await execute_single_action("farm", "")
        else:
            await PENDING_TASKS.put((args.action, args.promo_code))

    if os.environ.get("GITHUB_ACTIONS") != "true":
        # Локальный однократный запуск вне GitHub Actions
        while not PENDING_TASKS.empty():
            act_c, prm_c = await PENDING_TASKS.get()
            await execute_single_action(act_c, prm_c)
        if ACTIVE_FARM_TASK:
            await ACTIVE_FARM_TASK
        return

    # 3. Запускаем прямой Telegram-поллер и обработчик задач параллельно на 4.1 часа
    poller_task = asyncio.create_task(telegram_direct_poller_loop(PENDING_TASKS, deadline_ts))
    executor_task = asyncio.create_task(task_executor_loop(PENDING_TASKS, deadline_ts))

    await asyncio.gather(poller_task, executor_task, return_exceptions=True)

    if ACTIVE_FARM_TASK and not ACTIVE_FARM_TASK.done():
        ACTIVE_FARM_TASK.cancel()
        try:
            await ACTIVE_FARM_TASK
        except Exception:
            pass

    # Передаём эстафету во 2-й джоб воркфлоу, чтобы сервер работал непрерывно 8+ часов
    gh_out = os.environ.get("GITHUB_OUTPUT", "")
    if gh_out:
        try:
            with open(gh_out, "a", encoding="utf-8") as f_out:
                f_out.write("continue_bot=true\n")
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(async_main())