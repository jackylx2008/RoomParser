from __future__ import annotations

import base64
import json
import os
import subprocess
import time
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
    api_key: str = ""
    timeout_seconds: int = 120
    max_tokens: int = 384
    temperature: float = 0.0
    autostart: bool = False
    server_path: str = ""
    model_path: str = ""
    mmproj_path: str = ""
    extra_dll_dirs: str = ""
    n_gpu_layers: int = 999
    ctx_size: int = 8192
    reasoning: str = "off"
    reasoning_budget: int = 0
    startup_timeout_seconds: int = 180
    startup_poll_interval_seconds: float = 1.0
    stdout_log_path: str = "./log/llama_server.out.log"
    stderr_log_path: str = "./log/llama_server.err.log"

    @classmethod
    def from_env(cls, env_file: str | Path = "common.env", config_file: str | Path = "config.yaml") -> "LocalAiConfig":
        values = _read_env_file(Path(env_file))
        yaml_values = _read_config_yaml(Path(config_file), values)
        merged = {**yaml_values, **values, **os.environ}
        return cls(
            base_url=merged.get("LLAMACPP_BASE_URL", cls.base_url).rstrip("/"),
            model=merged.get("LLAMACPP_MODEL", cls.model),
            api_key=merged.get("LLAMACPP_API_KEY", cls.api_key),
            timeout_seconds=int(merged.get("LLAMACPP_TIMEOUT_SECONDS", merged.get("LLAMACPP_TIMEOUT_SEC", cls.timeout_seconds))),
            max_tokens=int(merged.get("LLAMACPP_MAX_TOKENS", cls.max_tokens)),
            temperature=float(merged.get("LLAMACPP_TEMPERATURE", cls.temperature)),
            autostart=_as_bool(merged.get("LLAMACPP_AUTOSTART", str(cls.autostart))),
            server_path=merged.get("LLAMACPP_SERVER_PATH", cls.server_path),
            model_path=merged.get("LLAMACPP_MODEL_PATH", cls.model_path),
            mmproj_path=merged.get("LLAMACPP_MMPROJ_PATH", cls.mmproj_path),
            extra_dll_dirs=merged.get("LLAMACPP_EXTRA_DLL_DIRS", cls.extra_dll_dirs),
            n_gpu_layers=int(merged.get("LLAMACPP_N_GPU_LAYERS", cls.n_gpu_layers)),
            ctx_size=int(merged.get("LLAMACPP_CTX_SIZE", cls.ctx_size)),
            reasoning=merged.get("LLAMACPP_REASONING", cls.reasoning),
            reasoning_budget=int(merged.get("LLAMACPP_REASONING_BUDGET", cls.reasoning_budget)),
            startup_timeout_seconds=int(merged.get("LLAMACPP_STARTUP_TIMEOUT_SECONDS", merged.get("LLAMACPP_STARTUP_TIMEOUT_SEC", cls.startup_timeout_seconds))),
            startup_poll_interval_seconds=float(
                merged.get("LLAMACPP_STARTUP_POLL_INTERVAL_SECONDS", merged.get("LLAMACPP_STARTUP_POLL_INTERVAL_SEC", cls.startup_poll_interval_seconds))
            ),
            stdout_log_path=merged.get("LLAMACPP_STDOUT_LOG_PATH", cls.stdout_log_path),
            stderr_log_path=merged.get("LLAMACPP_STDERR_LOG_PATH", cls.stderr_log_path),
        )


class LocalAiClient:
    """Small OpenAI-compatible HTTP client used by room image checks."""

    def __init__(self, config: LocalAiConfig) -> None:
        self.config = config
        self._server_process: subprocess.Popen | None = None

    def ensure_server(self) -> None:
        if self.health_ok():
            return
        if not self.config.autostart:
            raise RuntimeError(f"Local AI service is unavailable: {self.config.base_url}")
        self._start_server()
        deadline = time.monotonic() + self.config.startup_timeout_seconds
        while time.monotonic() < deadline:
            if self.health_ok():
                return
            time.sleep(self.config.startup_poll_interval_seconds)
        raise RuntimeError(f"Local AI service did not become healthy within {self.config.startup_timeout_seconds}s")

    def shutdown_server(self) -> None:
        if self._server_process is None:
            return
        self._server_process.terminate()
        try:
            self._server_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._server_process.kill()
            self._server_process.wait(timeout=10)
        self._server_process = None

    def health_ok(self) -> bool:
        url = self.config.base_url.rsplit("/v1", 1)[0].rstrip("/") + "/health"
        request = urllib.request.Request(url, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=min(self.config.timeout_seconds, 5)) as response:
                return response.status < 400
        except urllib.error.URLError:
            return False

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
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        request = urllib.request.Request(
            f"{self.config.base_url}{path}",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Local AI request failed: {exc}") from exc

    def _start_server(self) -> None:
        server_path = Path(self.config.server_path)
        model_path = Path(self.config.model_path)
        if not self.config.server_path or not server_path.exists():
            raise RuntimeError("LLAMACPP_AUTOSTART=true but LLAMACPP_SERVER_PATH is missing or invalid")
        if not self.config.model_path or not model_path.exists():
            raise RuntimeError("LLAMACPP_AUTOSTART=true but LLAMACPP_MODEL_PATH is missing or invalid")
        host, port = _host_port_from_base_url(self.config.base_url)
        command = [
            str(server_path),
            "-m",
            str(model_path),
            "--alias",
            self.config.model,
            "-c",
            str(self.config.ctx_size),
            "-ngl",
            str(self.config.n_gpu_layers),
            "--reasoning",
            self.config.reasoning,
            "--reasoning-budget",
            str(self.config.reasoning_budget),
            "--host",
            host,
            "--port",
            str(port),
        ]
        if self.config.mmproj_path:
            command.extend(["--mmproj", self.config.mmproj_path])
        env = os.environ.copy()
        extra_paths = [str(server_path.parent), *_split_paths(self.config.extra_dll_dirs)]
        env["PATH"] = ";".join(path for path in extra_paths if path) + ";" + env.get("PATH", "")
        stdout_path = Path(self.config.stdout_log_path)
        stderr_path = Path(self.config.stderr_log_path)
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self._server_process = subprocess.Popen(
            command,
            env=env,
            stdout=stdout_path.open("ab"),
            stderr=stderr_path.open("ab"),
            creationflags=creationflags,
        )


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


def _read_config_yaml(path: Path, env_values: dict[str, str]) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    in_llamacpp = False
    key_map = {
        "base_url": "LLAMACPP_BASE_URL",
        "model": "LLAMACPP_MODEL",
        "api_key": "LLAMACPP_API_KEY",
        "timeout_sec": "LLAMACPP_TIMEOUT_SEC",
        "max_tokens": "LLAMACPP_MAX_TOKENS",
        "temperature": "LLAMACPP_TEMPERATURE",
        "autostart": "LLAMACPP_AUTOSTART",
        "server_path": "LLAMACPP_SERVER_PATH",
        "model_path": "LLAMACPP_MODEL_PATH",
        "mmproj_path": "LLAMACPP_MMPROJ_PATH",
        "extra_dll_dirs": "LLAMACPP_EXTRA_DLL_DIRS",
        "n_gpu_layers": "LLAMACPP_N_GPU_LAYERS",
        "ctx_size": "LLAMACPP_CTX_SIZE",
        "reasoning": "LLAMACPP_REASONING",
        "reasoning_budget": "LLAMACPP_REASONING_BUDGET",
        "startup_timeout_sec": "LLAMACPP_STARTUP_TIMEOUT_SEC",
        "startup_poll_interval_sec": "LLAMACPP_STARTUP_POLL_INTERVAL_SEC",
        "stdout_log_path": "LLAMACPP_STDOUT_LOG_PATH",
        "stderr_log_path": "LLAMACPP_STDERR_LOG_PATH",
    }
    env = {**env_values, **os.environ}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        if not raw_line.startswith(" ") and raw_line.rstrip() == "llamacpp:":
            in_llamacpp = True
            continue
        if not in_llamacpp:
            continue
        if raw_line and not raw_line.startswith(" "):
            break
        if ":" not in raw_line:
            continue
        key, raw_value = raw_line.strip().split(":", 1)
        env_key = key_map.get(key)
        if env_key:
            values[env_key] = _expand_env_default(raw_value.strip(), env)
    return values


def _expand_env_default(value: str, env: dict[str, str]) -> str:
    if value.startswith("${") and value.endswith("}") and ":-" in value:
        name, default = value[2:-1].split(":-", 1)
        return env.get(name, default)
    if value.startswith("${") and value.endswith("}"):
        return env.get(value[2:-1], "")
    return value.strip('"').strip("'")


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _split_paths(value: str) -> list[str]:
    return [str(Path(part).resolve()) for part in value.split(";") if part.strip()]


def _host_port_from_base_url(base_url: str) -> tuple[str, int]:
    url = base_url.rsplit("/v1", 1)[0].rstrip("/")
    host_port = url.split("://", 1)[-1].split("/", 1)[0]
    host, _, port = host_port.partition(":")
    return host or "127.0.0.1", int(port or 8080)
