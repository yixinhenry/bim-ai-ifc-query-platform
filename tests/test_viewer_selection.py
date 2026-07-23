import json
import shutil
import tempfile
import unittest
from pathlib import Path
from urllib.request import Request, urlopen

import ifcopenshell

from bim_ai.storage import (
    add_audit_event,
    create_conversation,
    create_project,
    get_viewer_selection,
    init_db,
    list_audit_events,
)
from bim_ai.viewer_server import start_viewer_server


SAMPLE_IFC = Path(__file__).resolve().parents[1] / "ifc_files" / "AC20-FZK-Haus.ifc"


class ViewerSelectionTests(unittest.TestCase):
    def test_project_level_selection_event_is_visible_in_the_active_conversation_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "app.db"
            init_db(db_path)
            project_id = create_project(db_path, "test", "C:/test/model.ifc", "model.ifc")
            conversation_id = create_conversation(db_path, project_id, "chat", "prompt")
            add_audit_event(db_path, project_id, None, "viewer_selection", "completed", {"step_id": 123})
            add_audit_event(db_path, project_id, conversation_id, "agent_run", "started", {})

            events = list_audit_events(db_path, project_id, conversation_id)

            self.assertEqual([event["event_type"] for event in events], ["agent_run", "viewer_selection"])

    def test_selection_endpoint_persists_the_ifc_step_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            model_path = data_dir / "projects" / "test_project" / "model.ifc"
            model_path.parent.mkdir(parents=True)
            shutil.copyfile(SAMPLE_IFC, model_path)
            db_path = data_dir / "app.db"
            init_db(db_path)
            project_id = create_project(db_path, "test", str(model_path), "model.ifc")
            door = next(entity for entity in ifcopenshell.open(model_path).by_type("IfcDoor"))
            door_id = door.id()
            door_global_id = door.GlobalId

            server_url = start_viewer_server(db_path)
            request = Request(
                f"{server_url}/selection",
                data=json.dumps({"project_id": project_id, "step_id": door_id}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=10) as response:
                payload = json.loads(response.read())

            selection = get_viewer_selection(db_path, project_id)
            self.assertEqual(payload["step_id"], door_id)
            self.assertEqual(selection["step_id"], door_id)
            self.assertEqual(selection["ifc_type"], "IfcDoor")
            self.assertEqual(list_audit_events(db_path, project_id)[0]["event_type"], "viewer_selection")

            global_id_request = Request(
                f"{server_url}/selection",
                data=json.dumps({"project_id": project_id, "global_id": door_global_id}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(global_id_request, timeout=10) as response:
                global_id_payload = json.loads(response.read())

            self.assertEqual(global_id_payload["step_id"], door_id)
            self.assertEqual(get_viewer_selection(db_path, project_id)["global_id"], door_global_id)


if __name__ == "__main__":
    unittest.main()
