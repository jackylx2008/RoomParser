from __future__ import annotations

from ezdxf.document import Drawing as DxfDrawing

from room_extractor.cad.entity_filter import iter_modelspace_entities
from room_extractor.models.drawing import CadTextEntity
from room_extractor.models.issue import Issue
from room_extractor.utils.logger import get_logger

logger = get_logger(__name__)


def extract_texts(
    doc: DxfDrawing,
    layers: list[str] | None = None,
    visible_only: bool = False,
) -> tuple[list[CadTextEntity], list[Issue]]:
    """Extract TEXT and MTEXT entities from modelspace."""
    texts: list[CadTextEntity] = []
    issues: list[Issue] = []
    allowed_layers = {layer.upper() for layer in layers} if layers else None
    for entity in iter_modelspace_entities(doc, visible_only=visible_only):
        if entity.dxftype() not in {"TEXT", "MTEXT"}:
            continue
        if allowed_layers is not None and str(getattr(entity.dxf, "layer", "0")).upper() not in allowed_layers:
            continue
        try:
            texts.append(_extract_text_entity(entity))
        except Exception as exc:
            message = f"Failed to extract {entity.dxftype()} entity: {exc}"
            logger.warning(message)
            issues.append(Issue(issue_code="TEXT_EXTRACT_FAILED", field="texts", message=message))
    return texts, issues


def _extract_text_entity(entity: object) -> CadTextEntity:
    entity_type = entity.dxftype()
    insert = getattr(entity.dxf, "insert", (0.0, 0.0, 0.0))
    if entity_type == "MTEXT":
        raw_text = entity.plain_text() if hasattr(entity, "plain_text") else getattr(entity, "text", "")
    else:
        raw_text = getattr(entity.dxf, "text", "")
    return CadTextEntity(
        text=str(raw_text).strip(),
        entity_type=entity_type,
        layer=getattr(entity.dxf, "layer", "0"),
        position=(float(insert[0]), float(insert[1])),
        height=_optional_float(getattr(entity.dxf, "height", None) or getattr(entity.dxf, "char_height", None)),
        rotation=float(getattr(entity.dxf, "rotation", 0.0) or 0.0),
    )


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)
