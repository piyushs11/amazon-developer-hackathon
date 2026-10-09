import os

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--disable-tests",
        action="store_true",
        default=False,
        help="Skip every test in the project (same as DISABLE_TESTS=1).",
    )


def _disabled(config) -> bool:
    env = os.getenv("DISABLE_TESTS", "").strip().lower()
    return config.getoption("--disable-tests") or env in {"1", "true", "yes", "on"}


def pytest_collection_modifyitems(config, items):
    if not _disabled(config):
        return
    skip = pytest.mark.skip(reason="tests disabled (--disable-tests / DISABLE_TESTS)")
    for item in items:
        item.add_marker(skip)
