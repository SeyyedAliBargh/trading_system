import re
import html
from datetime import datetime, timedelta, timezone

import feedparser
import requests
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.orm import Session

from db import engine, News, init_db

FEEDS = {
    "coindesk":      "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "decrypt":       "https://decrypt.co/feed",
    "theblock":      "https://www.theblock.co/rss.xml",
}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; news-bot/1.0)"}
KEYWORD_RE = re.compile(
    r"\b(bitcoin|btc|crypto|etf|fed|sec|stablecoin|ethereum|market|tariff|inflation|rates?)\b",
    re.IGNORECASE,
)


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clean(text, n=200):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(re.sub(r"\s+", " ", text)).strip()
    return text[:n]


def collect_news():
    now = _now()
    rows = []
    for source, url in FEEDS.items():
        try:
            r = requests.get(url, headers=HEADERS, timeout=15)
            r.raise_for_status()
        except Exception as e:
            print(f"[news] {source} failed: {e}")
            continue
        entries = feedparser.parse(r.content).entries
        if not entries:
            print(f"[news] {source}: 0 entries (status {r.status_code})")
        for e in entries:
            pp = e.get("published_parsed") or e.get("updated_parsed")
            if not pp or not e.get("link"):
                continue
            rows.append({
                "url": e.link.split("?")[0],
                "source": source,
                "title": _clean(e.get("title"), 300),
                "summary": _clean(e.get("summary")),
                "published_at": datetime(*pp[:6]),  # published_parsed در feedparser UTC است
                "fetched_at": now,
            })
    if not rows:
        return 0
    with Session(engine) as s:
        res = s.execute(insert(News).values(rows).on_conflict_do_nothing())
        s.commit()
        print(f"[news] +{res.rowcount} new")
        return res.rowcount
    

def get_recent_news(minutes=60, now=None, limit=8):
    now = now or _now()
    since = now - timedelta(minutes=minutes)
    with Session(engine) as s:
        items = s.scalars(
            select(News)
            .where(News.published_at >= since, News.fetched_at <= now)
            .order_by(News.published_at.desc())
        ).all()
    out = []
    for n in items:
        if KEYWORD_RE.search(f"{n.title} {n.summary or ''}"):
            out.append({
                "published_at": n.published_at.isoformat() + "Z",
                "source": n.source,
                "title": n.title,
                "summary": n.summary,
            })
        if len(out) >= limit:
            break
    return out


if __name__ == "__main__":
    init_db()
    print("new rows:", collect_news())
    for n in get_recent_news(minutes=360):
        print(n["published_at"], n["source"], "|", n["title"])