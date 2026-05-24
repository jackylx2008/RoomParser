from __future__ import annotations

from collections.abc import Iterable, Iterator

from ezdxf.document import Drawing as DxfDrawing


def iter_modelspace_entities(doc: DxfDrawing, visible_only: bool = False) -> Iterator[object]:
    """Yield modelspace entities, optionally excluding hidden or frozen content."""
    for entity in doc.modelspace():
        if visible_only and not is_entity_visible(doc, entity):
            continue
        yield entity


def is_entity_visible(doc: DxfDrawing, entity: object) -> bool:
    """Return False for entities on off/frozen layers or with DXF invisible flag."""
    if bool(getattr(entity.dxf, "invisible", 0) or 0):
        return False
    layer_name = str(getattr(entity.dxf, "layer", "0"))
    try:
        layer = doc.layers.get(layer_name)
    except Exception:
        return True
    return not bool(layer.is_off() or layer.is_frozen())


def filter_visible_entities(doc: DxfDrawing, entities: Iterable[object], visible_only: bool = False) -> list[object]:
    """Filter arbitrary entity iterables with the same visibility rule."""
    if not visible_only:
        return list(entities)
    return [entity for entity in entities if is_entity_visible(doc, entity)]
