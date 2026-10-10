import time
import requests
import feedparser

FEEDS = {
    "coindesk":      "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "cointelegraph": "https://cointelegraph.com/rss",
    "decrypt":       "https://decrypt.co/feed",
    "bitcoinmag":    "https://bitcoinmagazine.com/.rss/full/",
    "theblock":      "https://www.theblock.co/rss.xml",
    "cryptoslate":   "https://cryptoslate.com/feed/",
    "bitcoin_news":  "https://news.bitcoin.com/feed/",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; news-test/1.0)"}


def test(name, url):
    t0 = time.time()
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
    except Exception as e:
        print(f"[FAIL] {name}: {type(e).__name__}: {e}")
        return
    dt = time.time() - t0
    if r.status_code != 200:
        print(f"[FAIL] {name}: HTTP {r.status_code} ({dt:.1f}s)")
        return
    feed = feedparser.parse(r.content)
    n = len(feed.entries)
    if n == 0:
        print(f"[FAIL] {name}: HTTP 200 ولی هیچ آیتمی پارس نشد")
        return
    e = feed.entries[0]
    print(f"[OK]   {name}: {n} آیتم، {dt:.1f}s")
    print(f"       published: {e.get('published')}")
    print(f"       title:     {e.get('title')}")
    print(f"       summary:   {(e.get('summary') or '')[:100]!r}")
    print(f"       link:      {e.get('link')}")


if __name__ == "__main__":
    for name, url in FEEDS.items():
        test(name, url)
        print()