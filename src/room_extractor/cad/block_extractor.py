from __future__ import annotations

from ezdxf.document import Drawing as DxfDrawing

from room_extractor.models.drawing import CadBlockEntity
from room_extractor.models.issue import Issue
from room_extractor.utils.logger import get_logger

logger = get_logger(__name__)


def extract_blocks(doc: DxfDrawing) -> tuple[list[CadBlockEntity], list[Issue]]:
    """Extract INSERT entities and attached ATTRIB values from modelspace."""
    blocks: list[CadBlockEntity] = []
    issues: list[Issue] = []
    for entity in doc.modelspace().query("INSERT"):
        try:
            insert = entity.dxf.insert
            attributes = {
                str(attrib.dxf.tag): str(attrib.dxf.text)
                for attrib in getattr(entity, "attribs", [])
            }
            blocks.append(
                CadBlockEntity(
                    name=str(entity.dxf.name),
                    layer=str(getattr(entity.dxf, "layer", "0")),
                    position=(float(insert[0]), float(insert[1])),
                    attributes=attributes,
                )
            )
        except Exception as exc:
            message = f"Failed to extract INSERT entity: {exc}"
            logger.warning(message)
            issues.append(Issue(issue_code="BLOCK_EXTRACT_FAILED", field="blocks", message=message))
    return blocks, issues
