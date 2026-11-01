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
    """Преобразует список edges из ответа GraphQL Senkuro в плоский список карт/осколков."""
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


def extract_rank_dom(slug: str, style_attr: str, text_content: str) -> str:
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
    """Надежное извлечение карточек прямо из DOM страницы."""
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


async def fetch_remaining_pages_in_browser(page, req_url: str, req_headers: dict, req_body: dict, initial_edges: list[dict], next_cursor: str | None) -> list[dict]:
    """Докачивает 2-ю, 3-ю и последующие страницы через браузерный fetch, если на странице >20 карт."""
    all_edges = list(initial_edges)
    if not next_cursor:
        return all_edges

    extra_edges = await page.evaluate(
        """async ({ url, headers, baseBody, startCursor }) => {
        const collected = [];
        let afterCursor = startCursor;
        const seenCursors = new Set([startCursor]);

        const cleanHeaders = {
            'Content-Type': 'application/json',
            'Accept': 'application/graphql-response+json, application/graphql+json, application/json',
            'App-Id': headers['app-id'] || headers['App-Id'] || '4026531840100',
            'App-Version': headers['app-version'] || headers['App-Version'] || '301026'
        };

        for (let i = 0; i < 40; i++) {
            try {
                const payload = JSON.parse(JSON.stringify(baseBody));
                payload.variables = payload.variables || {};
                payload.variables.after = afterCursor;

                const resp = await fetch(url, {
                    method: 'POST',
                    headers: cleanHeaders,
                    body: JSON.stringify(payload)
                });
                if (!resp.ok) break;
                const data = await resp.json();
                const uc = data?.data?.userCards;
                if (!uc) break;

                if (Array.isArray(uc.edges)) {
                    collected.push(...uc.edges);
                }
                const pi = uc.pageInfo || {};
                if (pi.hasNextPage && pi.endCursor && !seenCursors.has(pi.endCursor)) {
                    seenCursors.add(pi.endCursor);
                    afterCursor = pi.endCursor;
                } else {
                    break;
                }
            } catch (e) {
                break;
            }
        }
        return collected;
    }""",
        {
            "url": req_url,
            "headers": req_headers,
            "baseBody": req_body,
            "startCursor": next_cursor,
        },
    )
    if isinstance(extra_edges, list):
        all_edges.extend(extra_edges)
    return all_edges


async def collect_tab_items(page, captured_responses: list[dict]) -> list[dict]:
    """
    Собирает элементы текущей вкладки (Карты или Осколки):
    1. Сначала берет реальный ответ сервера Senkuro (и докачивает страницы 2+, если hasNextPage=true).
    2. Дополнительно скроллит страницу и сверяет с DOM: если в DOM больше элементов или ответ не перехвачен,
       объединяет/берет из DOM, чтобы НИКОГДА не вернуть 0 карт на непустом аккаунте!
    """
    # Прокручиваем страницу вниз, чтобы сам браузер тоже подгрузил карточки в DOM
    for _ in range(3):
        await page.evaluate(
            """() => {
            const cards = document.querySelectorAll('.card-collect-preview, a.card-collect');
            if (cards.length > 0) {
                cards[cards.length - 1].scrollIntoView({ behavior: 'instant', block: 'end' });
            }
            window.scrollTo(0, document.body.scrollHeight);
        }"""
        )
        await page.wait_for_timeout(800)

    dom_items = await extract_items_from_dom(page)

    if captured_responses:
        last_cap = captured_responses[-1]
        all_edges = await fetch_remaining_pages_in_browser(
            page,
            last_cap["url"],
            last_cap["headers"],
            last_cap["postData"],
            last_cap["edges"],
            last_cap["endCursor"] if last_cap["hasNextPage"] else None,
        )
        gql_items = parse_graphql_edges(all_edges)
        if len(gql_items) >= len(dom_items) and len(gql_items) > 0:
            return gql_items

    return dom_items


async def scrape_account(context, account: dict) -> dict:
    """Последовательно открывает профиль и собирает все Карты и Осколки с двойной проверкой (GraphQL + DOM)."""
    page = await context.new_page()
    print(f"Проверка {account['label']} -> {account['url']}")

    card_responses = []
    shard_responses = []
    current_mode = "cards"

    async def on_response(response):
        if "graphql" in response.url and response.request.method == "POST":
            try:
                post_str = response.request.post_data or ""
                if not post_str:
                    return
                post_json = json.loads(post_str)
                if not isinstance(post_json, dict) or post_json.get("operationName") != "fetchUserCards":
                    return
                resp_json = await response.json()
                uc = (resp_json.get("data") or {}).get("userCards")
                if not uc:
                    return
                entry = {
                    "url": response.url,
                    "headers": response.request.headers,
                    "postData": post_json,
                    "edges": uc.get("edges") or [],
                    "hasNextPage": bool((uc.get("pageInfo") or {}).get("hasNextPage")),
                    "endCursor": (uc.get("pageInfo") or {}).get("endCursor"),
                }
                if current_mode == "cards":
                    card_responses.append(entry)
                else:
                    shard_responses.append(entry)
            except Exception:
                pass

    page.on("response", on_response)

    try:
        await page.goto(account["url"], wait_until="domcontentloaded", timeout=35000)
        try:
            await page.wait_for_selector(".card-collect-preview, a.card-collect", timeout=7000)
        except Exception:
            await page.wait_for_timeout(2500)

        await page.wait_for_timeout(1200)
        cards = await collect_tab_items(page, card_responses)
        print(f"  Итог карт у {account['id']}: {len(cards)}")

        # Переключаемся на вкладку «Осколки»
        shards = []
        shard_tab = page.locator("text=/Осколки/i").first
        if await shard_tab.count() > 0:
            current_mode = "shards"
            await shard_tab.click()
            await page.wait_for_timeout(2000)
            shards = await collect_tab_items(page, shard_responses)
            print(f"  Итог осколков у {account['id']}: {len(shards)}")

        return {"cards": cards, "shards": shards, "error": None}
    except Exception as e:
        print(f"Ошибка при проверке {account['id']}: {e}")
        return {"cards": [], "shards": [], "error": str(e)}
    finally:
        await page.close()


def format_rank_breakdown(items: list[dict]) -> str:
    """Форматирует краткую сводку по рангам: например '3 🟥 S  |  1 🟨 A  |  2 🟪 B'."""
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

    # Прикрепляем фотографии ВСЕХ целых карт (отсортированных от высшего ранга R/S/A/B к низшему F)
    card_photos = [c["img"] for c in cards if c.get("img", "").startswith("http")]
    return full_text, card_photos


def send_account_report(text: str, photo_urls: list[str], add_reply_button: bool = False):
    """
    Отправляет отчёт и картинки ВСЕХ целых карт по аккаунту.
    Если карт больше 10, разбивает фотографии на альбомы по 10 штук.
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
