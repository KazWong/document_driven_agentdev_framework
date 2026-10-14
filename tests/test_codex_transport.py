import ast
import importlib.util
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "providers/codex/driver.py"


def load_driver():
    spec = importlib.util.spec_from_file_location("codex_driver", DRIVER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_codex_transport_schema_is_strict_and_root_object():
    driver = load_driver()
    schema = driver.transport_schema()
    assert schema == {
        "type": "object",
        "properties": {"payload": {"type": "string"}},
        "required": ["payload"],
        "additionalProperties": False,
    }


def test_codex_transport_decodes_canonical_role_object():
    driver = load_driver()
    role_output = {
        "role": "planner",
        "artifact_type": "planning",
        "findings": [],
    }
    assert driver.decode_transport({"payload": json.dumps(role_output)}) == role_output


def test_codex_transport_rejects_non_object_payload():
    driver = load_driver()
    for value in (
        {},
        {"payload": "[]"},
        {"payload": "{}", "extra": "no"},
        {"payload": 1},
    ):
        try:
            driver.decode_transport(value)
        except (ValueError, json.JSONDecodeError):
            pass
        else:
            raise AssertionError(f"accepted invalid transport: {value!r}")


def test_worker_driver_remains_python310_stdlib_only():
    tree = ast.parse(DRIVER.read_text(), feature_version=(3, 10))
    imports = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.add((node.module or "").split(".")[0])
    assert imports <= sys.stdlib_module_names
