"""
briefing.py — ARJUN Morning Briefing (Fixed)
- Uses ddgs with fallback to duckduckgo_search
- Rate limit handling with retry
- Interruptible via stop_speaking()
- Parallel fetch under 10 seconds
"""

import logging
import threading
import time
import psutil
from datetime import datetime

from config import (
    BRIEFING_USER_NAME, BRIEFING_LOCATION,
    BRIEFING_NEWS_TOPICS, BRIEFING_NEWS_COUNT,
    MEMORY_FILE
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  SEARCH HELPER
# ─────────────────────────────────────────────

def _search(query: str, news: bool = False, max_results: int = 3) -> list:
    """Try ddgs first, fall back to duckduckgo_search, then Bing."""
    for attempt in range(2):
        try:
            from ddgs import DDGS
            with DDGS() as ddgs:
                if news:
                    return list(ddgs.news(query, max_results=max_results, timelimit="d"))
                return list(ddgs.text(query, max_results=max_results))
        except ImportError:
            pass
        except Exception as e:
            if "ratelimit" in str(e).lower() and attempt == 0:
                time.sleep(2)
                continue
            break

    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            if news:
                return list(ddgs.news(query, max_results=max_results, timelimit="d"))
            return list(ddgs.text(query, max_results=max_results))
    except Exception:
        pass

    # Bing fallback
    try:
        import requests
        from bs4 import BeautifulSoup
        headers = {"User-Agent": "Mozilla/5.0"}
        url     = f"https://www.bing.com/search?q={query.replace(' ', '+')}"
        resp    = requests.get(url, headers=headers, timeout=8)
        soup    = BeautifulSoup(resp.text, "lxml")
        results = []
        for li in soup.select(".b_algo")[:max_results]:
            title = li.select_one("h2")
            body  = li.select_one(".b_caption p")
            if title and body:
                results.append({"title": title.get_text(), "body": body.get_text()})
        return results
    except Exception as e:
        logger.warning(f"All search fallbacks failed: {e}")
        return []


# ─────────────────────────────────────────────
#  PARALLEL FETCHERS
# ─────────────────────────────────────────────

def _fetch_weather(location: str, results: dict):
    try:
        query = f"weather {location} today temperature"
        data  = _search(query, max_results=3)
        for r in data:
            body = r.get("body", r.get("snippet", ""))
            if any(w in body.lower() for w in
                   ["°", "celsius", "fahrenheit", "degrees", "humidity",
                    "cloudy", "sunny", "rain", "hot", "cool", "warm"]):
                sentences = body.split(".")[:2]
                results["weather"] = ". ".join(sentences).strip()
                return
        # Use first result regardless
        if data:
            results["weather"] = data[0].get("body", data[0].get("snippet", ""))[:200]
        else:
            results["weather"] = f"Could not get weather for {location} right now."
    except Exception as e:
        logger.warning(f"Weather fetch: {e}")
        results["weather"] = "Weather data unavailable right now."


def _fetch_news(topics: list, count: int, results: dict):
    try:
        stories   = []
        seen      = set()

        for topic in topics:
            if len(stories) >= count:
                break
            time.sleep(0.5)   # avoid rate limit
            data = _search(topic, news=True, max_results=4)
            for r in data:
                title = r.get("title", "").strip()
                body  = r.get("body", r.get("excerpt", "")).strip()
                if title and title not in seen and body:
                    seen.add(title)
                    body_short = body.split(".")[0].strip()
                    stories.append(f"{title}. {body_short}.")
                if len(stories) >= count:
                    break

        results["news"] = stories[:count] if stories else [
            "No major news stories available right now."
        ]
    except Exception as e:
        logger.warning(f"News fetch: {e}")
        results["news"] = ["Could not fetch news right now."]


def _fetch_fact(results: dict):
    try:
        data = _search("interesting fact today", max_results=2)
        for r in data:
            body = r.get("body", r.get("snippet", "")).strip()
            if body and len(body) > 30:
                results["fact"] = body.split(".")[0].strip() + "."
                return
        results["fact"] = "The human brain can hold roughly 2.5 petabytes of information."
    except Exception:
        results["fact"] = "Every day brings a new chance to learn something remarkable."


def _fetch_system(results: dict):
    try:
        mem = psutil.virtual_memory()
        b   = psutil.sensors_battery()
        s   = f"RAM is at {mem.percent} percent."
        if b:
            status = "charging" if b.power_plugged else "on battery"
            s += f" Battery is at {round(b.percent)} percent and {status}."
        results["system"] = s
    except Exception:
        results["system"] = ""


def _get_name() -> str:
    import json, os
    try:
        if not os.path.exists(MEMORY_FILE):
            return BRIEFING_USER_NAME
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        for entry in data.get("facts", []):
            fact = entry.get("fact", "").lower()
            for phrase in ["my name is", "i am called", "call me", "name's"]:
                if phrase in fact:
                    name = fact.split(phrase)[-1].strip().split()[0]
                    name = name.strip(".,!?").capitalize()
                    if len(name) > 1:
                        return name
        return BRIEFING_USER_NAME
    except Exception:
        return BRIEFING_USER_NAME


# ─────────────────────────────────────────────
#  ASSEMBLE
# ─────────────────────────────────────────────

def assemble_briefing() -> str:
    now      = datetime.now()
    day_name = now.strftime("%A")
    date_str = now.strftime("%B %d, %Y")
    hour     = now.hour

    if hour < 12:
        greeting_time = "Good morning"
    elif hour < 17:
        greeting_time = "Good afternoon"
    else:
        greeting_time = "Good evening"

    name     = _get_name()
    greeting = f"{greeting_time} {name}. Today is {day_name}, {date_str}."

    results = {}

    # Parallel fetch
    threads = [
        threading.Thread(target=_fetch_weather, args=(BRIEFING_LOCATION, results), daemon=True),
        threading.Thread(target=_fetch_news,    args=(BRIEFING_NEWS_TOPICS, BRIEFING_NEWS_COUNT, results), daemon=True),
        threading.Thread(target=_fetch_fact,    args=(results,), daemon=True),
        threading.Thread(target=_fetch_system,  args=(results,), daemon=True),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=15)

    parts = [greeting]

    weather = results.get("weather", "")
    if weather:
        parts.append(f"Here is the weather. {weather}")

    news = results.get("news", [])
    if news and "unavailable" not in news[0]:
        parts.append(f"Here are your top {len(news)} news stories.")
        for i, s in enumerate(news, 1):
            parts.append(f"Story {i}. {s}")

    fact = results.get("fact", "")
    if fact:
        parts.append(f"And here is something interesting. {fact}")

    system = results.get("system", "")
    if system:
        parts.append(f"Quick system check. {system}")

    parts.append("That is your briefing. I am ready whenever you are.")

    text = " ".join(parts)
    logger.info(f"Briefing assembled: {len(text)} chars.")
    return text


# ─────────────────────────────────────────────
#  DELIVER
# ─────────────────────────────────────────────

def deliver_briefing(speak_fn, ui_event_queue=None):
    def _run():
        try:
            if ui_event_queue:
                ui_event_queue.put({"type": "status", "data": "Preparing briefing..."})
                ui_event_queue.put({"type": "state",  "data": "thinking"})

            text = assemble_briefing()

            if ui_event_queue:
                ui_event_queue.put({"type": "state", "data": "speaking"})
                ui_event_queue.put({"type": "arjun", "data": text})

            speak_fn(text)   # interruptible via stop_speaking()

        except Exception as e:
            logger.error(f"Briefing delivery error: {e}")
        finally:
            if ui_event_queue:
                ui_event_queue.put({"type": "state",  "data": "listening"})
                ui_event_queue.put({"type": "status", "data": "Listening for Hey Jarvis"})

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
