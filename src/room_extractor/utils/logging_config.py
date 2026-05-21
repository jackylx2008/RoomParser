"""日志配置模块。

提供项目统一的日志记录器初始化、获取和路径标记解析能力。
"""

from __future__ import annotations

import logging
import os
import platform
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def get_cloudstation_root() -> str:
    """
    Return the Synology CloudStation root for the current platform.

    Priority:
    1. CLOUDSTATION_ROOT
    2. CLOUDSTATION_ROOT_WINDOWS / CLOUDSTATION_ROOT_MACOS / CLOUDSTATION_ROOT_LINUX
    3. ~/CloudStation
    """
    explicit_root = os.getenv("CLOUDSTATION_ROOT")
    if explicit_root:
        return str(Path(explicit_root).expanduser())

    system = platform.system().lower()
    platform_env_names = {
        "windows": ("CLOUDSTATION_ROOT_WINDOWS",),
        "darwin": ("CLOUDSTATION_ROOT_MACOS", "CLOUDSTATION_ROOT_DARWIN"),
        "linux": ("CLOUDSTATION_ROOT_LINUX",),
    }

    for env_name in platform_env_names.get(system, ()):
        platform_root = os.getenv(env_name)
        if platform_root:
            return str(Path(platform_root).expanduser())

    return str(Path("~/CloudStation").expanduser())


def resolve_path_markers(path: str | os.PathLike[str]) -> str:
    """Expand supported path markers in YAML/.env values."""
    raw_path = os.fspath(path)
    has_cloudstation_marker = any(
        marker in raw_path
        for marker in ("${CLOUDSTATION_ROOT}", "{CLOUDSTATION_ROOT}", "%CLOUDSTATION_ROOT%")
    )
    cloudstation_root = get_cloudstation_root()
    if _is_cloudstation_relative_root(raw_path):
        return str(Path(cloudstation_root) / raw_path.lstrip("/\\"))

    resolved = (
        raw_path.replace("${CLOUDSTATION_ROOT}", cloudstation_root)
        .replace("{CLOUDSTATION_ROOT}", cloudstation_root)
        .replace("%CLOUDSTATION_ROOT%", cloudstation_root)
    )
    if has_cloudstation_marker:
        return str(Path(resolved).expanduser())
    return os.path.expanduser(resolved)


def setup_logger(
    log_level: int | str = logging.DEBUG,
    log_file: Optional[str] = None,
    filemode: str = "w",
) -> logging.Logger:
    """
    设置日志记录器。

    :param log_level: 日志级别，默认为 DEBUG。
    :param log_file: 日志文件路径，如果为 None，则根据主模块名自动生成。
    :param filemode: 文件打开模式，保留该参数用于兼容调用方。
    :return: 配置好的日志记录器。
    """
    if log_file is None:
        main_module = os.path.splitext(os.path.basename(sys.argv[0]))[0] or "app"
        log_file = str(PROJECT_ROOT / "log" / f"{main_module}.log")

    log_file = resolve_path_markers(log_file)
    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    log_format = "%(asctime)s - %(levelname)s - %(module)s - %(message)s"
    app_logger = logging.getLogger()
    app_logger.setLevel(_coerce_log_level(log_level))

    if app_logger.handlers:
        app_logger.handlers.clear()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))

    file_handler = RotatingFileHandler(
        log_file,
        mode="a",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(log_format))

    app_logger.addHandler(console_handler)
    app_logger.addHandler(file_handler)
    return app_logger


def get_logger(name: str | None = None) -> logging.Logger:
    """获取项目统一配置下的 logger。"""
    return logging.getLogger(name)


def _is_cloudstation_relative_root(path: str) -> bool:
    if not path.startswith(("/", "\\")):
        return False
    if path.startswith(("//", "\\\\")):
        return False
    if Path(path).anchor not in ("/", "\\"):
        return False
    return True


def _coerce_log_level(log_level: int | str) -> int:
    if isinstance(log_level, str):
        level = logging.getLevelName(log_level.upper())
        if isinstance(level, int):
            return level
        raise ValueError(f"Unknown log level: {log_level}")
    return log_level

