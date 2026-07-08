from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


def _load_ifc(ifc_path: str):
    try:
        import ifcopenshell
    except ImportError as exc:
        raise RuntimeError(
            "IfcOpenShell is not installed. Install project dependencies with `pip install -r requirements.txt`."
        ) from exc
    return ifcopenshell.open(str(Path(ifc_path)))


def _entity_summary(entity: Any) -> dict[str, Any]:
    info = entity.get_info(recursive=False)
    return {
        "step_id": entity.id(),
        "ifc_type": entity.is_a(),
        "GlobalId": info.get("GlobalId"),
        "Name": info.get("Name"),
        "ObjectType": info.get("ObjectType"),
        "Tag": info.get("Tag"),
    }


def to_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def model_overview(ifc_path: str) -> str:
    model = _load_ifc(ifc_path)
    counts = Counter(entity.is_a() for entity in model)
    top_types = [{"ifc_type": key, "count": value} for key, value in counts.most_common(30)]
    return to_json(
        {
            "schema": model.schema,
            "entity_count": len(list(model)),
            "top_types": top_types,
        }
    )


def list_entities_by_type(ifc_path: str, ifc_type: str, limit: int = 50) -> str:
    model = _load_ifc(ifc_path)
    entities = model.by_type(ifc_type)
    return to_json(
        {
            "ifc_type": ifc_type,
            "total": len(entities),
            "items": [_entity_summary(entity) for entity in entities[:limit]],
            "limit": limit,
        }
    )


def get_entity_by_global_id(ifc_path: str, global_id: str) -> str:
    model = _load_ifc(ifc_path)
    entity = model.by_guid(global_id)
    if entity is None:
        return to_json({"found": False, "global_id": global_id})
    return to_json({"found": True, "entity": entity.get_info(recursive=True)})


def get_entity_by_step_id(ifc_path: str, step_id: int) -> str:
    model = _load_ifc(ifc_path)
    entity = model.by_id(step_id)
    if entity is None:
        return to_json({"found": False, "step_id": step_id})
    return to_json({"found": True, "entity": entity.get_info(recursive=True)})


def get_property_sets(ifc_path: str, global_id: str) -> str:
    model = _load_ifc(ifc_path)
    entity = model.by_guid(global_id)
    if entity is None:
        return to_json({"found": False, "global_id": global_id})
    try:
        import ifcopenshell.util.element
    except ImportError as exc:
        raise RuntimeError("IfcOpenShell util module is unavailable.") from exc
    return to_json(
        {
            "found": True,
            "global_id": global_id,
            "ifc_type": entity.is_a(),
            "property_sets": ifcopenshell.util.element.get_psets(entity, psets_only=True),
            "quantity_sets": ifcopenshell.util.element.get_psets(entity, qtos_only=True),
        }
    )


def find_by_attribute(ifc_path: str, ifc_type: str, attribute: str, value: str, limit: int = 50) -> str:
    model = _load_ifc(ifc_path)
    matches = []
    needle = value.lower()
    for entity in model.by_type(ifc_type):
        info = entity.get_info(recursive=False)
        attr_value = info.get(attribute)
        if attr_value is not None and needle in str(attr_value).lower():
            matches.append(_entity_summary(entity))
        if len(matches) >= limit:
            break
    return to_json(
        {
            "ifc_type": ifc_type,
            "attribute": attribute,
            "value": value,
            "matches": matches,
            "limit": limit,
        }
    )


def spatial_structure(ifc_path: str) -> str:
    model = _load_ifc(ifc_path)
    result = []
    for spatial_type in ["IfcProject", "IfcSite", "IfcBuilding", "IfcBuildingStorey", "IfcSpace"]:
        result.append(
            {
                "ifc_type": spatial_type,
                "items": [_entity_summary(entity) for entity in model.by_type(spatial_type)],
            }
        )
    return to_json(result)
