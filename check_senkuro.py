#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
SENKURO FULL AUTOMATION BOT v7.0 (CLOUD / GITHUB ACTIONS / KAGGLE)
================================================================================
Полный комбайн автоматизации Senkuro с управлением через Telegram:
1. Уникальный IP (Opera VPN / прокси) на каждый из 4 фарм-аккаунтов:
   - ber_turtle -> 77.111.244.37
   - ainz       -> 77.111.244.209
   - catswat    -> 77.111.244.210
   - wolfrice   -> 77.111.246.8
2. Автоматический вход (sso.senkuro.org) с сохранением сессий (cookies + storage)
   между запусками, чтобы не вводить пароли заново.
3. Активация промокодов (--action promo --promo-code КОД):
   - Входит на все 4 аккаунта под своими IP, активирует промокод (GraphQL + UI)
     и присылает в Telegram отчет о начисленных сенкоинах и новом балансе.
4. Быстрая прокрутка пака «Хардкор» (--action packs):
   - Проверяет баланс сенкоинов на 4 аккаунтах. Если >= 480 монет, открывает
     https://senkuro.com/packs/for-hardcore-gamers и выбирает из первых 2 слотов
     (3-й слот заблокирован без премиума) карту наивысшего ранга (S > A > B > C > D > F).
5. Умная Кузница «Переплавка» + Межаккаунтный Трейд (--action forge):
   - Строго режим «Переплавка» (UPGRADE: 3 карты одного ранга -> 1 карта рангом выше:
     3 F -> 1 D -> 1 C -> 1 B -> 1 A -> 1 S; ранг S не переплавляется).
   - Никогда не использует «Раскол» (SPLIT) или «Объединение» (MERGE).
   - Если карты одного ранга разбросаны по разным аккаунтам или на одном аккаунте
     закончились 5 суточных попыток кузни, автоматически перекидывает карты трейдом
     на другой фарм-аккаунт со свободными слотами кузни и продолжает крафт.
   - Строгий белый список трейдов (принимает обмены ТОЛЬКО от ber_turtle, ainz,
     catswat, wolfrice и основы cesium254).
   - Финальный сбор: когда все возможные переплавки завершены, отправляет ВСЕ
     полученные карты и осколки трейдом на основной аккаунт cesium254 и присылает
     текстовый отчет в Telegram (без картинок). Если слоты кузни (5/5 на всех 4 акках)
     закончились раньше, чем докрафтились все тройки — не отправляет недокрафченные
     карты на основу, а сообщает в Telegram, что продолжит завтра после сброса лимита.
6. Чекер всех 5 аккаунтов с картинками (--action check):
   - Полностью сохранена проверка карт и осколков по всем 5 аккаунтам (включая cesium254).
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
# 1. КОНФИГУРАЦИЯ TELEGRAM И АККАУНТОВ
# ==============================================================================

TELEGRAM_BOT_TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    or "8868493953:AAHyGgQCt4n2FrvyL6mPmFK8w1fq_LNpug4"
)
TELEGRAM_CHAT_ID = (
    os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    or "457787014"
)

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

# СТРОГИЙ БЕЛЫЙ СПИСОК ДЛЯ ПРИНЯТИЯ ТРЕЙДОВ (ни от кого другого трейды НЕ принимаются!)
ALLOWED_TRADE_SLUGS = {
    "ber_turtle",
    "ainz",
    "catswat",
    "wolfrice",
    "cesium254",
}

HARDCORE_PACK_SLUG = "for-hardcore-gamers"
HARDCORE_PACK_URL = f"https://senkuro.com/packs/{HARDCORE_PACK_SLUG}"
HARDCORE_PACK_COST = 480
FORGE_URL = "https://senkuro.com/forge"
GRAPHQL_API_URL = "https://api.senkuro.com/graphql"
APP_VERSION = "301026"

RANK_ORDER = ["R", "S", "A", "B", "C", "D", "F", "?"]
RANK_PRIORITY = {"F": 1, "D": 2, "C": 3, "B": 4, "A": 5, "S": 6, "R": 7, "X": 8, "?": 0}
FORGE_UPGRADE_CHAIN = ["F", "D", "C", "B", "A"]  # 3 F -> D, 3 D -> C, 3 C -> B, 3 B -> A, 3 A -> S (на S стоп!)
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
# 2. TELEGRAM BOT API И КЛАВИАТУРА УПРАВЛЕНИЯ
# ==============================================================================

def get_main_inline_keyboard() -> dict:
    """Клавиатура быстрого управления всеми функциями из Telegram в 1 клик."""
    return {
        "inline_keyboard": [
            [
                {"text": "🔄 Проверить 5 аккаунтов", "callback_data": "check_senkuro"},
                {"text": "🎟 Ввести промокод", "callback_data": "prompt_promo"},
            ],
            [
                {"text": "🎴 Крутить паки Хардкор", "callback_data": "roll_packs"},
                {"text": "⚒️ Переплавка + Трейд", "callback_data": "run_forge"},
            ],
            [
                {"text": "🚀 Сделать ВСЁ (Паки + Кузня + Трейд)", "callback_data": "run_all"},
            ],
            [
                {"text": "🤝 Принять входящие трейды (Свои)", "callback_data": "accept_trades"},
            ],
        ]
    }


def tg_request(method: str, payload: dict) -> dict:
    """Отправка запроса к Telegram Bot API."""
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
    """Отправка текстового сообщения в Telegram с панелью кнопок."""
    payload: dict[str, Any] = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if add_keyboard:
        payload["reply_markup"] = get_main_inline_keyboard()
    return tg_request("sendMessage", payload)


# ==============================================================================
# 3. УПРАВЛЕНИЕ ТУННЕЛЯМИ OPERA-PROXY (УНИКАЛЬНЫЙ IP НА КАЖДЫЙ АККАУНТ)
# ==============================================================================

def is_ipv4_address(ip_str: str) -> bool:
    s = (ip_str or "").strip()
    parts = s.split(".")
    return len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts)


def ensure_opera_proxy_binary() -> Optional[str]:
    """Проверяет или скачивает бинарник opera-proxy для изоляции IP каждого аккаунта."""
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
    """Проверяет реальный выходной IP-адрес локального прокси-порта."""
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
    """Поднимает и контролирует 4 изолированных VPN-туннеля для 4 фарм-аккаунтов."""

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
        """Возвращает URL локального прокси http://127.0.0.1:<port> с уникальным IP."""
        aid = acc["acc_id"]
        port = acc["proxy_port"]
        pinned_ip = acc["pinned_ip"]
        if not port:
            return None

        # Если порт уже поднят (например, скрипт запущен внутри активного сервера Kaggle)
        if self._port_open(port):
            ok, ip = verify_proxy_exit_ip(port, timeout=2.5)
            if ok:
                self.active_ips[aid] = ip
                print(f"[VPN] {acc['id']}: используется уже активный туннель 127.0.0.1:{port} -> {ip}")
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

        # Попытка 1: Привязка через локальный CSV (EU 77.111.244.*)
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

        # Попытка 2: Регионы AM (77.111.246.*) / AS (77.111.245.*) / EU
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

        print(f"[VPN WARNING] {acc['id']}: работаем напрямую без прокси (не удалось поднять туннель)")
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
# 4. ПРЯМЫЕ GRAPHQL ЗАПРОСЫ И АВТОРИЗАЦИЯ В АККАУНТАХ SENKURO
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

GQL_FETCH_USER_ID = """
query fetchUserId($slug: String!) {
  user(slug: $slug) {
    id
    slug
    name
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
    """Выполняет авторизованный GraphQL-запрос из контекста открытой вкладки Senkuro (с автоматическим подхватом куки access_token)."""
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
                'App-Version': appVersion
            };
            if (token) {
                headers['Authorization'] = 'Bearer ' + token;
            }
            try {
                const resp = await fetch(apiUrl, {
                    method: 'POST',
                    headers: headers,
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


def get_session_file(acc_id: str) -> Path:
    return SESSIONS_DIR / f"session_{acc_id}.json"


async def create_account_context(playwright_browser, acc: dict, proxy_url: Optional[str]) -> BrowserContext:
    """Создает изолированный контекст браузера с сохраненной сессией (если есть) и индивидуальным прокси."""
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
    """
    Открывает senkuro.com, проверяет статус входа через GraphQL `fetchViewer`.
    Если сессия не авторизована — автоматически выполняет вход через sso.senkuro.org
    и сохраняет свежую сессию в .sessions/session_<id>.json.
    """
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
        print(f"[AUTH SKIP] {acc['id']}: нет логина/пароля")
        return page, None

    print(f"[AUTH] Выполняем автоматический вход для {acc['id']} ({acc['login']})...")

    # Нажимаем кнопку «Войти» в шапке сайта
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

        # Ждем перехода на sso.senkuro.org или появления формы пароля
        for _ in range(25):
            await page.wait_for_timeout(600)
            cur_url = page.url
            if "sso.senkuro." in cur_url:
                break

        if "sso.senkuro." in page.url:
            await page.wait_for_timeout(1200)
            # Заполняем логин и пароль через нативный setter
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

            # Ждем возврата на senkuro.com и обмена OAuth-кода на access_token
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

    print(f"[AUTH ERROR] Не удалось авторизоваться в аккаунте {acc['id']}")
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
    """Выгружает все страницы userCards через GraphQL."""
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
# 5. СЦЕНАРИЙ 1: АКТИВАЦИЯ ПРОМОКОДА НА ВСЕХ 4 АККАУНТАХ
# ==============================================================================

async def run_promo_code_activation(promo_code: str) -> None:
    code_clean = (promo_code or "").strip().upper()
    if not code_clean:
        send_tg_message("⚠️ Промокод не указан. Нажмите «🎟 Ввести промокод» и отправьте код ответным сообщением.")
        return

    send_tg_message(f"⏳ Начинаю активацию промокода <code>{code_clean}</code> на всех 4 аккаунтах (под уникальными IP)...", add_keyboard=False)

    proxy_mgr = AccountProxyManager()
    report_lines = [f"🎟 <b>Отчёт по активации промокода <code>{code_clean}</code>:</b>\n"]

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
                        report_lines.append(f"❌ <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): не удалось войти в аккаунт")
                        continue

                    before_pts = int(user_obj.get("points") or 0)

                    # 1. Прямая мутация redeemRedemption (input: {code: CODE})
                    res = await gql_call(
                        page,
                        GQL_REDEEM_PROMO,
                        {"input": {"code": code_clean}},
                        "redeemRedemption",
                    )
                    errors = res.get("errors") or []
                    payload = (res.get("data") or {}).get("redeemRedemption")

                    # 2. Резервный UI-сценарий (меню -> Активировать промокод -> Введите код -> Окей)
                    if not payload and not errors:
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
                                    # Клик в пустую область для закрытия окна
                                    await page.mouse.click(10, 10)
                        except Exception:
                            pass

                    # Проверяем обновленный баланс через fetchViewer
                    viewer_after = await gql_call(page, GQL_FETCH_VIEWER, {}, "fetchViewer")
                    user_after = ((viewer_after.get("data") or {}).get("viewer") or {}).get("user") or {}
                    after_pts = int(user_after.get("points") or before_pts)

                    if payload:
                        added_pts = int(payload.get("points") or (after_pts - before_pts))
                        exp_gain = int(payload.get("experience") or 0)
                        extra = f", +{exp_gain} опыта" if exp_gain else ""
                        report_lines.append(
                            f"✅ <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): "
                            f"<b>+{added_pts} сенкоинов</b>{extra} (баланс: <b>{after_pts}</b> 🪙)"
                        )
                    elif after_pts > before_pts:
                        diff = after_pts - before_pts
                        report_lines.append(
                            f"✅ <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): "
                            f"<b>+{diff} сенкоинов</b> (баланс: <b>{after_pts}</b> 🪙)"
                        )
                    else:
                        err_msg = errors[0].get("message", "Код уже активирован или недействителен") if errors else "Код не дал монет"
                        report_lines.append(
                            f"⚠️ <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): {err_msg} (баланс: <b>{after_pts}</b> 🪙)"
                        )

                    await context.storage_state(path=str(get_session_file(acc["id"])))
                finally:
                    await context.close()
            await browser.close()
    finally:
        proxy_mgr.stop_all()

    send_tg_message("\n".join(report_lines), add_keyboard=True)


# ==============================================================================
# 6. СЦЕНАРИЙ 2: ОТКРЫТИЕ ПАКОВ «ХАРДКОР» (ЗА 480 МОНЕТ, ВЫБОР ЛУЧШЕЙ ИЗ 2 КАРТ)
# ==============================================================================

def choose_best_unlocked_card_index(result_cards: list[dict], has_premium: bool = False) -> tuple[int, dict]:
    """
    На аккаунтах без премиума (has_premium=False) 3-я карта (индекс 2) заблокирована.
    Разблокированы только первые 2 карты по очереди (индексы 0 и 1).
    Выбирает карту строго выше по рангу: S > A > B > C > D > F (при равном ранге — анимированную).
    """
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
    """Крутит пак for-hardcore-gamers на все доступные сенкоины (по 480 монет) и забирает лучшие карты из 1-2 слотов."""
    logs: list[str] = []
    user_id = user_obj["id"]
    points = int(user_obj.get("points") or 0)
    has_premium = int(user_obj.get("subscriptionTier") or 0) > 0

    pack_res = await gql_call(page, GQL_FETCH_PACK_AND_PENDING, {"slug": HARDCORE_PACK_SLUG}, "fetchPackAndPending")
    data = pack_res.get("data") or {}
    pack = data.get("cardPack")
    if not pack:
        logs.append("⚠️ Пак for-hardcore-gamers не найден")
        return logs

    pack_id = pack["id"]
    pack_cost = int(pack.get("points") or HARDCORE_PACK_COST)
    pending_opens = list(data.get("viewerPendingCardPackOpens") or [])

    chosen_cards_summary: list[str] = []

    # 1. Сначала закрываем незавершенные открытия паков, если они висят на аккаунте
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
            chosen_cards_summary.append(f"{r_badge} «{c_title}» (слот #{best_idx + 1})")

        if opens_input:
            await gql_call(
                page,
                GQL_BULK_CHOOSE_PACK_OPEN,
                {"input": {"opens": opens_input}},
                "bulkChooseCardPackOpen",
            )

    # 2. Крутим новые паки Хардкор, пока хватает монет (>= 480)
    rolls_available = points // pack_cost
    if rolls_available <= 0 and not chosen_cards_summary:
        logs.append(f"недостаточно монет ({points}/{pack_cost} 🪙)")
        return logs

    for _ in range(rolls_available):
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
                logs.append(f"остановка прокрутки: {errs[0].get('message')}")
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
            slots_str = "/".join(
                f"{c.get('rank')}{'(🔒)' if (i == 2 and not has_premium) else ''}"
                for i, c in enumerate(rcards)
            )
            r_badge = RANK_BADGE.get(str(best_card.get("rank", "F")).upper(), best_card.get("rank", "F"))
            c_title = extract_card_title(best_card)
            chosen_cards_summary.append(f"{r_badge} «{c_title}» [выпало: {slots_str} -> взят слот #{best_idx + 1}]")

        if choose_payload:
            await gql_call(
                page,
                GQL_BULK_CHOOSE_PACK_OPEN,
                {"input": {"opens": choose_payload}},
                "bulkChooseCardPackOpen",
            )
        points -= pack_cost

    if chosen_cards_summary:
        logs.append(f"открыто паков: <b>{len(chosen_cards_summary)}</b> (остаток: <b>{points}</b> 🪙):")
        for item in chosen_cards_summary:
            logs.append(f"   • {item}")
    return logs


async def run_all_packs_opening() -> None:
    send_tg_message("🎴 Проверяю баланс сенкоинов и кручу пак «Хардкор» (480 🪙) на 4 аккаунтах...", add_keyboard=False)
    proxy_mgr = AccountProxyManager()
    report_lines = ["🎴 <b>Отчёт по открытию паков «Для хардкорщиков»:</b>\n"]

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
                        report_lines.append(f"❌ <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): ошибка входа")
                        continue
                    acc_logs = await roll_hardcore_packs_for_account(page, acc, user_obj)
                    report_lines.append(f"👤 <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): " + "\n".join(acc_logs))
                    await context.storage_state(path=str(get_session_file(acc["id"])))
                finally:
                    await context.close()
            await browser.close()
    finally:
        proxy_mgr.stop_all()

    send_tg_message("\n".join(report_lines), add_keyboard=True)


# ==============================================================================
# 7. СЦЕНАРИЙ 3: БЕЗОПАСНЫЙ ПРИЁМ ТРЕЙДОВ (СТРОГО ПО БЕЛОМУ СПИСКУ)
# ==============================================================================

async def accept_whitelisted_incoming_trades(page: Page, acc_slug: str, user_id: str) -> list[str]:
    """
    Проверяет входящие трейды (status=PENDING) и принимает ТОЛЬКО те, где:
    1) Отправитель (source.slug) входит в ALLOWED_TRADE_SLUGS (ber_turtle, ainz, catswat, wolfrice, cesium254).
    2) От нашего аккаунта ничего не требуют взамен (request пустой) или получатель — мы.
    Никакие чужие трейды никогда не принимаются!
    """
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

        # ЖЕЛЕЗОБЕТОННАЯ ПРОВЕРКА БЕЛОГО СПИСКА
        if source_slug not in ALLOWED_TRADE_SLUGS:
            print(f"[SECURITY BLOCK] {acc_slug}: проигнорирован входящий трейд {trade_id} от ЧУЖОГО игрока '{source_slug}'!")
            continue

        # Если вдруг в трейде просят наши карты не на наш фарм-аккаунт — тоже блокируем
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


# ==============================================================================
# 8. СЦЕНАРИЙ 4: УМНАЯ ПЕРЕПЛАВКА (КУЗНЯ) + МЕЖАККАУНТНЫЙ ТРЕЙД + СБОР НА ОСНОВУ
# ==============================================================================

def expand_craftable_cards_by_rank(user_cards_nodes: list[dict]) -> dict[str, list[dict]]:
    """
    Группирует доступные для переплавки целые карты по рангам F, D, C, B, A.
    В переплавку идут только:
    - целые карты (shard == False и modifier == 0)
    - незаблокированные (locked == False)
    - неанимированные (animated == False, как требует фильтр кузни Senkuro)
    - ранги строго F, D, C, B, A (ранг S, R, X НЕ переплавляется!).
    Каждая единица quantity разворачивается в отдельный элемент для удобного набора троек.
    """
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
    """Схлопывает список отдельных карт с одинаковым (cardId, modifier) в формат [{cardId, modifier, quantity}]."""
    counts: dict[tuple[str, int], int] = Counter()
    for u in units:
        counts[(str(u["cardId"]), int(u.get("modifier") or 0))] += 1
    return [
        {"cardId": cid, "modifier": mod, "quantity": qty}
        for (cid, mod), qty in counts.items()
    ]


def format_text_only_inventory_summary(cards_nodes: list[dict], shards_nodes: list[dict]) -> str:
    """
    Форматирует чисто текстовую сводку карт и осколков по рангам (без картинок),
    например: «1 🟥 S, 1 🟪 B, 2 ⬜ F | Осколки: 4 🟩 D, 2 ⬜ F».
    """
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
    """Обновляет слоты кузни и инвентарь карт/осколков на всех 4 открытых фарм-аккаунтах."""
    for aid, st in state_map.items():
        page: Page = st["page"]
        uid: str = st["user_id"]

        # 1. Принимаем входящие трейды из белого списка
        acc_trades = await accept_whitelisted_incoming_trades(page, aid, uid)
        if acc_trades:
            st["logs"].extend(acc_trades)

        # 2. Проверяем слоты кузни (строго режим UPGRADE = Переплавка)
        slots_res = await gql_call(page, GQL_FETCH_FORGE_SLOTS, {"mode": "UPGRADE"}, "fetchForgeCardsSlots")
        slots_obj = (slots_res.get("data") or {}).get("forgeCardsSlots") or {}
        st["available_slots"] = int(slots_obj.get("available") or 0)
        st["used_slots"] = int(slots_obj.get("used") or 0)
        st["reset_at"] = slots_obj.get("resetAt")

        # 3. Загружаем все целые карты (modifier=0) и осколки (modifier=1)
        st["cards_nodes"] = await fetch_all_user_cards_gql(page, uid, modifier_val=0)
        st["shards_nodes"] = await fetch_all_user_cards_gql(page, uid, modifier_val=1)
        st["craftable_by_rank"] = expand_craftable_cards_by_rank(st["cards_nodes"])


async def forge_local_triples_on_account(st: dict) -> int:
    """
    Переплавляет все доступные локальные тройки карт на одном аккаунте снизу вверх (F -> D -> C -> B -> A -> S),
    пока есть тройки и свободные попытки кузни (available_slots > 0).
    Возвращает количество выполненных переплавок.
    """
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

                # Перечитываем инвентарь, чтобы новая карта сразу участвовала в переплавке следующего ранга
                st["cards_nodes"] = await fetch_all_user_cards_gql(page, st["user_id"], modifier_val=0)
                st["craftable_by_rank"] = expand_craftable_cards_by_rank(st["cards_nodes"])
                break  # Начинаем проверку заново с низшего ранга

        if not did_forge_in_pass:
            break

    return forged_count


async def run_smart_forge_and_trade_pipeline() -> None:
    """
    Полный конвейер Умной Переплавки + Межаккаунтного Трейда + Финальной отправки на cesium254.
    """
    send_tg_message(
        "⚒️ Запускаю умную Кузницу («Переплавка» 3 в 1 до S ранга) и проверку трейдов на всех 4 аккаунтах...",
        add_keyboard=False,
    )

    proxy_mgr = AccountProxyManager()
    state_map: dict[str, dict] = {}

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            contexts: list[BrowserContext] = []

            # 1. Запускаем все 4 фарм-аккаунта под уникальными IP
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

            # 2. Первичная загрузка инвентаря и слотов кузни + локальная переплавка на каждом аккаунте
            await refresh_farm_state(state_map)
            for aid, st in state_map.items():
                await forge_local_triples_on_account(st)

            # 3. Межаккаунтная кооперация: собираем разрозненные карты одного ранга ИЛИ перекидываем тройки
            # на аккаунты, где еще остались свободные слоты кузни (available_slots > 0)!
            for round_idx in range(15):
                await refresh_farm_state(state_map)
                total_free_slots = sum(st["available_slots"] for st in state_map.values())
                if total_free_slots <= 0:
                    break

                # Ищем самый низший ранг r в ["F", "D", "C", "B", "A"], где суммарно по всем 4 аккаунтам есть >= 3 карт
                target_rank = None
                for r in FORGE_UPGRADE_CHAIN:
                    total_r = sum(len(st["craftable_by_rank"].get(r, [])) for st in state_map.values())
                    if total_r >= 3:
                        target_rank = r
                        break

                if not target_rank:
                    # Ни одного ранга F..A больше нет даже по 3 штуки суммарно — ВСЯ переплавка полностью завершена!
                    break

                # Выбираем целевой аккаунт со свободными слотами кузни (предпочитаем тот, у которого уже больше карт этого ранга)
                ReceiverCandidates = [
                    st for st in state_map.values() if st["available_slots"] > 0
                ]
                if not ReceiverCandidates:
                    break
                ReceiverCandidates.sort(
                    key=lambda s: (len(s["craftable_by_rank"].get(target_rank, [])), s["available_slots"]),
                    reverse=True,
                )
                receiver = ReceiverCandidates[0]
                rec_id = receiver["acc"]["id"]
                rec_uid = receiver["user_id"]

                have_on_receiver = len(receiver["craftable_by_rank"].get(target_rank, []))
                need_count = max(0, 3 - have_on_receiver)

                if need_count == 0:
                    # У получателя уже >= 3 карт этого ранга и есть слот — просто переплавляем!
                    await forge_local_triples_on_account(receiver)
                    continue

                # Добираем недостающие need_count карт ранга target_rank с других фарм-аккаунтов
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

            # 4. Финальная проверка после всех переплавок
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

            # Если остались недокрафченные тройки из-за исчерпания 5/5 лимитов кузни на всех 4 аккаунтах:
            if remaining_craftable_ranks and total_free_slots == 0:
                rem_str = ", ".join(f"{cnt}×{r}" for r, cnt in remaining_craftable_ranks.items())
                report_lines.append(
                    "⏳ <b>Внимание: суточные лимиты кузни (5 из 5) на всех 4 аккаунтах исчерпаны!</b>\n"
                    f"Остались карты для дальнейшей переплавки ({rem_str}). "
                    "Трейд на основу <b>cesium254</b> отложен до завтрашнего сброса лимитов, чтобы докачать карты до максимального ранга!"
                )
            else:
                # Все возможные крафты завершены! Отправляем ВСЕ карты и осколки с 4 аккаунтов на основу cesium254
                first_page = next(iter(state_map.values()))["page"]
                main_res = await gql_call(first_page, GQL_FETCH_USER_ID, {"slug": MAIN_ACCOUNT_SLUG}, "fetchUserId")
                main_user = (main_res.get("data") or {}).get("user")
                if not main_user or not main_user.get("id"):
                    report_lines.append(f"⚠️ Не удалось получить ID основного аккаунта {MAIN_ACCOUNT_SLUG}.")
                else:
                    main_uid = main_user["id"]
                    total_sent_cards: Counter = Counter()
                    total_sent_shards: Counter = Counter()
                    sent_accounts_count = 0

                    for aid, st in state_map.items():
                        # Собираем все незаблокированные целые карты и все осколки
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

                        # Отправляем трейдами по 50 позиций (лимит Senkuro на 1 трейд)
                        for i in range(0, len(all_offer_entries), 50):
                            chunk = all_offer_entries[i : i + 50]
                            tr_res = await gql_call(
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
                            if ((tr_res.get("data") or {}).get("suggestCardTrade") or {}).get("success"):
                                sent_accounts_count += 1

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
                            f"🎁 <b>Всего хватило, вся переплавка завершена! Отправляю вам трейд на основу <a href=\"{MAIN_ACCOUNT_URL}\">{MAIN_ACCOUNT_SLUG}</a>:</b>\n"
                            f"🃏 <b>Карты ({sum(total_sent_cards.values())} шт.):</b> {c_summary}\n"
                            f"🧩 <b>Осколки ({sum(total_sent_shards.values())} шт.):</b> {s_summary}"
                        )
                    else:
                        report_lines.append("ℹ️ На фарм-аккаунтах сейчас нет свободных карт или осколков для отправки на основу.")

            # Сохраняем сессии всех аккаунтов
            for aid, st in state_map.items():
                await st["context"].storage_state(path=str(get_session_file(aid)))
            for ctx in contexts:
                await ctx.close()
            await browser.close()
    finally:
        proxy_mgr.stop_all()

    send_tg_message("\n".join(report_lines), add_keyboard=True)


async def run_only_accept_trades() -> None:
    """Принимает все входящие трейды строго от аккаунтов из белого списка."""
    send_tg_message("🤝 Проверяю и принимаю входящие трейды от своих аккаунтов (Белый список)...", add_keyboard=False)
    proxy_mgr = AccountProxyManager()
    lines = ["🤝 <b>Проверка входящих трейдов (Белый список: ber_turtle, ainz, catswat, wolfrice, cesium254):</b>\n"]
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            for acc in FARM_ACCOUNTS:
                proxy_url = proxy_mgr.start_account_proxy(acc)
                ip_used = proxy_mgr.active_ips.get(acc["acc_id"], "прямой")
                ctx = await create_account_context(browser, acc, proxy_url)
                try:
                    page, user_obj = await ensure_logged_in(ctx, acc)
                    if not user_obj:
                        lines.append(f"❌ <b>{acc['id']}</b>: ошибка входа")
                        continue
                    accepted = await accept_whitelisted_incoming_trades(page, acc["id"], user_obj["id"])
                    if accepted:
                        lines.append(f"✅ <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): " + "; ".join(accepted))
                    else:
                        lines.append(f"ℹ️ <b>{acc['id']}</b> (IP: <code>{ip_used}</code>): нет ожидающих трейдов от своих аккаунтов")
                    await ctx.storage_state(path=str(get_session_file(acc["id"])))
                finally:
                    await ctx.close()
            await browser.close()
    finally:
        proxy_mgr.stop_all()
    send_tg_message("\n".join(lines), add_keyboard=True)


# ==============================================================================
# 9. СЦЕНАРИЙ 5: КЛАССИЧЕСКИЙ ЧЕКЕР КАРТ И ОСКОЛКОВ ПО ВСЕМ 5 АККАУНТАМ (С ФОТО)
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

        # Fallback через прямое разрешение userId
        u_res = await gql_call(page, GQL_FETCH_USER_ID, {"slug": account["id"]}, "fetchUserId")
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
# 10. ТОЧКА ВХОДА И МАРШРУТИЗАТОР КОМАНД (CLI + GITHUB ACTIONS ENV)
# ==============================================================================

async def async_main() -> None:
    parser = argparse.ArgumentParser(description="Senkuro Full Automation Suite v7.0")
    parser.add_argument(
        "--action",
        default=os.environ.get("SENKURO_ACTION", "check").strip().lower() or "check",
        choices=["check", "promo", "packs", "forge", "trades", "all"],
        help="Режим работы: check (проверка 5 аккаунтов), promo (промокод), packs (крутка Хардкор), forge (переплавка + трейд), trades (принять трейды), all (всё сразу)",
    )
    parser.add_argument(
        "--promo-code",
        default=os.environ.get("SENKURO_PROMO_CODE", "").strip(),
        help="Промокод для активации на всех 4 аккаунтах",
    )
    args = parser.parse_args()

    action = args.action
    promo_code = args.promo_code

    print(f"🚀 Запуск Senkuro Automation v7.0 | Режим: {action} | Промокод: {promo_code or '-'}")

    if action == "promo":
        await run_promo_code_activation(promo_code)
    elif action == "packs":
        await run_all_packs_opening()
    elif action == "forge":
        await run_smart_forge_and_trade_pipeline()
    elif action == "trades":
        await run_only_accept_trades()
    elif action == "all":
        if promo_code:
            await run_promo_code_activation(promo_code)
        await run_all_packs_opening()
        await run_smart_forge_and_trade_pipeline()
    else:
        await run_check_all_5_accounts()


if __name__ == "__main__":
    asyncio.run(async_main())
