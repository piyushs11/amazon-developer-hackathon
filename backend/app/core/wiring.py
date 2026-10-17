"""Single place that picks fake or real implementations by MODE."""
# def get_spec_source(): ...    # Dev 1
# def get_mapper(): ...         # Dev 1
# def get_storage(): ...        # Dev 2

# ---- Dev 3 (each reads TOKEN_PROVIDER / IDENTITY / REGISTRY / DEPLOYER from env) ----
from backend.app.auth.factory import get_identity, get_mapping, get_token_provider  # noqa: F401
from backend.app.deploy import get_deployer, get_registrar  # noqa: F401
from backend.app.gateway.bundles import get_registry  # noqa: F401
