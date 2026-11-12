"""Azure OpenAI completion function for :class:`~.explain.LlmExplainer`.

It sends one system and one user message and nothing else: no ``tools``, no ``functions`` and no
``tool_choice``, so the model has no way to call anything. Network use happens only when the
returned function is called, which the CLI does for ``run --explain``; tests inject a fake client.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from ..config import ConfigError
from .explain import Completer

API_VERSION = "2024-10-21"
DEFAULT_DEPLOYMENT = "gpt-mini"
MAX_OUTPUT_TOKENS = 400
REQUEST_TIMEOUT_S = 25.0


class ChatClient(Protocol):
    @property
    def chat(self) -> Any: ...


def completer_from_env(env: Mapping[str, str], *, client: ChatClient | None = None) -> Completer:
    endpoint = env.get("AZURE_OPENAI_ENDPOINT", "").strip()
    api_key = env.get("AZURE_OPENAI_KEY", "").strip()
    deployment = env.get("AZURE_OPENAI_DEPLOYMENT", "").strip() or DEFAULT_DEPLOYMENT
    if client is None:
        if not endpoint or not api_key:
            raise ConfigError("--explain requires AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_KEY")
        try:
            from openai import AzureOpenAI
        except ImportError as exc:
            raise ConfigError(
                "--explain requires the 'openai' package: pip install -e \".[llm]\""
            ) from exc
        client = AzureOpenAI(
            azure_endpoint=endpoint,
            api_key=api_key,
            api_version=API_VERSION,
            timeout=REQUEST_TIMEOUT_S,
            max_retries=0,
        )
    chat_client = client

    def complete(system: str, user: str) -> str:
        response = chat_client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0,
            max_tokens=MAX_OUTPUT_TOKENS,
        )
        content = response.choices[0].message.content
        if not isinstance(content, str):
            raise ValueError("the model returned no text")
        return content

    return complete
