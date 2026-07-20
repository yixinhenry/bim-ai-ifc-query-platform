from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any
from uuid import uuid4


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


def _entity_by_global_id(model: Any, global_id: str) -> Any | None:
    try:
        return model.by_guid(global_id)
    except RuntimeError:
        return None


def _entity_by_step_id(model: Any, step_id: int) -> Any | None:
    try:
        return model.by_id(step_id)
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


def _validation_report(model: Any, baseline_keys: set[str] | None = None) -> dict[str, Any]:
    try:
        import ifcopenshell.validate
    except ImportError as exc:
        raise RuntimeError("IfcOpenShell validation API is unavailable.") from exc

    logger = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, logger)
    issues = []
    keys = set()
    for statement in logger.statements:
        instance = statement.get("instance")
        step_id = None
        if instance is not None:
            try:
                step_id = instance.id()
            except RuntimeError:
                pass
        issue = {
            "level": statement.get("level"),
            "type": statement.get("type"),
            "message": statement.get("message"),
            "step_id": step_id,
            "attribute": statement.get("attribute"),
        }
        key = json.dumps(issue, sort_keys=True, ensure_ascii=False)
        keys.add(key)
        issues.append(issue)
    new_keys = keys if baseline_keys is None else keys - baseline_keys
    return {
        "schema_valid": not issues,
        "no_new_issues": not new_keys,
        "issue_count": len(issues),
        "new_issue_count": len(new_keys),
        "new_issues": [issue for issue in issues if json.dumps(issue, sort_keys=True, ensure_ascii=False) in new_keys][:20],
        "issue_keys": keys,
    }


def _baseline_validation_keys(model: Any) -> set[str]:
    return _validation_report(model)["issue_keys"]


def _save_mutation(model: Any, ifc_path: str, result: dict[str, Any], baseline_keys: set[str]) -> dict[str, Any]:
    validation = _validation_report(model, baseline_keys)
    validation.pop("issue_keys", None)
    result["validation"] = validation
    result["output_ifc_path"] = _write_modified_copy(model, ifc_path)
    return result


def _write_modified_copy(model: Any, ifc_path: str) -> str:
    """Write changes atomically back to the single IFC owned by the project."""
    source = Path(ifc_path)
    temp_path = source.with_name(f".{source.stem}.{uuid4().hex}.tmp{source.suffix}")
    try:
        model.write(str(temp_path))
        os.replace(temp_path, source)
    finally:
        temp_path.unlink(missing_ok=True)
    return str(source)


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


def _get_unfilled_opening(model: Any, step_id: int) -> tuple[Any | None, dict[str, Any] | None]:
    opening = _entity_by_step_id(model, step_id)
    if opening is None:
        return None, {"error": "entity_not_found", "step_id": step_id}
    if not opening.is_a("IfcOpeningElement"):
        return None, {"error": "entity_is_not_opening", "step_id": step_id, "ifc_type": opening.is_a()}
    if getattr(opening, "HasFillings", None):
        return None, {"error": "opening_has_filling", "step_id": step_id}
    if not getattr(opening, "VoidsElements", None):
        return None, {"error": "opening_has_no_host", "step_id": step_id}
    return opening, None


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


def list_openings_with_filling_status(ifc_path: str, limit: int = 50) -> str:
    """List openings, their host elements, and whether a window or door fills them."""
    model = _load_ifc(ifc_path)
    items = []
    openings = model.by_type("IfcOpeningElement")
    for opening in openings[:limit]:
        hosts = [
            _entity_summary(relation.RelatingBuildingElement)
            for relation in getattr(opening, "VoidsElements", []) or []
            if relation.RelatingBuildingElement is not None
        ]
        fillings = [
            _entity_summary(relation.RelatedBuildingElement)
            for relation in getattr(opening, "HasFillings", []) or []
            if relation.RelatedBuildingElement is not None
        ]
        items.append(
            {
                **_entity_summary(opening),
                "is_empty": not fillings,
                "host_elements": hosts,
                "filling_elements": fillings,
            }
        )
    return to_json({"total": len(openings), "items": items, "limit": limit})


def get_entity_relations_by_step_id(ifc_path: str, step_id: int) -> str:
    """Return concise IFC relationship context for one entity."""
    model = _load_ifc(ifc_path)
    entity = _entity_by_step_id(model, step_id)
    if entity is None:
        return to_json({"found": False, "step_id": step_id})
    try:
        import ifcopenshell.util.element
    except ImportError as exc:
        raise RuntimeError("IfcOpenShell util API is unavailable.") from exc

    def summary_or_none(value: Any) -> dict[str, Any] | None:
        return _entity_summary(value) if value is not None else None

    return to_json(
        {
            "found": True,
            "entity": _entity_summary(entity),
            "container": summary_or_none(ifcopenshell.util.element.get_container(entity)),
            "aggregate_parent": summary_or_none(ifcopenshell.util.element.get_aggregate(entity)),
            "type": summary_or_none(ifcopenshell.util.element.get_type(entity)),
            "material": summary_or_none(ifcopenshell.util.element.get_material(entity)),
            "voids": [summary_or_none(relation.RelatingBuildingElement) for relation in getattr(entity, "VoidsElements", []) or []],
            "openings": [summary_or_none(relation.RelatedOpeningElement) for relation in getattr(entity, "HasOpenings", []) or []],
            "fills": [summary_or_none(relation.RelatingOpeningElement) for relation in getattr(entity, "FillsVoids", []) or []],
            "fillings": [summary_or_none(relation.RelatedBuildingElement) for relation in getattr(entity, "HasFillings", []) or []],
            "inverse_relations": [
                {"step_id": relation.id(), "ifc_type": relation.is_a()}
                for relation in list(model.get_inverse(entity))[:100]
            ],
        }
    )


def validate_ifc_model(ifc_path: str) -> str:
    """Validate IFC schema constraints and return a compact issue report."""
    report = _validation_report(_load_ifc(ifc_path))
    report.pop("issue_keys", None)
    return to_json(report)


def update_text_attribute_by_global_id(ifc_path: str, global_id: str, attribute: str, value: str) -> str:
    model = _load_ifc(ifc_path)
    baseline_keys = _baseline_validation_keys(model)
    entity = _entity_by_global_id(model, global_id)
    if entity is None:
        return to_json({"updated": False, "error": "entity_not_found", "global_id": global_id})
    result = _set_text_attribute(entity, attribute, value)
    if result["updated"]:
        _save_mutation(model, ifc_path, result, baseline_keys)
    return to_json(result)


def update_text_attribute_by_step_id(ifc_path: str, step_id: int, attribute: str, value: str) -> str:
    model = _load_ifc(ifc_path)
    baseline_keys = _baseline_validation_keys(model)
    entity = model.by_id(step_id)
    if entity is None:
        return to_json({"updated": False, "error": "entity_not_found", "step_id": step_id})
    result = _set_text_attribute(entity, attribute, value)
    if result["updated"]:
        _save_mutation(model, ifc_path, result, baseline_keys)
    return to_json(result)


def update_property_single_value(
    ifc_path: str,
    global_id: str,
    pset_name: str,
    property_name: str,
    value: str,
) -> str:
    model = _load_ifc(ifc_path)
    baseline_keys = _baseline_validation_keys(model)
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
                _save_mutation(
                    model,
                    ifc_path,
                    {
                    "updated": True,
                    "global_id": global_id,
                    "step_id": entity.id(),
                    "ifc_type": entity.is_a(),
                    "pset_name": pset_name,
                    "property_name": property_name,
                    "old_value": old_value,
                    "new_value": prop.NominalValue.wrappedValue,
                    },
                    baseline_keys,
                )
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
    baseline_keys = _baseline_validation_keys(model)
    entity = _entity_by_global_id(model, global_id)
    if entity is None:
        return to_json({"deleted": False, "error": "entity_not_found", "global_id": global_id})
    result = _remove_product(model, entity)
    if result["deleted"]:
        _save_mutation(model, ifc_path, result, baseline_keys)
    return to_json(result)


def delete_product_by_step_id(ifc_path: str, step_id: int) -> str:
    model = _load_ifc(ifc_path)
    baseline_keys = _baseline_validation_keys(model)
    entity = _entity_by_step_id(model, step_id)
    if entity is None:
        return to_json({"deleted": False, "error": "entity_not_found", "step_id": step_id})
    result = _remove_product(model, entity)
    if result["deleted"]:
        _save_mutation(model, ifc_path, result, baseline_keys)
    return to_json(result)


def fill_unfilled_opening_by_step_id(ifc_path: str, opening_step_id: int) -> str:
    """Remove an empty opening so the host wall's original body is restored."""
    model = _load_ifc(ifc_path)
    baseline_keys = _baseline_validation_keys(model)
    opening, error = _get_unfilled_opening(model, opening_step_id)
    if error:
        return to_json({"filled": False, **error})

    try:
        import ifcopenshell.api.feature
    except ImportError as exc:
        raise RuntimeError("IfcOpenShell feature API is unavailable.") from exc

    host = opening.VoidsElements[0].RelatingBuildingElement
    opening_summary = _entity_summary(opening)
    host_summary = _entity_summary(host)
    ifcopenshell.api.feature.remove_feature(model, feature=opening)
    return to_json(
        _save_mutation(
            model,
            ifc_path,
            {
            "filled": True,
            "removed_opening": opening_summary,
            "host_element": host_summary,
            },
            baseline_keys,
        )
    )


def edit_property_set_by_global_id(
    ifc_path: str,
    global_id: str,
    pset_name: str,
    properties: dict[str, Any],
) -> str:
    """Create or batch-edit an IfcPropertySet; a None value removes the named property."""
    model = _load_ifc(ifc_path)
    baseline_keys = _baseline_validation_keys(model)
    entity = _entity_by_global_id(model, global_id)
    if entity is None:
        return to_json({"updated": False, "error": "entity_not_found", "global_id": global_id})
    if not pset_name.strip() or not isinstance(properties, dict) or not all(isinstance(key, str) for key in properties):
        return to_json({"updated": False, "error": "invalid_property_set_input"})
    if any(not isinstance(value, (str, int, float, bool, type(None))) for value in properties.values()):
        return to_json({"updated": False, "error": "unsupported_property_value_type"})
    try:
        import ifcopenshell.api.pset
    except ImportError as exc:
        raise RuntimeError("IfcOpenShell property-set API is unavailable.") from exc

    pset = next(
        (
            relation.RelatingPropertyDefinition
            for relation in getattr(entity, "IsDefinedBy", []) or []
            if relation.is_a("IfcRelDefinesByProperties")
            and relation.RelatingPropertyDefinition.is_a("IfcPropertySet")
            and relation.RelatingPropertyDefinition.Name == pset_name
        ),
        None,
    )
    created = pset is None
    if pset is None:
        pset = ifcopenshell.api.pset.add_pset(model, product=entity, name=pset_name)
    ifcopenshell.api.pset.edit_pset(model, pset=pset, properties=properties, should_purge=True)
    return to_json(
        _save_mutation(
            model,
            ifc_path,
            {
                "updated": True,
                "created_property_set": created,
                "entity": _entity_summary(entity),
                "pset_name": pset_name,
                "properties": properties,
            },
            baseline_keys,
        )
    )


def _place_product(model: Any, product: Any, x: float, y: float, z: float, rotation_z_degrees: float) -> dict[str, Any]:
    try:
        import numpy as np
        import ifcopenshell.api.geometry
        import ifcopenshell.util.placement
        import ifcopenshell.util.unit
    except ImportError as exc:
        raise RuntimeError("Required IfcOpenShell placement APIs are unavailable.") from exc
    if getattr(product, "ObjectPlacement", None) is None:
        raise ValueError("entity_has_no_object_placement")
    matrix = np.array(ifcopenshell.util.placement.get_local_placement(product.ObjectPlacement), dtype=float)
    matrix[:3, 3] *= ifcopenshell.util.unit.calculate_unit_scale(model)
    angle = np.deg2rad(rotation_z_degrees)
    rotation = np.array(
        [[np.cos(angle), -np.sin(angle), 0.0], [np.sin(angle), np.cos(angle), 0.0], [0.0, 0.0, 1.0]]
    )
    matrix[:3, :3] = rotation @ matrix[:3, :3]
    matrix[:3, 3] = [x, y, z]
    ifcopenshell.api.geometry.edit_object_placement(model, product=product, matrix=matrix, is_si=True)
    return {"x": x, "y": y, "z": z, "rotation_z_degrees": rotation_z_degrees}


def place_product_by_step_id(
    ifc_path: str,
    step_id: int,
    x: float,
    y: float,
    z: float,
    rotation_z_degrees: float = 0.0,
) -> str:
    """Set an existing product's world position in metres and optional Z rotation."""
    model = _load_ifc(ifc_path)
    baseline_keys = _baseline_validation_keys(model)
    entity = _entity_by_step_id(model, step_id)
    if entity is None:
        return to_json({"moved": False, "error": "entity_not_found", "step_id": step_id})
    try:
        placement = _place_product(model, entity, float(x), float(y), float(z), float(rotation_z_degrees))
    except ValueError as exc:
        return to_json({"moved": False, "error": str(exc), "step_id": step_id})
    return to_json(_save_mutation(model, ifc_path, {"moved": True, "entity": _entity_summary(entity), "placement": placement}, baseline_keys))


def copy_product_by_step_id(
    ifc_path: str,
    source_step_id: int,
    x: float,
    y: float,
    z: float,
    rotation_z_degrees: float = 0.0,
    name: str = "",
) -> str:
    """Copy an existing product and place the copy at a world position in metres."""
    model = _load_ifc(ifc_path)
    baseline_keys = _baseline_validation_keys(model)
    source = _entity_by_step_id(model, source_step_id)
    if source is None:
        return to_json({"copied": False, "error": "entity_not_found", "step_id": source_step_id})
    if source.is_a("IfcWindow") or source.is_a("IfcDoor"):
        return to_json({"copied": False, "error": "use_opening_restore_tool_for_window_or_door", "step_id": source_step_id})
    try:
        import ifcopenshell.api.root
        import ifcopenshell.api.spatial
        import ifcopenshell.util.element
    except ImportError as exc:
        raise RuntimeError("Required IfcOpenShell copy APIs are unavailable.") from exc

    copy = ifcopenshell.api.root.copy_class(model, product=source)
    if name.strip():
        copy.Name = name.strip()
    placement = _place_product(model, copy, float(x), float(y), float(z), float(rotation_z_degrees))
    container = ifcopenshell.util.element.get_container(source)
    if container is not None:
        ifcopenshell.api.spatial.assign_container(model, products=[copy], relating_structure=container)
    return to_json(
        _save_mutation(
            model,
            ifc_path,
            {"copied": True, "source": _entity_summary(source), "copy": _entity_summary(copy), "placement": placement},
            baseline_keys,
        )
    )


def restore_window_from_template_by_opening_step_id(
    ifc_path: str,
    opening_step_id: int,
    template_window_step_id: int,
    name: str = "",
) -> str:
    """Create a window from an existing template and assign it to an empty opening."""
    model = _load_ifc(ifc_path)
    baseline_keys = _baseline_validation_keys(model)
    opening, error = _get_unfilled_opening(model, opening_step_id)
    if error:
        return to_json({"restored": False, **error})

    template = _entity_by_step_id(model, template_window_step_id)
    if template is None:
        return to_json({"restored": False, "error": "template_not_found", "step_id": template_window_step_id})
    if not template.is_a("IfcWindow"):
        return to_json(
            {
                "restored": False,
                "error": "template_is_not_window",
                "step_id": template_window_step_id,
                "ifc_type": template.is_a(),
            }
        )

    try:
        import ifcopenshell.api.feature
        import ifcopenshell.api.geometry
        import ifcopenshell.api.root
        import ifcopenshell.api.spatial
        import ifcopenshell.util.element
        import ifcopenshell.util.placement
    except ImportError as exc:
        raise RuntimeError("Required IfcOpenShell authoring APIs are unavailable.") from exc

    host = opening.VoidsElements[0].RelatingBuildingElement
    window = ifcopenshell.api.root.copy_class(model, product=template)
    if name.strip():
        window.Name = name.strip()
    opening_matrix = ifcopenshell.util.placement.get_local_placement(opening.ObjectPlacement)
    ifcopenshell.api.geometry.edit_object_placement(
        model,
        product=window,
        matrix=opening_matrix,
        is_si=False,
    )
    container = ifcopenshell.util.element.get_container(host)
    if container is not None:
        ifcopenshell.api.spatial.assign_container(model, products=[window], relating_structure=container)
    ifcopenshell.api.feature.add_filling(model, opening=opening, element=window)

    return to_json(
        _save_mutation(
            model,
            ifc_path,
            {
            "restored": True,
            "opening_step_id": opening_step_id,
            "template_window_step_id": template_window_step_id,
            "window": _entity_summary(window),
            "host_element": _entity_summary(host),
            },
            baseline_keys,
        )
    )
