from __future__ import annotations

import ast
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

try:
    from streamlit_ace import st_ace
except Exception:  # graceful fallback if requirements were not installed yet
    st_ace = None

from ai_provider import (
    active_model,
    active_provider,
    list_ollama_models,
    load_settings,
    provider_status,
    save_settings,
    generate_text,
)
from executor import run_code
from prompts import SYSTEM_PROMPT, build_prompt
from rag import retrieve

st.set_page_config(
    page_title="CodePilot AI",
    page_icon="🟧",
    layout="wide",
    initial_sidebar_state="expanded",
)

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
USAGE_FILE = DATA_DIR / "usage.json"
AUTH_FILE = DATA_DIR / "users.json"
CSS_FILE = ROOT / "style.css"

if CSS_FILE.exists():
    st.markdown(f"<style>{CSS_FILE.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True)

# ------------------------- session defaults -------------------------
DEFAULTS = {
    "page": "Home",
    "authenticated": False,
    "user_email": "",
    "user_name": "",
    "auth_mode": "signin",
    "messages": [],
    "home_messages": [],
    "chat_language": "Python",
    "chat_mode": "Learn a concept",
    "theme": "dark",
    "show_page_menu": False,
    "show_deploy_help": False,
    "settings": load_settings(),
}
for key, value in DEFAULTS.items():
    st.session_state.setdefault(key, value)

# Light mode is intentionally subtle; the supplied references are primarily dark.
if st.session_state.theme == "light":
    st.markdown(
        """
        <style>
        .stApp{filter:brightness(1.13) saturate(.92)}
        </style>
        """,
        unsafe_allow_html=True,
    )

# ------------------------- local authentication -------------------------
def _legacy_hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return f"pbkdf2_sha256$240000${salt.hex()}${digest.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    if stored.startswith("pbkdf2_sha256$"):
        try:
            _, rounds, salt_hex, digest_hex = stored.split("$", 3)
            digest = hashlib.pbkdf2_hmac(
                "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds)
            ).hex()
            return hmac.compare_digest(digest, digest_hex)
        except Exception:
            return False
    # Backward compatibility with the original project's SHA-256 accounts.
    return hmac.compare_digest(_legacy_hash_password(password), stored)


def load_users() -> dict:
    try:
        if AUTH_FILE.exists():
            data = json.loads(AUTH_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def save_users(users: dict) -> None:
    tmp = AUTH_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(users, indent=2), encoding="utf-8")
    tmp.replace(AUTH_FILE)


def valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))


def auth_switcher(prefix: str) -> None:
    a, b = st.columns(2)
    with a:
        if st.button(
            "👤  Sign In",
            key=f"{prefix}_signin",
            type="primary" if st.session_state.auth_mode == "signin" else "secondary",
            use_container_width=True,
        ):
            st.session_state.auth_mode = "signin"
            st.rerun()
    with b:
        if st.button(
            "👥  Create Account",
            key=f"{prefix}_signup",
            type="primary" if st.session_state.auth_mode == "signup" else "secondary",
            use_container_width=True,
        ):
            st.session_state.auth_mode = "signup"
            st.rerun()


def render_signin() -> None:
    left, right = st.columns([1.02, 1], gap="large")
    with left:
        st.markdown(
            """
            <div class="auth-promo">
              <div class="auth-brand-row"><div class="auth-logo">&lt;/&gt;</div>
                <div><div class="auth-brand">CodePilot <span>AI</span></div><div class="auth-tagline">Your AI Coding Mentor</div></div>
              </div>
              <div class="auth-pill">SMART &nbsp;•&nbsp; FAST &nbsp;•&nbsp; LOCAL + CLOUD</div>
              <p class="auth-copy">CodePilot AI is a personal GenAI + RAG coding mentor designed to help you learn, understand, debug, optimize, generate and enhance code.</p>
              <div class="promo-feature"><b>⌘ &nbsp; Understand Your Code</b><span>Get clear explanations in simple language.</span></div>
              <div class="promo-feature green"><b>🐞 &nbsp; Debug &amp; Fix</b><span>Find and solve issues quickly.</span></div>
              <div class="promo-feature purple"><b>💡 &nbsp; Generate &amp; Improve</b><span>Create better, optimized and efficient code.</span></div>
              <div class="promo-feature blue"><b>📘 &nbsp; Learn with Confidence</b><span>Build your skills step by step.</span></div>
              <div class="auth-quote">❝ &nbsp; Better Code &nbsp;•&nbsp; Smarter Learning &nbsp;•&nbsp; Powered by You</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with right:
        st.markdown('<div class="auth-form-title">Welcome Back!</div><div class="auth-form-sub">Sign in to continue your coding journey with CodePilot AI.</div>', unsafe_allow_html=True)
        auth_switcher("signin_top")
        users = load_users()
        with st.form("signin_form"):
            email = st.text_input("Email", placeholder="you@example.com")
            password = st.text_input("Password", type="password", placeholder="Enter your password")
            remember = st.checkbox("Keep me signed in during this session", value=True)
            submitted = st.form_submit_button("↪  Sign In  →", type="primary", use_container_width=True)
        if submitted:
            key = email.strip().lower()
            account = users.get(key)
            if account and _verify_password(password, str(account.get("password_hash", ""))):
                # Upgrade legacy hashes after a successful login.
                if not str(account.get("password_hash", "")).startswith("pbkdf2_sha256$"):
                    account["password_hash"] = _hash_password(password)
                    save_users(users)
                st.session_state.authenticated = True
                st.session_state.user_email = key
                st.session_state.user_name = account.get("name", "Developer")
                st.session_state.page = "Home"
                st.session_state.remember_me = remember
                st.rerun()
            else:
                st.error("Incorrect email or password.")

        with st.expander("Forgot password?"):
            st.caption("Local account recovery: confirm the display name and email stored in this project.")
            with st.form("reset_password_form"):
                re_email = st.text_input("Account email", key="reset_email")
                re_name = st.text_input("Display name", key="reset_name")
                new_password = st.text_input("New password", type="password", key="reset_new_pw")
                reset = st.form_submit_button("Reset local password")
            if reset:
                key = re_email.strip().lower()
                account = users.get(key)
                if not account or account.get("name", "").strip().lower() != re_name.strip().lower():
                    st.error("The email and display name do not match a local account.")
                elif len(new_password) < 6:
                    st.error("Password must contain at least 6 characters.")
                else:
                    account["password_hash"] = _hash_password(new_password)
                    save_users(users)
                    st.success("Local password updated. You can sign in now.")

        st.markdown(
            '<div class="privacy-note">🛡️ &nbsp; Your account data is stored locally in this project. No cloud authentication service is used.</div>',
            unsafe_allow_html=True,
        )


def render_signup() -> None:
    st.markdown(
        """
        <div class="signup-brand">
          <div class="signup-logo">&lt;/&gt;</div>
          <div class="signup-title">CodePilot <span>AI</span></div>
          <div class="signup-sub">Your local AI coding mentor</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    _, center, _ = st.columns([1.0, 1.28, 1.0])
    with center:
        auth_switcher("signup_top")
        users = load_users()
        with st.form("signup_form"):
            name = st.text_input("Display name", placeholder="Your name")
            email = st.text_input("Email", placeholder="you@example.com", key="signup_email")
            password = st.text_input("Password", type="password", placeholder="At least 6 characters", key="signup_password")
            confirm = st.text_input("Confirm password", type="password", placeholder="Repeat your password")
            create = st.form_submit_button("Create account  →", type="primary", use_container_width=True)
        if create:
            key = email.strip().lower()
            if not name.strip() or not valid_email(key):
                st.error("Enter a valid display name and email address.")
            elif len(password) < 6:
                st.error("Password must contain at least 6 characters.")
            elif password != confirm:
                st.error("Passwords do not match.")
            elif key in users:
                st.error("An account with this email already exists. Sign in instead.")
            else:
                users[key] = {
                    "name": name.strip(),
                    "password_hash": _hash_password(password),
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                }
                save_users(users)
                st.success("Account created successfully. Select Sign In to continue.")
        st.markdown('<div class="auth-bottom-link">Already have an account? Choose <b>Sign In</b> above.</div>', unsafe_allow_html=True)


def render_auth() -> None:
    # Hide sidebar and Streamlit chrome while logged out.
    st.markdown("<style>section[data-testid='stSidebar']{display:none} .block-container{max-width:1500px}</style>", unsafe_allow_html=True)
    if st.session_state.auth_mode == "signup":
        render_signup()
    else:
        render_signin()


if not st.session_state.authenticated:
    render_auth()
    st.stop()

# ------------------------- usage / activity -------------------------
def _default_usage() -> dict:
    now = time.time()
    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "last_seen": now,
        "today": datetime.now().date().isoformat(),
        "today_active_seconds": 0.0,
        "total_active_seconds": 0.0,
        "sessions": 0,
        "lines_processed": 0,
        "executions": 0,
        "successful_runs": 0,
        "failed_runs": 0,
        "ai_uses": 0,
        "questions": 0,
        "pages_visited": 0,
        "activity": [],
    }


def load_usage() -> dict:
    base = _default_usage()
    try:
        if USAGE_FILE.exists():
            data = json.loads(USAGE_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                base.update(data)
    except Exception:
        pass
    if base.get("today") != datetime.now().date().isoformat():
        base["today"] = datetime.now().date().isoformat()
        base["today_active_seconds"] = 0.0
    return base


def save_usage(data: dict) -> None:
    tmp = USAGE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(USAGE_FILE)


if "usage" not in st.session_state:
    st.session_state.usage = load_usage()
if "session_started" not in st.session_state:
    st.session_state.session_started = time.time()
    st.session_state.usage["sessions"] = int(st.session_state.usage.get("sessions", 0)) + 1
    save_usage(st.session_state.usage)


def track_active_time() -> None:
    usage = st.session_state.usage
    now = time.time()
    last = float(usage.get("last_seen", now))
    delta = max(0.0, now - last)
    if delta <= 180:
        usage["total_active_seconds"] = float(usage.get("total_active_seconds", 0)) + delta
        usage["today_active_seconds"] = float(usage.get("today_active_seconds", 0)) + delta
    usage["last_seen"] = now
    save_usage(usage)


def record_usage(kind: str, amount: int = 1) -> None:
    usage = st.session_state.usage
    usage[kind] = int(usage.get(kind, 0)) + int(amount)
    save_usage(usage)


def add_activity(label: str, detail: str = "") -> None:
    item = {
        "time": datetime.now().strftime("%d %b %Y, %I:%M %p"),
        "label": label,
        "detail": detail,
    }
    usage = st.session_state.usage
    usage.setdefault("activity", []).insert(0, item)
    usage["activity"] = usage["activity"][:80]
    save_usage(usage)


def reset_workspace_usage() -> None:
    fresh = _default_usage()
    fresh["sessions"] = 1
    st.session_state.usage = fresh
    st.session_state.messages = []
    st.session_state.home_messages = []
    for key in list(st.session_state.keys()):
        if key.startswith(("code_", "result_", "answer_", "convert_")):
            del st.session_state[key]
    save_usage(fresh)


@st.fragment(run_every="60s")
def _heartbeat():
    track_active_time()
    st.empty()


_heartbeat()

# ------------------------- helpers -------------------------
def go(page: str) -> None:
    st.session_state.page = page
    st.session_state.show_page_menu = False
    st.rerun()


def code_language(language: str) -> str:
    return {
        "C++": "cpp",
        "C#": "csharp",
        "JavaScript": "javascript",
    }.get(language, language.lower())


def active_settings() -> dict:
    # Session is the immediate source so unsaved settings changes never leak.
    return dict(st.session_state.get("settings") or load_settings())


def safe_ai(prompt: str, label: str, *, system_prompt: str = SYSTEM_PROMPT, max_tokens: int = 2200) -> str | None:
    settings = active_settings()
    provider = active_provider(settings)
    model = active_model(settings)
    try:
        with st.spinner(f"Thinking with {provider} · {model}..."):
            answer = generate_text(
                prompt,
                settings,
                system_prompt=system_prompt,
                temperature=0.2,
                max_tokens=max_tokens,
            )
        record_usage("ai_uses", 1)
        add_activity(label, f"{provider} · {model}")
        return answer
    except Exception as exc:
        st.error(str(exc))
        return None


def get_rag_context(query: str, n_results: int = 5):
    settings = active_settings()
    if not settings.get("use_rag", True):
        return "Local RAG is disabled in Settings.", []
    docs = retrieve(query, n_results=n_results)
    context = "\n\n".join(f"[Source: {x['source']}]\n{x['text']}" for x in docs)
    return context or "No matching local documents were found.", docs


def run_tutor(question: str, language: str, mode: str):
    record_usage("questions", 1)
    context, docs = get_rag_context(question)
    prompt = build_prompt(question, language, context, mode)
    answer = safe_ai(prompt, "AI Mentor")
    return answer, docs


def run_general_chat(question: str) -> str | None:
    record_usage("questions", 1)
    system = (
        "You are CodePilot AI, a capable general-purpose AI assistant inside a coding workspace. "
        "Answer the user's actual question directly. You may help with programming, study topics, "
        "general knowledge, writing, brainstorming, calculations, and everyday questions. Be clear, "
        "accurate, and practical. Do not pretend you have live data unless the user supplies it."
    )
    return safe_ai(question, "Home AI Chat", system_prompt=system, max_tokens=2200)


def provider_badge() -> tuple[str, str, bool]:
    settings = active_settings()
    provider = active_provider(settings)
    model = active_model(settings)
    ok, status = provider_status(settings, live=False)
    return f"{provider} · {model}", status, ok


def page_header(title: str, subtitle: str, icon: str = "⌘") -> None:
    left, deploy, menu = st.columns([8.5, 1.0, 0.36], vertical_alignment="center")
    with left:
        safe_title = html.escape(title)
        safe_sub = html.escape(subtitle)
        words = safe_title.rsplit(" ", 1)
        styled = f"{words[0]} <span>{words[1]}</span>" if len(words) == 2 else f"<span>{safe_title}</span>"
        st.markdown(
            f"<div class='page-head'><div class='page-icon'>{icon}</div><div><div class='page-title'>{styled}</div><div class='page-sub'>{safe_sub}</div></div></div>",
            unsafe_allow_html=True,
        )
    with deploy:
        if st.button("🚀 Deploy", key=f"deploy_{title}", use_container_width=True):
            st.session_state.show_deploy_help = not st.session_state.show_deploy_help
    with menu:
        if st.button("⋮", key=f"menu_{title}", use_container_width=True):
            st.session_state.show_page_menu = not st.session_state.show_page_menu
    if st.session_state.show_page_menu:
        c1, c2, c3 = st.columns(3)
        if c1.button("🕘 Recent Activity", key=f"menu_activity_{title}", use_container_width=True):
            go("Recent Activity")
        if c2.button("⚙ Settings", key=f"menu_settings_{title}", use_container_width=True):
            go("Settings")
        if c3.button("ⓘ About", key=f"menu_about_{title}", use_container_width=True):
            go("About")
    if st.session_state.show_deploy_help:
        with st.expander("Deployment options", expanded=True):
            st.markdown(
                "**Local:** run `python -m streamlit run backend/app.py`.  \n"
                "**LAN:** add `--server.address 0.0.0.0`.  \n"
                "**Cloud:** deploy the repository to a Python/Streamlit host and set API keys as environment secrets. "
                "Local Ollama only works when the deployed app can reach your Ollama server."
            )


def nav_button(label: str, icon: str) -> None:
    active = st.session_state.page == label
    if st.button(
        f"{icon}   {label}",
        key=f"nav_{label}",
        use_container_width=True,
        type="primary" if active else "secondary",
    ):
        go(label)


def stat_card(icon: str, value, label: str, tone: str = "orange", badge: str = "Total") -> str:
    return f"""
    <div class='stat-card {tone}'>
      <div class='stat-icon'>{icon}</div>
      <div class='stat-body'><strong>{html.escape(str(value))}</strong><span>{html.escape(label)}</span><small>{html.escape(badge)}</small></div>
      <div class='stat-bars'><i></i><i></i><i></i><i></i><i></i></div>
    </div>"""


def section_card_start(extra: str = "") -> None:
    st.markdown(f"<div class='glass-card {extra}'>", unsafe_allow_html=True)


def section_card_end() -> None:
    st.markdown("</div>", unsafe_allow_html=True)


# ------------------------- code editor helpers -------------------------
ACE_LANG = {"Python": "python", "C": "c_cpp", "C++": "c_cpp", "Java": "java", "JavaScript": "javascript"}
EXAMPLES = {
    "Python": "def fibonacci(n):\n    if n <= 1:\n        return n\n    return fibonacci(n-1) + fibonacci(n-2)\n\nprint(fibonacci(10))",
    "C": '#include <stdio.h>\n\nint main(void) {\n    printf("Hello, CodePilot AI!\\n");\n    return 0;\n}',
    "C++": '#include <iostream>\nusing namespace std;\n\nint main() {\n    cout << "Hello, CodePilot AI!" << endl;\n    return 0;\n}',
    "Java": 'public class Main {\n    public static void main(String[] args) {\n        System.out.println("Hello, CodePilot AI!");\n    }\n}',
    "JavaScript": 'function greet(name) {\n  return `Hello, ${name}!`;\n}\n\nconsole.log(greet("CodePilot AI"));',
}


def _rev_key(state_key: str) -> str:
    return f"{state_key}__rev"


def set_editor_code(state_key: str, value: str) -> None:
    st.session_state[state_key] = value
    st.session_state[_rev_key(state_key)] = int(st.session_state.get(_rev_key(state_key), 0)) + 1


def code_editor(state_key: str, language: str, height: int = 300, placeholder: str = "Paste your code here...") -> str:
    st.session_state.setdefault(state_key, "")
    rev = int(st.session_state.setdefault(_rev_key(state_key), 0))
    current = st.session_state[state_key]
    if st_ace is not None:
        value = st_ace(
            value=current,
            language=ACE_LANG.get(language, "text"),
            theme="tomorrow_night_eighties",
            key=f"ace_{state_key}_{rev}",
            height=height,
            font_size=15,
            tab_size=4,
            show_gutter=True,
            show_print_margin=False,
            wrap=True,
            auto_update=True,
            placeholder=placeholder,
        )
    else:
        value = st.text_area(
            "Code",
            value=current,
            height=height,
            key=f"textarea_{state_key}_{rev}",
            label_visibility="collapsed",
            placeholder=placeholder,
        )
    if value is not None:
        st.session_state[state_key] = value
    return st.session_state[state_key]


def format_code(code: str, language: str) -> str:
    code = code.replace("\r\n", "\n")
    if language == "Python" and code.strip():
        try:
            # Built-in formatter fallback: normalize valid Python via AST.
            # It intentionally avoids adding a heavyweight mandatory formatter.
            tree = ast.parse(code)
            return ast.unparse(tree).rstrip() + "\n"
        except Exception:
            pass
    return "\n".join(line.rstrip() for line in code.splitlines()).strip("\n") + ("\n" if code.strip() else "")


def editor_toolbar(state_key: str, language: str, prefix: str, *, allow_file: bool = False) -> None:
    c1, c2, c3, c4 = st.columns([1.15, 1.0, .85, .95])
    with c1:
        if allow_file:
            with st.popover("📄 Load File", use_container_width=True):
                uploaded = st.file_uploader("Choose a source file", type=["py", "c", "cpp", "h", "java", "js", "txt"], key=f"file_{prefix}")
                if uploaded is not None and st.button("Load into editor", key=f"load_file_{prefix}", use_container_width=True):
                    try:
                        set_editor_code(state_key, uploaded.getvalue().decode("utf-8"))
                        st.rerun()
                    except UnicodeDecodeError:
                        st.error("Please upload a UTF-8 text source file.")
        else:
            if st.button("📄 Load Example", key=f"example_{prefix}", use_container_width=True):
                set_editor_code(state_key, EXAMPLES.get(language, ""))
                st.rerun()
    with c2:
        with st.popover("📋 Paste", use_container_width=True):
            st.caption("Paste from your clipboard below, then apply it to the editor.")
            pasted = st.text_area("Clipboard text", key=f"paste_buffer_{prefix}", height=130, label_visibility="collapsed")
            if st.button("Apply pasted code", key=f"apply_paste_{prefix}", use_container_width=True):
                set_editor_code(state_key, pasted)
                st.rerun()
    with c3:
        if st.button("🗑 Clear", key=f"clear_{prefix}", use_container_width=True):
            set_editor_code(state_key, "")
            st.rerun()
    with c4:
        if st.button("🪄 Format", key=f"format_{prefix}", use_container_width=True):
            set_editor_code(state_key, format_code(st.session_state.get(state_key, ""), language))
            st.rerun()


# ------------------------- sidebar -------------------------
with st.sidebar:
    st.markdown(
        """
        <div class="brand-block"><div class="brand-logo">&lt;/&gt;</div><div><div class="brand-title">CodePilot AI</div><div class="brand-sub">Your AI Coding Mentor</div></div></div>
        <div class="side-section-title">NAVIGATION</div>
        """,
        unsafe_allow_html=True,
    )
    for label, icon in [
        ("Home", "⌂"),
        ("Chat (AI Mentor)", "◯"),
        ("Compiler / Run Code", "▶"),
        ("Debug & Fix", "🔧"),
        ("Explain Code", "▤"),
        ("Improve Code", "✦"),
        ("Generate Tests", "⌘"),
        ("Convert Code", "⇄"),
        ("Dashboard", "▥"),
    ]:
        nav_button(label, icon)

    # The Resources block is intentionally removed per the requested design.
    st.markdown("<div class='sidebar-divider'></div>", unsafe_allow_html=True)
    nav_button("Recent Activity", "◷")
    nav_button("Settings", "⚙")
    nav_button("About", "ⓘ")
    st.markdown("<div class='sidebar-divider'></div>", unsafe_allow_html=True)
    if st.button("↪   Sign out", key="sign_out", use_container_width=True):
        st.session_state.authenticated = False
        st.session_state.user_email = ""
        st.session_state.user_name = ""
        st.session_state.auth_mode = "signin"
        st.rerun()

    label, status_text, ok = provider_badge()
    st.markdown(
        f"<div class='provider-card {'ok' if ok else 'warn'}'><b><i></i>{html.escape(label)}</b><span>{html.escape(status_text)}</span><small>{'Local / configured AI' if ok else 'Open Settings to configure'}</small></div>",
        unsafe_allow_html=True,
    )

# ------------------------- home -------------------------
def render_top_home_controls() -> None:
    left, theme, avatar, deploy, menu = st.columns([8, .7, .7, 1, .35], vertical_alignment="center")
    with left:
        st.markdown("<div class='top-brand-line'>CodePilot <span>AI</span> <small>Local-first coding workspace</small></div>", unsafe_allow_html=True)
    with theme:
        if st.button("☀ / ☾", key="home_theme", help="Toggle display brightness"):
            st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"
            st.rerun()
    with avatar:
        initial = (st.session_state.user_name or "U")[:1].upper()
        st.markdown(f"<div class='mini-avatar'>{html.escape(initial)}</div>", unsafe_allow_html=True)
    with deploy:
        if st.button("🚀 Deploy", key="home_deploy", use_container_width=True):
            st.session_state.show_deploy_help = not st.session_state.show_deploy_help
    with menu:
        if st.button("⋮", key="home_menu"):
            st.session_state.show_page_menu = not st.session_state.show_page_menu
    if st.session_state.show_page_menu:
        c1, c2, c3 = st.columns(3)
        if c1.button("🕘 Recent Activity", key="home_recent", use_container_width=True): go("Recent Activity")
        if c2.button("⚙ Settings", key="home_settings", use_container_width=True): go("Settings")
        if c3.button("ⓘ About", key="home_about", use_container_width=True): go("About")
    if st.session_state.show_deploy_help:
        st.info("Deploy this Streamlit app locally or to a Python host. Cloud deployments should store API keys as environment secrets. Local Ollama must be reachable from the host.")


def render_home_chat() -> None:
    provider, status, ok = provider_badge()
    st.markdown(
        f"""
        <div class='assistant-head'>
          <div class='assistant-avatar'>🧠</div><div><b>CodePilot <span>AI</span></b><small>Ask, learn, debug, optimize and chat with AI.</small></div>
          <div class='assistant-status {'online' if ok else 'offline'}'><i></i>{'Online' if ok else 'Needs setup'}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if st.session_state.home_messages:
        with st.container(height=280, border=False):
            for msg in st.session_state.home_messages[-10:]:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
    qrev = int(st.session_state.setdefault("home_question_rev", 0))
    question = st.text_area(
        "Home AI question",
        placeholder="Ask any coding question or start a conversation...",
        height=180,
        key=f"home_question_{qrev}",
        label_visibility="collapsed",
    )
    ask, clear = st.columns([5, 1.2])
    with ask:
        if st.button("▶  Ask AI", key="ask_home", type="primary", use_container_width=True):
            q = question.strip()
            if not q:
                st.warning("Type a question first.")
            else:
                st.session_state.home_messages.append({"role": "user", "content": q})
                answer = run_general_chat(q)
                if answer:
                    st.session_state.home_messages.append({"role": "assistant", "content": answer})
                st.session_state.home_question_rev = qrev + 1
                st.rerun()
    with clear:
        if st.button("🗑 Clear", key="clear_home", use_container_width=True):
            st.session_state.home_messages = []
            st.session_state.home_question_rev = qrev + 1
            st.rerun()
    st.caption(f"Active AI: {provider} · {status}")


def render_home() -> None:
    render_top_home_controls()
    now_date = datetime.now().strftime("%a, %d %b %Y")
    now_time = datetime.now().strftime("%I:%M %p").lstrip("0")
    st.markdown(
        f"""
        <section class='home-hero'>
          <div><small>WELCOME TO CODEPILOT AI</small><h1>Learn. Build. Solve.<br><span>Together.</span></h1><p>Your personal AI coding mentor, available 24/7.<br>“Better code. Brighter future.”</p></div>
          <div class='hero-laptop-art'><div>&lt;/&gt;</div></div>
          <div class='hero-date'>▣ <span>{html.escape(now_date)}<b>{html.escape(now_time)}</b><small>Stay consistent 🚀</small></span></div>
        </section>
        """,
        unsafe_allow_html=True,
    )
    usage = st.session_state.usage
    today_min = int(float(usage.get("today_active_seconds", 0)) // 60)
    stats = [
        stat_card("◷", f"{today_min//60}h {today_min%60:02d}m", "Active Today", "gold", "Live"),
        stat_card("▤", f"{usage.get('lines_processed',0):,}", "Lines Processed", "teal"),
        stat_card("▶", usage.get("executions", 0), "Code Executions", "blue"),
        stat_card("✓", usage.get("successful_runs", 0), "Successful Runs", "green"),
        stat_card("×", usage.get("failed_runs", 0), "Failed Runs", "red"),
        stat_card("◉", usage.get("ai_uses", 0), "AI Guide Uses", "purple"),
    ]
    st.markdown("<div class='stats-grid'>" + "".join(stats) + "</div>", unsafe_allow_html=True)
    section_card_start("home-assistant")
    render_home_chat()
    section_card_end()

# ------------------------- AI Mentor Chat -------------------------
def render_chat() -> None:
    page_header("AI Mentor Chat", "Ask coding questions and get answers grounded in your local programming knowledge base.", "◯")
    a, b = st.columns(2)
    with a:
        section_card_start()
        language = st.selectbox("Language", ["Python", "C", "C++", "Java", "JavaScript", "General"], key="chat_language_select")
        st.caption("Select the programming language for better answers.")
        section_card_end()
    with b:
        section_card_start()
        mode = st.selectbox("Mode", ["Learn a concept", "Debug my code", "Explain my code", "Optimize my code", "Generate unit tests", "Practice questions"], key="chat_mode_select")
        st.caption("Choose the assistant mode for your query.")
        section_card_end()

    section_card_start("chat-stage")
    if not st.session_state.messages:
        st.markdown("<div class='empty-chat'><div>🤖</div><b>Start a conversation</b><span>Ask your coding tutor anything about coding, concepts, debugging, projects, and more.</span></div>", unsafe_allow_html=True)
    else:
        with st.container(height=430, border=False):
            for msg in st.session_state.messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])
    section_card_end()
    with st.popover("📎 Attach code / context"):
        attached = st.file_uploader("Attach a text/source file", type=["py", "c", "cpp", "h", "java", "js", "txt", "md", "json"], key="chat_attachment_file")
        if attached is not None:
            try:
                content = attached.getvalue().decode("utf-8")
                st.session_state.chat_attachment_text = content[:30000]
                st.session_state.chat_attachment_name = attached.name
                st.success(f"Attached: {attached.name}")
            except UnicodeDecodeError:
                st.error("Attachment must be a UTF-8 text/source file.")
        if st.session_state.get("chat_attachment_text") and st.button("Remove attachment", key="remove_chat_attachment"):
            st.session_state.chat_attachment_text = ""
            st.session_state.chat_attachment_name = ""
            st.rerun()
    if st.session_state.get("chat_attachment_name"):
        st.caption(f"📎 Next message includes: {st.session_state.chat_attachment_name}")
    question = st.chat_input(f"Ask your {language} tutor anything...")
    if question:
        display_question = question
        attachment = st.session_state.get("chat_attachment_text", "")
        if attachment:
            question = f"{question}\n\nATTACHED FILE ({st.session_state.get('chat_attachment_name','source')}):\n```{code_language(language)}\n{attachment}\n```"
        st.session_state.messages.append({"role": "user", "content": display_question})
        answer, docs = run_tutor(question, language, mode)
        if answer:
            st.session_state.messages.append({"role": "assistant", "content": answer})
            st.session_state.chat_attachment_text = ""
            st.session_state.chat_attachment_name = ""
            st.rerun()

# ------------------------- Compiler -------------------------
def render_compiler() -> None:
    page_header("Compiler / Run Code", "Execute trusted local code using tools installed on your computer.", "⌘")
    section_card_start()
    language = st.selectbox("Language", ["Python", "C", "C++", "Java", "JavaScript"], key="compiler_language")
    st.caption("Select the programming language for execution.")
    section_card_end()

    section_card_start()
    h1, h2 = st.columns([1.5, 1])
    with h1:
        st.markdown("### 📄 Code")
        st.caption("Paste your code here.")
    with h2:
        editor_toolbar("code_compiler", language, "compiler")
    code = code_editor("code_compiler", language, 300)
    section_card_end()

    section_card_start()
    st.markdown("### ▣ Standard Input (optional)")
    stdin_text = st.text_area("stdin", height=90, key="compiler_stdin", label_visibility="collapsed", placeholder="Example:\n10\n20")
    section_card_end()

    section_card_start()
    st.markdown("### ◷ Timeout (seconds)")
    timeout = st.number_input("Maximum execution time", min_value=1, max_value=30, value=5, step=1, key="compiler_timeout", label_visibility="collapsed")
    section_card_end()

    run_col, clear_col = st.columns([1, 1])
    with run_col:
        if st.button("▶  Run / Compile", key="run_compile", type="primary", use_container_width=True):
            result = run_code(language, code, stdin_text, int(timeout))
            st.session_state.result_compiler = result
            record_usage("executions", 1)
            record_usage("lines_processed", len(code.splitlines()))
            record_usage("successful_runs" if result.get("success") else "failed_runs", 1)
            add_activity(f"Ran {language} code", result.get("status", ""))
    with clear_col:
        if st.button("🗑  Clear Output", key="clear_compile_output", use_container_width=True):
            st.session_state.result_compiler = None
            st.rerun()
    result = st.session_state.get("result_compiler")
    if result:
        section_card_start("result-panel")
        st.markdown(f"### {'✅' if result.get('success') else '❌'} {result.get('status','Result')}")
        if result.get("stdout"):
            st.markdown("**Output**")
            st.code(result["stdout"], language="text")
        if result.get("stderr"):
            st.markdown("**Errors / diagnostics**")
            st.code(result["stderr"], language="text")
        section_card_end()

# ------------------------- AI code tools -------------------------
def _code_ai_prompt(action: str, language: str, code: str, extra: str = "", context_text: str = "") -> tuple[str, list]:
    rag_context, docs = get_rag_context(f"{action} {language} {extra}")
    request_text = f"{action} this {language} code.\n"
    if context_text.strip():
        request_text += f"Context/error:\n{context_text.strip()}\n"
    if extra.strip():
        request_text += f"Additional instructions:\n{extra.strip()}\n"
    request_text += f"```{code_language(language)}\n{code}\n```"
    return build_prompt(request_text, language, rag_context, action), docs


def render_debug() -> None:
    page_header("Debug & Fix", "Find the root cause and produce a corrected version.", "🔧")
    section_card_start()
    language = st.selectbox("Language", ["Python", "C", "C++", "Java", "JavaScript"], key="debug_language")
    st.caption("Select the programming language of your code.")
    section_card_end()
    section_card_start()
    h1, h2 = st.columns([1.5, 1])
    with h1:
        st.markdown("### 📄 Code")
        st.caption("Paste your code here...")
    with h2:
        editor_toolbar("code_debug", language, "debug")
    code = code_editor("code_debug", language, 340)
    section_card_end()
    error_context = st.text_area("Error / context (optional)", key="debug_error", placeholder="Paste the error message or describe the wrong behavior...")
    if st.button("🔧  Debug & Fix", key="debug_action", type="primary", use_container_width=True):
        if not code.strip():
            st.warning("Paste code first.")
        else:
            prompt, _ = _code_ai_prompt("Debug and fix", language, code, context_text=error_context)
            answer = safe_ai(prompt, "Debug & Fix")
            if answer:
                record_usage("lines_processed", len(code.splitlines()))
                st.session_state.answer_debug = answer
    if st.session_state.get("answer_debug"):
        section_card_start("result-panel")
        st.markdown(st.session_state.answer_debug)
        section_card_end()


def render_explain() -> None:
    page_header("Explain Code", "Understand code line-by-line without losing the big picture.", "▤")
    a, b = st.columns(2)
    with a:
        section_card_start()
        language = st.selectbox("Programming Language", ["Python", "C", "C++", "Java", "JavaScript"], key="explain_language")
        section_card_end()
    with b:
        section_card_start()
        level = st.selectbox("Explanation Level", ["Detailed (Line-by-line)", "Balanced", "Beginner-friendly", "Concise summary"], key="explain_level")
        section_card_end()
    section_card_start()
    h1, h2 = st.columns([1.5, 1])
    with h1:
        st.markdown("### 📄 Your Code")
        st.caption("Paste the code you want to explain below.")
    with h2:
        editor_toolbar("code_explain", language, "explain")
    code = code_editor("code_explain", language, 260)
    section_card_end()
    section_card_start()
    context_text = st.text_area("Error / Context (Optional)", key="explain_context", placeholder="Paste the error message or add context...")
    section_card_end()
    section_card_start()
    extra = st.text_area("Additional Instructions (Optional)", key="explain_extra", placeholder="What would you like the AI to focus on?")
    section_card_end()
    if st.button("▤  Explain Code", key="explain_action", type="primary", use_container_width=True):
        if not code.strip():
            st.warning("Paste code first.")
        else:
            prompt, _ = _code_ai_prompt(f"Explain at {level} level", language, code, extra, context_text)
            answer = safe_ai(prompt, "Explain Code")
            if answer:
                record_usage("lines_processed", len(code.splitlines()))
                st.session_state.answer_explain = answer
    if st.session_state.get("answer_explain"):
        section_card_start("result-panel")
        st.markdown(st.session_state.answer_explain)
        section_card_end()


def render_improve() -> None:
    page_header("Improve Code", "Refactor for correctness, readability, maintainability, and performance.", "✦")
    a, b = st.columns(2)
    with a:
        section_card_start()
        language = st.selectbox("Programming Language", ["Python", "C", "C++", "Java", "JavaScript"], key="improve_language")
        section_card_end()
    with b:
        section_card_start()
        focus = st.selectbox("Optimization Focus (Optional)", ["General Improvement", "Performance", "Readability", "Memory efficiency", "Best practices", "Security"], key="improve_focus")
        section_card_end()
    section_card_start()
    h1, h2 = st.columns([1.5, 1])
    with h1:
        st.markdown("### 📄 Your Code")
        st.caption("Paste the code you want to improve below.")
    with h2:
        editor_toolbar("code_improve", language, "improve")
    code = code_editor("code_improve", language, 300)
    section_card_end()
    section_card_start()
    extra = st.text_area("Additional Instructions (Optional)", key="improve_extra", placeholder="What would you like the AI to focus on?")
    section_card_end()
    if st.button("✦  Improve Code", key="improve_action", type="primary", use_container_width=True):
        if not code.strip():
            st.warning("Paste code first.")
        else:
            prompt, _ = _code_ai_prompt(f"Improve/refactor with focus on {focus}", language, code, extra)
            answer = safe_ai(prompt, "Improve Code")
            if answer:
                record_usage("lines_processed", len(code.splitlines()))
                st.session_state.answer_improve = answer
    if st.session_state.get("answer_improve"):
        section_card_start("result-panel")
        st.markdown(st.session_state.answer_improve)
        section_card_end()


def render_generate_tests() -> None:
    page_header("Generate Tests", "Generate unit tests covering normal, edge, boundary and failure cases.", "⌘")
    section_card_start()
    language = st.selectbox("Language", ["Python", "C", "C++", "Java", "JavaScript"], key="tests_language")
    st.caption("Select the programming language for which you want to generate tests.")
    section_card_end()
    section_card_start()
    h1, h2 = st.columns([1.5, 1])
    with h1:
        st.markdown("### 📄 Source Code")
        st.caption("Paste your function, class or full code below. The AI will generate comprehensive test cases.")
    with h2:
        editor_toolbar("code_tests", language, "tests")
    code = code_editor("code_tests", language, 300)
    section_card_end()
    frameworks = {
        "Python": ["pytest", "unittest"],
        "C": ["Unity", "CMocka", "Plain assertions"],
        "C++": ["GoogleTest", "Catch2", "Plain assertions"],
        "Java": ["JUnit 5", "TestNG"],
        "JavaScript": ["Jest", "Vitest", "Mocha"],
    }
    section_card_start()
    framework = st.selectbox("Testing Framework", frameworks[language], key=f"framework_{language}")
    st.caption("Choose the testing framework to use.")
    section_card_end()
    if st.button("✦  Generate Tests", key="tests_action", type="primary", use_container_width=True):
        if not code.strip():
            st.warning("Paste source code first.")
        else:
            prompt, _ = _code_ai_prompt(f"Generate comprehensive {framework} tests. Cover normal, edge, boundary and failure cases for", language, code)
            answer = safe_ai(prompt, "Generate Tests")
            if answer:
                record_usage("lines_processed", len(code.splitlines()))
                st.session_state.answer_tests = answer
    if st.session_state.get("answer_tests"):
        section_card_start("result-panel")
        st.markdown(st.session_state.answer_tests)
        section_card_end()


def extract_first_code_block(text: str) -> tuple[str, str]:
    match = re.search(r"```(?:[A-Za-z0-9_+#.-]+)?\s*\n?(.*?)```", text, re.DOTALL)
    if not match:
        return text.strip(), ""
    code = match.group(1).strip()
    explanation = (text[:match.start()] + text[match.end():]).strip()
    return code, explanation


def render_convert() -> None:
    page_header("Convert Code", "Translate code between languages while preserving behavior.", "⇄")
    a, mid, b = st.columns([1, .18, 1], vertical_alignment="center")
    with a:
        section_card_start()
        source = st.selectbox("Source Language", ["Python", "C", "C++", "Java", "JavaScript"], key="convert_source")
        section_card_end()
    with mid:
        st.markdown("<div class='swap-icon'>⇄</div>", unsafe_allow_html=True)
    with b:
        section_card_start()
        targets = [x for x in ["Python", "C", "C++", "Java", "JavaScript"] if x != source]
        target = st.selectbox("Target Language", targets, key="convert_target")
        section_card_end()
    left, right = st.columns(2)
    with left:
        section_card_start()
        st.markdown("### ⌘ Source Code")
        editor_toolbar("code_convert", source, "convert", allow_file=True)
        code = code_editor("code_convert", source, 360)
        st.caption(f"{source} code will be converted to {target}. Press the button below to apply.")
        section_card_end()
    with right:
        section_card_start()
        st.markdown("### ⌘ Converted Code")
        converted = st.session_state.get("convert_output", "")
        if converted:
            st.code(converted, language=code_language(target))
            ext = {"Python": "py", "C": "c", "C++": "cpp", "Java": "java", "JavaScript": "js"}[target]
            st.download_button("⬇ Download", converted, file_name=f"converted_code.{ext}", mime="text/plain", use_container_width=True)
            st.caption("Use the copy icon on the code block to copy the converted output.")
            if st.session_state.get("convert_explanation"):
                with st.expander("Conversion notes"):
                    st.markdown(st.session_state.convert_explanation)
        else:
            st.text_area("Converted output", value="", height=360, disabled=True, label_visibility="collapsed", placeholder="AI converted code will appear here...")
            st.caption("🔒 Read-only output")
        section_card_end()
    if st.button("⇄  Convert Code", key="convert_action", type="primary", use_container_width=True):
        if not code.strip():
            st.warning("Enter source code first.")
        elif source == target:
            st.warning("Choose a different target language.")
        else:
            rag_context, _ = get_rag_context(f"Convert {source} to {target}")
            request_text = (
                f"Convert the following {source} code to {target}. Preserve behavior. "
                "Return the complete runnable converted code first in one fenced code block, then briefly note important differences.\n"
                f"```{code_language(source)}\n{code}\n```"
            )
            prompt = build_prompt(request_text, target, rag_context, "Convert code to another language")
            answer = safe_ai(prompt, "Convert Code")
            if answer:
                converted_code, explanation = extract_first_code_block(answer)
                st.session_state.convert_output = converted_code
                st.session_state.convert_explanation = explanation
                record_usage("lines_processed", len(code.splitlines()))
                st.rerun()

# ------------------------- dashboard / activity -------------------------
def progress_row(icon: str, label: str, value: int, total: int, tone: str) -> str:
    pct = min(100, int((value / total) * 100)) if total else 0
    return f"<div class='progress-row'><div class='progress-icon {tone}'>{icon}</div><span>{html.escape(label)}</span><div class='progress-track'><i class='{tone}' style='width:{pct}%'></i></div><small>{value}/{total}</small></div>"


def render_dashboard() -> None:
    page_header("Dashboard", "Your real CodePilot usage, coding practice and learning activity.", "▥")
    usage = st.session_state.usage
    total_min = int(float(usage.get("total_active_seconds", 0)) // 60)
    today_min = int(float(usage.get("today_active_seconds", 0)) // 60)
    stats = [
        stat_card("◷", f"{today_min}m", "Active Today", "gold", "Live"),
        stat_card("▤", usage.get("lines_processed", 0), "Lines Processed", "teal"),
        stat_card("▶", usage.get("executions", 0), "Code Executions", "blue"),
        stat_card("✓", usage.get("successful_runs", 0), "Successful Runs", "green"),
        stat_card("×", usage.get("failed_runs", 0), "Failed Runs", "red"),
        stat_card("◉", usage.get("ai_uses", 0), "AI Guide Uses", "purple"),
    ]
    st.markdown("<div class='stats-grid'>" + "".join(stats) + "</div>", unsafe_allow_html=True)

    minutes = total_min
    ai = int(usage.get("ai_uses", 0))
    executions = int(usage.get("executions", 0))
    lines = int(usage.get("lines_processed", 0))
    overall = round((min(minutes / 600, 1) + min(ai / 50, 1) + min(executions / 50, 1) + min(lines / 5000, 1)) * 25)
    section_card_start("learning-panel")
    st.markdown("<div class='section-title'>▥ &nbsp; Learning Progress <small>Updates automatically as you work</small></div>", unsafe_allow_html=True)
    left, right = st.columns([.8, 1.8])
    with left:
        st.markdown(f"<div class='progress-ring' style='--p:{overall}'><div><b>{overall}%</b><span>Overall Progress</span></div></div>", unsafe_allow_html=True)
    with right:
        st.markdown(progress_row("◷", "Time on CodePilot", minutes, 600, "gold"), unsafe_allow_html=True)
        st.markdown(progress_row("📘", "AI Learning", ai, 50, "blue"), unsafe_allow_html=True)
        st.markdown(progress_row("⌘", "Coding Practice", executions, 50, "green"), unsafe_allow_html=True)
        st.markdown(progress_row("📁", "Code Work", lines, 5000, "orange"), unsafe_allow_html=True)
    st.caption(f"Tracked locally: {minutes} min active · {ai} AI interactions · {executions} executions · {lines} lines processed · {len(usage.get('activity', []))} activities")
    section_card_end()

    left, right = st.columns([1.25, .9])
    with left:
        section_card_start()
        st.markdown("<div class='section-title'>◷ &nbsp; Recent Activity <small>Saved locally</small></div>", unsafe_allow_html=True)
        activities = usage.get("activity", [])[:6]
        if not activities:
            st.markdown("<div class='empty-state'>No activity yet. Open a page, ask AI or run code.</div>", unsafe_allow_html=True)
        for item in activities:
            st.markdown(f"<div class='activity-row'><i>◷</i><div><b>{html.escape(item.get('label',''))}</b><span>{html.escape(item.get('detail',''))}</span></div><time>{html.escape(item.get('time',''))}</time></div>", unsafe_allow_html=True)
        section_card_end()
    with right:
        section_card_start()
        st.markdown("<div class='section-title'>▥ &nbsp; Workspace Summary</div>", unsafe_allow_html=True)
        for icon, label, value in [
            ("◷", "Total active time", f"{total_min} min"),
            ("▱", "Sessions", usage.get("sessions", 0)),
            ("◯", "Questions asked", usage.get("questions", 0)),
            ("✓", "Successful runs", usage.get("successful_runs", 0)),
        ]:
            st.markdown(f"<div class='summary-row'><i>{icon}</i><span>{html.escape(label)}<b>{html.escape(str(value))}</b></span></div>", unsafe_allow_html=True)
        section_card_end()


def render_activity() -> None:
    page_header("Recent Activity", "Your latest CodePilot actions in this session.", "◷")
    activities = st.session_state.usage.get("activity", [])
    if not activities:
        st.markdown("<div class='empty-state big'>No activity recorded yet. Start using CodePilot and your actions will appear here.</div>", unsafe_allow_html=True)
    for item in activities:
        st.markdown(
            f"<div class='activity-card'><i>◷</i><div><b>{html.escape(item.get('label','Opened page'))}</b><span>{html.escape(item.get('detail',''))}</span></div><time>◷ &nbsp; {html.escape(item.get('time',''))} &nbsp; ❯</time></div>",
            unsafe_allow_html=True,
        )

# ------------------------- settings -------------------------
def render_settings() -> None:
    page_header("Settings", "Local configuration for the CodePilot AI workspace.", "⚙")
    settings = active_settings()

    section_card_start()
    st.markdown("### 🔗 Ollama host")
    ollama_host = st.text_input("Ollama server URL", value=str(settings.get("ollama_host", "http://127.0.0.1:11434")), key="setting_ollama_host")
    section_card_end()

    section_card_start()
    st.markdown("### 🧊 Ollama model")
    temp_settings = dict(settings)
    temp_settings["ollama_host"] = ollama_host
    models = list_ollama_models(temp_settings, timeout=1.0)
    current_model = str(settings.get("ollama_model", "qwen2.5-coder:7b"))
    if current_model not in models:
        models = [current_model] + models
    if models:
        ollama_model = st.selectbox("Local model", models, index=models.index(current_model), key="setting_ollama_model")
    else:
        ollama_model = st.text_input("Local model", value=current_model, key="setting_ollama_model_text")
    section_card_end()

    section_card_start()
    use_rag = st.toggle("Use local RAG knowledge", value=bool(settings.get("use_rag", True)), key="setting_use_rag", help="Retrieve local ChromaDB programming notes before AI coding answers.")
    cloud_enabled = st.toggle("Cloud AI APIs", value=bool(settings.get("cloud_enabled", False)), key="setting_cloud_enabled", help="OFF uses Ollama. ON uses the selected cloud provider.")
    section_card_end()

    cloud_provider = str(settings.get("cloud_provider", "OpenAI"))
    openai_key = str(settings.get("openai_api_key", ""))
    gemini_key = str(settings.get("gemini_api_key", ""))
    groq_key = str(settings.get("groq_api_key", ""))
    openai_model = str(settings.get("openai_model", "gpt-5-mini"))
    gemini_model = str(settings.get("gemini_model", "gemini-2.5-flash"))
    groq_model = str(settings.get("groq_model", "llama-3.3-70b-versatile"))
    openai_base = str(settings.get("openai_base_url", "https://api.openai.com/v1"))
    groq_base = str(settings.get("groq_base_url", "https://api.groq.com/openai/v1"))

    if cloud_enabled:
        section_card_start("cloud-settings")
        cloud_provider = st.selectbox("Cloud provider", ["OpenAI", "Gemini", "Groq"], index=["OpenAI", "Gemini", "Groq"].index(cloud_provider if cloud_provider in ["OpenAI", "Gemini", "Groq"] else "OpenAI"), key="setting_provider")
        if cloud_provider == "OpenAI":
            openai_key = st.text_input("OpenAI / ChatGPT API key", value=openai_key, type="password", key="setting_openai_key")
            openai_model = st.text_input("OpenAI model", value=openai_model, key="setting_openai_model")
            openai_base = st.text_input("OpenAI API base URL", value=openai_base, key="setting_openai_base")
        elif cloud_provider == "Gemini":
            gemini_key = st.text_input("Google Gemini API key", value=gemini_key, type="password", key="setting_gemini_key")
            gemini_model = st.text_input("Gemini model", value=gemini_model, key="setting_gemini_model")
        else:
            groq_key = st.text_input("Groq API key", value=groq_key, type="password", key="setting_groq_key")
            groq_model = st.text_input("Groq model", value=groq_model, key="setting_groq_model")
            groq_base = st.text_input("Groq API base URL", value=groq_base, key="setting_groq_base")
        section_card_end()

    section_card_start()
    remember = st.checkbox("Remember API keys locally in data/settings.json", value=bool(settings.get("remember_api_keys", True)), key="setting_remember_keys")
    st.caption("For a shared/cloud deployment, prefer environment secrets instead of saving API keys in the project folder.")
    section_card_end()

    candidate = dict(settings)
    candidate.update({
        "ollama_host": ollama_host.strip().rstrip("/"),
        "ollama_model": ollama_model.strip(),
        "use_rag": use_rag,
        "cloud_enabled": cloud_enabled,
        "cloud_provider": cloud_provider,
        "remember_api_keys": remember,
        "openai_api_key": openai_key.strip(),
        "openai_model": openai_model.strip(),
        "openai_base_url": openai_base.strip().rstrip("/"),
        "gemini_api_key": gemini_key.strip(),
        "gemini_model": gemini_model.strip(),
        "groq_api_key": groq_key.strip(),
        "groq_model": groq_model.strip(),
        "groq_base_url": groq_base.strip().rstrip("/"),
    })

    c1, c2 = st.columns(2)
    with c1:
        if st.button("💾 Save Settings", key="save_settings", type="primary", use_container_width=True):
            save_settings(candidate)
            st.session_state.settings = load_settings()
            add_activity("Updated settings", f"Active provider: {active_provider(st.session_state.settings)}")
            st.success("Settings saved.")
            st.rerun()
    with c2:
        if st.button("🔌 Test Active AI Connection", key="test_provider", use_container_width=True):
            ok, message = provider_status(candidate, live=True)
            if ok:
                st.success(message)
            else:
                st.error(message)

    active = active_provider(candidate)
    model = active_model(candidate)
    st.markdown(f"<div class='info-banner'>ⓘ &nbsp; Active after save: <b>{html.escape(active)}</b> · {html.escape(model)}. Local RAG: <b>{'ON' if use_rag else 'OFF'}</b></div>", unsafe_allow_html=True)

    with st.expander("Reset workspace progress / activity"):
        st.warning("This clears Dashboard statistics, Recent Activity, current Home chat, and AI Mentor chat. Your account and API settings are kept.")
        if st.button("Reset workspace now", key="reset_workspace"):
            reset_workspace_usage()
            st.success("Workspace progress reset.")
            st.rerun()

# ------------------------- about -------------------------
def render_about() -> None:
    page_header("About CodePilot AI", "A personal, local-first GenAI + RAG coding mentor.", "ⓘ")
    section_card_start()
    st.markdown(
        """
        ### 🤖 Overview
        CodePilot AI is a personal coding mentor that can run through a **local Ollama model** or a selected **cloud AI provider**. It combines AI guidance, local Retrieval-Augmented Generation (RAG), code execution, debugging, explanations, refactoring, test generation and code conversion in one workspace.
        """
    )
    section_card_end()
    a, b = st.columns(2)
    with a:
        section_card_start()
        st.markdown("### 🧱 Tech Stack")
        st.markdown("`Streamlit` · `Python` · `ChromaDB` · `Ollama` · `OpenAI` · `Gemini` · `Groq`")
        section_card_end()
    with b:
        section_card_start("privacy-card")
        st.markdown("### 🛡️ Privacy Model")
        st.markdown("- Local Ollama prompts remain on your machine.\n- RAG knowledge is stored locally in ChromaDB.\n- Cloud prompts are sent only when Cloud AI APIs are enabled.\n- API keys can be provided through environment variables or saved locally by choice.")
        section_card_end()
    section_card_start()
    st.markdown("### 🗄️ RAG (Retrieval-Augmented Generation)")
    st.markdown("Programming notes in `backend/knowledge/` are indexed into ChromaDB. When RAG is enabled, relevant notes are retrieved before coding answers are generated.")
    c1, c2, c3 = st.columns(3)
    c1.markdown("**1. Store Notes**  \nLocal programming notes → ChromaDB")
    c2.markdown("**2. Retrieve Context**  \nRelevant notes are fetched for the query")
    c3.markdown("**3. Generate Answer**  \nThe selected AI provider uses that context")
    section_card_end()

# ------------------------- routing -------------------------
PAGES = {
    "Home": render_home,
    "Chat (AI Mentor)": render_chat,
    "Compiler / Run Code": render_compiler,
    "Debug & Fix": render_debug,
    "Explain Code": render_explain,
    "Improve Code": render_improve,
    "Generate Tests": render_generate_tests,
    "Convert Code": render_convert,
    "Dashboard": render_dashboard,
    "Recent Activity": render_activity,
    "Settings": render_settings,
    "About": render_about,
}

if st.session_state.get("_last_page") != st.session_state.page:
    previous = st.session_state.get("_last_page")
    st.session_state._last_page = st.session_state.page
    st.session_state.usage["pages_visited"] = int(st.session_state.usage.get("pages_visited", 0)) + 1
    save_usage(st.session_state.usage)
    if previous is not None and previous != st.session_state.page:
        add_activity("Opened page", st.session_state.page)

PAGES.get(st.session_state.page, render_home)()
track_active_time()
st.markdown("<div class='app-footer'>CodePilot AI · Ollama / Cloud AI · Local RAG · ChromaDB · Streamlit</div>", unsafe_allow_html=True)
