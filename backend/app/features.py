"""What is built and what isn't, served at GET /features so the UI can flag it honestly.

Keep this list current: the frontend shows a "Not built yet" badge next to each feature here
that isn't "built", and the launcher lists them all.
"""
from fastapi import APIRouter

router = APIRouter(tags=["meta"])

FEATURES = [
    {"id": "alexa_registration", "title": "Real Alexa+ registration", "status": "not_built",
     "detail": "The Alexa+ MCP toolkit is partner-only. Publishing runs a mock registrar; the MCP URL "
               "works with any MCP client, but nothing is registered with Alexa.",
     "where": ["client.publish.registering", "review.catalog"]},
    {"id": "llm_routing", "title": "LLM intent routing in Ask mode", "status": "not_built",
     "detail": "Ask mode matches what you say to a tool using each service's example phrases and "
               "templates (no LLM). An LLM router is a planned stretch goal.",
     "where": ["client.simulator.ask"]},
    {"id": "alexa_account_linking", "title": "Alexa account linking", "status": "not_built",
     "detail": "Users sign in with a demo username. Real Alexa account linking (our own OAuth "
               "server for Alexa) is a stretch goal.",
     "where": ["client.login"]},
    {"id": "aws_mode", "title": "AWS mode on EC2 (S3, Secrets Manager, SES)", "status": "partial",
     "detail": "Implemented and unit tested, not yet run on EC2. The local demo stores bundles on "
               "disk, tokens in Postgres and emails in an outbox folder.",
     "where": ["launcher"]},
]


@router.get("/features")
def features() -> list[dict]:
    return FEATURES
