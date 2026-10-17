# generate_folder inputs

Function under test: `load_mapped_service(uuid, storage)` then `generate(mapped, out_dir)`
(`backend/app/pipeline/flow_onboard.py`, runs `create_folders.sh`).

Each case folder (`success/`, `failure/`) holds:

| File | Feeds | Format |
|---|---|---|
| `mapped_service.json` | the JSON the mapper stored as `mapped.{uuid}.json`; setup writes it with `LocalStorage.write_mapped` | MappedService (contract C2): `service_uuid`, `service_name`, `base_url`, `endpoints[]` each with `endpoint_id`, `tool_name`, `method`, `description`, `path_template`, `read_only`, `params[]` (`name`, `python_type`, `json_type`, `required`, `location`, `description`), `input_schema` |
| `setup.json` | the only argument the caller has | `{"service_uuid": "<uuid>"}` |

Expected output (`../expected/<case>/`):
- `success`: `folder/demo_bistro/*.py`, the whole generated tree (compared byte for byte).
- `failure`: `result.json` = `{"error_code": ..., "folder_created": false}`.
