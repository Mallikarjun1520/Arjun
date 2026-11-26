"""
tools.py — ARJUN Agent Tools (Fixed)
- Uses ddgs instead of duckduckgo_search
- All tool functions verified working
- Clean dispatcher with no chained overwrites
"""

import os
import json
import subprocess
import logging
from datetime import datetime

import psutil
import sympy
from bs4 import BeautifulSoup
import requests as req

from config import (
    MEMORY_FILE, MAX_MEMORY_FACTS, PROJECTS_DIR,
    VSCODE_PATH, GMAIL_ADDRESS, GMAIL_APP_PASSWORD,
    GMAIL_IMAP_SERVER, GMAIL_SMTP_SERVER, GMAIL_SMTP_PORT
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
#  SEARCH HELPER  (ddgs with fallback)
# ─────────────────────────────────────────────

def _ddg_search(query: str, max_results: int = 5, news: bool = False) -> list:
    """
    Try ddgs first, fall back to duckduckgo_search if not installed.
    Returns list of result dicts.
    """
    search_clients = []
    try:
        from ddgs import DDGS as CurrentDDGS
        search_clients.append(CurrentDDGS)
    except ImportError:
        pass
    try:
        from duckduckgo_search import DDGS as LegacyDDGS
        if LegacyDDGS not in search_clients:
            search_clients.append(LegacyDDGS)
    except ImportError:
        pass

    for ddgs_client in search_clients:
        try:
            with ddgs_client() as ddgs:
                if news:
                    return list(ddgs.news(query, max_results=max_results, timelimit="d"))
                return list(ddgs.text(query, max_results=max_results))
        except Exception as e:
            logger.warning("%s search failed: %s", ddgs_client.__module__, e)

    # Last resort: use requests to Bing
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        url     = f"https://www.bing.com/search?q={query.replace(' ', '+')}"
        resp    = req.get(url, headers=headers, timeout=8)
        soup    = BeautifulSoup(resp.text, "lxml")
        results = []
        for li in soup.select(".b_algo")[:max_results]:
            title = li.select_one("h2")
            body  = li.select_one(".b_caption p")
            if title and body:
                results.append({
                    "title": title.get_text(),
                    "body":  body.get_text()
                })
        return results
    except Exception as e:
        logger.error(f"All search methods failed: {e}")
        return []


# ─────────────────────────────────────────────
#  1. WEB SEARCH
# ─────────────────────────────────────────────

def web_search(query: str) -> str:
    try:
        results = _ddg_search(query, max_results=5)
        if not results:
            return "The search returned no results."
        parts = []
        for r in results:
            title = r.get("title", "")
            body  = r.get("body",  r.get("snippet", ""))
            if title and body:
                parts.append(f"{title}: {body}")
        return " | ".join(parts)[:2500] if parts else "No useful results found."
    except Exception as e:
        logger.error(f"web_search error: {e}")
        return f"Search failed: {str(e)}"


# ─────────────────────────────────────────────
#  2. DEEP RESEARCH
# ─────────────────────────────────────────────

def deep_research(topic: str) -> str:
    try:
        results = _ddg_search(topic, max_results=5)
        urls = []
        for r in results:
            url = r.get("href", r.get("url", ""))
            if url and url.startswith("http"):
                urls.append(url)
            if len(urls) >= 3:
                break

        if not urls:
            return f"Could not find pages to research about {topic}."

        scraped   = []
        headers   = {"User-Agent": "Mozilla/5.0"}
        for url in urls:
            try:
                resp = req.get(url, headers=headers, timeout=8)
                soup = BeautifulSoup(resp.text, "lxml")
                for tag in soup(["script","style","nav","footer","header","aside"]):
                    tag.decompose()
                text = " ".join(soup.get_text(separator=" ", strip=True).split())
                scraped.append(text[:1500])
            except Exception as e:
                logger.warning(f"Scrape failed {url}: {e}")

        if not scraped:
            return "Could not scrape content from search results."
        return "\n\n---\n\n".join(scraped)[:4000]

    except Exception as e:
        logger.error(f"deep_research error: {e}")
        return f"Research failed: {str(e)}"


# ─────────────────────────────────────────────
#  3. MATH
# ─────────────────────────────────────────────

def calculate_math(expression: str) -> str:
    try:
        result = sympy.sympify(expression)
        simplified = sympy.simplify(result)
        try:
            numeric = float(simplified.evalf())
            if simplified == sympy.Integer(int(numeric)):
                return f"The answer is {int(numeric)}."
            return f"The answer is {simplified}, approximately {round(numeric, 6)}."
        except (TypeError, ValueError):
            return f"The result is {simplified}."
    except Exception:
        try:
            from sympy.parsing.sympy_parser import (
                parse_expr, standard_transformations,
                implicit_multiplication_application
            )
            expr = parse_expr(
                expression,
                transformations=standard_transformations + (implicit_multiplication_application,)
            )
            return f"The result is {sympy.simplify(expr)}."
        except Exception as e:
            return f"Could not evaluate: {str(e)}"


# ─────────────────────────────────────────────
#  4. MEMORY
# ─────────────────────────────────────────────

def _load_memory() -> dict:
    if not os.path.exists(MEMORY_FILE):
        return {"facts": [], "created": datetime.now().isoformat()}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"facts": [], "created": datetime.now().isoformat()}

def _write_memory(data: dict):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def save_memory(fact: str) -> str:
    try:
        data = _load_memory()
        data["facts"].append({
            "fact":      fact,
            "timestamp": datetime.now().isoformat()
        })
        if len(data["facts"]) > MAX_MEMORY_FACTS:
            data["facts"] = data["facts"][-MAX_MEMORY_FACTS:]
        _write_memory(data)
        return "Got it, I have remembered that."
    except Exception as e:
        return f"Failed to save memory: {str(e)}"

def recall_memory() -> str:
    try:
        data  = _load_memory()
        facts = data.get("facts", [])
        if not facts:
            return "No memories stored yet."
        return "Here is what I remember: " + ". ".join(f["fact"] for f in facts)
    except Exception as e:
        return f"Failed to read memory: {str(e)}"


# ─────────────────────────────────────────────
#  5. SYSTEM CONTROL
# ─────────────────────────────────────────────

APP_MAP = {
    "notepad":      "notepad.exe",
    "calculator":   "calc.exe",
    "explorer":     "explorer.exe",
    "edge":         "msedge.exe",
    "firefox":      "firefox.exe",
    "settings":     "ms-settings:",
    "task manager": "taskmgr.exe",
    "paint":        "mspaint.exe",
    "word":         "winword.exe",
    "excel":        "excel.exe",
    "powerpoint":   "powerpnt.exe",
    "terminal":     "wt.exe",
    "cmd":          "cmd.exe",
    "discord":      rf"C:\Users\{os.environ.get('USERNAME','user')}\AppData\Local\Discord\Update.exe",
    "whatsapp":     rf"C:\Users\{os.environ.get('USERNAME','user')}\AppData\Local\WhatsApp\WhatsApp.exe",
}

def system_control(action: str, target: str = "") -> str:
    action = action.lower().strip()
    target_l = target.lower().strip()

    # ── Open app ──
    if action == "open":
        app_key = target_l
        if any(name in app_key for name in ("chrome", "spotify", "youtube", "you tube")):
            from app_launcher import launch_app
            return launch_app(target)

        if app_key in ("vscode", "vs code", "visual studio code"):
            try:
                vscode = rf"C:\Users\{os.environ.get('USERNAME','user')}\AppData\Local\Programs\Microsoft VS Code\Code.exe"
                subprocess.Popen([vscode], creationflags=subprocess.CREATE_NO_WINDOW)
            except FileNotFoundError:
                subprocess.Popen(["code"], shell=True)
            return "Opening VS Code for you."

        if app_key in APP_MAP:
            cmd = APP_MAP[app_key]
            try:
                if cmd.startswith("ms-"):
                    os.startfile(cmd)
                else:
                    subprocess.Popen(cmd, shell=True,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
                return f"Opening {target_l} for you."
            except Exception as e:
                return f"Could not open {target_l}: {str(e)}"

        # Try directly
        try:
            subprocess.Popen(target_l, shell=True,
                             creationflags=subprocess.CREATE_NO_WINDOW)
            return f"Trying to open {target_l}."
        except Exception as e:
            return f"Could not open {target_l}: {str(e)}"

    # ── Battery ──
    elif action in ("battery", "check battery"):
        b = psutil.sensors_battery()
        if not b:
            return "Could not read battery info."
        pct    = round(b.percent)
        status = "charging" if b.power_plugged else "on battery"
        if b.secsleft > 0 and not b.power_plugged:
            h, m = divmod(b.secsleft // 60, 60)
            time_str = f"about {h} hours and {m} minutes remaining"
        else:
            time_str = "plugged in" if b.power_plugged else "time remaining unknown"
        return f"Battery is at {pct} percent, {status}, {time_str}."

    # ── CPU ──
    elif action in ("cpu", "check cpu", "cpu usage"):
        cpu   = psutil.cpu_percent(interval=1)
        cores = psutil.cpu_count(logical=False)
        freq  = psutil.cpu_freq()
        f_str = f" at {round(freq.current)} MHz" if freq else ""
        return f"CPU is at {cpu} percent across {cores} physical cores{f_str}."

    # ── RAM ──
    elif action in ("ram", "memory", "check ram"):
        m     = psutil.virtual_memory()
        used  = round(m.used  / 1024**3, 1)
        total = round(m.total / 1024**3, 1)
        return f"Using {used} GB out of {total} GB of RAM, that is {m.percent} percent."

    # ── Stats ──
    elif action in ("stats", "system stats", "status"):
        cpu = psutil.cpu_percent(interval=1)
        m   = psutil.virtual_memory()
        b   = psutil.sensors_battery()
        batt = f" Battery at {round(b.percent)} percent." if b else ""
        return (f"CPU at {cpu} percent. "
                f"RAM {round(m.used/1024**3,1)} of {round(m.total/1024**3,1)} GB.{batt}")

    # ── Volume ──
    elif action in ("volume up", "increase volume"):
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            devices = AudioUtilities.GetSpeakers()
            iface   = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol     = cast(iface, POINTER(IAudioEndpointVolume))
            new_vol = min(1.0, vol.GetMasterVolumeLevelScalar() + 0.1)
            vol.SetMasterVolumeLevelScalar(new_vol, None)
            return f"Volume increased to {round(new_vol*100)} percent."
        except Exception as e:
            return f"Could not adjust volume: {str(e)}"

    elif action in ("volume down", "decrease volume"):
        try:
            from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            devices = AudioUtilities.GetSpeakers()
            iface   = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            vol     = cast(iface, POINTER(IAudioEndpointVolume))
            new_vol = max(0.0, vol.GetMasterVolumeLevelScalar() - 0.1)
            vol.SetMasterVolumeLevelScalar(new_vol, None)
            return f"Volume decreased to {round(new_vol*100)} percent."
        except Exception as e:
            return f"Could not adjust volume: {str(e)}"

    # ── Write script ──
    elif action in ("write script", "create script", "write code", "create code"):
        try:
            os.makedirs(PROJECTS_DIR, exist_ok=True)
            ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"arjun_script_{ts}.py"
            filepath = os.path.join(PROJECTS_DIR, filename)
            content  = target if target else "# Script generated by ARJUN\n\nprint('Hello!')\n"
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            try:
                vscode = rf"C:\Users\{os.environ.get('USERNAME','user')}\AppData\Local\Programs\Microsoft VS Code\Code.exe"
                subprocess.Popen([vscode, filepath],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            except FileNotFoundError:
                subprocess.Popen(["code", filepath], shell=True)
            return f"Script written and opened in VS Code."
        except Exception as e:
            return f"Failed to create script: {str(e)}"

    return f"I do not know how to handle the action '{action}'."


# ─────────────────────────────────────────────
#  6. APP LAUNCHER (voice)
# ─────────────────────────────────────────────

def open_application(app_name: str) -> str:
    try:
        from app_launcher import launch_app
        return launch_app(app_name)
    except Exception as e:
        # Fallback to system_control
        return system_control("open", app_name)

def list_applications() -> str:
    from app_launcher import list_available_apps
    return list_available_apps()


# ─────────────────────────────────────────────
#  7. EMAIL
# ─────────────────────────────────────────────

def send_email(to: str, subject: str, body: str, attachment_path: str = "") -> str:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return "Gmail credentials not configured in .env file."
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text      import MIMEText
        from email.mime.base      import MIMEBase
        from email                import encoders

        msg = MIMEMultipart()
        msg["From"]    = GMAIL_ADDRESS
        msg["To"]      = to
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if attachment_path and os.path.exists(attachment_path):
            with open(attachment_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition",
                            f"attachment; filename={os.path.basename(attachment_path)}")
            msg.attach(part)

        with smtplib.SMTP(GMAIL_SMTP_SERVER, GMAIL_SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, to, msg.as_string())
        return f"Email sent to {to}."
    except Exception as e:
        return f"Failed to send email: {str(e)}"

def check_email(max_messages: int = 5) -> str:
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        return "Gmail credentials not configured."
    try:
        import imaplib, email as email_lib
        from email.header import decode_header

        mail = imaplib.IMAP4_SSL(GMAIL_IMAP_SERVER)
        mail.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        mail.select("inbox")

        status, messages = mail.search(None, "UNSEEN")
        if status != "OK" or not messages[0]:
            mail.logout()
            return "No unread emails right now."

        email_ids  = messages[0].split()[-max_messages:][::-1]
        summaries  = []

        for eid in email_ids:
            status, msg_data = mail.fetch(eid, "(RFC822)")
            if status != "OK":
                continue
            msg = email_lib.message_from_bytes(msg_data[0][1])
            subject_parts = decode_header(msg.get("Subject", "No Subject"))
            subject = "".join(
                p.decode(enc or "utf-8") if isinstance(p, bytes) else p
                for p, enc in subject_parts
            )
            sender = msg.get("From", "Unknown")
            body   = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        payload = part.get_payload(decode=True)
                        if payload:
                            body = payload.decode("utf-8", errors="replace")[:200]
                            break
            else:
                payload = msg.get_payload(decode=True)
                if payload:
                    body = payload.decode("utf-8", errors="replace")[:200]
            summaries.append(f"From {sender}. Subject: {subject}. {body.strip()}")

        mail.logout()
        return " Next: ".join(summaries) if summaries else "Could not read emails."
    except Exception as e:
        return f"Failed to check email: {str(e)}"


# ─────────────────────────────────────────────
#  8. KNOWLEDGE BASE
# ─────────────────────────────────────────────

def search_knowledge_base(query: str) -> str:
    try:
        from knowledge_base import get_knowledge_base
        kb = get_knowledge_base()
        result = kb.search(query, n=5)
        return result if result else "Nothing relevant found in the knowledge base."
    except Exception as e:
        return f"Knowledge base search failed: {str(e)}"

def add_to_knowledge_base(filepath: str) -> str:
    try:
        from knowledge_base import get_knowledge_base
        return get_knowledge_base().add_document(filepath)
    except Exception as e:
        return f"Failed to add document: {str(e)}"

def list_knowledge_base() -> str:
    try:
        from knowledge_base import get_knowledge_base
        return get_knowledge_base().list_documents()
    except Exception as e:
        return f"Failed to list knowledge base: {str(e)}"


# ─────────────────────────────────────────────
#  9. BROWSER AGENT
# ─────────────────────────────────────────────

def browse_url(url: str) -> str:
    try:
        from browser_agent import browse_url as _b
        return _b(url)
    except Exception as e:
        return f"Browser unavailable: {str(e)}"

def browser_search(query: str) -> str:
    try:
        from browser_agent import browser_search as _bs
        return _bs(query)
    except Exception as e:
        # Fallback to basic search
        return web_search(query)

def fill_form(url: str, fields: dict, submit: bool = True) -> str:
    try:
        from browser_agent import fill_form as _fill_form
        return _fill_form(url, fields, submit)
    except Exception as e:
        return f"Form fill failed: {str(e)}"

def click_and_read(url: str, element_text: str) -> str:
    try:
        from browser_agent import click_and_read as _click_and_read
        return _click_and_read(url, element_text)
    except Exception as e:
        return f"Browser click failed: {str(e)}"

def send_whatsapp(contact_name: str, message: str) -> str:
    from whatsapp_bridge import send_whatsapp_message
    return send_whatsapp_message(contact_name, message)

def read_whatsapp(contact_name: str = "", count: int = 5) -> str:
    from whatsapp_bridge import read_whatsapp_messages
    return read_whatsapp_messages(contact_name, count)

def reply_whatsapp(message: str) -> str:
    from whatsapp_bridge import reply_last_whatsapp
    return reply_last_whatsapp(message)

def whatsapp_status() -> str:
    from whatsapp_bridge import get_whatsapp_status
    return get_whatsapp_status()


# ─────────────────────────────────────────────
#  TOOL DISPATCHER
# ─────────────────────────────────────────────

def dispatch_tool(tool_name: str, tool_args: dict) -> str:
    logger.info(f"Tool called: {tool_name} | args: {tool_args}")

    DISPATCH = {
        "web_search":            lambda a: web_search(a.get("query", "")),
        "deep_research":         lambda a: deep_research(a.get("topic", "")),
        "calculate_math":        lambda a: calculate_math(a.get("expression", "")),
        "save_memory":           lambda a: save_memory(a.get("fact", "")),
        "recall_memory":         lambda a: recall_memory(),
        "system_control":        lambda a: system_control(a.get("action",""), a.get("target","")),
        "open_application":      lambda a: open_application(a.get("app_name","")),
        "list_applications":     lambda a: list_applications(),
        "send_email":            lambda a: send_email(a.get("to",""), a.get("subject",""), a.get("body",""), a.get("attachment_path","")),
        "check_email":           lambda a: check_email(a.get("max_messages", 5)),
        "search_knowledge_base": lambda a: search_knowledge_base(a.get("query","")),
        "add_to_knowledge_base": lambda a: add_to_knowledge_base(a.get("filepath","")),
        "list_knowledge_base":   lambda a: list_knowledge_base(),
        "browse_url":            lambda a: browse_url(a.get("url","")),
        "browser_search":        lambda a: browser_search(a.get("query","")),
        "fill_form":             lambda a: fill_form(a.get("url",""), a.get("fields",{}), a.get("submit",True)),
        "click_and_read":        lambda a: click_and_read(a.get("url",""), a.get("element_text","")),
        "send_whatsapp":         lambda a: send_whatsapp(a.get("contact_name",""), a.get("message","")),
        "read_whatsapp":         lambda a: read_whatsapp(a.get("contact_name",""), a.get("count",5)),
        "reply_whatsapp":        lambda a: reply_whatsapp(a.get("message","")),
        "whatsapp_status":       lambda a: whatsapp_status(),
    }

    fn = DISPATCH.get(tool_name)
    if fn:
        return fn(tool_args)
    return f"Unknown tool: {tool_name}"


# ─────────────────────────────────────────────
#  TOOL SCHEMAS
# ─────────────────────────────────────────────

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the internet for current news, facts, and recent events. Use for anything that might have changed recently.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "deep_research",
            "description": "Research a topic deeply by scraping full text from the top 3 web pages. Use for thorough detailed answers.",
            "parameters": {
                "type": "object",
                "properties": {"topic": {"type": "string", "description": "Topic to research"}},
                "required": ["topic"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_math",
            "description": "Evaluate any math expression using SymPy for exact results. ALWAYS use this for any arithmetic or algebra, never calculate in your head.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string", "description": "Math expression to evaluate"}},
                "required": ["expression"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_memory",
            "description": "Save a personal fact about the user to long-term memory.",
            "parameters": {
                "type": "object",
                "properties": {"fact": {"type": "string", "description": "Fact to remember"}},
                "required": ["fact"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "recall_memory",
            "description": "Retrieve all stored personal facts about the user from memory.",
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "system_control",
            "description": "Control the Windows PC. Open apps, check battery/cpu/ram stats, adjust volume, write Python scripts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "description": "Action: open, battery, cpu, ram, stats, volume up, volume down, write script"},
                    "target": {"type": "string", "description": "App name for open, or code content for write script"}
                },
                "required": ["action"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "open_application",
            "description": "Open a desktop application by name. Use when user says open, launch, start, or run followed by an app name.",
            "parameters": {
                "type": "object",
                "properties": {"app_name": {"type": "string", "description": "Application name to open"}},
                "required": ["app_name"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Send an email from ARJUN's Gmail account.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to":              {"type": "string", "description": "Recipient email"},
                    "subject":         {"type": "string", "description": "Email subject"},
                    "body":            {"type": "string", "description": "Email body"},
                    "attachment_path": {"type": "string", "description": "Optional file path to attach"}
                },
                "required": ["to", "subject", "body"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "check_email",
            "description": "Check ARJUN's Gmail inbox for unread emails.",
            "parameters": {
                "type": "object",
                "properties": {"max_messages": {"type": "integer", "description": "Number of emails to fetch"}},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_knowledge_base",
            "description": "Search the user's personal document library. Use for questions about uploaded notes, textbooks, or documents.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Query to search"}},
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browse_url",
            "description": "Open a URL in a real browser and return full page content.",
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string", "description": "URL to visit"}},
                "required": ["url"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "browser_search",
            "description": "Search the web and read the full content of the top result using a real browser. More powerful than web_search for detailed content.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"]
            }
        }
    }
]

TOOL_SCHEMAS.extend([
    {
        "type": "function",
        "function": {
            "name": "list_applications",
            "description": "List desktop applications ARJUN can open.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_knowledge_base",
            "description": "Add a local document to the personal knowledge base.",
            "parameters": {
                "type": "object",
                "properties": {"filepath": {"type": "string", "description": "Path to a local document."}},
                "required": ["filepath"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_knowledge_base",
            "description": "List documents stored in the personal knowledge base.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
])

from browser_agent import BROWSER_TOOL_SCHEMAS
from whatsapp_bridge import WHATSAPP_TOOL_SCHEMAS

TOOL_SCHEMAS.extend(
    schema for schema in BROWSER_TOOL_SCHEMAS
    if schema["function"]["name"] in ("fill_form", "click_and_read")
)
TOOL_SCHEMAS.extend(WHATSAPP_TOOL_SCHEMAS)
