"""
KenBot OS — Live News Fetcher
Pulls real headlines from free public RSS feeds + optional NewsAPI.
No API key needed for RSS mode. Set NEWS_API_KEY in .env for enhanced mode.

Sources:
  World / Top:   BBC News          https://feeds.bbci.co.uk/news/rss.xml
  India:         Times of India    https://timesofindia.indiatimes.com/rssfeedstopstories.cms
  Tech:          BBC Tech          https://feeds.bbci.co.uk/news/technology/rss.xml
  Cricket:       ESPNcricinfo      https://www.espncricinfo.com/rss/content/story/feeds/0.xml
  Sports:        Sportstar (Hindu) https://sportstar.thehindu.com/cricket/?service=rss
  Trending:      Reddit r/worldnews + r/india already in trend_scanner
  Generic:       Google News RSS   https://news.google.com/rss/search?q=<query>
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
from datetime import datetime
from typing import Optional

import feedparser
import requests

from config.settings import settings
from memory.store import memory
from utils.logger import logger

# ── Cache TTLs ────────────────────────────────────────────────────────────────
_NEWS_TTL     = 300   # 5 min for general news (was 15)
_CRICKET_TTL  = 120   # 2 min for live cricket (scores change fast)

# ── RSS feed registry ─────────────────────────────────────────────────────────
_FEEDS = {
    "top": [
        ("BBC World",       "https://feeds.bbci.co.uk/news/rss.xml"),
        ("Times of India",  "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
        ("Reuters",         "https://feeds.reuters.com/reuters/topNews"),
    ],
    "tech": [
        ("BBC Tech",        "https://feeds.bbci.co.uk/news/technology/rss.xml"),
        ("Ars Technica",    "https://feeds.arstechnica.com/arstechnica/index"),
        ("The Verge",       "https://www.theverge.com/rss/index.xml"),
    ],
    "cricket": [
        ("ESPNcricinfo",    "https://www.espncricinfo.com/rss/content/story/feeds/0.xml"),
        ("Sportstar",       "https://sportstar.thehindu.com/cricket/?service=rss"),
        ("Cricbuzz",        "https://cricbuzz.com/cricket-news/rss-feed"),
    ],
    "f1": [
        ("BBC F1",          "https://feeds.bbci.co.uk/sport/formula1/rss.xml"),
        ("Autosport",       "https://www.autosport.com/rss/f1/news/"),
        ("Sky Sports F1",   "https://www.skysports.com/rss/12040"),
        ("Motorsport.com",  "https://www.motorsport.com/rss/f1/news/"),
    ],
    "sports": [
        ("BBC Sport",       "https://feeds.bbci.co.uk/sport/rss.xml"),
        ("ESPN",            "https://www.espn.com/espn/rss/news"),
        ("Sky Sports",      "https://www.skysports.com/rss/0,20514,11661,00.xml"),
        ("Times of India Sport", "https://timesofindia.indiatimes.com/rssfeeds/4719161.cms"),
    ],
    "india": [
        ("Times of India",  "https://timesofindia.indiatimes.com/rssfeedstopstories.cms"),
        ("NDTV",            "https://feeds.feedburner.com/ndtvnews-top-stories"),
        ("The Hindu",       "https://www.thehindu.com/feeder/default.rss"),
    ],
    "gaming": [
        ("IGN",             "https://feeds.ign.com/ign/all"),
        ("PC Gamer",        "https://www.pcgamer.com/rss/"),
        ("Dot Esports",     "https://dotesports.com/feed"),
        ("Dexerto",         "https://www.dexerto.com/feed/"),
    ],
    "esports": [
        ("Dexerto",         "https://www.dexerto.com/feed/"),
        ("Dot Esports",     "https://dotesports.com/feed"),
        ("The Loadout",     "https://www.theloadout.com/feed"),
        ("HLTV",            "https://www.hltv.org/rss/news"),
        ("PC Gamer",        "https://www.pcgamer.com/rss/"),
    ],
}

_HEADERS = {"User-Agent": "KenBot/2.0 (+personal project; contact owner)"}


class NewsFetcher:
    """Fetch live news from RSS feeds. Results are memory-cached per category."""

    # ── Public API ─────────────────────────────────────────────────────────────

    def get_headlines(self, category: str = "top", n: int = 5, force: bool = False) -> list[dict]:
        """
        Return up to n latest headlines for the given category.
        Each item: {title, summary, source, url, published}
        """
        cache_key = f"news_cache_{category}"
        if not force:
            cached = memory.get(cache_key)
            if cached:
                try:
                    data = json.loads(cached) if isinstance(cached, str) else cached
                    age = time.time() - data.get("ts", 0)
                    ttl = _CRICKET_TTL if category == "cricket" else _NEWS_TTL
                    if age < ttl:
                        return data.get("items", [])[:n]
                except Exception:
                    pass

        items = self._fetch_rss_category(category)

        # Fallback: try NewsAPI if key set and RSS gave nothing
        if not items:
            items = self._try_newsapi(category)

        memory.set(cache_key, json.dumps({"ts": time.time(), "items": items[:30]}))
        return items[:n]

    def search_news(self, query: str, max_results: int = 5) -> list[dict]:
        """
        Search live news across all relevant feeds for a query.
        Picks feeds to search based on keywords, then filters by relevance.
        Returns list of matching items sorted by title-match score.
        """
        q = query.lower()

        # Pick which categories to search based on keywords
        cats: list[str] = []
        if any(k in q for k in ["f1", "formula 1", "formula one", "gp", "grand prix",
                                  "qualifying", "race result", "verstappen", "hamilton",
                                  "leclerc", "sainz", "norris", "alonso", "ferrari",
                                  "mercedes", "red bull", "mclaren"]):
            cats += ["f1", "sports"]
        if any(k in q for k in ["cricket", "ipl", "test match", "odi", "t20",
                                  "kohli", "rohit", "bumrah", "bcci", "espncricinfo"]):
            cats += ["cricket", "sports"]
        if any(k in q for k in ["football", "soccer", "premier league", "la liga",
                                  "champions league", "efl", "bundesliga", "serie a",
                                  "fifa", "messi", "ronaldo"]):
            cats += ["sports"]
        if any(k in q for k in ["nba", "nfl", "mlb", "nhl", "ufc", "boxing",
                                  "tennis", "wimbledon", "us open"]):
            cats += ["sports"]
        if any(k in q for k in ["tech", "ai", "apple", "google", "microsoft",
                                  "nvidia", "openai", "startup"]):
            cats += ["tech"]
        if any(k in q for k in ["valorant", "vct", "sentinels", "tenz", "nrg",
                                  "fnatic", "loud", "cloud9", "100 thieves", "faze",
                                  "team liquid", "vitality", "paper rex", "drx",
                                  "masters", "champions", "valo", "esports",
                                  "cs2", "csgo", "dota", "league of legends",
                                  "overwatch", "hltv", "roster swap", "signed",
                                  "streamer", "twitch"]):
            cats += ["esports", "gaming"]
        if not cats:
            cats = ["top", "sports"]  # default broad search

        # Fetch all items from chosen categories (de-duped)
        seen_titles: set[str] = set()
        all_items: list[dict] = []
        for cat in dict.fromkeys(cats):  # preserve order, drop duplicates
            for item in self.get_headlines(cat, n=15):
                key = item["title"].lower()[:50]
                if key not in seen_titles:
                    seen_titles.add(key)
                    all_items.append(item)

        # Score items by keyword overlap with query
        query_words = set(q.split())
        def _score(item: dict) -> int:
            text = (item["title"] + " " + item.get("summary", "")).lower()
            return sum(1 for w in query_words if len(w) > 3 and w in text)

        ranked = sorted(all_items, key=_score, reverse=True)
        return [r for r in ranked if _score(r) > 0][:max_results]

    @staticmethod
    def _clean_summary(text: str) -> str:
        """Strip HTML entities and Google News trailing-source noise from a summary."""
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&nbsp;", " ").replace("&amp;", "&") \
                   .replace("&lt;", "<").replace("&gt;", ">") \
                   .replace("&quot;", '"').replace("\xa0", " ")
        # "Title  Source" pattern — strip trailing source after 2+ spaces
        text = re.sub(r"\s{2,}.{2,50}$", "", text).strip()
        return text

    def google_news_search(self, query: str, n: int = 5) -> list[dict]:
        """
        Search Google News RSS for *any* topic — man city, TenZ, Tesla, anything.
        No API key needed. Results are real-time (Google updates every few minutes).
        """
        cache_key = f"gnews_{query.lower().strip()[:60]}"
        cached = memory.get(cache_key, "")
        if cached:
            try:
                stored = json.loads(cached)
                if time.time() - stored["ts"] < 120:  # 2-min cache
                    return stored["items"][:n]
            except Exception:
                pass

        encoded = urllib.parse.quote_plus(query)
        # No &when filter — rely on Google's natural recency+relevance sorting.
        # This ensures older key facts (player retirements, roster moves, etc.) are found.
        url = f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"
        try:
            feed = feedparser.parse(url)
            items: list[dict] = []
            for entry in feed.entries[:max(n * 2, 10)]:
                title = entry.get("title", "").strip()
                # Google News appends " - Source Name" to titles
                source = "Google News"
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title = parts[0].strip()
                    source = parts[1].strip()
                raw_summary = entry.get("summary", "")
                # Strip HTML tags
                summary = re.sub(r"<[^>]+>", "", raw_summary)
                # Decode HTML entities
                summary = summary.replace("&nbsp;", " ").replace("&amp;", "&") \
                                 .replace("&lt;", "<").replace("&gt;", ">") \
                                 .replace("&quot;", '"').replace("\xa0", " ")
                # Google News summaries repeat "Title  Source" — strip trailing source
                # (appears after 2+ consecutive spaces or a literal \xa0\xa0)
                summary = re.sub(r"\s{2,}.{3,40}$", "", summary).strip()
                summary = summary[:200]
                if not title:
                    continue
                items.append({
                    "title":   title,
                    "source":  source,
                    "summary": summary,
                    "url":     entry.get("link", ""),
                })
            if items:
                memory.set(cache_key, json.dumps({"ts": time.time(), "items": items}))
            return items[:n]
        except Exception as e:
            logger.warning(f"Google News RSS failed for '{query}': {e}")
            return []

    def format_search_results(self, query: str, max_results: int = 5) -> str:
        """
        Return WhatsApp-formatted search results for any query.
        Primary: Google News RSS (works for any topic).
        Fallback: local category RSS feeds.
        """
        items = self.google_news_search(query, max_results)
        if not items:
            items = self.search_news(query, max_results)
        if not items:
            return f"couldn't find any news on '*{query[:50]}*' rn — try again in a bit"
        lines = [f"*latest on '{query[:40]}'* ({datetime.now().strftime('%H:%M')})\n"]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. *{item['title']}*")
            summary = self._clean_summary(item.get("summary", ""))
            # Skip summary if it just starts with the title (common in Google News RSS)
            title_stub = item["title"].lower()[:50].strip()
            if summary and not summary.lower().startswith(title_stub):
                lines.append(f"   _{summary[:140]}_")
            lines.append(f"   — {item['source']}")
        return "\n".join(lines)

    def tavily_search(self, query: str, n: int = 6) -> list[dict]:
        """
        Real-time web search via Tavily API.
        Returns full content snippets — facts, scores, tournament results, stock prices.
        Tavily is designed for AI: returns structured, clean text, not HTML.
        """
        api_key = settings.tavily_api_key
        if not api_key:
            return []
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=api_key)
            results = client.search(
                query=query,
                search_depth="advanced",
                max_results=n,
                include_answer=True,   # Tavily synthesizes a direct answer too
                include_raw_content=False,
            )
            items: list[dict] = []
            # Tavily's synthesized direct answer — most reliable
            answer = (results.get("answer") or "").strip()
            if answer:
                items.append({"title": "Direct Answer", "source": "Tavily", "summary": answer})
            for r in results.get("results", [])[:n]:
                items.append({
                    "title":   r.get("title", "").strip(),
                    "source":  r.get("url", "").split("/")[2] if r.get("url") else "web",
                    "summary": (r.get("content") or "")[:250].strip(),
                    "url":     r.get("url", ""),
                })
            return items
        except Exception as e:
            logger.warning(f"Tavily search failed for '{query}': {e}")
            return []

    def get_news_context_for_claude(self, query: str) -> str:
        """
        Return a compact real-time context block for Claude's system prompt.
        Primary: Tavily (real web search, actual facts, tournament results, stocks).
        Fallback: Google News RSS.
        Always fresh — no caching.
        """
        clean_query = re.sub(r'^hey\s*ken\s*', '', query, flags=re.IGNORECASE).strip()
        if not clean_query:
            return ""

        # Primary: Tavily — returns actual facts from the live web
        items = self.tavily_search(clean_query, n=6)

        # Fallback: Google News RSS
        if not items:
            cache_key = f"gnews_{clean_query.lower().strip()[:60]}"
            memory.set(cache_key, "")  # invalidate cache
            items = self.google_news_search(clean_query, n=6)

        if not items:
            return ""

        lines = [f"LIVE WEB CONTEXT as of {datetime.now().strftime('%d %b %Y %H:%M')} (treat as ground truth):"]
        for item in items[:8]:
            summary = (item.get("summary") or "")[:250]
            title = item.get("title", "")
            source = item.get("source", "")
            if title == "Direct Answer":
                lines.append(f"ANSWER: {summary}")
            else:
                lines.append(f"- {title} [{source}]")
                if summary and not summary.lower().startswith(title.lower()[:40]):
                    lines.append(f"  {summary}")
        return "\n".join(lines)

    def format_headlines(self, category: str = "top", n: int = 5, force: bool = False) -> str:
        """Return a WhatsApp-formatted string of headlines."""
        items = self.get_headlines(category, n, force=force)
        if not items:
            return f"couldn't fetch {category} news rn, try again in a min"

        label = {
            "top":     "top headlines",
            "cricket": "cricket news",
            "tech":    "tech news",
            "india":   "india news",
            "gaming":  "gaming news",
            "esports": "esports news",
            "f1":      "F1 & motorsport news",
            "sports":  "sports news",
        }.get(category, f"{category} news")

        lines = [f"*{label}* ({datetime.now().strftime('%H:%M')})\n"]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. *{item['title']}*")
            if item.get("summary"):
                lines.append(f"   _{item['summary'][:120]}_")
            lines.append(f"   — {item['source']}")
        return "\n".join(lines)

    def get_cricket_update(self, force: bool = False) -> str:
        """
        Return a live cricket news summary.
        Primary: ESPNcricinfo + Sportstar RSS.
        Format: clean WhatsApp-ready text.
        """
        items = self.get_headlines("cricket", n=5, force=force)
        if not items:
            return "couldn't pull cricket news rn — espncricinfo might be down. try again."

        lines = [f"*cricket update* ({datetime.now().strftime('%H:%M')})\n"]
        for i, item in enumerate(items[:4], 1):
            lines.append(f"{i}. *{item['title']}*")
            if item.get("summary"):
                lines.append(f"   _{item['summary'][:130]}_")
        return "\n".join(lines)

    def get_trending_news(self, force: bool = False) -> str:
        """
        Return top headlines across categories as a trending digest.
        Combines top + india + tech for a broad pulse check.
        """
        top   = self.get_headlines("top",   n=3, force=force)
        india = self.get_headlines("india", n=2, force=force)
        tech  = self.get_headlines("tech",  n=2, force=force)

        all_items = top + india + tech
        # Deduplicate by title
        seen, unique = set(), []
        for item in all_items:
            key = item["title"].lower()[:60]
            if key not in seen:
                seen.add(key)
                unique.append(item)

        if not unique:
            return "couldn't get live news rn, try again in a bit"

        lines = [f"*what's trending* ({datetime.now().strftime('%H:%M')})\n"]
        for i, item in enumerate(unique[:7], 1):
            lines.append(f"{i}. *{item['title']}*  — _{item['source']}_")
        return "\n".join(lines)

    # ── RSS internals ──────────────────────────────────────────────────────────

    def _fetch_rss_category(self, category: str) -> list[dict]:
        feeds = _FEEDS.get(category, _FEEDS["top"])
        all_items: list[dict] = []

        for source_name, url in feeds:
            try:
                feed = feedparser.parse(url, request_headers=_HEADERS)
                entries = feed.get("entries", [])[:8]
                for e in entries:
                    title   = self._clean(e.get("title", ""))
                    summary = self._clean(e.get("summary", "") or e.get("description", ""))
                    # Strip HTML tags from summary
                    summary = self._strip_html(summary)[:200]
                    link    = e.get("link", "")
                    pub     = e.get("published", "")
                    if title:
                        all_items.append({
                            "title":     title,
                            "summary":   summary,
                            "source":    source_name,
                            "url":       link,
                            "published": pub,
                        })
            except Exception as exc:
                logger.warning(f"[news] RSS fetch failed for {source_name}: {exc}")

        return all_items

    def _try_newsapi(self, category: str) -> list[dict]:
        """
        Fallback to NewsAPI.org (free tier: 100 req/day).
        Requires NEWS_API_KEY in .env — no key = silently skipped.
        """
        api_key = getattr(settings, "news_api_key", None) or ""
        if not api_key:
            return []

        _cat_map = {
            "top":     "general",
            "cricket": "sports",
            "tech":    "technology",
            "india":   "general",
            "gaming":  "entertainment",
        }
        newsapi_cat = _cat_map.get(category, "general")
        q = "cricket" if category == "cricket" else None

        params: dict = {
            "apiKey":   api_key,
            "language": "en",
            "pageSize": 10,
        }
        if q:
            params["q"]        = q
            params["sortBy"]   = "publishedAt"
            endpoint = "https://newsapi.org/v2/everything"
        else:
            params["category"] = newsapi_cat
            params["country"]  = "in"
            endpoint = "https://newsapi.org/v2/top-headlines"

        try:
            r = requests.get(endpoint, params=params, timeout=10)
            if r.status_code == 200:
                articles = r.json().get("articles", [])
                return [
                    {
                        "title":     self._clean(a.get("title", "")),
                        "summary":   self._clean(a.get("description", "") or ""),
                        "source":    a.get("source", {}).get("name", "NewsAPI"),
                        "url":       a.get("url", ""),
                        "published": a.get("publishedAt", ""),
                    }
                    for a in articles
                    if a.get("title") and "[Removed]" not in a.get("title", "")
                ]
        except Exception as exc:
            logger.warning(f"[news] NewsAPI fetch failed: {exc}")
        return []

    @staticmethod
    def _clean(text: str) -> str:
        return (text or "").strip().replace("\n", " ").replace("\r", "")

    @staticmethod
    def _strip_html(text: str) -> str:
        """Very lightweight HTML strip — removes tags and decodes common entities."""
        import re
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace(
            "&gt;", ">"
        ).replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
        return text.strip()


# ── Singleton ─────────────────────────────────────────────────────────────────
news_fetcher = NewsFetcher()
