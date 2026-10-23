"""Ask mode: match what the user said to a tool of their services and answer with the business's
own templates (see router.py and engine.py). By default the matching is rule-based, from the
phrases in the database; with ASSISTANT=llm a Bedrock model does the matching (llm.py)."""
