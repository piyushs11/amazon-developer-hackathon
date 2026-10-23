"""Spoken answers from the templates a business wrote in its manifest (x-alexa).

    {field}            a field of the result: "Order {order_id} is {status}."
    {count:path}       number of items in a list: "{count:results} dishes"
    {list:path.field}  "a, b and c" from a field of each item (first 3)

Unknown placeholders are dropped rather than read out as "{status}".
"""
import re

_PLACEHOLDER = re.compile(r"\{(?:(count|list):)?([A-Za-z0-9_.]+)\}")


def _get(data, path: str):
    for part in path.split("."):
        if isinstance(data, dict):
            data = data.get(part)
        else:
            return None
    return data


def list_names(items: list[str]) -> str:
    items = [str(i) for i in items if i not in (None, "")]
    if len(items) <= 1:
        return items[0] if items else ""
    return ", ".join(items[:-1]) + " and " + items[-1]


def render(template: str | None, data: dict | None) -> str:
    if not template:
        return ""
    data = data or {}

    def one(m: re.Match) -> str:
        fn, path = m.group(1), m.group(2)
        if fn == "count":
            value = _get(data, path)
            return str(len(value)) if isinstance(value, list) else "0"
        if fn == "list":
            list_path, _, field = path.rpartition(".")
            items = _get(data, list_path) if list_path else None
            if not isinstance(items, list):
                return ""
            return list_names([(i.get(field) if isinstance(i, dict) else i) for i in items[:3]])
        value = _get(data, path)
        return "" if value is None or isinstance(value, (dict, list)) else str(value)

    text = _PLACEHOLDER.sub(one, template)
    return re.sub(r"\s{2,}", " ", text).replace(" .", ".").strip()


def first_list(data: dict | None) -> list | None:
    """The first list value in a result (used to tell an empty answer apart)."""
    for value in (data or {}).values():
        if isinstance(value, list):
            return value
    return None


def speak(tool_profile: dict | None, data: dict | None, *, is_error: bool, status: int | None,
          fallback: str = "") -> str:
    """What Alexa says for one tool result, from that tool's profile templates."""
    tp = tool_profile or {}
    if is_error:
        errors = tp.get("error_responses") or {}
        if status is not None and str(status) in errors:
            return errors[str(status)]
        return fallback or "Something went wrong with that request."
    items = first_list(data)
    if items is not None and not items and tp.get("empty_response"):
        return tp["empty_response"]
    return render(tp.get("speakable_response"), data) or fallback
