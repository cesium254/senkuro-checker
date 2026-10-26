import asyncio
import json
import os
import re
import urllib.request
import urllib.error
from collections import Counter
from playwright.async_api import async_playwright

TELEGRAM_BOT_TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    or "8868493953:AAHyGgQCt4n2FrvyL6mPmFK8w1fq_LNpug4"
)
TELEGRAM_CHAT_ID = (
    os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    or "457787014"
)

ACCOUNTS = [
    {"id": "ber_turtle", "label": "First (Ber Turtle)", "url": "https://senkuro.com/users/ber_turtle/cards"},
    {"id": "ainz", "label": "Second (Ainz)", "url": "https://senkuro.com/users/ainz/cards"},
    {"id": "catswat", "label": "Third (Cat Swat)", "url": "https://senkuro.com/users/catswat/cards"},
    {"id": "wolfrice", "label": "Fourth (Wolf Rice)", "url": "https://senkuro.com/users/wolfrice/cards"},
    {"id": "cesium254", "label": "Main (Cesium254)", "url": "https://senkuro.com/users/cesium254/cards"},
]

RANK_ORDER = ["R", "S", "A", "B", "C", "D", "F", "?"]
RANK_BADGE = {
    "R": "💎 R",
    "S": "🟨 S",
    "A": "🟥 A",
    "B": "🟪 B",
    "C": "🟦 C",
    "D": "🟩 D",
    "F": "⬜ F",
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


def extract_rank(slug: str, style_attr: str, text_content: str) -> str:
    """Определение ранга карты из clip-path, ссылки или текста."""
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


async def extract_items_from_dom(page) -> list[dict]:
    """Извлекает ровно 1 запись на каждую карточку/осколок (без дублей x3)."""
    raw_items = await page.evaluate(
        """() => {
        const results = [];
        // Выбираем только верхнеуровневый контейнер карточки, чтобы не множить на 3!
        let elements = Array.from(document.querySelectorAll('.card-collect-preview'));
        if (elements.length === 0) {
            elements = Array.from(document.querySelectorAll('a.card-collect'));
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
            const titleText = infoEl ? infoEl.innerText.trim() : el.innerText.trim();

            results.push({
                href,
                style,
                name: name || 'Карта',
                img,
                titleText
            });
        });
        return results;
    }"""
    )

    parsed = []
    for item in raw_items:
        href = item["href"]
        full_url = f"https://senkuro.com{href}" if href.startswith("/") else href
        rank = extract_rank(href, item["style"], item["titleText"])
        parsed.append(
            {
                "slug": href,
                "url": full_url,
                "name": item["name"],
                "rank": rank,
                "img": item["img"],
            }
        )

    rank_idx = {r: i for i, r in enumerate(RANK_ORDER)}
    parsed.sort(key=lambda x: (rank_idx.get(x["rank"], 9), x["name"]))
    return parsed


async def scrape_account(context, account: dict) -> dict:
    """Последовательно открывает профиль и считывает Карты и Осколки."""
    page = await context.new_page()
    print(f"Проверка {account['label']} -> {account['url']}")
    try:
        # Используем domcontentloaded вместо networkidle, чтобы никогда не падало по Timeout 45000ms
        await page.goto(account["url"], wait_until="domcontentloaded", timeout=30000)
        try:
            await page.wait_for_selector(".card-collect-preview, a.card-collect", timeout=8000)
        except Exception:
            await page.wait_for_timeout(2500)

        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(1000)

        cards = await extract_items_from_dom(page)

        # Переключаемся на вкладку «Осколки»
        shards = []
        shard_tab = page.locator("text=/Осколки/i").first
        if await shard_tab.count() > 0:
            await shard_tab.click()
            await page.wait_for_timeout(2000)
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(800)
            shards = await extract_items_from_dom(page)

        return {"cards": cards, "shards": shards, "error": None}
    except Exception as e:
        print(f"Ошибка при проверке {account['id']}: {e}")
        return {"cards": [], "shards": [], "error": str(e)}
    finally:
        await page.close()


def format_rank_breakdown(items: list[dict], word_one: str, word_two: str, word_many: str) -> str:
    """Форматирует краткую сводку по рангам: например '1 B-ранга, 2 C-ранга, 3 D-ранга'."""
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
    """Формирует компактный отчёт по аккаунту (только текущее наличие) и список фото ЦЕЛЫХ карт."""
    cards = current["cards"]
    shards = current["shards"]

    total_cards = len(cards)
    total_shards = len(shards)

    cards_summary = format_rank_breakdown(cards, "карта", "карты", "карт")
    shards_summary = format_rank_breakdown(shards, "осколок", "осколка", "осколков")

    lines = [
        f"👤 <b><a href=\"{account['url']}\">{account['label']}</a></b>",
        "",
        f"🃏 <b>Карты ({total_cards}):</b> {cards_summary}",
        f"🧩 <b>Осколки ({total_shards}):</b> {shards_summary}",
    ]

    full_text = "\n".join(lines)

    # Прикрепляем фотографии ТОЛЬКО целых карт (без осколков, чтобы не путать!)
    card_photos = [c["img"] for c in cards if c.get("img", "").startswith("http")]
    return full_text, card_photos[:10]


def send_account_report(text: str, photo_urls: list[str], add_reply_button: bool = False):
    """Отправляет компактный отчёт и картинки целых карт по аккаунту."""
    if photo_urls and not add_reply_button:
        if len(photo_urls) == 1:
            res = tg_request(
                "sendPhoto",
                {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "photo": photo_urls[0],
                    "caption": text,
                    "parse_mode": "HTML",
                },
            )
            if res.get("ok"):
                return
        else:
            media = []
            for idx, url in enumerate(photo_urls[:10]):
                item = {"type": "photo", "media": url}
                if idx == 0:
                    item["caption"] = text
                    item["parse_mode"] = "HTML"
                media.append(item)
            res = tg_request("sendMediaGroup", {"chat_id": TELEGRAM_CHAT_ID, "media": media})
            if res.get("ok"):
                return

    # Для последнего (5-го) аккаунта: сначала отправляем альбом его карт, а следом — его текст с кнопкой запуска
    if photo_urls:
        if len(photo_urls) == 1:
            tg_request("sendPhoto", {"chat_id": TELEGRAM_CHAT_ID, "photo": photo_urls[0]})
        else:
            media = [{"type": "photo", "media": url} for url in photo_urls[:10]]
            tg_request("sendMediaGroup", {"chat_id": TELEGRAM_CHAT_ID, "media": media})

    msg_payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if add_reply_button:
        msg_payload["reply_markup"] = {
            "inline_keyboard": [[{"text": "🔄 Проверить все 5 аккаунтов", "callback_data": "check_senkuro"}]]
        }
    tg_request("sendMessage", msg_payload)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="ru-RU",
        )

        # Проверяем аккаунты СТРОГО ПО ОЧЕРЕДИ (чтобы не триггерить защиту от DDoS и слать сообщения по порядку)
        for idx, acc in enumerate(ACCOUNTS):
            acc_data = await scrape_account(context, acc)
            is_last = idx == len(ACCOUNTS) - 1

            if acc_data["error"]:
                err_msg = f"⚠️ <b><a href=\"{acc['url']}\">{acc['label']}</a></b>: ошибка загрузки ({acc_data['error']})"
                send_account_report(err_msg, [], add_reply_button=is_last)
                continue

            text, card_photos = build_account_message(acc, acc_data)
            send_account_report(text, card_photos, add_reply_button=is_last)
            # Небольшая пауза между аккаунтами
            await asyncio.sleep(1.5)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
