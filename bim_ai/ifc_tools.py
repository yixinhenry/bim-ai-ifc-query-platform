from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


EDITABLE_TEXT_ATTRIBUTES = {"Name", "Description", "ObjectType", "LongName", "Tag"}
REMOVABLE_PRODUCT_TYPES = {
    "IfcAnnotation",
    "IfcElement",
    "IfcElementType",
    "IfcSpatialElement",
    "IfcSpatialElementType",
}


def _load_ifc(ifc_path: str):
    try:
        import ifcopenshell
    except ImportError as exc:
        raise RuntimeError(
            "IfcOpenShell is not installed. Install project dependencies with `pip install -r requirements.txt`."
        ) from exc
    return ifcopenshell.open(str(Path(ifc_path)))


def _modified_ifc_path(ifc_path: str) -> Path:
    source = Path(ifc_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_dir = source.parent / "modified"
    target_dir.mkdir(parents=True, exist_ok=True)
    return target_dir / f"{source.stem}_modified_{timestamp}{source.suffix}"


def _entity_by_global_id(model: Any, global_id: str) -> Any | None:
    try:
        return model.by_guid(global_id)
    except RuntimeError:
        return None


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


def _set_text_attribute(entity: Any, attribute: str, value: str) -> dict[str, Any]:
    if attribute not in EDITABLE_TEXT_ATTRIBUTES:
        return {
            "updated": False,
            "error": "attribute_not_editable",
            "editable_attributes": sorted(EDITABLE_TEXT_ATTRIBUTES),
        }
    info = entity.get_info(recursive=False)
    if attribute not in info:
        return {
            "updated": False,
            "error": "attribute_not_available_for_entity",
            "ifc_type": entity.is_a(),
            "attribute": attribute,
        }
    old_value = info.get(attribute)
    setattr(entity, attribute, value)
    return {
        "updated": True,
        "step_id": entity.id(),
        "ifc_type": entity.is_a(),
        "GlobalId": info.get("GlobalId"),
        "attribute": attribute,
        "old_value": old_value,
        "new_value": value,
    }


def _coerce_like_existing(existing_value: Any, new_value: str) -> Any:
    if isinstance(existing_value, bool):
        lowered = new_value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n"}:
            return False
        return new_value
    if isinstance(existing_value, int) and not isinstance(existing_value, bool):
        try:
            return int(new_value)
        except ValueError:
            return new_value
    if isinstance(existing_value, float):
        try:
            return float(new_value)
        except ValueError:
            return new_value
    return new_value


def _write_modified_copy(model: Any, ifc_path: str) -> str:
    output_path = _modified_ifc_path(ifc_path)
    model.write(str(output_path))
    return str(output_path)


def _can_remove_with_root_api(entity: Any) -> bool:
    return any(entity.is_a(ifc_type) for ifc_type in REMOVABLE_PRODUCT_TYPES)


def _remove_product(model: Any, entity: Any) -> dict[str, Any]:
    if not _can_remove_with_root_api(entity):
        return {
            "deleted": False,
            "error": "entity_type_not_supported_for_deletion",
            "step_id": entity.id(),
            "ifc_type": entity.is_a(),
            "supported_parent_types": sorted(REMOVABLE_PRODUCT_TYPES),
        }
    try:
        import ifcopenshell.api.root
    except ImportError as exc:
        raise RuntimeError("IfcOpenShell root API is unavailable.") from exc

    summary = _entity_summary(entity)
    ifcopenshell.api.root.remove_product(model, product=entity)
    return {"deleted": True, "deleted_entity": summary}


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


def update_text_attribute_by_global_id(ifc_path: str, global_id: str, attribute: str, value: str) -> str:
    model = _load_ifc(ifc_path)
    entity = _entity_by_global_id(model, global_id)
    if entity is None:
        return to_json({"updated": False, "error": "entity_not_found", "global_id": global_id})
    result = _set_text_attribute(entity, attribute, value)
    if result["updated"]:
        result["output_ifc_path"] = _write_modified_copy(model, ifc_path)
    return to_json(result)


def update_text_attribute_by_step_id(ifc_path: str, step_id: int, attribute: str, value: str) -> str:
    model = _load_ifc(ifc_path)
    entity = model.by_id(step_id)
    if entity is None:
        return to_json({"updated": False, "error": "entity_not_found", "step_id": step_id})
    result = _set_text_attribute(entity, attribute, value)
    if result["updated"]:
        result["output_ifc_path"] = _write_modified_copy(model, ifc_path)
    return to_json(result)


def update_property_single_value(
    ifc_path: str,
    global_id: str,
    pset_name: str,
    property_name: str,
    value: str,
) -> str:
    model = _load_ifc(ifc_path)
    entity = _entity_by_global_id(model, global_id)
    if entity is None:
        return to_json({"updated": False, "error": "entity_not_found", "global_id": global_id})

    for relation in getattr(entity, "IsDefinedBy", []) or []:
        if not relation.is_a("IfcRelDefinesByProperties"):
            continue
        pset = relation.RelatingPropertyDefinition
        if not pset or not pset.is_a("IfcPropertySet") or pset.Name != pset_name:
            continue
        for prop in pset.HasProperties:
            if prop.Name != property_name:
                continue
            if not prop.is_a("IfcPropertySingleValue") or prop.NominalValue is None:
                return to_json(
                    {
                        "updated": False,
                        "error": "property_is_not_single_value",
                        "global_id": global_id,
                        "pset_name": pset_name,
                        "property_name": property_name,
                    }
                )
            old_value = prop.NominalValue.wrappedValue
            prop.NominalValue.wrappedValue = _coerce_like_existing(old_value, value)
            return to_json(
                {
                    "updated": True,
                    "global_id": global_id,
                    "step_id": entity.id(),
                    "ifc_type": entity.is_a(),
                    "pset_name": pset_name,
                    "property_name": property_name,
                    "old_value": old_value,
                    "new_value": prop.NominalValue.wrappedValue,
                    "output_ifc_path": _write_modified_copy(model, ifc_path),
                }
            )

    return to_json(
        {
            "updated": False,
            "error": "property_not_found",
            "global_id": global_id,
            "pset_name": pset_name,
            "property_name": property_name,
        }
    )


def delete_product_by_global_id(ifc_path: str, global_id: str) -> str:
    model = _load_ifc(ifc_path)
    entity = _entity_by_global_id(model, global_id)
    if entity is None:
        return to_json({"deleted": False, "error": "entity_not_found", "global_id": global_id})
    result = _remove_product(model, entity)
    if result["deleted"]:
        result["output_ifc_path"] = _write_modified_copy(model, ifc_path)
    return to_json(result)


def delete_product_by_step_id(ifc_path: str, step_id: int) -> str:
    model = _load_ifc(ifc_path)
    entity = model.by_id(step_id)
    if entity is None:
        return to_json({"deleted": False, "error": "entity_not_found", "step_id": step_id})
    result = _remove_product(model, entity)
    if result["deleted"]:
        result["output_ifc_path"] = _write_modified_copy(model, ifc_path)
    return to_json(result)
