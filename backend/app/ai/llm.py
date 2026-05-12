from __future__ import annotations

import base64
import json
import logging
import time
import uuid
from typing import Any, Protocol

import httpx
from openai import AsyncOpenAI

from app.ai.json_llm import parse_command_batch_lenient
from app.ai.prompt import JSON_OUTPUT_SUFFIX, SYSTEM_PROMPT
from app.config import get_settings
from app.core.commands import CommandBatch
from app.core.engine import mock_command_batch, plan_for_prompt
from app.core.models import ProjectPlan

log = logging.getLogger(__name__)

# A chat history turn: {"user": raw_user_text, "assistant": summary_text}
ChatTurn = dict[str, str]


class LLMClient(Protocol):
    async def generate_command_batch(
        self,
        user_message: str,
        plan: ProjectPlan,
        history: list[ChatTurn] | None = None,
        extra_system_suffix: str = "",
    ) -> CommandBatch: ...


def _current_user_payload(user_message: str, plan: ProjectPlan, max_tasks: int) -> str:
    """The payload for the *current* turn: plan JSON + user request + output instructions."""
    ctx = plan_for_prompt(plan, max_tasks)
    return f"Current plan JSON:\n{ctx}\n\nUser request:\n{user_message}{JSON_OUTPUT_SUFFIX}"


def _build_openai_messages(
    user_message: str,
    plan: ProjectPlan,
    max_tasks: int,
    history: list[ChatTurn] | None,
    extra_system_suffix: str = "",
) -> list[dict[str, str]]:
    sys_content = SYSTEM_PROMPT + (extra_system_suffix or "")
    msgs: list[dict[str, str]] = [{"role": "system", "content": sys_content}]
    for turn in (history or []):
        msgs.append({"role": "user", "content": turn["user"]})
        msgs.append({"role": "assistant", "content": turn["assistant"]})
    msgs.append({"role": "user", "content": _current_user_payload(user_message, plan, max_tasks)})
    return msgs


def _build_yandex_messages(
    user_message: str,
    plan: ProjectPlan,
    max_tasks: int,
    history: list[ChatTurn] | None,
    extra_system_suffix: str = "",
) -> list[dict[str, str]]:
    sys_text = SYSTEM_PROMPT + (extra_system_suffix or "")
    msgs: list[dict[str, str]] = [{"role": "system", "text": sys_text}]
    for turn in (history or []):
        msgs.append({"role": "user", "text": turn["user"]})
        msgs.append({"role": "assistant", "text": turn["assistant"]})
    msgs.append({"role": "user", "text": _current_user_payload(user_message, plan, max_tasks)})
    return msgs


class OpenAIClient:
    def __init__(self) -> None:
        s = get_settings()
        self._model = s.llm_model or "gpt-4o-mini"
        self._client = AsyncOpenAI(api_key=s.openai_api_key or None, timeout=s.llm_request_timeout_seconds)
        self._max_tasks = s.max_tasks_in_prompt

    async def generate_command_batch(
        self,
        user_message: str,
        plan: ProjectPlan,
        history: list[ChatTurn] | None = None,
        extra_system_suffix: str = "",
    ) -> CommandBatch:
        msgs = _build_openai_messages(
            user_message, plan, self._max_tasks, history, extra_system_suffix
        )
        completion = await self._client.beta.chat.completions.parse(
            model=self._model,
            messages=msgs,  # type: ignore[arg-type]
            response_format=CommandBatch,
        )
        choice = completion.choices[0]
        parsed = choice.message.parsed
        if parsed is None:
            raise RuntimeError("OpenAI returned no parsed CommandBatch")
        if completion.usage:
            log.info("OpenAI usage: %s", completion.usage.model_dump())
        return parsed


class GeminiClient:
    def __init__(self) -> None:
        from google import genai

        s = get_settings()
        self._model = s.llm_model or "gemini-1.5-flash"
        key = s.gemini_api_key
        if not key:
            raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        self._client = genai.Client(api_key=key)
        self._max_tasks = s.max_tasks_in_prompt
        self._timeout = s.llm_request_timeout_seconds

    async def generate_command_batch(
        self,
        user_message: str,
        plan: ProjectPlan,
        history: list[ChatTurn] | None = None,
        extra_system_suffix: str = "",
    ) -> CommandBatch:
        import asyncio

        # Gemini flat-text: prepend history as Q/A pairs
        history_text = ""
        for turn in (history or []):
            history_text += f"\nPrevious user request: {turn['user']}\nAssistant response: {turn['assistant']}\n"

        prompt = (
            f"{SYSTEM_PROMPT}{extra_system_suffix or ''}{history_text}\n\n"
            f"{_current_user_payload(user_message, plan, self._max_tasks)}"
        )

        def _call() -> str:
            resp = self._client.models.generate_content(
                model=self._model,
                contents=prompt,
                config={"response_mime_type": "application/json"},
            )
            return (resp.text or "{}").strip()

        raw = await asyncio.wait_for(asyncio.to_thread(_call), timeout=self._timeout)
        return parse_command_batch_lenient(raw)


def _folder_from_model_uri(uri: str) -> str | None:
    if uri.startswith("gpt://"):
        rest = uri[6:]
        part = rest.split("/", 1)[0].strip()
        return part or None
    return None


class YandexGPTClient:
    """Yandex Cloud Foundation Models (works from Render with Api-Key + folder)."""

    def __init__(self) -> None:
        s = get_settings()
        if not s.yandex_api_key:
            raise ValueError("YANDEX_API_KEY is required when LLM_PROVIDER=yandex")
        self._api_key = s.yandex_api_key.strip()
        self._url = s.yandex_completion_url
        model_uri = (s.yandex_model_uri or "").strip()
        folder = (s.yandex_folder_id or "").strip()
        if not model_uri and folder:
            model_uri = f"gpt://{folder}/yandexgpt/latest"
        if not model_uri:
            raise ValueError("Set YANDEX_FOLDER_ID or YANDEX_MODEL_URI when LLM_PROVIDER=yandex")
        if not folder:
            folder = _folder_from_model_uri(model_uri) or ""
        if not folder:
            raise ValueError("Could not determine folder id: set YANDEX_FOLDER_ID explicitly")
        self._model_uri = model_uri
        self._folder_id = folder
        self._max_tasks = s.max_tasks_in_prompt
        self._timeout = s.llm_request_timeout_seconds

    def _headers(self) -> dict[str, str]:
        key = self._api_key
        auth = key if key.lower().startswith("api-key ") else f"Api-Key {key}"
        return {
            "Authorization": auth,
            "Content-Type": "application/json",
            "x-folder-id": self._folder_id,
        }

    async def generate_command_batch(
        self,
        user_message: str,
        plan: ProjectPlan,
        history: list[ChatTurn] | None = None,
        extra_system_suffix: str = "",
    ) -> CommandBatch:
        msgs = _build_yandex_messages(
            user_message, plan, self._max_tasks, history, extra_system_suffix
        )
        body: dict[str, Any] = {
            "modelUri": self._model_uri,
            "completionOptions": {
                "stream": False,
                "temperature": 0.2,
                "maxTokens": "4000",
            },
            "messages": msgs,
        }
        async with httpx.AsyncClient(timeout=float(self._timeout)) as client:
            r = await client.post(self._url, headers=self._headers(), json=body)
            if r.status_code >= 400:
                log.warning("Yandex error body: %s", r.text[:2000])
            r.raise_for_status()
            data = r.json()
        alts = data.get("result", {}).get("alternatives") or []
        if not alts:
            raise RuntimeError(f"Yandex empty response: {json.dumps(data)[:500]}")
        text = (alts[0].get("message") or {}).get("text") or ""
        preview = (text[:800] + "…") if len(text) > 800 else text
        log.info("Yandex completion text preview: %s", preview.replace("\n", " "))
        batch = parse_command_batch_lenient(text)
        log.info(
            "Yandex parsed CommandBatch: %s",
            batch.model_dump(mode="json", exclude_none=True),
        )
        return batch


_giga_token: str | None = None
_giga_expires: float = 0.0


class GigaChatClient:
    """Sber GigaChat OAuth + chat/completions (OpenAI-like)."""

    def __init__(self) -> None:
        s = get_settings()
        if not s.gigachat_client_id or not s.gigachat_client_secret:
            raise ValueError(
                "GIGACHAT_CLIENT_ID and GIGACHAT_CLIENT_SECRET required when LLM_PROVIDER=gigachat"
            )
        self._client_id = s.gigachat_client_id.strip()
        self._client_secret = s.gigachat_client_secret.strip()
        self._oauth_url = s.gigachat_oauth_url
        self._api_url = s.gigachat_api_url
        self._model = (get_settings().llm_model or "GigaChat").strip()
        self._max_tasks = s.max_tasks_in_prompt
        self._timeout = s.llm_request_timeout_seconds

    async def _access_token(self, client: httpx.AsyncClient) -> str:
        global _giga_token, _giga_expires
        now = time.time()
        if _giga_token and now < _giga_expires - 120:
            return _giga_token
        basic = base64.b64encode(f"{self._client_id}:{self._client_secret}".encode()).decode()
        headers = {
            "Authorization": f"Basic {basic}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
        }
        r = await client.post(
            self._oauth_url,
            headers=headers,
            data={"scope": "GIGACHAT_API_PERS"},
        )
        r.raise_for_status()
        data = r.json()
        _giga_token = data["access_token"]
        exp_in = data.get("expires_in")
        _giga_expires = now + (float(exp_in) if isinstance(exp_in, (int, float)) and exp_in > 0 else 1700.0)
        return _giga_token

    async def generate_command_batch(
        self,
        user_message: str,
        plan: ProjectPlan,
        history: list[ChatTurn] | None = None,
        extra_system_suffix: str = "",
    ) -> CommandBatch:
        msgs = _build_openai_messages(
            user_message, plan, self._max_tasks, history, extra_system_suffix
        )
        async with httpx.AsyncClient(timeout=float(self._timeout)) as client:
            token = await self._access_token(client)
            payload: dict[str, Any] = {
                "model": self._model,
                "messages": msgs,
                "temperature": 0.2,
            }
            r = await client.post(
                self._api_url,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"GigaChat empty choices: {json.dumps(data)[:500]}")
        content = choices[0].get("message", {}).get("content") or ""
        prev = (content[:800] + "…") if len(content) > 800 else content
        log.info("GigaChat message preview: %s", prev.replace("\n", " "))
        batch = parse_command_batch_lenient(content)
        log.info("GigaChat parsed CommandBatch: %s", batch.model_dump(mode="json", exclude_none=True))
        return batch


class MockClient:
    async def generate_command_batch(
        self,
        user_message: str,
        plan: ProjectPlan,
        history: list[ChatTurn] | None = None,
        extra_system_suffix: str = "",
    ) -> CommandBatch:
        _ = extra_system_suffix  # few-shot not used in deterministic mock
        cmds, summary = mock_command_batch(user_message, plan)
        return CommandBatch(commands=cmds, summary=summary)


def get_llm() -> LLMClient:
    s = get_settings()
    p = (s.llm_provider or "openai").lower().strip()
    if p == "mock":
        return MockClient()
    if p == "gemini":
        return GeminiClient()
    if p == "openai":
        return OpenAIClient()
    if p == "yandex":
        return YandexGPTClient()
    if p == "gigachat":
        return GigaChatClient()
    raise ValueError(f"Unknown LLM_PROVIDER: {p!r} (use openai|gemini|yandex|gigachat|mock)")
