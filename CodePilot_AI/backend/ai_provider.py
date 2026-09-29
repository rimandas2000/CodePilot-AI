"""Unified AI provider layer for CodePilot AI.

Supports:
- Local Ollama
- OpenAI-compatible ChatGPT API
- Google Gemini API
- Groq (OpenAI-compatible)

The UI selects one active provider in Settings. RAG remains local and can be
used with any provider by adding retrieved context to the prompt before this
module is called.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib import error, parse, request

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
SETTINGS_FILE = DATA_DIR / "settings.json"

DEFAULT_SETTINGS: dict[str, Any] = {
    "ollama_host": os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434"),
    "ollama_model": os.getenv("OLLAMA_MODEL", "qwen2.5-coder:7b"),
    "use_rag": True,
    "cloud_enabled": False,
    "cloud_provider": os.getenv("CLOUD_PROVIDER", "OpenAI"),
    "remember_api_keys": True,
    "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
    "openai_model": os.getenv("OPENAI_MODEL", "gpt-5-mini"),
    "openai_base_url": os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
    "gemini_api_key": os.getenv("GEMINI_API_KEY", ""),
    "gemini_model": os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
    "groq_api_key": os.getenv("GROQ_API_KEY", ""),
    "groq_model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
    "groq_base_url": os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
}


def load_settings() -> dict[str, Any]:
    settings = dict(DEFAULT_SETTINGS)
    try:
        if SETTINGS_FILE.exists():
            saved = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                settings.update(saved)
    except Exception:
        pass
    # Environment variables take precedence when explicitly supplied. This
    # lets users keep secrets out of settings.json if they prefer.
    env_map = {
        "OLLAMA_HOST": "ollama_host",
        "OLLAMA_MODEL": "ollama_model",
        "OPENAI_API_KEY": "openai_api_key",
        "OPENAI_MODEL": "openai_model",
        "OPENAI_BASE_URL": "openai_base_url",
        "GEMINI_API_KEY": "gemini_api_key",
        "GEMINI_MODEL": "gemini_model",
        "GROQ_API_KEY": "groq_api_key",
        "GROQ_MODEL": "groq_model",
        "GROQ_BASE_URL": "groq_base_url",
    }
    for env_name, key in env_map.items():
        if os.getenv(env_name):
            settings[key] = os.getenv(env_name)
    return settings


def save_settings(settings: dict[str, Any]) -> None:
    payload = dict(DEFAULT_SETTINGS)
    payload.update(settings)
    if not payload.get("remember_api_keys", True):
        for key in ("openai_api_key", "gemini_api_key", "groq_api_key"):
            payload[key] = ""
    tmp = SETTINGS_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_FILE)


def active_provider(settings: dict[str, Any]) -> str:
    if not settings.get("cloud_enabled", False):
        return "Ollama"
    provider = str(settings.get("cloud_provider", "OpenAI")).strip()
    return provider if provider in {"OpenAI", "Gemini", "Groq"} else "OpenAI"


def active_model(settings: dict[str, Any]) -> str:
    provider = active_provider(settings)
    if provider == "Ollama":
        return str(settings.get("ollama_model") or DEFAULT_SETTINGS["ollama_model"])
    if provider == "Gemini":
        return str(settings.get("gemini_model") or DEFAULT_SETTINGS["gemini_model"])
    if provider == "Groq":
        return str(settings.get("groq_model") or DEFAULT_SETTINGS["groq_model"])
    return str(settings.get("openai_model") or DEFAULT_SETTINGS["openai_model"])


def _read_json_response(req: request.Request, timeout: float) -> dict[str, Any]:
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw)
    except error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="ignore")
        try:
            parsed = json.loads(details)
            message = parsed.get("error", {}).get("message") or parsed.get("message") or details
        except Exception:
            message = details
        raise RuntimeError(f"HTTP {exc.code}: {str(message)[:700]}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Network connection failed: {exc.reason}") from exc
    except TimeoutError as exc:
        raise RuntimeError("The AI provider request timed out.") from exc


def list_ollama_models(settings: dict[str, Any], timeout: float = 2.0) -> list[str]:
    host = str(settings.get("ollama_host") or DEFAULT_SETTINGS["ollama_host"]).rstrip("/")
    req = request.Request(f"{host}/api/tags", method="GET")
    try:
        data = _read_json_response(req, timeout)
    except Exception:
        return []
    names = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
    return sorted(dict.fromkeys(names))


def provider_status(settings: dict[str, Any], live: bool = False) -> tuple[bool, str]:
    provider = active_provider(settings)
    model = active_model(settings)
    if provider == "Ollama":
        models = list_ollama_models(settings, timeout=2.0 if live else 0.8)
        if not models:
            return False, "Ollama offline"
        base = model.split(":", 1)[0]
        present = model in models or any(m.split(":", 1)[0] == base for m in models)
        return (present, f"{model} ready" if present else f"Pull {model}")
    key_name = {
        "OpenAI": "openai_api_key",
        "Gemini": "gemini_api_key",
        "Groq": "groq_api_key",
    }[provider]
    if not str(settings.get(key_name, "")).strip():
        return False, f"{provider} API key missing"
    if not live:
        return True, f"{provider} configured"
    try:
        result = generate_text(
            "Reply with exactly: OK",
            settings,
            system_prompt="You are a connection test. Follow the user's instruction exactly.",
            temperature=0,
            max_tokens=8,
            timeout=25,
        )
        return bool(result.strip()), f"{provider} connected"
    except Exception as exc:
        return False, str(exc)


def _ollama_generate(prompt: str, settings: dict[str, Any], system_prompt: str, temperature: float, max_tokens: int, timeout: float) -> str:
    host = str(settings.get("ollama_host") or DEFAULT_SETTINGS["ollama_host"]).rstrip("/")
    model = str(settings.get("ollama_model") or DEFAULT_SETTINGS["ollama_model"])
    full_prompt = f"{system_prompt.strip()}\n\n{prompt.strip()}" if system_prompt.strip() else prompt.strip()
    payload = {
        "model": model,
        "prompt": full_prompt,
        "stream": False,
        "options": {"temperature": float(temperature), "num_predict": int(max_tokens)},
    }
    req = request.Request(
        f"{host}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        data = _read_json_response(req, timeout)
    except RuntimeError as exc:
        raise RuntimeError(f"Ollama error: {exc}. Start Ollama and pull model '{model}'.") from exc
    answer = str(data.get("response", "")).strip()
    if not answer:
        raise RuntimeError("Ollama returned an empty response.")
    return answer


def _openai_compatible_generate(prompt: str, settings: dict[str, Any], provider: str, system_prompt: str, temperature: float, max_tokens: int, timeout: float) -> str:
    if provider == "Groq":
        key = str(settings.get("groq_api_key", "")).strip()
        model = str(settings.get("groq_model") or DEFAULT_SETTINGS["groq_model"])
        base_url = str(settings.get("groq_base_url") or DEFAULT_SETTINGS["groq_base_url"]).rstrip("/")
    else:
        key = str(settings.get("openai_api_key", "")).strip()
        model = str(settings.get("openai_model") or DEFAULT_SETTINGS["openai_model"])
        base_url = str(settings.get("openai_base_url") or DEFAULT_SETTINGS["openai_base_url"]).rstrip("/")
    if not key:
        raise RuntimeError(f"{provider} API key is missing. Add it in Settings.")
    messages = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    messages.append({"role": "user", "content": prompt.strip()})
    payload = {
        "model": model,
        "messages": messages,
        "temperature": float(temperature),
        "max_tokens": int(max_tokens),
    }

    def do_request(body: dict[str, Any]) -> dict[str, Any]:
        req = request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
            method="POST",
        )
        return _read_json_response(req, timeout)

    try:
        data = do_request(payload)
    except RuntimeError as exc:
        # Some newer OpenAI-compatible reasoning models use
        # max_completion_tokens and/or reject a custom temperature. Retry in
        # a broadly compatible form instead of making users edit code.
        message = str(exc).lower()
        if provider == "OpenAI" and ("max_tokens" in message or "temperature" in message or "unsupported" in message):
            retry_payload = {
                "model": model,
                "messages": messages,
                "max_completion_tokens": int(max_tokens),
            }
            data = do_request(retry_payload)
        else:
            raise
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError(f"{provider} returned no completion choices.")
    content = choices[0].get("message", {}).get("content", "")
    if isinstance(content, list):
        # Some OpenAI-compatible APIs can return content parts.
        content = "".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    answer = str(content).strip()
    if not answer:
        raise RuntimeError(f"{provider} returned an empty response.")
    return answer


def _gemini_generate(prompt: str, settings: dict[str, Any], system_prompt: str, temperature: float, max_tokens: int, timeout: float) -> str:
    key = str(settings.get("gemini_api_key", "")).strip()
    model = str(settings.get("gemini_model") or DEFAULT_SETTINGS["gemini_model"])
    if not key:
        raise RuntimeError("Gemini API key is missing. Add it in Settings.")
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{parse.quote(model, safe='-._')}:generateContent?key={parse.quote(key, safe='')}"
    )
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt.strip()}]}],
        "generationConfig": {
            "temperature": float(temperature),
            "maxOutputTokens": int(max_tokens),
        },
    }
    if system_prompt.strip():
        payload["systemInstruction"] = {"parts": [{"text": system_prompt.strip()}]}
    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    data = _read_json_response(req, timeout)
    candidates = data.get("candidates") or []
    if not candidates:
        feedback = data.get("promptFeedback")
        raise RuntimeError(f"Gemini returned no candidates. {feedback or ''}".strip())
    parts = candidates[0].get("content", {}).get("parts", [])
    answer = "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict)).strip()
    if not answer:
        raise RuntimeError("Gemini returned an empty response.")
    return answer


def generate_text(
    prompt: str,
    settings: dict[str, Any] | None = None,
    *,
    system_prompt: str = "",
    temperature: float = 0.2,
    max_tokens: int = 1800,
    timeout: float = 180,
) -> str:
    settings = settings or load_settings()
    provider = active_provider(settings)
    if provider == "Ollama":
        return _ollama_generate(prompt, settings, system_prompt, temperature, max_tokens, timeout)
    if provider == "Gemini":
        return _gemini_generate(prompt, settings, system_prompt, temperature, max_tokens, timeout)
    return _openai_compatible_generate(prompt, settings, provider, system_prompt, temperature, max_tokens, timeout)
