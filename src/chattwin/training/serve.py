"""Authenticated, scope-bound adapter inference. No channel or control credentials."""

from __future__ import annotations

import argparse
import json
import os
import secrets
import threading
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .spec import sha256_file, validate_scope
from .worker import _imports, load_base, verify_artifact


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["system", "user", "assistant"]
    content: str = Field(max_length=16000)


class InferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = "chattwin-adapter"
    messages: list[ChatMessage] = Field(min_length=1, max_length=100)
    max_tokens: int = Field(default=128, ge=1, le=1024)
    metadata: dict[str, str]
    stream: Literal[False] = False
    temperature: float = Field(default=0, ge=0, le=2)


def create_inference_app(artifact: Path, token: str) -> FastAPI:
    if len(token) < 32:
        raise ValueError("use a separate model endpoint token of at least 32 characters")
    if json.loads((artifact / "status.json").read_text()).get("status") != "succeeded":
        raise ValueError("only a successful, reloaded artifact may be served")
    spec, manifest = verify_artifact(artifact)
    manifest_hash = sha256_file(artifact / "manifest.json")
    torch, base, tokenizer = load_base(spec)
    _, _, peft_model, _, _, _ = _imports()
    model = peft_model.from_pretrained(base, artifact / "adapter", is_trainable=False)
    model.eval()
    app = FastAPI(title="ChatTwin private adapter inference", docs_url=None, redoc_url=None)
    generation_lock = threading.Lock()

    def authenticate(authorization: str | None) -> None:
        if authorization is None or not secrets.compare_digest(
            authorization.encode(), ("Bearer " + token).encode()
        ):
            raise HTTPException(401, "model endpoint authentication required")

    @app.get("/health")
    def health(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        authenticate(authorization)
        return {
            "status": "ready",
            "model": "chattwin-adapter",
            "evidence": manifest["evidence"],
            "persona_id": manifest["persona_id"],
            "relationship_id": manifest["relationship_id"],
            "artifact_manifest_hash": manifest_hash,
            "base_model_id": spec.base_model_id,
            "base_model_revision": spec.base_model_revision,
            "tokenizer_revision": spec.tokenizer_revision,
            "chat_template_hash": spec.chat_template_hash,
            "models": ["chattwin-base", "chattwin-adapter"],
        }

    @app.post("/v1/chat/completions")
    def generate(
        body: InferenceRequest, authorization: str | None = Header(default=None)
    ) -> dict[str, Any]:
        authenticate(authorization)
        try:
            validate_scope(
                manifest,
                body.metadata.get("persona_id", ""),
                body.metadata.get("relationship_id", ""),
            )
        except ValueError as exc:
            raise HTTPException(403, str(exc)) from exc
        if body.model not in {"chattwin-adapter", "chattwin-base"}:
            raise HTTPException(400, "unknown model deployment")
        messages = [message.model_dump() for message in body.messages]
        ids = tokenizer.apply_chat_template(messages, tokenize=True, add_generation_prompt=True)
        if len(ids) + body.max_tokens > spec.max_sequence_length:
            raise HTTPException(413, "context exceeds this deployment's validated token budget")
        if not generation_lock.acquire(blocking=False):
            raise HTTPException(429, "model busy")
        try:
            with (
                torch.inference_mode(),
                model.disable_adapter() if body.model == "chattwin-base" else nullcontext(),
            ):
                inputs = torch.tensor([ids], device=spec.device)
                kwargs: dict[str, Any] = {"do_sample": body.temperature > 0}
                if body.temperature > 0:
                    kwargs["temperature"] = body.temperature
                output = model.generate(
                    input_ids=inputs,
                    max_new_tokens=body.max_tokens,
                    pad_token_id=tokenizer.pad_token_id,
                    **kwargs,
                )
            generated = output[0, len(ids) :]
            return {
                "object": "chat.completion",
                "chattwin_evidence": manifest["evidence"],
                "model": body.model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": tokenizer.decode(generated, skip_special_tokens=True),
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": len(ids),
                    "completion_tokens": len(generated),
                    "total_tokens": len(ids) + len(generated),
                },
            }
        finally:
            generation_lock.release()

    return app


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    token = os.environ.get("CHATTWIN_MODEL_TOKEN", "")
    uvicorn.run(
        create_inference_app(args.artifact.resolve(), token), host="127.0.0.1", port=args.port
    )


if __name__ == "__main__":
    main()
