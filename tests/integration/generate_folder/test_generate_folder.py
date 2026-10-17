"""Integration test: mapped service JSON  ->  generated folder structure.

WHAT THIS CHECKS
  The path a mapped service takes before any verification happens:
    Dev 1's mapper stores mapped.{uuid}.json  (emulated in the setup by write_mapped)
    -> load_mapped_service(uuid) reads and validates it
    -> generate(mapped, out_dir) runs create_folders.sh on it
  success: the generated demo_bistro/ folder (one file per tool + demo_bistro_tools.py) is
           identical, file for file and byte for byte, to expected/success/folder/.
  failure: a mapped JSON with an invalid endpoint name is refused by the loader
           (error code "mapped_invalid") and no folder is created (expected/failure/result.json).

run_integration(case) returns True when the real output matches the expected files.
Inputs are described in inputs/README.md. Needs `jq` (used by create_folders.sh).
"""

import tempfile
from pathlib import Path

import pytest

from backend.app.codegen.verifier.utilities import MappedServiceError, load_mapped_service
from backend.app.pipeline.flow_onboard import generate
from backend.app.storage.add_n_read_mcp_tool import LocalStorage
from tests.integration.harness import (
    CASES,
    assert_case,
    compare_json,
    compare_tree,
    load_json,
    main,
    require_jq,
)

HERE = Path(__file__).parent


def run_integration(case: str) -> bool:
    require_jq()
    inputs, expected = HERE / "inputs" / case, HERE / "expected" / case
    mapped = load_json(inputs / "mapped_service.json")  # what the mapper produced
    service_uuid = load_json(inputs / "setup.json")["service_uuid"]  # the only thing the caller knows

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        storage = LocalStorage(tmp / "bundles", tmp / "mapped")
        storage.write_mapped(service_uuid, mapped)  # setup: emulate the mapper's output in storage
        out_dir = tmp / "out"

        try:
            loaded = load_mapped_service(service_uuid, storage)  # step 1: read it back by uuid
            generate(loaded, str(out_dir))  # step 2: render the folder structure
        except MappedServiceError as e:
            # failure path: the loader refused the JSON, so the generator must never have run
            actual = {"error_code": e.code, "folder_created": out_dir.exists()}
            return compare_json(actual, expected / "result.json")

        # success path: the whole generated tree must equal the expected tree
        return compare_tree(out_dir, expected / "folder")


@pytest.mark.parametrize("case", CASES)
def test_integration(case):
    assert_case(run_integration, case)


if __name__ == "__main__":
    main(run_integration)
