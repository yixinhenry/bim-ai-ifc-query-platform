import tempfile
import unittest
from pathlib import Path

from bim_ai.agent import _active_model_context


class ActiveModelContextTests(unittest.TestCase):
    def test_keeps_the_application_model_authoritative(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            model_path = Path(temp_dir) / "model.ifc"
            model_path.write_text("ISO-10303-21;", encoding="utf-8")

            context = _active_model_context(str(model_path))

            self.assertIn(str(model_path.resolve()), context)
            self.assertIn("already been loaded into the current IFC MCP session", context)
            self.assertIn("Do not ask the user for a file path", context)

    def test_fails_early_for_a_missing_model(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.ifc"
            with self.assertRaisesRegex(FileNotFoundError, "Project IFC file is unavailable"):
                _active_model_context(str(missing_path))


if __name__ == "__main__":
    unittest.main()
