#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SENKURO FULL AUTOMATION COMBINE v11.0 (100% TELEGRAM -> CLOUDFLARE -> GITHUB)
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

TELEGRAM_BOT_TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    or "8868493953:AAHyGgQCt4n2FrvyL6mPmFK8w1fq_LNpug4"
)
TELEGRAM_CHAT_ID = (
    os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    or "457787014"
)

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
    Базовая панель кнопок, которая прикрепляется после завершения любой задачи.
    Никаких вложенных подменю — каждая кнопка сразу запускает свою задачу!
    """
    return {
        "inline_keyboard": [
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
            [
                {"text": "🛑 ОСТАНОВИТЬ ФАРМ / ВСЕ ЗАДАЧИ", "callback_data": "stop_all_farm"},
            ],
        ]
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


def send_tg_message(text: str, add_keyboard: bool = True) -> dict:
    payload: dict[str, Any] = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if add_keyboard:
        payload["reply_markup"] = get_main_inline_keyboard()
    return tg_request("sendMessage", payload)


WORKER_PUBLIC_URL = "https://sparkling-meadow-68b3.ev20291.workers.dev/"
INSTANT_CMD_QUEUE_TOPIC = "senkuro_cesium254_v11_cmd_queue"
INSTANT_CMD_ACK_TOPIC = "senkuro_cesium254_v11_cmd_ack"


def configure_telegram_bot_profile() -> None:
    # Автоматически привязываем вебхук Telegram к рабочему Cloudflare Worker пользователя
    tg_request(
        "setWebhook",
        {
            "url": WORKER_PUBLIC_URL,
            "drop_pending_updates": False,
        },
    )
    commands = [
        {"command": "menu", "description": "📋 Открыть базовую панель кнопок"},
        {"command": "farm", "description": "▶️ Запустить 8-часовой фарм манги"},
        {"command": "status", "description": "📊 Проверить статус фарма (читают или нет)"},
        {"command": "balance", "description": "🪙 Баланс монет на 4 аккаунтах"},
        {"command": "packs", "description": "🎴 Крутить паки Хардкор (480 монет)"},
        {"command": "forge", "description": "⚒️ Переплавка карт до S + трейд на основу"},
        {"command": "check", "description": "🔄 Проверить карты и осколки (5 аккаунтов)"},
        {"command": "stop", "description": "🛑 Остановить фарм и все задачи"},
    ]
    tg_request("setMyCommands", {"commands": commands})


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


async def gql_call(page: Page, query: str, variables: Optional[dict] = None, operation_name: Optional[str] = None) -> dict:
    payload: dict[str, Any] = {"query": query, "variables": variables or {}}
    if operation_name:
        payload["operationName"] = operation_name

    result = await page.evaluate(
        """async ({ apiUrl, appVersion, bodyPayload }) => {
            function getCookie(name) {
                const m = document.cookie.match(new RegExp('(?:^|; )' + name.replace(/([.$?*|{}()\\[\\]\\\\/+^])/g, '\\\\$1') + '=([^;]*)'));
                return m ? decodeURIComponent(m[1]) : '';
            }
            const token = getCookie('access_token');
            const headers = {
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'App-Version': appVersion,
                'Cache-Control': 'no-cache'
            };
            if (token) {
                headers['Authorization'] = 'Bearer ' + token;
            }
            try {
                const resp = await fetch(apiUrl + '?_t=' + Date.now(), {
                    method: 'POST',
                    headers: headers,
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
    return result or {}


async def get_fresh_points_balance(page: Page, slug: str) -> int:
    v_res = await gql_call(page, GQL_FETCH_VIEWER, {}, "fetchViewer")
    v_user = ((v_res.get("data") or {}).get("viewer") or {}).get("user") or {}
    if v_user.get("points") is not None:
        return int(v_user["points"])

    u_res = await gql_call(page, GQL_FETCH_USER_BY_SLUG, {"slug": slug}, "fetchUserBySlug")
    u_obj = (u_res.get("data") or {}).get("user") or {}
    return int(u_obj.get("points") or 0)


def get_session_file(acc_id: str) -> Path:
    return SESSIONS_DIR / f"session_{acc_id}.json"


async def create_account_context(playwright_browser, acc: dict, proxy_url: Optional[str]) -> BrowserContext:
    sess_file = get_session_file(acc["id"])
    ctx_kwargs: dict[str, Any] = {
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
        "viewport": {"width": 1280, "height": 900},
        "locale": "ru-RU",
    }
    if proxy_url:
        ctx_kwargs["proxy"] = {"server": proxy_url}
    if sess_file.exists():
        try:
            ctx_kwargs["storage_state"] = str(sess_file)
            print(f"[SESSION] Загружена сохраненная сессия для {acc['id']}")
        except Exception:
            pass
    return await playwright_browser.new_context(**ctx_kwargs)


async def ensure_logged_in(context: BrowserContext, acc: dict) -> tuple[Page, Optional[dict]]:
    page = await context.new_page()
    await page.goto("https://senkuro.com/", wait_until="domcontentloaded", timeout=40000)
    await page.wait_for_timeout(1500)

    viewer_res = await gql_call(page, GQL_FETCH_VIEWER, {}, "fetchViewer")
    user_obj = ((viewer_res.get("data") or {}).get("viewer") or {}).get("user")
    if user_obj and user_obj.get("id"):
        print(f"[AUTH OK] {acc['id']}: уже авторизован (id={user_obj['id']}, points={user_obj.get('points', 0)})")
        await context.storage_state(path=str(get_session_file(acc["id"])))
        return page, user_obj

    if not acc.get("login") or not acc.get("password"):
        return page, None

    print(f"[AUTH] Выполняем автоматический вход для {acc['id']} ({acc['login']})...")

    for attempt in range(3):
        try:
            login_btn = page.locator("a:has-text('Войти'), button:has-text('Войти')").first
            if await login_btn.count() > 0:
                await login_btn.click(timeout=8000)
            else:
                await page.evaluate(
                    """() => {
                        const btn = Array.from(document.querySelectorAll('a, button')).find(el => {
                            const t = (el.innerText || el.textContent || '').trim();
                            return t === 'Войти' || t === 'Вход';
                        });
                        if (btn) btn.click();
                    }"""
                )
        except Exception as e:
            print(f"[AUTH] Попытка клика Войти #{attempt+1}: {e}")

        for _ in range(25):
            await page.wait_for_timeout(600)
            if "sso.senkuro." in page.url:
                break

        if "sso.senkuro." in page.url:
            await page.wait_for_timeout(1200)
            await page.evaluate(
                """({ loginStr, passStr }) => {
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
                    const passInput = document.querySelector('input[type="password"]');
                    const allInputs = Array.from(document.querySelectorAll('input:not([type="hidden"]):not([type="password"]):not([type="checkbox"])'));
                    const userInput = allInputs[0];
                    if (userInput) setNativeVal(userInput, loginStr);
                    if (passInput) setNativeVal(passInput, passStr);
                    setTimeout(() => {
                        const submitBtn = document.querySelector('button[type="submit"]') ||
                            Array.from(document.querySelectorAll('button')).find(b => {
                                const t = (b.innerText || b.textContent || '').trim().toLowerCase();
                                return t.includes('продолжить') || t.includes('войти') || t.includes('вход') || t.includes('login');
                            });
                        if (submitBtn) submitBtn.click();
                    }, 350);
                }""",
                {"loginStr": acc["login"], "passStr": acc["password"]},
            )

            for _ in range(35):
                await page.wait_for_timeout(700)
                if "senkuro.com" in page.url and "/auth/" not in page.url:
                    viewer_res = await gql_call(page, GQL_FETCH_VIEWER, {}, "fetchViewer")
                    user_obj = ((viewer_res.get("data") or {}).get("viewer") or {}).get("user")
                    if user_obj and user_obj.get("id"):
                        print(f"[AUTH SUCCESS] {acc['id']}: вход выполнен! Баланс: {user_obj.get('points', 0)} сенкоинов")
                        await context.storage_state(path=str(get_session_file(acc["id"])))
                        return page, user_obj

        await page.goto("https://senkuro.com/", wait_until="domcontentloaded", timeout=35000)
        await page.wait_for_timeout(1500)
        viewer_res = await gql_call(page, GQL_FETCH_VIEWER, {}, "fetchViewer")
        user_obj = ((viewer_res.get("data") or {}).get("viewer") or {}).get("user")
        if user_obj and user_obj.get("id"):
            await context.storage_state(path=str(get_session_file(acc["id"])))
            return page, user_obj

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
            browser = await p.chromium.launch(headless=True)
            for acc in FARM_ACCOUNTS:
                proxy_url = proxy_mgr.start_account_proxy(acc)
                ip_used = proxy_mgr.active_ips.get(acc["acc_id"], "прямой")
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
            browser = await p.chromium.launch(headless=True)
            for acc in FARM_ACCOUNTS:
                proxy_url = proxy_mgr.start_account_proxy(acc)
                ip_used = proxy_mgr.active_ips.get(acc["acc_id"], "прямой")
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
            await browser.close()
    finally:
        proxy_mgr.stop_all()

    lines.append(f"\n💰 <b>Всего монет на 4 аккаунтах:</b> {total_coins} 🪙 (доступно прокруток Хардкор: <b>{total_packs_possible}</b>)")
    send_tg_message("\n".join(lines), add_keyboard=True)


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
            browser = await p.chromium.launch(headless=True)
            for acc in FARM_ACCOUNTS:
                proxy_url = proxy_mgr.start_account_proxy(acc)
                ip_used = proxy_mgr.active_ips.get(acc["acc_id"], "прямой")
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
            browser = await p.chromium.launch(headless=True)
            contexts: list[BrowserContext] = []

            for acc in FARM_ACCOUNTS:
                proxy_url = proxy_mgr.start_account_proxy(acc)
                ip_used = proxy_mgr.active_ips.get(acc["acc_id"], "прямой")
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
                proxy_url = proxy_mgr.start_account_proxy(acc)
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

def parse_graphql_edges(edges: list[dict]) -> list[dict]:
    parsed = []
    for edge in edges:
        node = edge.get("node") or edge
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


async def fetch_all_pages_via_graphql(page: Page, captured_req: dict, modifier_val: int) -> list[dict]:
    raw_edges = await page.evaluate(
        """async ({ reqInfo, modifierVal }) => {
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
        {"reqInfo": captured_req, "modifierVal": modifier_val},
    )
    return parse_graphql_edges(raw_edges or [])


async def scrape_account_cards_public(context: BrowserContext, account: dict) -> dict:
    page = await context.new_page()
    print(f"Проверка {account['label']} -> {account['url']}")
    captured_req: dict[str, Any] = {}

    def on_request(request):
        if "graphql" in request.url and request.method == "POST":
            try:
                post_json = request.post_data_json
                if isinstance(post_json, dict) and post_json.get("operationName") == "fetchUserCards":
                    if not captured_req:
                        captured_req["url"] = request.url
                        captured_req["headers"] = request.headers
                        captured_req["postData"] = post_json
            except Exception:
                pass

    page.on("request", on_request)

    try:
        await page.goto(account["url"], wait_until="domcontentloaded", timeout=35000)
        for _ in range(16):
            if captured_req:
                break
            await page.wait_for_timeout(500)

        if captured_req:
            cards = await fetch_all_pages_via_graphql(page, captured_req, modifier_val=0)
            shards = await fetch_all_pages_via_graphql(page, captured_req, modifier_val=1)
            return {"cards": cards, "shards": shards, "error": None}

        u_res = await gql_call(page, GQL_FETCH_USER_BY_SLUG, {"slug": account["id"]}, "fetchUserBySlug")
        uid = ((u_res.get("data") or {}).get("user") or {}).get("id")
        if uid:
            c_nodes = await fetch_all_user_cards_gql(page, uid, modifier_val=0)
            s_nodes = await fetch_all_user_cards_gql(page, uid, modifier_val=1)
            return {"cards": parse_graphql_edges(c_nodes), "shards": parse_graphql_edges(s_nodes), "error": None}

        return {"cards": [], "shards": [], "error": None}
    except Exception as e:
        return {"cards": [], "shards": [], "error": str(e)}
    finally:
        await page.close()


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
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="ru-RU",
        )
        for idx, acc in enumerate(ALL_CHECK_ACCOUNTS):
            acc_data = await scrape_account_cards_public(context, acc)
            is_last = idx == len(ALL_CHECK_ACCOUNTS) - 1
            if acc_data["error"]:
                err_msg = f"⚠️ <b><a href=\"{acc['url']}\">{acc['label']}</a></b>: ошибка загрузки ({acc_data['error']})"
                send_account_report(err_msg, [], add_reply_button=is_last)
                continue
            text, card_photos = build_account_message(acc, acc_data)
            send_account_report(text, card_photos, add_reply_button=is_last)
            await asyncio.sleep(1.0)
        await browser.close()


# ==============================================================================
# 11. ТОЧКА ВХОДА
# ==============================================================================

async def execute_single_action(action: str, promo_code: str = "") -> str:
    if action == "menu":
        send_tg_message(
            "✅ <b>Единый комбайн Senkuro v11.0 готов к работе!</b>\n\n"
            "Все задачи (включая 8-часовой фарм манги, проверку статуса, промокоды с проверкой баланса, проверку монет, паки «Хардкор», Переплавку с трейдом на основу, чекер 5 аккаунтов и красную кнопку остановки) запускаются напрямую с кнопок ниже:",
            add_keyboard=True,
        )
    elif action == "daemon":
        print("🟢 Тихий запуск тёплого демона ожидания команд из Telegram...")
    elif action == "promo":
        await run_promo_code_activation(promo_code)
    elif action == "balance":
        await run_check_coins_balance()
    elif action == "packs":
        await run_all_packs_opening()
    elif action == "forge":
        await run_smart_forge_and_trade_pipeline()
    elif action in ("farm", "farm_part1"):
        await run_farm_segment("farm_part1")
        return "farm_done"
    elif action == "farm_part2":
        await run_farm_segment("farm_part2")
        return "farm_done"
    elif action == "farm_status":
        await run_check_farm_status()
    elif action == "all":
        if promo_code:
            await run_promo_code_activation(promo_code)
        await run_all_packs_opening()
        await run_smart_forge_and_trade_pipeline()
    elif action == "check":
        await run_check_all_5_accounts()
    return "ok"


async def listen_for_instant_commands_loop(start_listen_ts: int, seen_ids: set[str], max_hours: float = 3.8) -> None:
    print(f"⚡ Включен режим мгновенного отклика (слушаем нажатия кнопок в Telegram до {max_hours} ч)...")
    deadline = time.time() + max_hours * 3600.0
    last_poll_ts = start_listen_ts

    while time.time() < deadline:
        await asyncio.sleep(1.2)
        now_ts = int(time.time())
        cmds = poll_instant_commands(max(start_listen_ts, last_poll_ts - 3), seen_ids)
        last_poll_ts = now_ts

        for cmd in cmds:
            act = str(cmd.get("action") or "").strip().lower()
            p_code = str(cmd.get("promo_code") or "").strip()
            print(f"⚡ [INSTANT QUEUE] Получена команда из Telegram: action={act}, promo={p_code}")
            if act == "stop":
                print("🛑 Получена команда полной остановки, завершаем демон ожидания.")
                return
            res = await execute_single_action(act, p_code)
            if res == "farm_done":
                return


async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Senkuro Full Automation Combine v11.0")
    parser.add_argument(
        "--action",
        default=os.environ.get("SENKURO_ACTION", "check").strip().lower() or "check",
        choices=["check", "menu", "daemon", "promo", "balance", "packs", "forge", "farm", "farm_part1", "farm_part2", "farm_status", "all"],
    )
    parser.add_argument(
        "--promo-code",
        default=os.environ.get("SENKURO_PROMO_CODE", "").strip(),
    )
    args = parser.parse_args()

    boot_ts = int(time.time())
    seen_cmd_ids: set[str] = set()

    configure_telegram_bot_profile()

    # Если этот запуск вызван через workflow_dispatch, проверим, не перехватил ли уже эту команду тёплый демон, пока ставился браузер
    if os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch" and args.action not in ("farm", "farm_part1", "farm_part2"):
        try:
            ack_url = f"https://ntfy.sh/{INSTANT_CMD_ACK_TOPIC}/json?poll=1&since={boot_ts - 50}"
            req = urllib.request.Request(ack_url, headers={"User-Agent": "SenkuroCombine/11.0"})
            with urllib.request.urlopen(req, timeout=5) as resp:
                ack_lines = resp.read().decode("utf-8", errors="ignore").strip().splitlines()
            for a_line in ack_lines:
                if '"event":"message"' in a_line and "cmd_" in a_line:
                    print("ℹ️ Задача уже была мгновенно выполнена активным тёплым сервером, дубль пропускаем.")
                    return
        except Exception:
            pass

    # Считываем уже накопившиеся в очереди ID за последние 90 сек, чтобы не дублировать текущую задачу
    for old_c in poll_instant_commands(boot_ts - 90, seen_cmd_ids):
        pass

    action = args.action
    promo_code = args.promo_code

    print(f"🚀 Запуск Senkuro Combine v11.0 | Режим: {action} | Параметр: {promo_code or '-'}")

    res = await execute_single_action(action, promo_code)

    # Если это не завершение 4-часового фарма, остаёмся в тёплом режиме ожидания кнопок из Telegram (отклик 1 сек!)
    if res != "farm_done" and os.environ.get("GITHUB_ACTIONS") == "true":
        await listen_for_instant_commands_loop(int(time.time()), seen_cmd_ids, max_hours=3.8)


if __name__ == "__main__":
    asyncio.run(async_main())
