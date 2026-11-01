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
    "S": "🟥 S",
    "A": "🟨 A",
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


def parse_graphql_edges(edges: list[dict]) -> list[dict]:
    """Преобразует список edges из ответа GraphQL Senkuro в плоский список карт/осколков (с учетом quantity)."""
    parsed = []
    for edge in edges:
        node = edge.get("node") or {}
        card = node.get("card") or {}
        qty = int(node.get("quantity") or 1)
        rank = str(card.get("rank") or "?").upper()
        slug = card.get("slug") or ""
        url = f"https://senkuro.com/cards/{slug}" if slug else "https://senkuro.com"

        name = "Карта"
        titles = card.get("titles") or []
        for t in titles:
            if t.get("lang") == "ru" and t.get("text"):
                name = t["text"]
                break
        if name == "Карта" and titles and titles[0].get("text"):
            name = titles[0]["text"]

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


async def fetch_all_pages_via_graphql(page, captured_req: dict, modifier_val: int) -> list[dict]:
    """
    Использует пойманный заголовок и шаблон запроса браузера к https://api.senkuro.com/graphql,
    чтобы напрямую выгрузить ВСЕ страницы (page 1, page 2, page 3...) через курсор `after`
    до тех пор, пока `hasNextPage` не станет False.
    """
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


def extract_rank_dom(slug: str, style_attr: str, text_content: str) -> str:
    """Резервное определение ранга карты из DOM."""
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
    """Резервное извлечение из DOM на случай, если GraphQL-запрос не был перехвачен."""
    raw_items = await page.evaluate(
        """() => {
        const results = [];
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
            results.push({ href, style, name: name || 'Карта', img, titleText });
        });
        return results;
    }"""
    )
    parsed = []
    for item in raw_items:
        href = item["href"]
        full_url = f"https://senkuro.com{href}" if href.startswith("/") else href
        rank = extract_rank_dom(href, item["style"], item["titleText"])
        parsed.append({"slug": href, "url": full_url, "name": item["name"], "rank": rank, "img": item["img"]})
    rank_idx = {r: i for i, r in enumerate(RANK_ORDER)}
    parsed.sort(key=lambda x: (rank_idx.get(x["rank"], 9), x["name"]))
    return parsed


async def scrape_account(context, account: dict) -> dict:
    """
    Открывает страницу аккаунта, перехватывает официальный запрос Senkuro `fetchUserCards`
    и за 1–2 секунды выкачивает абсолютно все карточки (modifier=0) и осколки (modifier=1)
    по всем страницам пагинации без пропуска!
    """
    page = await context.new_page()
    print(f"Проверка {account['label']} -> {account['url']}")

    captured_req = {}

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

        # Ждем до 8 секунд, пока страница сама отправит первый запрос fetchUserCards
        for _ in range(16):
            if captured_req:
                break
            await page.wait_for_timeout(500)

        if captured_req:
            cards = await fetch_all_pages_via_graphql(page, captured_req, modifier_val=0)
            shards = await fetch_all_pages_via_graphql(page, captured_req, modifier_val=1)
            print(f"  [GraphQL API] {account['id']}: карт = {len(cards)}, осколков = {len(shards)}")
            return {"cards": cards, "shards": shards, "error": None}

        # Резервный вариант через DOM, если GraphQL не перехватился
        await page.wait_for_timeout(2500)
        cards = await extract_items_from_dom(page)
        shards = []
        shard_tab = page.locator("text=/Осколки/i").first
        if await shard_tab.count() > 0:
            await shard_tab.click()
            await page.wait_for_timeout(2000)
            shards = await extract_items_from_dom(page)
        print(f"  [DOM Fallback] {account['id']}: карт = {len(cards)}, осколков = {len(shards)}")
        return {"cards": cards, "shards": shards, "error": None}
    except Exception as e:
        print(f"Ошибка при проверке {account['id']}: {e}")
        return {"cards": [], "shards": [], "error": str(e)}
    finally:
        await page.close()


def format_rank_breakdown(items: list[dict]) -> str:
    """Форматирует краткую сводку по рангам: например '3 🟥 S  |  3 🟪 B  |  7 🟦 C'."""
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
    """Формирует компактный отчёт по аккаунту со ВСЕМИ карточками и список фото ЦЕЛЫХ карт."""
    cards = current["cards"]
    shards = current["shards"]

    total_cards = len(cards)
    total_shards = len(shards)

    cards_summary = format_rank_breakdown(cards)
    shards_summary = format_rank_breakdown(shards)

    lines = [
        f"👤 <b><a href=\"{account['url']}\">{account['label']}</a></b>",
        "",
        f"🃏 <b>Карты ({total_cards}):</b> {cards_summary}",
        f"🧩 <b>Осколки ({total_shards}):</b> {shards_summary}",
    ]

    full_text = "\n".join(lines)

    # Прикрепляем фотографии ВСЕХ целых карт (отсортированных от высшего ранга R/S к низшему F)
    card_photos = [c["img"] for c in cards if c.get("img", "").startswith("http")]
    return full_text, card_photos


def send_account_report(text: str, photo_urls: list[str], add_reply_button: bool = False):
    """
    Отправляет отчёт и картинки ВСЕХ целых карт по аккаунту.
    Если карт больше 10 (например, 33 штуки на основе), разбивает фотографии на альбомы по 10 штук,
    чтобы Telegram показал абсолютно все карты без урезания!
    """
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
                item = {"type": "photo", "media": url}
                if idx == 0:
                    item["caption"] = text
                    item["parse_mode"] = "HTML"
                media.append(item)
            res = tg_request("sendMediaGroup", {"chat_id": TELEGRAM_CHAT_ID, "media": media})
            if res.get("ok"):
                return

    # Если альбомов несколько (>10 карт) или это последний аккаунт с кнопкой:
    # отправляем все пачки фотографий по 10 штук, а следом — итоговое сообщение с текстом (и кнопкой)
    for chunk in chunks:
        if len(chunk) == 1:
            tg_request("sendPhoto", {"chat_id": TELEGRAM_CHAT_ID, "photo": chunk[0]})
        else:
            media = [{"type": "photo", "media": url} for url in chunk]
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

        for idx, acc in enumerate(ACCOUNTS):
            acc_data = await scrape_account(context, acc)
            is_last = idx == len(ACCOUNTS) - 1

            if acc_data["error"]:
                err_msg = f"⚠️ <b><a href=\"{acc['url']}\">{acc['label']}</a></b>: ошибка загрузки ({acc_data['error']})"
                send_account_report(err_msg, [], add_reply_button=is_last)
                continue

            text, card_photos = build_account_message(acc, acc_data)
            send_account_report(text, card_photos, add_reply_button=is_last)
            await asyncio.sleep(1.0)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
