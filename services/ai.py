"""Provider-agnostic structured-JSON generation.

Every task (screenshot/text extraction, email drafting) describes its output as a JSON Schema and
calls `generate_json`. Providers are interchangeable and tried in order, so the app is never tied
to one model. Calls go over plain HTTPS with `requests`; no vendor SDKs are required.

Configuration (environment only; never sent to the browser):
    AI_PROVIDER      auto (default) | gemini | openai | ollama | none
    AI_API_KEY       key for the provider named in AI_PROVIDER (alternative to the per-provider key)
    AI_MODEL         model for the provider named in AI_PROVIDER
    GEMINI_API_KEY, GEMINI_MODEL, GEMINI_FALLBACK_MODEL
    OPENAI_API_KEY, OPENAI_MODEL, OPENAI_BASE_URL
    OLLAMA_URL, OLLAMA_MODEL, OLLAMA_VISION_MODEL
"""
import base64
import json
import logging
import os
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

AUTO_ORDER = ("gemini", "ollama", "openai")  # free tier first, then local, then paid


class AIUnavailable(Exception):
    """No provider could produce a valid response. The message is safe to show to users."""


class ProviderError(Exception):
    pass


@dataclass
class StructuredRequest:
    system: str
    prompt: str
    schema: dict
    schema_name: str
    image: Optional[bytes] = None
    image_mime: Optional[str] = None
    max_output_tokens: int = 4096


def _env(name, default=""):
    return (os.environ.get(name) or default).strip()


def _selected_provider():
    return _env("AI_PROVIDER", "auto").lower()


def _setting(provider, name, default=""):
    """Per-provider setting, falling back to the generic AI_* variable when that provider is selected."""
    value = _env(f"{provider.upper()}_{name}")
    if not value and _selected_provider() == provider:
        value = _env(f"AI_{name}")
    return value or default


def _parse_json(text, provider):
    if not text:
        raise ProviderError(f"{provider} returned an empty response")
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text[text.find("{"):]
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise ProviderError(f"{provider} returned invalid JSON") from exc
    if not isinstance(data, dict):
        raise ProviderError(f"{provider} returned JSON that is not an object")
    return data


def _post(url, provider, **kwargs):
    try:
        response = requests.post(url, **kwargs)
    except requests.RequestException as exc:
        raise ProviderError(f"{provider} request failed: {exc.__class__.__name__}") from exc
    if response.status_code >= 400:
        raise ProviderError(f"{provider} HTTP {response.status_code}: {response.text[:200]}")
    try:
        return response.json()
    except ValueError as exc:
        raise ProviderError(f"{provider} returned a non-JSON body") from exc


def to_gemini_schema(schema):
    """JSON Schema subset -> Gemini's OpenAPI-style responseSchema (uppercase types, `nullable`)."""
    result = {}
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        non_null = [t for t in schema_type if t != "null"]
        schema_type = non_null[0] if non_null else "string"
        result["nullable"] = True
    if schema_type:
        result["type"] = schema_type.upper()
    for key in ("description", "enum"):
        if key in schema:
            result[key] = schema[key]
    if "properties" in schema:
        result["properties"] = {name: to_gemini_schema(sub) for name, sub in schema["properties"].items()}
        result["required"] = list(schema.get("required", []))
        result["propertyOrdering"] = list(schema["properties"])
    if "items" in schema:
        result["items"] = to_gemini_schema(schema["items"])
    return result


class Provider:
    name = ""
    supports_vision = True

    def is_configured(self):
        raise NotImplementedError

    def can_handle(self, request):
        return self.is_configured() and (request.image is None or self.supports_vision)

    def generate_json(self, request):
        raise NotImplementedError


class GeminiProvider(Provider):
    name = "gemini"
    base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    def is_configured(self):
        return bool(_setting("gemini", "API_KEY"))

    def _call(self, model, request):
        parts = []
        if request.image is not None:
            parts.append({"inlineData": {"mimeType": request.image_mime, "data": base64.b64encode(request.image).decode("ascii")}})
        parts.append({"text": request.prompt})
        body = {
            "systemInstruction": {"parts": [{"text": request.system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": to_gemini_schema(request.schema),
                "temperature": 0.3,
                "maxOutputTokens": max(request.max_output_tokens, 8192),  # thinking tokens count here too
            },
        }
        payload = _post(
            f"{self.base_url}/{model}:generateContent",
            "Gemini",
            headers={"x-goog-api-key": _setting("gemini", "API_KEY")},
            json=body,
            timeout=(5, 60),
        )
        candidates = payload.get("candidates") or []
        if not candidates:
            reason = (payload.get("promptFeedback") or {}).get("blockReason", "no candidates")
            raise ProviderError(f"Gemini returned no answer ({reason})")
        parts = (candidates[0].get("content") or {}).get("parts") or []
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        return _parse_json(text, "Gemini")

    def generate_json(self, request):
        model = _setting("gemini", "MODEL", "gemini-flash-latest")
        fallback = _env("GEMINI_FALLBACK_MODEL", "gemini-flash-lite-latest")
        try:
            return self._call(model, request)
        except ProviderError as exc:
            # Free-tier models are often busy (429/503); the lighter model usually still answers.
            if fallback and fallback != model and any(code in str(exc) for code in ("429", "500", "503", "504")):
                logger.info("Gemini %s busy, retrying with %s", model, fallback)
                return self._call(fallback, request)
            raise


class OpenAIProvider(Provider):
    name = "openai"

    def is_configured(self):
        return bool(_setting("openai", "API_KEY"))

    def generate_json(self, request):
        content = [{"type": "text", "text": request.prompt}]
        if request.image is not None:
            data_url = f"data:{request.image_mime};base64,{base64.b64encode(request.image).decode('ascii')}"
            content.append({"type": "image_url", "image_url": {"url": data_url, "detail": "high"}})
        body = {
            "model": _setting("openai", "MODEL", "gpt-5-mini"),
            "messages": [{"role": "system", "content": request.system}, {"role": "user", "content": content}],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": request.schema_name, "strict": True, "schema": request.schema},
            },
            "max_completion_tokens": max(request.max_output_tokens, 6000),
        }
        base_url = _env("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        payload = _post(
            f"{base_url}/chat/completions",
            "OpenAI",
            headers={"Authorization": f"Bearer {_setting('openai', 'API_KEY')}"},
            json=body,
            timeout=(5, 90),
        )
        message = ((payload.get("choices") or [{}])[0]).get("message") or {}
        if message.get("refusal"):
            raise ProviderError("OpenAI refused the request")
        return _parse_json(message.get("content"), "OpenAI")


class OllamaProvider(Provider):
    """Local models. Text-only unless OLLAMA_VISION_MODEL (e.g. llama3.2-vision) is set."""

    name = "ollama"

    @property
    def supports_vision(self):
        return bool(_env("OLLAMA_VISION_MODEL"))

    def is_configured(self):
        # Opt-in: probing a local server that isn't running costs ~2 s per request on Windows.
        return bool(_env("OLLAMA_URL") or _env("OLLAMA_MODEL") or _env("OLLAMA_VISION_MODEL") or _selected_provider() == "ollama")

    def _base_url(self):
        url = _env("OLLAMA_URL", "http://localhost:11434").rstrip("/")
        for suffix in ("/api/generate", "/api/chat"):
            if url.endswith(suffix):
                url = url[: -len(suffix)]
        return url

    def generate_json(self, request):
        user_message = {"role": "user", "content": request.prompt}
        model = _setting("ollama", "MODEL", "llama3.1")
        if request.image is not None:
            user_message["images"] = [base64.b64encode(request.image).decode("ascii")]
            model = _env("OLLAMA_VISION_MODEL")
        payload = _post(
            f"{self._base_url()}/api/chat",
            "Ollama",
            json={
                "model": model,
                "messages": [{"role": "system", "content": request.system}, user_message],
                "format": request.schema,
                "stream": False,
                "options": {"temperature": 0.3},
            },
            timeout=(2, 120),
        )
        return _parse_json((payload.get("message") or {}).get("content"), "Ollama")


PROVIDERS = {provider.name: provider for provider in (GeminiProvider(), OpenAIProvider(), OllamaProvider())}


def provider_chain():
    selected = _selected_provider()
    if selected == "none":
        return []
    if selected in PROVIDERS:
        return [PROVIDERS[selected]]
    return [PROVIDERS[name] for name in AUTO_ORDER]


def is_available(require_vision=False):
    return any(p.is_configured() and (p.supports_vision or not require_vision) for p in provider_chain())


def generate_json(request):
    """Returns (data, provider_name). Raises AIUnavailable when every provider fails."""
    candidates = [provider for provider in provider_chain() if provider.can_handle(request)]
    if not candidates:
        raise AIUnavailable("AI generation is not configured.")
    for provider in candidates:
        try:
            return provider.generate_json(request), provider.name
        except ProviderError as exc:
            logger.warning("AI provider %s failed: %s", provider.name, exc)
    raise AIUnavailable("AI generation is temporarily unavailable.")
