"""Conversation memory for the LLM router (ASSISTANT=llm): a summary buffer.

The model is stateless, so every turn it is handed what happened so far, in two parts:

  _recent    the last few messages, word for word (user + Alexa, with a note of any tool that ran
             and any items shown, so "the first one" or "two of those" can be resolved)
  _summary   a short rolling summary of everything older, written by the model itself

When `_recent` grows past TRIGGER messages, the oldest ones are folded into `_summary` and only
the last KEEP stay verbatim. So the prompt stays small however long the chat gets.

Both live inside the `memory` dict the client already sends back every turn, so no server-side
session store is needed. Keys starting with "_" are bookkeeping: they are never offered to the
model as "known values" and never used as tool arguments (those are keyed by parameter name).

This module is plain data handling. The model call that writes the summary is passed in
(`llm.summarise`), which keeps the import one-way: llm.py uses this module, not the reverse.
"""
import logging

log = logging.getLogger(__name__)

RECENT_KEY = "_recent"
SUMMARY_KEY = "_summary"

TRIGGER = 6  # fold when more than this many messages are kept word for word
KEEP = 4  # ...leaving this many (the last two exchanges)
MAX_ENTRY_CHARS = 300  # one message
MAX_SUMMARY_CHARS = 700


def _clip(text: str, limit: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def recent(memory: dict | None) -> list[dict]:
    """The verbatim messages, tolerating anything odd the client sent back."""
    out = []
    for m in (memory or {}).get(RECENT_KEY) or []:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("text"), str):
            out.append({"role": m["role"], "text": m["text"]})
    return out


def summary(memory: dict | None) -> str:
    s = (memory or {}).get(SUMMARY_KEY)
    return s.strip() if isinstance(s, str) else ""


def record(memory: dict, *, user: str, alexa: str, note: str = "", summarise=None) -> None:
    """Add one exchange to `memory` (in place), folding old messages into the summary when needed.

    `summarise(previous_summary, old_messages) -> str` writes the new summary; if it is missing or
    raises, the old messages are folded in crudely (what the user asked) so nothing breaks."""
    reply = _clip(alexa, MAX_ENTRY_CHARS)
    if note:
        reply = _clip(f"{reply} {note}", MAX_ENTRY_CHARS + 200)
    msgs = recent(memory) + [
        {"role": "user", "text": _clip(user, MAX_ENTRY_CHARS)},
        {"role": "assistant", "text": reply},
    ]
    if len(msgs) > TRIGGER:
        old, msgs = msgs[:-KEEP], msgs[-KEEP:]
        previous = summary(memory)
        try:
            if summarise is None:
                raise RuntimeError("no summariser")
            folded = summarise(previous, old)
        except Exception as e:  # noqa: BLE001 - never lose a turn over a failed summary
            log.warning("assistant memory summary failed (%s: %s); folding crudely", type(e).__name__, e)
            asked = "; ".join(m["text"] for m in old if m["role"] == "user")
            folded = f"{previous} Earlier the user asked: {asked}".strip()
        memory[SUMMARY_KEY] = _clip(folded, MAX_SUMMARY_CHARS)
    memory[RECENT_KEY] = msgs


def messages(memory: dict | None, text: str) -> list[dict]:
    """Converse `messages`: the verbatim history, then the new request. Bedrock needs roles to
    alternate, start with the user and end with the user, so neighbours with the same role are
    merged and a leading assistant message is dropped."""
    chat: list[dict] = []
    for m in recent(memory) + [{"role": "user", "text": text}]:
        if chat and chat[-1]["role"] == m["role"]:
            chat[-1]["text"] += "\n" + m["text"]
        else:
            chat.append(dict(m))
    while chat and chat[0]["role"] != "user":
        chat.pop(0)
    return [{"role": m["role"], "content": [{"text": m["text"]}]} for m in chat]


def context(memory: dict | None) -> str:
    """The summary, worded for the system prompt ('' when there is none yet)."""
    s = summary(memory)
    return f"Summary of the earlier conversation: {s}" if s else ""
