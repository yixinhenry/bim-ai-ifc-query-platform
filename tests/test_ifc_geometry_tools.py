import json
import shutil
import tempfile
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom

from bim_ai import ifc_tools


SAMPLE_IFC = Path(__file__).resolve().parents[1] / "ifc_files" / "AC20-FZK-Haus.ifc"


def _window_opening(model):
    return next(
        opening
        for opening in model.by_type("IfcOpeningElement")
        if getattr(opening, "HasFillings", None)
        and opening.HasFillings[0].RelatedBuildingElement.is_a("IfcWindow")
    )


def test_fill_empty_opening_and_restore_window_from_template():
    opening_statuses = json.loads(ifc_tools.list_openings_with_filling_status(str(SAMPLE_IFC)))
    assert opening_statuses["total"] > 0
    assert opening_statuses["items"][0]["host_elements"]

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir = Path(temp_dir)

        fill_path = temp_dir / "fill.ifc"
        shutil.copyfile(SAMPLE_IFC, fill_path)
        model = ifcopenshell.open(fill_path)
        opening = _window_opening(model)
        opening_id = opening.id()
        window_id = opening.HasFillings[0].RelatedBuildingElement.id()
        host_id = opening.VoidsElements[0].RelatingBuildingElement.id()

        assert json.loads(ifc_tools.delete_product_by_step_id(str(fill_path), window_id))["deleted"] is True
        settings = ifcopenshell.geom.settings()
        model = ifcopenshell.open(fill_path)
        ifcopenshell.geom.create_shape(settings, model.by_id(host_id))
        result = json.loads(ifc_tools.fill_unfilled_opening_by_step_id(str(fill_path), opening_id))
        assert result["filled"] is True
        model = ifcopenshell.open(fill_path)
        try:
            model.by_id(opening_id)
            assert False, "The empty opening should have been removed"
        except RuntimeError:
            pass
        ifcopenshell.geom.create_shape(settings, model.by_id(host_id))

        restore_path = temp_dir / "restore.ifc"
        shutil.copyfile(SAMPLE_IFC, restore_path)
        model = ifcopenshell.open(restore_path)
        opening = _window_opening(model)
        opening_id = opening.id()
        deleted_window_id = opening.HasFillings[0].RelatedBuildingElement.id()
        template_id = next(window.id() for window in model.by_type("IfcWindow") if window.id() != deleted_window_id)

        assert json.loads(ifc_tools.delete_product_by_step_id(str(restore_path), deleted_window_id))["deleted"] is True
        result = json.loads(
            ifc_tools.restore_window_from_template_by_opening_step_id(
                str(restore_path), opening_id, template_id, "Restored test window"
            )
        )
        assert result["restored"] is True
        model = ifcopenshell.open(restore_path)
        restored_window = model.by_id(opening_id).HasFillings[0].RelatedBuildingElement
        assert restored_window.is_a("IfcWindow")
        assert restored_window.Name == "Restored test window"


if __name__ == "__main__":
    test_fill_empty_opening_and_restore_window_from_template()
    print("IFC geometry tool checks passed")
