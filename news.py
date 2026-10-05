from datetime import datetime, timedelta, timezone


def get_recent_news(minutes=60):
    """
    خبرهای منتشرشده در `minutes` دقیقه‌ی اخیر رو برمی‌گردونه.

    قرارداد خروجی (دوستت باید دقیقاً همین شکل رو برگردونه):
    لیستی از دیکشنری‌ها، هر کدوم:
      - published_at: رشته‌ی ISO، UTC  (مثلاً "2026-10-03T09:10:00+00:00")
      - source: نام منبع               (مثلاً "CoinDesk")
      - title: عنوان خبر
      - summary: خلاصه یا چند خط اول متن (می‌تونه رشته‌ی خالی باشه)
    مرتب‌شده از جدید به قدیم، بدون خبر تکراری.
    """
    now = datetime.now(timezone.utc)
    mock = [
        {
            "published_at": (now - timedelta(minutes=12)).isoformat(),
            "source": "MockNews",
            "title": "Spot Bitcoin ETFs see net inflows for third straight day",
            "summary": "Net inflows into US spot Bitcoin ETFs continued, led by the largest issuers.",
        },
        {
            "published_at": (now - timedelta(minutes=35)).isoformat(),
            "source": "MockNews",
            "title": "Fed official signals patience on rate cuts",
            "summary": "A Federal Reserve official said policymakers want more data before easing further.",
        },
    ]
    return [n for n in mock if datetime.fromisoformat(n["published_at"]) >= now - timedelta(minutes=minutes)]


if __name__ == "__main__":
    for n in get_recent_news():
        print(n)