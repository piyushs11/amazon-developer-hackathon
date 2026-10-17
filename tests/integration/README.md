# integration tests

**Owner:** All (Dev 2 wrote the four below)

One test per component. Each runs the real code the way the pipeline calls it, with earlier steps
emulated by running the real earlier functions, and compares the output with expected files.
No Bedrock, AWS or internet is used.

| Folder | Component | Success case | Failure case |
|---|---|---|---|
| `generate_folder/` | mapped JSON -> generated folder structure | tree matches expected | invalid JSON refused, no folder |
| `verify_endpoint/` | `hit_endpoint` against a fake API with the `_dev` token | `verified` | 401 x5, patch loop, email |
| `mail/` | `notify_unresolved` failure email | email + attachment correct | SES error, returns `failed` |
| `client_call/` | `call_api` runtime tool call | user's token reaches the API | unconnected user, no API call |

## Layout of every component folder
```
<component>/
  test_<component>.py      what it checks is written at the top of the file
  inputs/README.md         every input file, the function argument it feeds, and its format
  inputs/<case>/           input files for case "success" / "failure"
  expected/<case>/         expected output files
```
`run_integration(case) -> bool` returns `True` when the real output matches the expected files.
pytest asserts it; the module can also run alone (prints PASS/FAIL, exit code 1 on failure).

## Running
```
python3 -m pytest tests/integration -v
python3 -m tests.integration.mail.test_mail        # one component
```
Needs Redis running (`brew services start redis`; tests use db 15) and `jq`. A missing
prerequisite makes the test skip with the reason.

## Adding a case
Add `inputs/<case>/` and `expected/<case>/`, then add the case name to `CASES` in the test module
(or call `run_integration("<case>")`). Shared helpers (fake API, scripted LLM, comparisons) are
in `harness.py`. On a mismatch the diff is printed (pytest shows it for failing tests).
