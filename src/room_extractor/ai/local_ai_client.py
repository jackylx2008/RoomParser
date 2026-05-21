from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LocalAiConfig:
    """OpenAI-compatible local AI endpoint settings."""

    base_url: str = "http://127.0.0.1:8080/v1"
    model: str = "local-model"
    timeout_seconds: int = 120
    max_tokens: int = 384
    temperature: float = 0.0

    @classmethod
    def from_env(cls, env_file: str | Path = "common.env") -> "LocalAiConfig":
        values = _read_env_file(Path(env_file))
        merged = {**values, **os.environ}
        return cls(
            base_url=merged.get("LLAMACPP_BASE_URL", cls.base_url).rstrip("/"),
            model=merged.get("LLAMACPP_MODEL", cls.model),
            timeout_seconds=int(merged.get("LLAMACPP_TIMEOUT_SECONDS", cls.timeout_seconds)),
            max_tokens=int(merged.get("LLAMACPP_MAX_TOKENS", cls.max_tokens)),
            temperature=float(merged.get("LLAMACPP_TEMPERATURE", cls.temperature)),
        )


class LocalAiClient:
    """Small OpenAI-compatible HTTP client used by room image checks."""

    def __init__(self, config: LocalAiConfig) -> None:
        self.config = config

    def chat_with_image(self, prompt: str, image_path: str | Path) -> dict[str, Any]:
        image_data = _image_data_url(Path(image_path))
        payload = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_data}},
                    ],
                }
            ],
        }
        return self._post_json("/chat/completions", payload)

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.config.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Local AI request failed: {exc}") from exc


def _image_data_url(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Review image not found: {path}")
    mime_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values
