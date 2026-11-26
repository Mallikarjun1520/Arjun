"""
browser_agent.py — ARJUN Playwright Web Browser Agent (Phase 4)
Gives ARJUN the ability to actually browse the web like a human.
Opens a real Chromium browser, navigates pages, clicks, fills forms,
extracts content from JavaScript-heavy sites, and returns clean text.

Runs headless by default (no visible browser window).
Set headless=False in config to watch Arjun browse in real time.
"""

import os
import re
import logging
import asyncio
import threading
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright not installed. Run: playwright install chromium")

HEADLESS      = True      # set False to watch Arjun browse
PAGE_TIMEOUT  = 20000     # ms
MAX_CONTENT   = 4000      # chars returned to Qwen
USER_AGENT    = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# ── Browser instance (kept alive between calls) ───────────
_browser: Optional["Browser"] = None
_browser_lock = None
_playwright_manager = None
_event_loop:   Optional[asyncio.AbstractEventLoop] = None
_event_loop_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    global _event_loop
    with _event_loop_lock:
        if _event_loop is None or _event_loop.is_closed():
            _event_loop = asyncio.new_event_loop()
            t = threading.Thread(
                target=_event_loop.run_forever,
                name="arjun-browser-loop",
                daemon=True,
            )
            t.start()
        return _event_loop


def _run_async(coro):
    """Run an async coroutine from sync code using the shared event loop."""
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=60)


# ─────────────────────────────────────────────
#  BROWSER LIFECYCLE
# ─────────────────────────────────────────────

async def _get_browser() -> "Browser":
    global _browser, _browser_lock, _playwright_manager
    if _browser_lock is None:
        _browser_lock = asyncio.Lock()
    async with _browser_lock:
        if _browser is None or not _browser.is_connected():
            if _playwright_manager is None:
                _playwright_manager = await async_playwright().__aenter__()
            _browser = await _playwright_manager.chromium.launch(
                headless=HEADLESS,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            logger.info("Playwright browser launched.")
        return _browser


async def _new_page() -> "Page":
    browser = await _get_browser()
    page    = await browser.new_page()
    await page.set_extra_http_headers({"User-Agent": USER_AGENT})
    return page


async def _clean_page_text(page: "Page") -> str:
    """Extract readable text from a page, removing nav/footer noise."""
    text = await page.evaluate("""() => {
        const remove = ['script','style','nav','footer','header',
                        'aside','noscript','iframe','advertisement'];
        remove.forEach(tag => {
            document.querySelectorAll(tag).forEach(el => el.remove());
        });
        return document.body ? document.body.innerText : '';
    }""")
    # Collapse whitespace
    text = re.sub(r'\n{3,}', '\n\n', text)
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()[:MAX_CONTENT]


# ─────────────────────────────────────────────
#  PUBLIC BROWSER TOOLS
# ─────────────────────────────────────────────

async def _browse_url_async(url: str) -> str:
    """Navigate to a URL and return the page text."""
    if not url.startswith("http"):
        url = "https://" + url
    page = await _new_page()
    try:
        await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        await page.wait_for_timeout(1500)   # let JS render
        title = await page.title()
        text  = await _clean_page_text(page)
        return f"Page title: {title}\n\n{text}"
    except Exception as e:
        return f"Could not load {url}: {str(e)}"
    finally:
        await page.close()


async def _web_search_browse_async(query: str) -> str:
    """
    Search DuckDuckGo and browse the top result's full page.
    Returns far richer content than a snippet search.
    """
    page = await _new_page()
    try:
        search_url = f"https://duckduckgo.com/?q={query.replace(' ', '+')}&ia=web"
        await page.goto(search_url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)

        # Get first result link
        first_link = await page.query_selector("a[data-testid='result-title-a']")
        if not first_link:
            first_link = await page.query_selector(".result__a")

        if first_link:
            href = await first_link.get_attribute("href")
            if href and href.startswith("http"):
                await page.goto(href, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
                await page.wait_for_timeout(1500)
                title = await page.title()
                text  = await _clean_page_text(page)
                return f"Source: {href}\nTitle: {title}\n\n{text}"

        # Fallback: return search results page text
        text = await _clean_page_text(page)
        return f"Search results for '{query}':\n\n{text}"

    except Exception as e:
        return f"Browser search failed: {str(e)}"
    finally:
        await page.close()


async def _fill_form_async(url: str, fields: dict, submit: bool = True) -> str:
    """
    Navigate to a URL and fill form fields.
    fields = {"selector_or_label": "value", ...}
    """
    page = await _new_page()
    try:
        await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)

        filled = []
        for selector, value in fields.items():
            try:
                # Try as CSS selector first, then as placeholder text
                element = await page.query_selector(selector)
                if not element:
                    element = await page.query_selector(
                        f"input[placeholder*='{selector}' i]"
                    )
                if not element:
                    element = await page.query_selector(
                        f"input[name*='{selector}' i]"
                    )
                if element:
                    await element.fill(str(value))
                    filled.append(selector)
            except Exception as e:
                logger.debug(f"Could not fill {selector}: {e}")

        if submit and filled:
            # Try submitting
            submit_btn = await page.query_selector(
                "button[type='submit'], input[type='submit'], button:has-text('Submit')"
            )
            if submit_btn:
                await submit_btn.click()
                await page.wait_for_timeout(2000)

        result_title = await page.title()
        result_text  = await _clean_page_text(page)
        return (f"Filled {len(filled)} field(s). "
                f"Result page: {result_title}\n\n{result_text[:500]}")

    except Exception as e:
        return f"Form fill failed: {str(e)}"
    finally:
        await page.close()


async def _click_and_read_async(url: str, element_text: str) -> str:
    """Navigate to URL, click an element containing text, return resulting page."""
    page = await _new_page()
    try:
        await page.goto(url, timeout=PAGE_TIMEOUT, wait_until="domcontentloaded")
        await page.wait_for_timeout(1000)

        await page.click(f"text={element_text}", timeout=5000)
        await page.wait_for_timeout(2000)

        title = await page.title()
        text  = await _clean_page_text(page)
        return f"Clicked '{element_text}'. New page: {title}\n\n{text}"

    except Exception as e:
        return f"Could not click '{element_text}': {str(e)}"
    finally:
        await page.close()


# ─────────────────────────────────────────────
#  SYNC WRAPPERS (called from tools.py)
# ─────────────────────────────────────────────

def browse_url(url: str) -> str:
    if not PLAYWRIGHT_AVAILABLE:
        return "Playwright is not installed. Run: pip install playwright && playwright install chromium"
    try:
        return _run_async(_browse_url_async(url))
    except Exception as e:
        return f"Browser error: {str(e)}"


def browser_search(query: str) -> str:
    if not PLAYWRIGHT_AVAILABLE:
        return "Playwright is not installed."
    try:
        return _run_async(_web_search_browse_async(query))
    except Exception as e:
        return f"Browser search error: {str(e)}"


def fill_form(url: str, fields: dict, submit: bool = True) -> str:
    if not PLAYWRIGHT_AVAILABLE:
        return "Playwright is not installed."
    try:
        return _run_async(_fill_form_async(url, fields, submit))
    except Exception as e:
        return f"Form fill error: {str(e)}"


def click_and_read(url: str, element_text: str) -> str:
    if not PLAYWRIGHT_AVAILABLE:
        return "Playwright is not installed."
    try:
        return _run_async(_click_and_read_async(url, element_text))
    except Exception as e:
        return f"Click error: {str(e)}"


# ─────────────────────────────────────────────
#  TOOL SCHEMAS
# ─────────────────────────────────────────────

BROWSER_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "browse_url",
            "description": (
                "Open a specific URL in a real browser and return the full page content. "
                "Use when you have a direct URL to visit. Far more powerful than web_search "
                "for JavaScript-heavy sites, news articles, and documentation pages."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The full URL to visit."}
                },
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_search",
            "description": (
                "Search the web and browse the top result's full page content using a real browser. "
                "Use this for deep research when web_search snippets are not detailed enough, "
                "or for sites that require JavaScript to render content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "The search query."}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "fill_form",
            "description": (
                "Navigate to a webpage and fill in form fields automatically. "
                "Use for submitting search forms, contact forms, or any web form."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The page URL containing the form."},
                    "fields": {
                        "type": "object",
                        "description": "Field selectors or names mapped to values to fill in."
                    },
                    "submit": {
                        "type": "boolean",
                        "description": "Whether to submit the form after filling. Default true."
                    }
                },
                "required": ["url", "fields"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "click_and_read",
            "description": (
                "Navigate to a URL, click on an element by its visible text, "
                "and return the resulting page content."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "The page URL."},
                    "element_text": {
                        "type": "string",
                        "description": "Visible text of the element to click."
                    }
                },
                "required": ["url", "element_text"]
            }
        }
    }
]
