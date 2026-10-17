import os

from backend.app.deploy.deployer import FakeDeployer, GatewayDeployer, MockRegistrar, mcp_url

__all__ = ["FakeDeployer", "GatewayDeployer", "MockRegistrar", "get_deployer", "get_registrar",
           "mcp_url"]


def get_deployer():
    """DEPLOYER=gateway (default) | fake."""
    return FakeDeployer() if os.getenv("DEPLOYER") == "fake" else GatewayDeployer()


def get_registrar():
    # AlexaRegistrar (wrapping `alexa-ai deploy`) only if we get partner access.
    return MockRegistrar()
