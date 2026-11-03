#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SENKURO FULL AUTOMATION COMBINE v15.0 (100% TELEGRAM -> CLOUDFLARE -> GITHUB)
================================================================================
Полный единый комбайн (Kaggle больше НЕ нужен — всё запускается из Telegram!):
1. ▶️ Запустить фарм (8 ч) (--action farm_part1 / farm_part2 / farm):
   - Запускается прямо с кнопки в Telegram на 8 часов (2 этапа по 4 часа в одном
     воркфлоу GitHub Actions с передачей сессий через артефакты).
   - Поднимает виртуальный экран Xvfb (реальный браузер без headless-ограничений),
     4 изолированных туннеля opera-proxy (4 разных IP), входит в 4 аккаунта,
     подключает полный боевой скрипт Senkuro Automation Suite v4.0 (анти-сон через
     Web Worker + AudioContext + WebLocks + requestAnimationFrame, сбор карт в 2 этапа,
     прокрутка закладок в самый низ, автоскролл глав и смена манги в конце).
   - Присылает отчет в Telegram при старте (когда все 4 аккаунта открыли главы)
     и финальный отчет ровно через 8 часов (без лишних уведомлений за 5 минут).
2. 📊 Проверить статус фарма (--action farm_status):
   - Показывает живую сводку: сколько времени идет фарм, какие IP у 4 аккаунтов,
     читают ли они сейчас главы манги и какие именно тайтлы открыты.
3. 🎟 Ввести промокод (--action promo --promo-code КОД):
   - Заходит на 4 фарм-аккаунта под их уникальными IP, проверяет баланс ДО,
     вводит промокод, запрашивает свежий баланс с сервера ПОСЛЕ, строго проверяет,
     что монеты реально начислились (after > before), и пишет финальный баланс.
4. 🪙 Баланс монет (4 акка) (--action balance):
   - Прямая кнопка без подменю: заходит на 4 фарм-аккаунта и показывает точное
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
7. 🔄 Проверить 5 аккаунтов (--action check):
   - Стандартная проверка карт и осколков всех 5 аккаунтов с альбомами фотографий.
================================================================================
"""

import argparse
import asyncio
import json
import os
import platform
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

TELEGRAM_BOT_TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    or "8868493953:AAHyGgQCt4n2FrvyL6mPmFK8w1fq_LNpug4"
)
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
        with open(DEBUG_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

FARM_STATE_SYNC_TOPIC = "senkuro_cesium254_v8_state_sync"

MAIN_ACCOUNT_SLUG = "cesium254"
MAIN_ACCOUNT_URL = f"https://senkuro.com/users/{MAIN_ACCOUNT_SLUG}"

FARM_ACCOUNTS = [
    {
        "idx": 1,
        "acc_id": "acc_1",
        "id": "ber_turtle",
        "label": "First (Ber Turtle)",
        "login": os.environ.get("SENKURO_LOGIN_1", "zerovillbusiness@gmail.com"),
        "password": os.environ.get("SENKURO_PASS_1", "Zazceq-2gukmy-vudhog"),
        "pinned_ip": "77.111.244.37",
        "proxy_port": 25341,
        "url": "https://senkuro.com/users/ber_turtle/cards",
        "bookmarks_url": "https://senkuro.com/users/ber_turtle/bookmarks",
    },
    {
        "idx": 2,
        "acc_id": "acc_2",
        "id": "ainz",
        "label": "Second (Ainz)",
        "login": os.environ.get("SENKURO_LOGIN_2", "dert124689@gmail.com"),
        "password": os.environ.get("SENKURO_PASS_2", "hohFac-segqyx-guwnu8"),
        "pinned_ip": "77.111.244.209",
        "proxy_port": 25342,
        "url": "https://senkuro.com/users/ainz/cards",
        "bookmarks_url": "https://senkuro.com/users/ainz/bookmarks",
    },
    {
        "idx": 3,
        "acc_id": "acc_3",
        "id": "catswat",
        "label": "Third (Cat Swat)",
        "login": os.environ.get("SENKURO_LOGIN_3", "gamerecapbusiness@gmail.com"),
        "password": os.environ.get("SENKURO_PASS_3", "ryhxoQ-wudny1-worsum"),
        "pinned_ip": "77.111.244.210",
        "proxy_port": 25343,
        "url": "https://senkuro.com/users/catswat/cards",
        "bookmarks_url": "https://senkuro.com/users/catswat/bookmarks",
    },
    {
        "idx": 4,
        "acc_id": "acc_4",
        "id": "wolfrice",
        "label": "Fourth (Wolf Rice)",
        "login": os.environ.get("SENKURO_LOGIN_4", "gameepicenterbusiness@gmail.com"),
        "password": os.environ.get("SENKURO_PASS_4", "hyqki0-gamhod-byzhaN"),
        "pinned_ip": "77.111.246.8",
        "proxy_port": 25344,
        "url": "https://senkuro.com/users/wolfrice/cards",
        "bookmarks_url": "https://senkuro.com/users/wolfrice/bookmarks",
    },
]

ALL_CHECK_ACCOUNTS = FARM_ACCOUNTS + [
    {
        "idx": 5,
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

def get_main_inline_keyboard() -> dict:
    """
    Базовая панель кнопок (в режиме DEBUG_MODE добавляет ряд «📸 Посмотреть экран» и «📜 Полный лог»).
    """
    rows = [
        [
            {"text": "▶️ Запустить фарм (8 ч)", "callback_data": "start_farm_8h"},
            {"text": "📊 Проверить статус фарма", "callback_data": "check_farm_status"},
        ],
        [
            {"text": "🎟 Ввести промокод", "callback_data": "prompt_promo"},
            {"text": "🪙 Баланс монет (4 акка)", "callback_data": "check_balance"},
        ],
        [
            {"text": "🎴 Крутить паки Хардкор", "callback_data": "roll_packs"},
            {"text": "⚒️ Переплавка + Трейд", "callback_data": "run_forge"},
        ],
        [
            {"text": "🔄 Проверить 5 аккаунтов", "callback_data": "check_senkuro"},
            {"text": "🚀 Сделать ВСЁ (Паки+Кузня)", "callback_data": "run_all"},
        ],
    ]
    if DEBUG_MODE:
        rows.append(
            [
                {"text": "📸 Посмотреть экран", "callback_data": "view_screen"},
                {"text": "📜 Полный лог (Файл+GitHub)", "callback_data": "dump_full_log"},
            ]
        )
    rows.append(
        [
            {"text": "🛑 ОСТАНОВИТЬ ФАРМ / ВСЕ ЗАДАЧИ", "callback_data": "stop_all_farm"},
        ]
    )
    return {"inline_keyboard": rows}


def get_collapsible_reply_keyboard() -> dict:
    """
    Компактная сворачиваемая нижняя клавиатура Telegram (значок 🎛 справа в поле ввода
    позволяет свободно сворачивать и разворачивать панель, а короткие подписи полностью
    помещаются на экране любого телефона без обрезки!).
    """
    rows = [
        [{"text": "▶️ Фарм (8 ч)"}, {"text": "📊 Статус фарма"}],
        [{"text": "🪙 Баланс монет"}, {"text": "🎴 Паки Хардкор"}],
        [{"text": "⚒️ Кузня + Трейд"}, {"text": "🎟 Промокод"}],
        [{"text": "🔄 Чекать 5 акков"}, {"text": "🚀 Сделать ВСЁ"}],
    ]
    if DEBUG_MODE:
        rows.append([{"text": "📸 Экран"}, {"text": "📜 Лог"}, {"text": "🛑 СТОП"}])
    else:
        rows.append([{"text": "🛑 СТОП"}])
    return {
        "keyboard": rows,
        "resize_keyboard": True,
        "is_persistent": False,
        "input_field_placeholder": "Промокод или меню 🎛 👇",
    }


def tg_request(method: str, payload: dict) -> dict:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print(f"[DRY-RUN] {method}: {json.dumps(payload, ensure_ascii=False)[:300]}")
        return {"ok": True}
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            print(f"[TG OK] {method}")
            return res_data
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="ignore")
        print(f"[TG ERROR] {method} ({e.code}): {err_body}")
        return {"ok": False, "error": err_body}
    except Exception as e:
        print(f"[TG ERROR] {method}: {e}")
        return {"ok": False, "error": str(e)}


_REPLY_KB_INITIALIZED: bool = False


def send_tg_message(text: str, add_keyboard: bool = True, force_reply_kb: bool = False) -> dict:
    global _REPLY_KB_INITIALIZED
    payload: dict[str, Any] = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    # Прикрепляем только нижнюю сворачиваемую клавиатуру (без дублирования гигантских верхних inline-кнопок!)
    if force_reply_kb or (add_keyboard and not _REPLY_KB_INITIALIZED):
        payload["reply_markup"] = get_collapsible_reply_keyboard()
        _REPLY_KB_INITIALIZED = True
    return tg_request("sendMessage", payload)


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
    if add_keyboard and not _REPLY_KB_INITIALIZED:
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
            "User-Agent": "SenkuroBot/15.0",
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


async def send_live_screen_snapshot(custom_caption: str = "") -> None:
    """
    Делает моментальный скриншот открытых вкладок браузера через CDP за 0.05 сек
    и отправляет фотографию прямо в Telegram без блокировки потока!
    """
    sent_any = False
    for label, pg in list(ACTIVE_BROWSER_PAGES.items()):
        try:
            if pg.is_closed():
                ACTIVE_BROWSER_PAGES.pop(label, None)
                continue
            png_data = await capture_page_png_fast(pg)
            if not png_data:
                continue
            try:
                t_str = await pg.title()
            except Exception:
                t_str = ""
            cap = (
                f"📸 <b>Экран браузера: {label}</b>\n"
                f"🌐 URL: <code>{pg.url[:120]}</code>\n"
                f"📄 Заголовок: <i>{t_str[:80]}</i>"
            )
            if custom_caption:
                cap = f"{custom_caption}\n\n" + cap
            await asyncio.to_thread(send_tg_photo_bytes, png_data, cap, True)
            sent_any = True
        except Exception as e:
            log_debug(f"[SCREENSHOT WARNING] {label}: {e}")

    if not sent_any:
        send_tg_message(
            "⚪ <b>Сейчас ни одно окно браузера не открыто</b> (сервер в режиме ожидания).\n\n"
            "Запустите любую задачу (например, «🪙 Баланс монет» или «▶️ Запустить фарм»), и прямо во время её работы нажимайте <b>«📸 Посмотреть экран»</b>!",
            add_keyboard=True,
        )


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
        {"command": "check", "description": "🔄 Проверить карты и осколки (5 аккаунтов)"},
        {"command": "balance", "description": "🪙 Баланс монет на 4 аккаунтах"},
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
    print(f"[VPN] Скачивание {asset} с GitHub...")
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
    """Поднимает и контролирует 4 изолированных VPN-туннеля (строго разные IP на каждый из 4 аккаунтов)."""

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
            ok, ip = verify_proxy_exit_ip(port, timeout=2.5)
            if ok:
                self.active_ips[aid] = ip
                print(f"[VPN] {acc['id']}: используется активный туннель 127.0.0.1:{port} -> {ip}")
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
                        print(f"[VPN] {acc['id']}: закреплен уникальный IP {ip} (порт {port})")
                        return f"http://127.0.0.1:{port}"
                    elif ok and ip:
                        used_ips.add(ip)

        regions = ["AM", "AS", "EU"] if not pinned_ip.startswith("77.111.244.") else ["EU", "AM", "AS"]
        for idx_try, region in enumerate(regions, start=1):
            self._stop_proc(aid)
            b_path = self._write_blacklist(aid, used_ips)
            args = [
                exe_path,
                "-bind-address", f"127.0.0.1:{port}",
                "-country", region,
                "-discover-repeat", "3",
                "-proxy-blacklist", b_path,
                "-server-selection", "first" if idx_try == 1 else "random",
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
                    print(f"[VPN] {acc['id']} ({region}): закреплен уникальный IP {ip} (порт {port})")
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
            return await playwright_obj.chromium.launch(
                executable_path=chrome_bin,
                headless=not has_display,
                ignore_default_args=["--enable-automation"],
                args=launch_args,
            )
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
    # ВАЖНО: НЕ подменяем user_agent на Windows внутри Linux и НЕ блокируем service_workers!
    # На сервере Kaggle использовался родной User-Agent Google Chrome для Linux — именно из-за несовпадения
    # Windows User-Agent и navigator.platform=="Linux x86_64" капча на sso.senkuro.org выдавала ошибку!
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
    await ctx.add_init_script(
        """
        Object.defineProperty(navigator, webdriver, {get: () => false});
        if (!window.chrome) { window.chrome = { runtime: {} }; }
        """
    )
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
        return v_user

    if not dom_state.get("hasLoginBtn") and "senkuro.com" in str(dom_state.get("url", "")) and "/auth/" not in str(dom_state.get("url", "")):
        u_res = await gql_call(page, GQL_FETCH_USER_BY_SLUG, {"slug": acc_slug}, "fetchUserBySlug")
        u_obj = (u_res.get("data") or {}).get("user") or {}
        if isinstance(u_obj, dict) and u_obj.get("id"):
            log_debug(f"[AUTH DOM+SLUG OK] {acc_slug}: вход подтвержден по отсутствию кнопки 'Войти' (id={u_obj['id']})")
            return u_obj
        if dom_state.get("hasTokenCookie") or dom_state.get("hasProfileLink"):
            log_debug(f"[AUTH DOM OK] {acc_slug}: вход подтвержден по куке/профилю в шапке")
            return {"id": acc_slug, "slug": acc_slug, "points": 0}

    return None


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
        elif "sso.senkuro.org" in u_str and (resp.request.method == "POST" or resp.status >= 400):
            try:
                body_preview = (await resp.text())[:300]
            except Exception:
                body_preview = ""
            log_debug(f"[SSO HTTP] {acc['id']}: {resp.request.method} {u_str[:100]} -> status={resp.status} body={body_preview}")

    page.on("response", on_gql_or_sso_resp)

    target_start_url = acc.get("bookmarks_url") or f"https://senkuro.com/users/{acc['id']}/bookmarks"
    log_debug(f"[AUTH START] {acc['id']}: открываю {target_start_url}")
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

    if not acc.get("login") or not acc.get("password"):
        return page, None

    log_debug(f"[AUTH LOGIN] {acc['id']}: выполняю вход через SSO ({acc['login']})...")

    for attempt in range(1, 3):
        try:
            if "senkuro.com" in page.url and "sso.senkuro" not in page.url:
                clicked = await page.evaluate(
                    """() => {
                        const btn = Array.from(document.querySelectorAll('a, button')).find(el => {
                            const t = (el.innerText || el.textContent || '').trim();
                            return t === 'Войти' || t === 'Вход';
                        });
                        if (btn) { btn.click(); return true; }
                        return false;
                    }"""
                )
                log_debug(f"[AUTH] {acc['id']} (попытка #{attempt}): клик 'Войти' = {clicked} (url={page.url})")
        except Exception as e:
            log_debug(f"[AUTH CLICK WARN] {acc['id']}: {e}")

        # Ждем перехода на sso.senkuro.org (до 12 сек)
        for _ in range(15):
            await page.wait_for_timeout(800)
            if "sso.senkuro." in page.url:
                break

        if "sso.senkuro." in page.url:
            # 1. Ждем, пока форма на sso.senkuro.org полностью отрисуется (до 10 сек)
            for _ in range(12):
                await page.wait_for_timeout(800)
                has_pass = await page.evaluate("() => !!document.querySelector('input[type=password]')")
                if has_pass:
                    break

            # 2. ВАЖНО: Даем скрипту капчи на sso.senkuro.org спокойно докачаться через прокси (3.5 сек)
            # и делаем плавные движения мышью, как живой пользователь (иначе капча выдает «Ошибка при прохождении капчи»!)
            try:
                await page.mouse.move(260, 240, steps=8)
                await page.wait_for_timeout(1200)
                await page.mouse.move(540, 380, steps=10)
                await page.wait_for_timeout(2000)
            except Exception:
                await page.wait_for_timeout(3000)

            # 3. Логируем информацию о капче и форме (и при попытке #1 заполняем ровно 1 раз методом Kaggle v6.5!)
            sso_fill_info = await page.evaluate(
                """({ loginStr, passStr, doNativeFill }) => {
                    function isVis(el) {
                        if (!el) return false;
                        const r = el.getBoundingClientRect();
                        return r.width > 5 && r.height > 5 && window.getComputedStyle(el).visibility !== 'hidden';
                    }
                    function setNativeVal(el, val) {
                        if (!el) return;
                        el.focus();
                        const proto = el.tagName === 'TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
                        const desc = Object.getOwnPropertyDescriptor(proto, 'value');
                        if (desc && desc.set) desc.set.call(el, val);
                        else el.value = val;
                        el.dispatchEvent(new Event('input', { bubbles: true }));
                        el.dispatchEvent(new Event('change', { bubbles: true }));
                    }

                    const allInputs = Array.from(document.querySelectorAll('input')).filter(isVis);
                    const passInput = allInputs.find(i => i.type === 'password');
                    const userInput = allInputs.find(i => i.type !== 'password' && i.type !== 'checkbox' && i.type !== 'hidden');

                    const scripts = Array.from(document.querySelectorAll('script[src]')).map(s => s.src).filter(u => /captcha|turnstile|recaptcha|hcaptcha|smart|cf|challenge/i.test(u));
                    const iframes = Array.from(document.querySelectorAll('iframe')).map(f => ({
                        src: (f.src || '').slice(0, 120),
                        w: Math.round(f.getBoundingClientRect().width),
                        h: Math.round(f.getBoundingClientRect().height),
                        x: Math.round(f.getBoundingClientRect().left + f.getBoundingClientRect().width / 2),
                        y: Math.round(f.getBoundingClientRect().top + f.getBoundingClientRect().height / 2)
                    }));
                    const hiddenInputs = Array.from(document.querySelectorAll('input[type="hidden"], textarea[name*="captcha"], textarea[name*="response"]')).map(i => ({
                        name: i.name || i.id || '',
                        valLen: (i.value || '').length
                    }));

                    if (doNativeFill) {
                        if (userInput) setNativeVal(userInput, loginStr);
                        if (passInput) setNativeVal(passInput, passStr);
                    }

                    const allBtns = Array.from(document.querySelectorAll('button, input[type="submit"], [role="button"]')).filter(isVis);
                    let targetBtn = allBtns.find(b => {
                        const t = (b.innerText || b.value || '').trim().toLowerCase();
                        return t === 'продолжить' || t === 'войти' || t === 'вход' || t === 'login' || t === 'sign in' ||
                               t.includes('продолжить') || t.includes('войти');
                    });

                    return {
                        foundUser: !!userInput,
                        foundPass: !!passInput,
                        targetBtnText: targetBtn ? (targetBtn.innerText || '').trim() : null,
                        ua: navigator.userAgent,
                        platform: navigator.platform,
                        webdriver: navigator.webdriver,
                        hasGrecaptcha: typeof window.grecaptcha !== 'undefined',
                        hasTurnstile: typeof window.turnstile !== 'undefined',
                        hasSmartCaptcha: typeof window.smartCaptcha !== 'undefined',
                        scripts,
                        iframes,
                        hiddenInputs
                    };
                }""",
                {"loginStr": acc["login"], "passStr": acc["password"], "doNativeFill": attempt == 1},
            )
            log_debug(f"[SSO CAPTCHA DIAG] {acc['id']} (попытка #{attempt}): {json.dumps(sso_fill_info, ensure_ascii=False)}")

            # Если на странице есть видимый iframe капчи (Turnstile / SmartCaptcha / reCAPTCHA checkbox) — кликаем по чекбоксу и ждем 2.5 сек
            try:
                for ifr in sso_fill_info.get("iframes") or []:
                    if ifr.get("w", 0) >= 30 and ifr.get("h", 0) >= 25 and ifr.get("x", 0) > 0 and ifr.get("y", 0) > 0:
                        click_x = int(ifr["x"]) - min(80, int(ifr["w"]) // 3)
                        click_y = int(ifr["y"])
                        log_debug(f"[SSO CAPTCHA CLICK] {acc['id']}: клик по чекбоксу капчи ({click_x}, {click_y})")
                        await page.mouse.move(click_x, click_y, steps=6)
                        await page.mouse.click(click_x, click_y)
                        await page.wait_for_timeout(2500)
            except Exception as e:
                log_debug(f"[SSO CAPTCHA CLICK WARN] {e}")

            try:
                u_loc = page.locator('input:visible:not([type="password"]):not([type="checkbox"]):not([type="hidden"])').first
                p_loc = page.locator('input[type="password"]:visible').first
                if attempt >= 2:
                    # На 2-й попытке вводим посимвольно с человеческой задержкой 50 мс между клавишами
                    if await u_loc.count() > 0:
                        await u_loc.click()
                        await u_loc.fill("")
                        await u_loc.press_sequentially(acc["login"], delay=50)
                    await page.wait_for_timeout(400)
                    if await p_loc.count() > 0:
                        await p_loc.click()
                        await p_loc.fill("")
                        await p_loc.press_sequentially(acc["password"], delay=50)

                # Пауза 1.2 сек после заполнения перед кликом «Войти» (как в Kaggle v6.5: setTimeout 650ms+)
                await page.wait_for_timeout(1200)

                btn_clicked = False
                for btn_txt in ("Продолжить", "Войти", "Вход", "Login", "Sign in"):
                    b_loc = page.locator(f'button:visible:has-text("{btn_txt}")').first
                    if await b_loc.count() > 0:
                        await b_loc.click()
                        btn_clicked = True
                        log_debug(f"[SSO SUBMIT] {acc['id']}: нажата кнопка '{btn_txt}'")
                        break
                if not btn_clicked and await p_loc.count() > 0:
                    await p_loc.press("Enter")
                    log_debug(f"[SSO SUBMIT] {acc['id']}: нажат Enter в поле пароля")
            except Exception as e:
                log_debug(f"[SSO PLAYWRIGHT SUBMIT WARN] {acc['id']}: {e}")

            # СПОКОЙНО ждём до 18 секунд завершения входа и редиректа (без авто-спама вторым скриншотом!)
            logged_6s_text = False
            for wait_sec in range(18):
                await page.wait_for_timeout(1000)
                cur_u = page.url

                # Если sso.senkuro.org перешёл на экран разрешения OAuth (/oauth/authorize) — нажимаем «Разрешить» / «Продолжить»
                if "sso.senkuro.org" in cur_u and ("/oauth/" in cur_u or "/account" in cur_u):
                    try:
                        await page.evaluate(
                            """() => {
                                const b = Array.from(document.querySelectorAll('button, a')).find(el => {
                                    const t = (el.innerText || '').trim().toLowerCase();
                                    return t.includes('разрешить') || t.includes('продолжить') || t.includes('авториз') || t.includes('allow') || t.includes('continue');
                                });
                                if (b) b.click();
                            }"""
                        )
                    except Exception:
                        pass

                if wait_sec == 6 and "sso.senkuro.org/auth/login" in cur_u and not logged_6s_text:
                    logged_6s_text = True
                    try:
                        page_txt = await page.evaluate("() => (document.body ? document.body.innerText : '').trim().slice(0, 500)")
                        log_debug(f"[SSO AFTER 6s] {acc['id']}: url={cur_u} | text={page_txt!r}")
                        if "капч" in page_txt.lower() or "что-то пошло не так" in page_txt.lower():
                            # Если на 1-й попытке выскочила ошибка капчи — не ждём лишние 12 сек, сразу переходим ко 2-й попытке с посимвольным вводом!
                            break
                    except Exception as e:
                        log_debug(f"[SSO 6S DIAG ERR] {e}")

                if "senkuro.com" in cur_u and "sso.senkuro" not in cur_u and "/auth/" not in cur_u:
                    await page.wait_for_timeout(1500)
                    u_now = await check_is_authenticated_on_senkuro(page, acc["id"], intercepted_user)
                    if u_now:
                        log_debug(f"[AUTH SUCCESS] {acc['id']}: вход успешно выполнен (id={u_now.get('id')})")
                        await context.storage_state(path=str(get_session_file(acc["id"])))
                        return page, u_now

        # Проверяем на основной странице
        try:
            await page.goto(target_start_url, wait_until="domcontentloaded", timeout=35000)
            await page.wait_for_timeout(2000)
            u_final = await check_is_authenticated_on_senkuro(page, acc["id"], intercepted_user)
            if u_final:
                log_debug(f"[AUTH SUCCESS AFTER RELOAD] {acc['id']}: вход выполнен!")
                await context.storage_state(path=str(get_session_file(acc["id"])))
                return page, u_final
        except Exception as e:
            log_debug(f"[AUTH RELOAD WARN] {acc['id']}: {e}")

    # Если войти не удалось — записываем финальную диагностику и делаем мгновенный CDP-скриншот
    try:
        diag_info = await page.evaluate(
            "() => ({ url: location.href, title: document.title, text: (document.body ? document.body.innerText : '').slice(0, 600) })"
        )
        log_debug(f"[AUTH FAILED DIAG] {acc['id']}: {json.dumps(diag_info, ensure_ascii=False)}")
        if DEBUG_MODE:
            png_err = await capture_page_png_fast(page)
            if png_err:
                await asyncio.to_thread(
                    send_tg_photo_bytes,
                    png_err,
                    f"⚠️ <b>Авто-скриншот ошибки входа ({acc['id']}):</b>\n"
                    f"🌐 URL: <code>{page.url[:120]}</code>\n"
                    f"📄 Текст на экране: <code>{str(diag_info.get('text', ''))[:250]}</code>",
                    False,
                )
    except Exception as e:
        log_debug(f"[AUTH DIAG SCREENSHOT ERR] {acc['id']}: {e}")

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
    code_clean = (promo_code or "").strip().upper()
    if not code_clean:
        send_tg_message("⚠️ Промокод не указан. Нажмите «🎟 Ввести промокод» и отправьте код ответным сообщением.")
        return

    send_tg_message(
        f"⏳ Запускаю 4 изолированных IP-туннеля, вхожу на 4 аккаунта и активирую промокод <code>{code_clean}</code>...",
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
                log_debug(f"[BALANCE STEP] #{acc['idx']}/4 {acc['id']} -> IP: {ip_used}")
                send_tg_message(f"⏳ <b>[{acc['idx']}/4] {acc['id']}</b> (IP: <code>{ip_used}</code>): проверяю вход и баланс...", add_keyboard=False)
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

    report_lines.insert(1, f"📊 Итог проверки: монеты реально увеличились на <b>{success_count} из 4</b> аккаунтов.\n")
    send_tg_message("\n".join(report_lines), add_keyboard=True)


# ==============================================================================
# 7. СЦЕНАРИЙ 2: ПРОВЕРКА БАЛАНСА МОНЕТ (4 АККА) И КРУТКА ПАКОВ «ХАРДКОР»
# ==============================================================================

async def run_check_coins_balance() -> None:
    """Проверяет баланс сенкоинов на всех 4 фарм-аккаунтах и возвращает базовую панель кнопок."""
    send_tg_message("🪙 Вхожу на 4 фарм-аккаунта под своими IP и проверяю баланс сенкоинов...", add_keyboard=False)
    proxy_mgr = AccountProxyManager()
    lines = ["🪙 <b>Баланс сенкоинов на 4 фарм-аккаунтах:</b>\n"]
    total_coins = 0
    total_packs_possible = 0

    try:
        async with async_playwright() as p:
            browser = await launch_senkuro_browser(p)
            for acc in FARM_ACCOUNTS:
                proxy_url = await asyncio.to_thread(proxy_mgr.start_account_proxy, acc)
                ip_used = proxy_mgr.active_ips.get(acc["acc_id"], "прямой")
                log_debug(f"[PROMO STEP] #{acc['idx']}/4 {acc['id']} -> IP: {ip_used}")
                send_tg_message(f"🎟 <b>[{acc['idx']}/4] {acc['id']}</b> (IP: <code>{ip_used}</code> ✅): вхожу и ввожу промокод <code>{code_clean}</code>...", add_keyboard=False)
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

    lines.append(f"\n💰 <b>Всего монет на 4 аккаунтах:</b> {total_coins} 🪙 (доступно прокруток Хардкор: <b>{total_packs_possible}</b>)")
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
    user_id = user_obj["id"]
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
            await gql_call(
                page,
                GQL_BULK_CHOOSE_PACK_OPEN,
                {"input": {"opens": opens_input}},
                "bulkChooseCardPackOpen",
            )

    rolls_available = before_points // pack_cost
    if rolls_available <= 0 and not chosen_cards_summary:
        logs.append(f"недостаточно монет для прокрутки (сейчас <b>{before_points} 🪙</b>, нужно <b>{pack_cost} 🪙</b>)")
        return logs

    for roll_num in range(1, rolls_available + 1):
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

    await page.wait_for_timeout(1000)
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
    send_tg_message("🎰 Захожу на 4 фарм-аккаунта под своими IP и кручу паки «Хардкор» (480 🪙)...", add_keyboard=False)
    proxy_mgr = AccountProxyManager()
    report_lines = ["🎴 <b>Статистика прокрутки паков «Для хардкорщиков» (480 🪙):</b>\n"]

    try:
        async with async_playwright() as p:
            browser = await launch_senkuro_browser(p)
            for acc in FARM_ACCOUNTS:
                proxy_url = await asyncio.to_thread(proxy_mgr.start_account_proxy, acc)
                ip_used = proxy_mgr.active_ips.get(acc["acc_id"], "прямой")
                log_debug(f"[PACKS STEP] #{acc['idx']}/4 {acc['id']} -> IP: {ip_used}")
                send_tg_message(f"🎴 <b>[{acc['idx']}/4] {acc['id']}</b> (IP: <code>{ip_used}</code> ✅): проверяю монеты и кручу паки «Хардкор»...", add_keyboard=False)
                context = await create_account_context(browser, acc, proxy_url)
                try:
                    page, user_obj = await ensure_logged_in(context, acc)
                    if not user_obj:
                        report_lines.append(f"❌ <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): ошибка входа\n")
                        continue
                    acc_logs = await roll_hardcore_packs_for_account(page, acc, user_obj)
                    report_lines.append(f"👤 <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): " + "\n".join(acc_logs) + "\n")
                    await context.storage_state(path=str(get_session_file(acc["id"])))
                finally:
                    await context.close()
                await asyncio.sleep(2.5)
            await browser.close()
    finally:
        proxy_mgr.stop_all()

    send_tg_message("\n".join(report_lines), add_keyboard=True)


# ==============================================================================
# 8. СЦЕНАРИЙ 3: УМНАЯ ПЕРЕПЛАВКА (КУЗНЯ) + МЕЖАККАУНТНЫЙ ТРЕЙД + СБОР НА ОСНОВУ
# ==============================================================================

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
        node = edge.get("node") or {}
        if node.get("status") != "PENDING" or not node.get("viewerCanAccept"):
            continue

        trade_id = node.get("id")
        source_user = node.get("source") or {}
        source_slug = str(source_user.get("slug") or "").strip().lower()
        req_items = node.get("request") or []
        offer_items = node.get("offer") or []

        if source_slug not in ALLOWED_TRADE_SLUGS:
            print(f"[SECURITY BLOCK] {acc_slug}: проигнорирован входящий трейд {trade_id} от ЧУЖОГО игрока '{source_slug}'!")
            continue

        if req_items and source_slug not in ALLOWED_TRADE_SLUGS:
            continue

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

    while st["available_slots"] > 0:
        did_forge_in_pass = False
        for r in FORGE_UPGRADE_CHAIN:
            pool = st["craftable_by_rank"].get(r, [])
            if len(pool) >= 3 and st["available_slots"] > 0:
                triple = pool[:3]
                gql_cards = compress_card_units_for_gql(triple)
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

                st["cards_nodes"] = await fetch_all_user_cards_gql(page, st["user_id"], modifier_val=0)
                st["craftable_by_rank"] = expand_craftable_cards_by_rank(st["cards_nodes"])
                break

        if not did_forge_in_pass:
            break

    return forged_count


async def run_smart_forge_and_trade_pipeline() -> None:
    send_tg_message(
        "⚒️ Запускаю умную Кузницу («Переплавка» 3 в 1 до S ранга) и межаккаунтный обмен на 4 аккаунтах...",
        add_keyboard=False,
    )

    proxy_mgr = AccountProxyManager()
    state_map: dict[str, dict] = {}

    try:
        async with async_playwright() as p:
            browser = await launch_senkuro_browser(p)
            contexts: list[BrowserContext] = []

            for acc in FARM_ACCOUNTS:
                proxy_url = await asyncio.to_thread(proxy_mgr.start_account_proxy, acc)
                ip_used = proxy_mgr.active_ips.get(acc["acc_id"], "прямой")
                log_debug(f"[FORGE STEP] #{acc['idx']}/4 {acc['id']} -> IP: {ip_used}")
                send_tg_message(f"⚒️ <b>[{acc['idx']}/4] {acc['id']}</b> (IP: <code>{ip_used}</code> ✅): подключаю кузню и проверяю карты...", add_keyboard=False)
                ctx = await create_account_context(browser, acc, proxy_url)
                contexts.append(ctx)
                page, user_obj = await ensure_logged_in(ctx, acc)
                if not user_obj:
                    continue
                state_map[acc["id"]] = {
                    "acc": acc,
                    "context": ctx,
                    "page": page,
                    "user_id": user_obj["id"],
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
                await browser.close()
                return

            await refresh_farm_state(state_map)
            for aid, st in state_map.items():
                await forge_local_triples_on_account(st)

            for _ in range(15):
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
                    if donor_id == rec_id or need_count <= 0:
                        continue
                    donor_pool = donor["craftable_by_rank"].get(target_rank, [])
                    if not donor_pool:
                        continue

                    take_units = donor_pool[:need_count]
                    offer_payload = compress_card_units_for_gql(take_units)
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
                        await receiver["page"].wait_for_timeout(800)
                        acc_logs = await accept_whitelisted_incoming_trades(receiver["page"], rec_id, rec_uid)
                        receiver["logs"].extend(acc_logs)

                if not transferred_any:
                    break

                await refresh_farm_state(state_map)
                await forge_local_triples_on_account(receiver)

            await refresh_farm_state(state_map)
            remaining_craftable_ranks = {}
            for r in FORGE_UPGRADE_CHAIN:
                tot_r = sum(len(st["craftable_by_rank"].get(r, [])) for st in state_map.values())
                if tot_r >= 3:
                    remaining_craftable_ranks[r] = tot_r

            total_free_slots = sum(st["available_slots"] for st in state_map.values())

            report_lines = ["⚒️ <b>Отчёт работы Кузницы (Переплавка):</b>\n"]
            for aid, st in state_map.items():
                inv_str = format_text_only_inventory_summary(st["cards_nodes"], st["shards_nodes"])
                report_lines.append(
                    f"👤 <b>{aid}</b> (IP: <code>{st['ip']}</code> | Слоты кузни: {st['available_slots']}/5 свободно):"
                )
                if st["logs"]:
                    for lg in st["logs"]:
                        report_lines.append(f"   • {lg}")
                else:
                    report_lines.append("   • Переплавок не требовалось")
                report_lines.append(f"   📦 Сейчас на аккаунте: {inv_str}\n")

            if remaining_craftable_ranks and total_free_slots == 0:
                rem_str = ", ".join(f"{cnt}×{r}" for r, cnt in remaining_craftable_ranks.items())
                report_lines.append(
                    "⏳ <b>Суточные лимиты кузни (5 из 5) на всех 4 аккаунтах исчерпаны!</b>\n"
                    f"Остались карты для дальнейшей переплавки ({rem_str}). "
                    "Трейд на основу <b>cesium254</b> отложен до завтрашнего сброса лимитов, чтобы докачать все карты до конца!"
                )
            else:
                first_page = next(iter(state_map.values()))["page"]
                main_res = await gql_call(first_page, GQL_FETCH_USER_BY_SLUG, {"slug": MAIN_ACCOUNT_SLUG}, "fetchUserBySlug")
                main_user = (main_res.get("data") or {}).get("user")
                if not main_user or not main_user.get("id"):
                    report_lines.append(f"⚠️ Не удалось получить ID основного аккаунта {MAIN_ACCOUNT_SLUG}.")
                else:
                    main_uid = main_user["id"]
                    total_sent_cards: Counter = Counter()
                    total_sent_shards: Counter = Counter()

                    for aid, st in state_map.items():
                        all_offer_entries = []
                        for node in st["cards_nodes"]:
                            if node.get("locked"):
                                continue
                            cid = (node.get("card") or {}).get("id") or node.get("cardId")
                            qty = int(node.get("quantity") or 1)
                            mod = int(node.get("modifier") or 0)
                            rank = str((node.get("card") or {}).get("rank") or "?").upper()
                            if cid and qty > 0:
                                all_offer_entries.append({"cardId": cid, "modifier": mod, "quantity": qty})
                                total_sent_cards[rank] += qty

                        for node in st["shards_nodes"]:
                            if node.get("locked"):
                                continue
                            cid = (node.get("card") or {}).get("id") or node.get("cardId")
                            qty = int(node.get("quantity") or 1)
                            mod = int(node.get("modifier") or 1)
                            rank = str((node.get("card") or {}).get("rank") or "?").upper()
                            if cid and qty > 0:
                                all_offer_entries.append({"cardId": cid, "modifier": mod, "quantity": qty})
                                total_sent_shards[rank] += qty

                        for i in range(0, len(all_offer_entries), 50):
                            chunk = all_offer_entries[i : i + 50]
                            await gql_call(
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

                    if sum(total_sent_cards.values()) > 0 or sum(total_sent_shards.values()) > 0:
                        report_lines.append(
                            f"🎁 <b>Всего хватило, отправляю вам трейд на основу <a href=\"{MAIN_ACCOUNT_URL}\">{MAIN_ACCOUNT_SLUG}</a>:</b>\n"
                            f"🃏 <b>Карты ({sum(total_sent_cards.values())} шт.):</b> {c_summary}\n"
                            f"🧩 <b>Осколки ({sum(total_sent_shards.values())} шт.):</b> {s_summary}"
                        )
                    else:
                        report_lines.append("ℹ️ На фарм-аккаунтах сейчас нет свободных карт или осколков для отправки на основу.")

            for aid, st in state_map.items():
                await st["context"].storage_state(path=str(get_session_file(aid)))
            for ctx in contexts:
                await ctx.close()
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
            if (step < 4) {
                sessionStorage.setItem('senkuro_bm_scroll_step', String(step + 1));
                window.scrollTo({ top: Math.max(0, document.documentElement.scrollHeight - 450), behavior: 'smooth' });
                return;
            }
            sessionStorage.setItem('senkuro_bm_scroll_step', '0');

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
        f"📖 <b>Читают главы сейчас:</b> <b>{reading_cnt}/4</b> аккаунтов | 🌐 <b>Уникальных IP:</b> <b>{unique_ips}/4</b>\n",
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
            "Нажмите кнопку <b>«▶️ Запустить фарм (8 ч)»</b> ниже, чтобы запустить чтение манги на всех 4 аккаунтах!",
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
            "🚀 <b>Запускаю 8-часовой фарм манги на всех 4 аккаунтах!</b>\n"
            "Поднимаю виртуальный экран, 4 уникальных IP, вхожу в аккаунты, выбираю мангу снизу закладок и пришлю сводку через ~45 сек...",
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

            # Ждем до 60 сек, пока все 4 аккаунта откроют чтение главы (/chapters/)
            for _ in range(12):
                await asyncio.sleep(5)
                for s in farm_sessions:
                    try:
                        await s["page"].evaluate(FULL_FARM_USERSCRIPT_V9)
                    except Exception:
                        pass
                if sum(1 for s in farm_sessions if "/chapters/" in s["page"].url) == 4:
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
                    "Все 4 аккаунта остановлены, прогресс чтения и сессии сохранены.\n\n"
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
    Для КАЖДОГО из 5 аккаунтов создаёт свежий изолированный BrowserContext с service_workers='block',
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


def send_account_report(text: str, photo_urls: list[str], add_reply_button: bool = False) -> None:
    chunks = [photo_urls[i : i + 10] for i in range(0, len(photo_urls), 10)]

    if chunks and not add_reply_button and len(chunks) == 1:
        chunk = chunks[0]
        if len(chunk) == 1:
            res = tg_request(
                "sendPhoto",
                {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "photo": chunk[0],
                    "caption": text,
                    "parse_mode": "HTML",
                },
            )
            if res.get("ok"):
                return
        else:
            media = []
            for idx, url in enumerate(chunk):
                item: dict[str, Any] = {"type": "photo", "media": url}
                if idx == 0:
                    item["caption"] = text
                    item["parse_mode"] = "HTML"
                media.append(item)
            res = tg_request("sendMediaGroup", {"chat_id": TELEGRAM_CHAT_ID, "media": media})
            if res.get("ok"):
                return

    for chunk in chunks:
        if len(chunk) == 1:
            tg_request("sendPhoto", {"chat_id": TELEGRAM_CHAT_ID, "photo": chunk[0]})
        else:
            media = [{"type": "photo", "media": url} for url in chunk]
            tg_request("sendMediaGroup", {"chat_id": TELEGRAM_CHAT_ID, "media": media})

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
    log_debug("[TASK START] Запуск проверки всех 5 аккаунтов (поочерёдно с изолированными контекстами)...")
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
        upload_debug_log_to_github_noop("check_5_accounts")


# ==============================================================================
# 11. ПРЯМОЙ ДВИЖОК TELEGRAM LONG POLLING (v15.0 — БЕЗ CLOUDFLARE WORKER!)
# ==============================================================================

CURRENT_FARM_STATUS: dict[str, Any] = {"active": False, "accounts": []}
FARM_STOP_FLAG: bool = False
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
    req = urllib.request.Request(url, headers={"User-Agent": "SenkuroDirectBot/15.0"})
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
            "🚀 <b>Запускаю 8-часовой фарм манги на всех 4 аккаунтах!</b>\n"
            "Поднимаю виртуальный экран, 4 уникальных IP, вхожу в аккаунты, выбираю мангу снизу закладок и пришлю сводку через ~40 сек...",
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
            browser = await p.chromium.launch(
                headless=not has_display,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-background-timer-throttling",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-renderer-backgrounding",
                ],
            )
            for acc in FARM_ACCOUNTS:
                if FARM_STOP_FLAG:
                    break
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

            for _ in range(12):
                if FARM_STOP_FLAG:
                    break
                await asyncio.sleep(5)
                for s in farm_sessions:
                    try:
                        await s["page"].evaluate(FULL_FARM_USERSCRIPT_V9)
                    except Exception:
                        pass
                if sum(1 for s in farm_sessions if "/chapters/" in s["page"].url) == 4:
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
                if base_elapsed_minutes == 0:
                    send_tg_message(
                        "✅ <b>8-часовой фарм манги успешно запущен!</b>\n\n" + format_farm_status_message(initial_snap),
                        add_keyboard=True,
                    )

            end_ts = start_ts + segment_hours * 3600.0
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
            elif final_elapsed >= 475 or base_elapsed_minutes >= 200:
                if FARM_RESUME_FILE.exists():
                    FARM_RESUME_FILE.unlink(missing_ok=True)
                send_tg_message(
                    "🏁 <b>8 часов фарма манги полностью завершены!</b>\n"
                    "Все 4 аккаунта остановлены, прогресс чтения и сессии сохранены.\n\n"
                    + format_farm_status_message(final_snap),
                    add_keyboard=True,
                )
            else:
                # Сохраняем состояние для бесшовного продолжения во 2-й половине воркфлоу (часы 4..8)
                FARM_RESUME_FILE.write_text(
                    json.dumps({"active": True, "elapsed_minutes": max(240, final_elapsed)}),
                    encoding="utf-8",
                )

            for s in farm_sessions:
                await s["context"].close()
            await browser.close()
    except asyncio.CancelledError:
        CURRENT_FARM_STATUS = {"active": False, "accounts": []}
        if FARM_RESUME_FILE.exists():
            FARM_RESUME_FILE.unlink(missing_ok=True)
    finally:
        proxy_mgr.stop_all()


async def execute_single_action(action: str, promo_code: str = "") -> None:
    global ACTIVE_FARM_TASK, FARM_STOP_FLAG
    if action == "menu":
        send_tg_message(
            "✅ <b>Единый комбайн Senkuro v15.0 готов к работе (Прямая связь с GitHub)!</b>\n\n"
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
            send_full_debug_log_to_user("Полный лог работы комбайна v15.0")
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
                "Сервер откроет 4 уникальных IP, зайдёт на каждый из 4 аккаунтов, введёт промокод, "
                "<b>реально проверит увеличение баланса монет</b> и пришлёт результат!",
                add_keyboard=True,
            )
            return

        action_map = {
            "start_farm_8h": ("farm", "▶️ Запускаю 8-часовой фарм манги на 4 аккаунтах!"),
            "check_balance": ("balance", "🪙 Проверяю баланс сенкоинов на 4 фарм-аккаунтах..."),
            "roll_packs": ("packs", "🎴 Запускаю прокрутку паков «Хардкор» (480 🪙)..."),
            "run_forge": ("forge", "⚒️ Запускаю Переплавку (Кузня) + Трейд на основу..."),
            "check_senkuro": ("check", "🔄 Проверяю карты и осколки всех 5 аккаунтов..."),
            "run_all": ("all", "🚀 Запускаю полный цикл (Паки + Переплавка + Трейд)..."),
        }
        act_code, act_label = action_map.get(data, ("check", "🔄 Проверяю карты и осколки всех 5 аккаунтов..."))
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
                "🤖 <b>Панель управления фермой Senkuro v15.0</b>\n\n"
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
            send_full_debug_log_to_user("Полный лог работы комбайна v15.0")
            return

        if lower in ("/stop", "🛑 стоп", "стоп", "🛑 остановить фарм / все задачи"):
            FARM_STOP_FLAG = True
            if FARM_RESUME_FILE.exists():
                FARM_RESUME_FILE.unlink(missing_ok=True)
            if ACTIVE_JOB_TASK and not ACTIVE_JOB_TASK.done():
                ACTIVE_JOB_TASK.cancel()
            CURRENT_FARM_STATUS = {"active": False, "accounts": []}
            send_tg_message("🛑 <b>Фарм и все активные задачи остановлены!</b>", add_keyboard=True)
            return

        if lower in ("/status", "📊 статус фарма", "📊 проверить статус фарма"):
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
            "🪙 баланс монет": "balance",
            "🪙 баланс монет (4 акка)": "balance",
            "/packs": "packs",
            "🎴 паки хардкор": "packs",
            "🎴 крутить паки хардкор": "packs",
            "/forge": "forge",
            "⚒️ кузня + трейд": "forge",
            "⚒️ переплавка + трейд": "forge",
            "/check": "check",
            "🔄 чекать 5 акков": "check",
            "🔄 проверить 5 аккаунтов": "check",
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
                "⏳ Открываю 4 уникальных IP, захожу на 4 аккаунта, ввожу промокод и проверяю реальное увеличение баланса монет (~40 сек)...",
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

    print(f"📡 Прямой Telegram Long Polling запущен (начальный offset={offset})...")
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
    global ACTIVE_JOB_TASK
    while time.time() < deadline_ts:
        try:
            item = await asyncio.wait_for(task_queue.get(), timeout=2.0)
        except asyncio.TimeoutError:
            continue
        act_code, p_code = item
        print(f"⚙️ [EXECUTOR] Запуск задачи: action={act_code}, promo={p_code or '-'}")
        try:
            ACTIVE_JOB_TASK = asyncio.create_task(execute_single_action(act_code, p_code))
            await ACTIVE_JOB_TASK
        except asyncio.CancelledError:
            print(f"🛑 [EXECUTOR] Задача {act_code} отменена пользователем.")
        except Exception as e:
            print(f"⚠️ [EXECUTOR ERROR] {act_code}: {e}")
            send_tg_message(f"⚠️ Ошибка при выполнении задачи <code>{act_code}</code>: {e}", add_keyboard=True)
        finally:
            ACTIVE_JOB_TASK = None
            task_queue.task_done()


async def async_main() -> None:
    global PENDING_TASKS, ACTIVE_FARM_TASK
    parser = argparse.ArgumentParser(description="Senkuro Full Automation Combine v15.0")
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

    PENDING_TASKS = asyncio.Queue()
    deadline_ts = time.time() + 4.1 * 3600.0

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

    # 2. Проверяем, нужно ли автоматически продолжить 2-ю половину 8-часового фарма (часы 4..8)
    if args.action == "farm_part2" or FARM_RESUME_FILE.exists():
        elapsed_prev = 240
        try:
            if FARM_RESUME_FILE.exists():
                st_data = json.loads(FARM_RESUME_FILE.read_text(encoding="utf-8"))
                elapsed_prev = int(st_data.get("elapsed_minutes") or 240)
        except Exception:
            pass
        rem_hours = max(0.5, (480 - elapsed_prev) / 60.0)
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
