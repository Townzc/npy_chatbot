"""Text generation providers have no channel, shell or recipient capability."""

import asyncio
import os
from typing import Protocol
from urllib.parse import urlparse

import httpx

from chattwin.domain import DomainError, GenerationRequest, GenerationResult


class ModelProvider(Protocol):
    name: str
    remote: bool

    async def generate(self, request: GenerationRequest) -> GenerationResult: ...


class MockProvider:
    name = "mock-v1"
    remote = False

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        await asyncio.sleep(0)
        prompt = request.messages[-1]["content"]
        return GenerationResult(
            text=f"【虚构演示】收到：{prompt[:160]}。一起慢慢聊～", model=self.name, synthetic=True
        )


class HTTPProvider:
    """OpenAI-shaped HTTP protocol, explicitly configured; no implicit paid requests."""

    remote = True

    def __init__(
        self, base_url: str, model: str, api_key: str, *, max_calls: int = 100, transport=None
    ):
        self.base_url, self.model, self.api_key = base_url.rstrip("/"), model, api_key
        self.name = f"http:{model}"
        self.remote = urlparse(base_url).hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
            "testserver",
        }
        self.remaining = max_calls
        self.lock = asyncio.Lock()
        self.transport = transport

    async def generate(self, request: GenerationRequest) -> GenerationResult:
        if sum(len(m["content"]) for m in request.messages) > 24000:
            raise DomainError("CONTEXT_LIMIT", "Input exceeds the configured context budget", 422)
        async with self.lock:
            if self.remaining <= 0:
                raise DomainError("BUDGET_EXHAUSTED", "Process request budget exhausted", 429)
            self.remaining -= 1
        try:
            async with httpx.AsyncClient(
                timeout=30, transport=self.transport, follow_redirects=False
            ) as client:
                response = await client.post(
                    self.base_url + "/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
                    json={
                        "model": self.model,
                        "messages": request.messages,
                        "max_tokens": request.max_tokens,
                        "stream": False,
                        **(
                            {"temperature": request.temperature}
                            if request.temperature is not None
                            else {}
                        ),
                        "metadata": {
                            "persona_id": request.persona_id,
                            "relationship_id": request.relationship_id,
                        },
                    },
                )
                response.raise_for_status()
                data = response.json()
            text = data["choices"][0]["message"]["content"]
            if isinstance(text, str) and not text.strip():
                raise DomainError(
                    "MODEL_EMPTY_RESPONSE",
                    "模型返回了空文本，未取得有效回复。请检查模型、adapter 和生成参数后重新测试。",
                    503,
                )
            if not isinstance(text, str) or len(text) > 4000:
                raise ValueError("invalid text")
            usage = data.get("usage") or {}
            if not isinstance(usage, dict):
                raise ValueError("invalid token usage")
            return GenerationResult(
                text=text,
                model=self.name,
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
                usage_reported="prompt_tokens" in usage and "completion_tokens" in usage,
                synthetic=data.get("chattwin_evidence") == "tiny_cpu_smoke",
            )
        except (httpx.HTTPError, KeyError, ValueError, TypeError, IndexError) as exc:
            # Never log response bodies: they may include private context or credentials.
            raise DomainError(
                "MODEL_UNAVAILABLE", "Model request failed or returned an invalid response", 503
            ) from exc


def configured_provider() -> ModelProvider:
    if os.environ.get("CHATTWIN_MODEL_URL"):
        if not os.environ.get("CHATTWIN_MODEL_NAME"):
            raise ValueError("CHATTWIN_MODEL_NAME is required for HTTP model")
        return HTTPProvider(
            os.environ["CHATTWIN_MODEL_URL"],
            os.environ["CHATTWIN_MODEL_NAME"],
            os.environ.get("CHATTWIN_MODEL_KEY", ""),
            max_calls=int(os.environ.get("CHATTWIN_MODEL_MAX_CALLS", "100")),
        )
    return MockProvider()
