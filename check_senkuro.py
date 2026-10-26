import asyncio
import json
import os
import re
import urllib.request
import urllib.error
from datetime import datetime, timezone
from playwright.async_api import async_playwright

TELEGRAM_BOT_TOKEN = (
    os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    or "8868493953:AAHyGgQCt4n2FrvyL6mPmFK8w1fq_LNpug4"
)
TELEGRAM_CHAT_ID = (
    os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    or "457787014"
)
STATE_FILE = os.environ.get("STATE_FILE", "last_state.json")

ACCOUNTS = [
    {"id": "ber_turtle", "label": "First (Ber Turtle)", "url": "https://senkuro.com/users/ber_turtle/cards"},
    {"id": "ainz", "label": "Second (Ainz)", "url": "https://senkuro.com/users/ainz/cards"},
    {"id": "catswat", "label": "Third (Cat Swat)", "url": "https://senkuro.com/users/catswat/cards"},
    {"id": "wolfrice", "label": "Fourth (Wolf Rice)", "url": "https://senkuro.com/users/wolfrice/cards"},
    {"id": "cesium254", "label": "Main (Cesium254)", "url": "https://senkuro.com/users/cesium254/cards"},
]

RANK_ORDER = {"R": 0, "S": 1, "A": 2, "B": 3, "C": 4, "D": 5, "F": 6, "?": 7}
RANK_BADGE = {
    "R": "💎 [R]",
    "S": "🟨 [S]",
    "A": "🟥 [A]",
    "B": "🟪 [B]",
    "C": "🟦 [C]",
    "D": "🟩 [D]",
    "F": "⬜ [F]",
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
    """Извлекает карточки или осколки из текущей открытой вкладки DOM."""
    raw_items = await page.evaluate(
        """() => {
        const results = [];
        const cards = document.querySelectorAll('.card-collect-preview, .user-card, a.card-collect');
        const seen = new Set();
        cards.forEach(el => {
            const linkEl = el.tagName === 'A' ? el : el.querySelector('a.card-collect, a[href*="/cards/"]');
            const href = linkEl ? linkEl.getAttribute('href') : '';
            if (!href || !href.includes('/cards/')) return;
            const style = linkEl ? (linkEl.getAttribute('style') || '') : '';
            const imgEl = el.querySelector('img.card-collect__img, img');
            const name = imgEl ? (imgEl.getAttribute('alt') || '').trim() : '';
            const img = imgEl ? (imgEl.getAttribute('src') || '').trim() : '';
            const infoEl = el.querySelector('.card-collect-preview__info, .card-collect-preview__title');
            const titleText = infoEl ? infoEl.innerText.trim() : el.innerText.trim();
            
            // Поиск количества (если есть бейдж x2, ×2 и т.д.)
            let qty = 1;
            const qtyMatch = el.innerText.match(/[xх×]\\s*(\\d+)/i);
            if (qtyMatch) {
                qty = parseInt(qtyMatch[1], 10) || 1;
            }
            
            const key = href + '|' + name;
            if (seen.has(key)) {
                const existing = results.find(r => (r.href + '|' + r.name) === key);
                if (existing) existing.qty += 1;
                return;
            }
            seen.add(key);
            results.push({
                href,
                style,
                name: name || 'Неизвестная карта',
                img,
                titleText,
                qty
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
        lines = [line.strip() for line in item["titleText"].splitlines() if line.strip()]
        manga_title = ""
        for line in lines:
            if line != item["name"] and line not in ("R", "S", "A", "B", "C", "D", "F") and not re.match(r"^[xх×]?\d+$", line):
                manga_title = line
                break
        parsed.append(
            {
                "slug": href,
                "url": full_url,
                "name": item["name"],
                "rank": rank,
                "manga": manga_title,
                "qty": item["qty"],
                "img": item["img"],
            }
        )

    parsed.sort(key=lambda x: (RANK_ORDER.get(x["rank"], 9), x["name"]))
    return parsed


async def scrape_account(context, account: dict) -> dict:
    """Собирает все карты и осколки с одного аккаунта Senkuro."""
    page = await context.new_page()
    print(f"Проверка {account['label']} -> {account['url']}")
    try:
        await page.goto(account["url"], wait_until="networkidle", timeout=45000)
        await page.wait_for_timeout(2000)

        # Автоскролл вниз на случай ленивой подгрузки карточек
        for _ in range(3):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(600)

        cards = await extract_items_from_dom(page)

        # Переключение на вкладку «Осколки»
        shards = []
        shard_tab = page.locator("text=/Осколки/i").first
        if await shard_tab.count() > 0:
            await shard_tab.click()
            await page.wait_for_timeout(2000)
            for _ in range(2):
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(500)
            shards = await extract_items_from_dom(page)

        return {"cards": cards, "shards": shards, "error": None}
    except Exception as e:
        print(f"Ошибка при проверке {account['id']}: {e}")
        return {"cards": [], "shards": [], "error": str(e)}
    finally:
        await page.close()


def compare_items(old_list: list[dict], new_list: list[dict]) -> dict:
    """Сравнивает прошлый и текущий списки карточек/осколков."""
    old_map = {item["slug"]: item for item in old_list}
    new_map = {item["slug"]: item for item in new_list}

    added = []
    removed = []

    for slug, item in new_map.items():
        if slug not in old_map:
            added.append({**item, "diff_qty": item["qty"]})
        elif item["qty"] > old_map[slug]["qty"]:
            added.append({**item, "diff_qty": item["qty"] - old_map[slug]["qty"]})

    for slug, item in old_map.items():
        if slug not in new_map:
            removed.append({**item, "diff_qty": item["qty"]})
        elif item["qty"] < old_map[slug]["qty"]:
            removed.append({**item, "diff_qty": old_map[slug]["qty"] - item["qty"]})

    return {"added": added, "removed": removed}


def format_item_line(item: dict, prefix: str = "•") -> str:
    badge = RANK_BADGE.get(item["rank"], f"[{item['rank']}]")
    qty_str = f" ×{item['qty']}" if item.get("qty", 1) > 1 else ""
    manga_str = f" — <i>{item['manga']}</i>" if item.get("manga") else ""
    return f"{prefix} {badge} <a href=\"{item['url']}\"><b>{item['name']}</b></a>{qty_str}{manga_str}"


def build_account_message(account: dict, current: dict, prev: dict | None) -> tuple[str, list[dict]]:
    """Формирует HTML-отчёт для аккаунта и список картинок для прикрепления."""
    cards = current["cards"]
    shards = current["shards"]

    total_cards = sum(c.get("qty", 1) for c in cards)
    total_shards = sum(s.get("qty", 1) for s in shards)

    header = f"👤 <b><a href=\"{account['url']}\">{account['label']}</a></b>\n"
    header += f"📊 Итог: <b>{total_cards}</b> карт | <b>{total_shards}</b> осколков\n"

    diff_lines = []
    new_media_items = []

    if prev is None:
        diff_lines.append("🆕 <i>Первая проверка (базовый снимок сохранён)</i>")
    else:
        card_diff = compare_items(prev.get("cards", []), cards)
        shard_diff = compare_items(prev.get("shards", []), shards)

        if not card_diff["added"] and not card_diff["removed"] and not shard_diff["added"] and not shard_diff["removed"]:
            diff_lines.append("✅ <b>Изменений с прошлой проверки нет</b>")
        else:
            diff_lines.append("🔔 <b>Изменения с прошлой проверки:</b>")
            for c in card_diff["added"]:
                diff_lines.append(format_item_line(c, "➕ Карта:"))
                if c.get("img"):
                    new_media_items.append(c)
            for c in card_diff["removed"]:
                diff_lines.append(format_item_line(c, "➖ Ушла карта:"))
            for s in shard_diff["added"]:
                diff_lines.append(format_item_line(s, "➕🧩 Осколок:"))
                if s.get("img"):
                    new_media_items.append(s)
            for s in shard_diff["removed"]:
                diff_lines.append(format_item_line(s, "➖🧩 Ушёл осколок:"))

    body_lines = ["\n".join(diff_lines), ""]

    if cards:
        body_lines.append(f"🃏 <b>Карты ({total_cards}):</b>")
        for c in cards:
            body_lines.append(format_item_line(c))
    else:
        body_lines.append("🃏 <b>Карты:</b> пусто")

    body_lines.append("")
    if shards:
        body_lines.append(f"🧩 <b>Осколки ({total_shards}):</b>")
        for s in shards:
            body_lines.append(format_item_line(s))
    else:
        body_lines.append("🧩 <b>Осколки:</b> нет осколков")

    full_text = header + "\n" + "\n".join(body_lines)

    # Прикрепляем новые выпавшие карты/осколки, а если их нет — показываем до 10 текущих карт/осколков аккаунта
    photos_to_send = new_media_items if new_media_items else [x for x in (cards + shards) if x.get("img")]
    return full_text, photos_to_send[:10]


def send_account_report(text: str, photos: list[dict], add_reply_button: bool = False):
    """Отправляет альбом с картинками карточек и подписью по конкретному аккаунту."""
    valid_photos = [p["img"] for p in photos if p.get("img", "").startswith("http")]

    if valid_photos and len(text) <= 1024 and not add_reply_button:
        if len(valid_photos) == 1:
            res = tg_request(
                "sendPhoto",
                {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "photo": valid_photos[0],
                    "caption": text,
                    "parse_mode": "HTML",
                },
            )
            if res.get("ok"):
                return
        else:
            media = []
            for idx, url in enumerate(valid_photos[:10]):
                item = {"type": "photo", "media": url}
                if idx == 0:
                    item["caption"] = text
                    item["parse_mode"] = "HTML"
                media.append(item)
            res = tg_request("sendMediaGroup", {"chat_id": TELEGRAM_CHAT_ID, "media": media})
            if res.get("ok"):
                return

    # Если текст длиннее 1024 символов, или нужно прикрепить inline-кнопку, или Telegram не принял фото по URL:
    if valid_photos:
        if len(valid_photos) == 1:
            tg_request("sendPhoto", {"chat_id": TELEGRAM_CHAT_ID, "photo": valid_photos[0]})
        else:
            media = [{"type": "photo", "media": url} for url in valid_photos[:10]]
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
    prev_state = {}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                prev_state = json.load(f)
        except Exception as e:
            print(f"Не удалось прочитать {STATE_FILE}: {e}")

    new_state = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "accounts": {},
    }

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 900},
            locale="ru-RU",
        )

        for idx, acc in enumerate(ACCOUNTS):
            acc_data = await scrape_account(context, acc)
            prev_acc = prev_state.get("accounts", {}).get(acc["id"])

            # Если возникла временная ошибка сети, сохраняем прошлое состояние
            if acc_data["error"] and prev_acc:
                new_state["accounts"][acc["id"]] = prev_acc
                err_msg = f"⚠️ <b>{acc['label']}</b>: ошибка загрузки ({acc_data['error']})"
                send_account_report(err_msg, [], add_reply_button=(idx == len(ACCOUNTS) - 1))
                continue

            new_state["accounts"][acc["id"]] = {
                "cards": acc_data["cards"],
                "shards": acc_data["shards"],
            }

            text, photos = build_account_message(acc, acc_data, prev_acc)
            is_last = idx == len(ACCOUNTS) - 1
            send_account_report(text, photos, add_reply_button=is_last)

        await browser.close()

    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(new_state, f, ensure_ascii=False, indent=2)
    print(f"Состояние успешно обновлено в {STATE_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
