from __future__ import annotations

import re


MOJIBAKE_MARKERS = "×ÖÎÀÉú¼äÇÚÒéÊÒÌÝ¼ó±öºóÄÐÅ®ÞÃæÏß"


def normalize_cad_text(text: str) -> str:
    """Normalize CAD text content for room label parsing."""
    recovered = recover_gbk_mojibake(text)
    normalized = recovered.replace("\\P", "\n")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = re.sub(r"[ \t\f\v]+", " ", normalized)
    normalized = "\n".join(part.strip() for part in normalized.split("\n"))
    normalized = re.sub(r"\n{2,}", "\n", normalized)
    normalized = normalized.replace("m²", "㎡").replace("m2", "㎡").replace("M2", "㎡")
    normalized = normalized.replace("©O", "㎡").replace("O", "O")
    return normalized.strip()


def recover_gbk_mojibake(text: str) -> str:
    """Recover common GBK text decoded as Latin-1 by CAD conversion."""
    if not text:
        return text
    if not any(marker in text for marker in MOJIBAKE_MARKERS):
        return text
    try:
        candidate = text.encode("latin1").decode("gbk")
    except UnicodeError:
        return text
    if _cjk_score(candidate) > _cjk_score(text):
        return candidate
    return text


def _cjk_score(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
