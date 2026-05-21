from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from room_extractor.ai.local_ai_client import LocalAiClient, LocalAiConfig
from room_extractor.models.issue import Issue
from room_extractor.pdf.pdf_checker import RoomsPdfCheck


def check_rooms_with_local_ai(
    rooms_with_images: RoomsPdfCheck,
    config: LocalAiConfig,
    limit: int | None = None,
    dry_run: bool = False,
) -> RoomsPdfCheck:
    """Check generated room screenshots with a local multimodal model."""
    checked = rooms_with_images.model_copy(deep=True)
    client = LocalAiClient(config)
    checked_count = 0
    dry_run_count = 0
    failed_count = 0
    review_required_count = 0
    for room in checked.rooms:
        if limit is not None and checked_count >= limit:
            break
        review_image = room.evidence.pdf_source.get("review_image")
        if not review_image:
            continue
        image_path = Path(str(review_image.get("path", "")))
        prompt = _build_prompt(room_payload=room.model_dump(mode="json"))
        try:
            if dry_run:
                result = {
                    "status": "dry_run",
                    "model": config.model,
                    "base_url": config.base_url,
                    "image_path": str(image_path),
                    "prompt_chars": len(prompt),
                }
                dry_run_count += 1
            else:
                response = client.chat_with_image(prompt, image_path)
                result = _parse_model_result(response)
                if result.get("needs_review") is True:
                    review_required_count += 1
                    _append_ai_issue(room, result)
            room.evidence.pdf_source["local_ai_check"] = result
            checked_count += 1
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            failed_count += 1
            room.evidence.pdf_source["local_ai_check"] = {"status": "failed", "message": str(exc)}
            room.issues.append(
                Issue(
                    issue_code="LOCAL_AI_CHECK_FAILED",
                    severity="medium",
                    field="pdf_source",
                    message=str(exc),
                    need_manual_review=True,
                )
            )
            room.review.required = True
            room.review.status = "pending_downstream_check"
            checked_count += 1
    checked.summary = {
        **checked.summary,
        "local_ai_checked": checked_count,
        "local_ai_dry_run": dry_run_count,
        "local_ai_failed": failed_count,
        "local_ai_review_required": review_required_count,
        "local_ai_model": config.model,
        "local_ai_base_url": config.base_url,
    }
    return checked


def _build_prompt(room_payload: dict[str, Any]) -> str:
    basic = room_payload.get("basic_info", {})
    area = room_payload.get("area", {})
    pdf_source = room_payload.get("evidence", {}).get("pdf_source", {})
    return (
        "你是建筑平面图局部截图校核助手。只根据截图和给定字段判断 CAD/PDF 自动提取是否可信。"
        "不要重新提取整张图，不要猜测截图外信息。请只返回 JSON，不要输出 Markdown。\n\n"
        "需要校核的自动结果：\n"
        f"房号: {basic.get('room_number')}\n"
        f"房名: {basic.get('room_name')}\n"
        f"面积: {area.get('text_value')} {area.get('unit')}\n"
        f"PDF局部矢量文字: {pdf_source.get('local_text', '')[:1000]}\n\n"
        "返回 JSON schema："
        '{"visible": true/false, "room_number_match": true/false/null, '
        '"room_name_match": true/false/null, "area_match": true/false/null, '
        '"needs_review": true/false, "confidence": 0.0, "notes": "简短中文原因"}'
    )


def _parse_model_result(response: dict[str, Any]) -> dict[str, Any]:
    content = str(response.get("choices", [{}])[0].get("message", {}).get("content", "")).strip()
    if not content:
        raise ValueError("Local AI response did not contain message.content")
    parsed = _extract_json(content)
    parsed["status"] = "ok"
    parsed["raw_content"] = content
    return parsed


def _extract_json(content: str) -> dict[str, Any]:
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Local AI response is not JSON")
        return json.loads(content[start : end + 1])


def _append_ai_issue(room, result: dict[str, Any]) -> None:
    room.issues.append(
        Issue(
            issue_code="LOCAL_AI_REVIEW_REQUIRED",
            severity="medium",
            field="pdf_source",
            pdf_value=result,
            message=str(result.get("notes") or "本地 AI 判断该截图需要后续校核"),
            need_manual_review=True,
        )
    )
    room.review.required = True
    room.review.status = "pending_downstream_check"
