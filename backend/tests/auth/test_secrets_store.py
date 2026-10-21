"""Secrets Manager token store + the Postgres fallback (no AWS needed: a fake client is injected)."""
import json

import pytest
from botocore.exceptions import ClientError, NoCredentialsError

from backend.app.auth import factory
from backend.app.auth.vault import (
    AwsUnavailable,
    FallbackTokenStore,
    InMemoryTokenStore,
    SecretsManagerTokenStore,
)
from runtime.tokens import TokenSet

SERVICE = "11111111-1111-1111-1111-111111111111"
TOKENS = TokenSet(access_token="acc-1", refresh_token="ref-1", expires_at=1234.0)


def _client_error(code: str, operation: str = "Op") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "x"}}, operation)


class FakeSecrets:
    """The few Secrets Manager calls the store uses."""

    def __init__(self):
        self.secrets: dict[str, str] = {}
        self.calls: list[str] = []
        self.error: Exception | None = None

    def _enter(self, op):
        self.calls.append(op)
        if self.error:
            raise self.error

    def get_secret_value(self, SecretId):
        self._enter("get")
        if SecretId not in self.secrets:
            raise _client_error("ResourceNotFoundException")
        return {"SecretString": self.secrets[SecretId]}

    def put_secret_value(self, SecretId, SecretString):
        self._enter("put")
        if SecretId not in self.secrets:
            raise _client_error("ResourceNotFoundException")
        self.secrets[SecretId] = SecretString

    def create_secret(self, Name, SecretString, Description=""):
        self._enter("create")
        if Name in self.secrets:
            raise _client_error("ResourceExistsException")
        self.secrets[Name] = SecretString

    def delete_secret(self, SecretId, ForceDeleteWithoutRecovery=False):
        self._enter("delete")
        assert ForceDeleteWithoutRecovery is True  # otherwise the name stays reserved for days
        if SecretId not in self.secrets:
            raise _client_error("ResourceNotFoundException")
        del self.secrets[SecretId]


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def sm():
    fake = FakeSecrets()
    clock = Clock()
    return SecretsManagerTokenStore(fake, cache_ttl=30, clock=clock), fake, clock


# ---- SecretsManagerTokenStore ----

def test_put_creates_then_updates_one_secret_per_user_and_service(sm):
    store, fake, _ = sm
    store.put("alice", SERVICE, TOKENS)
    assert list(fake.secrets) == [f"mcp-bridge/{SERVICE}/alice"]
    store.put("alice", SERVICE, TOKENS.model_copy(update={"access_token": "acc-2"}))
    assert fake.calls == ["put", "create", "put"]  # first save creates, the second updates
    assert store.get("alice", SERVICE).access_token == "acc-2"
    store.put("bob", SERVICE, TOKENS)
    assert len(fake.secrets) == 2


def test_secret_has_the_token_field_get_user_token_reads(sm):
    store, fake, _ = sm
    store.put("alice", SERVICE, TOKENS)
    body = json.loads(fake.secrets[f"mcp-bridge/{SERVICE}/alice"])
    assert body["token"] == "acc-1" and body["refresh_token"] == "ref-1"


def test_get_round_trip_and_missing_user(sm):
    store, _, _ = sm
    store.put("alice", SERVICE, TOKENS)
    assert store.get("alice", SERVICE) == TOKENS
    assert store.get("nobody", SERVICE) is None


def test_get_is_cached_briefly_and_put_clears_it(sm):
    store, fake, clock = sm
    store.put("alice", SERVICE, TOKENS)
    store.get("alice", SERVICE)
    store.get("alice", SERVICE)
    assert fake.calls.count("get") == 1  # second read served from memory
    clock.now += 31
    store.get("alice", SERVICE)
    assert fake.calls.count("get") == 2  # cache expired
    store.put("alice", SERVICE, TOKENS.model_copy(update={"access_token": "acc-9"}))
    assert store.get("alice", SERVICE).access_token == "acc-9"  # not the stale cached one


def test_delete_removes_the_secret_and_allows_reconnect(sm):
    store, fake, _ = sm
    store.put("alice", SERVICE, TOKENS)
    store.delete("alice", SERVICE)
    assert fake.secrets == {} and store.get("alice", SERVICE) is None
    store.delete("alice", SERVICE)  # already gone: no error
    store.put("alice", SERVICE, TOKENS)
    assert store.get("alice", SERVICE) == TOKENS


def test_create_race_falls_back_to_update(sm):
    store, fake, _ = sm
    original = fake.create_secret

    def racing_create(Name, SecretString, Description=""):
        fake.secrets[Name] = "{}"  # another request created it first
        return original(Name, SecretString, Description)

    fake.create_secret = racing_create
    store.put("alice", SERVICE, TOKENS)
    assert store.get("alice", SERVICE) == TOKENS


@pytest.mark.parametrize("user, service", [("../x", SERVICE), ("a/b", SERVICE), ("", SERVICE), ("alice", "../s")])
def test_names_are_validated_before_any_aws_call(sm, user, service):
    store, fake, _ = sm
    with pytest.raises(ValueError):
        store.put(user, service, TOKENS)
    with pytest.raises(ValueError):
        store.get(user, service)
    assert fake.calls == []


@pytest.mark.parametrize("error", [
    _client_error("AccessDeniedException"),
    _client_error("ThrottlingException"),
    NoCredentialsError(),
])
def test_aws_trouble_becomes_aws_unavailable(sm, error):
    store, fake, _ = sm
    fake.error = error
    for call in (lambda: store.get("alice", SERVICE), lambda: store.put("alice", SERVICE, TOKENS),
                 lambda: store.delete("alice", SERVICE)):
        with pytest.raises(AwsUnavailable):
            call()


def test_garbage_secret_is_treated_as_not_connected(sm):
    store, fake, _ = sm
    fake.secrets[f"mcp-bridge/{SERVICE}/alice"] = "not json"
    assert store.get("alice", SERVICE) is None


# ---- FallbackTokenStore ----

@pytest.fixture
def pair(sm):
    store, fake, clock = sm
    postgres = InMemoryTokenStore()  # stands in for the Postgres store
    built = []

    def factory_():
        built.append(1)
        return postgres

    fallback = FallbackTokenStore(store, factory_, retry_after=60, clock=clock)
    return fallback, fake, postgres, built, clock


def test_healthy_aws_never_touches_postgres(pair):
    fallback, fake, postgres, built, _ = pair
    fallback.put("alice", SERVICE, TOKENS)
    assert fallback.get("alice", SERVICE) == TOKENS
    assert len(fake.secrets) == 1 and postgres.get("alice", SERVICE) is None
    assert built == []


def test_unknown_user_checks_the_fallback_too(pair):
    fallback, _, postgres, built, _ = pair
    assert fallback.get("nobody", SERVICE) is None
    postgres.put("late", SERVICE, TOKENS)  # saved there during an earlier outage
    assert fallback.get("late", SERVICE) == TOKENS
    assert built == [1]


def test_aws_down_saves_and_reads_from_postgres(pair):
    fallback, fake, postgres, _, _ = pair
    fake.error = NoCredentialsError()
    fallback.put("alice", SERVICE, TOKENS)
    assert postgres.get("alice", SERVICE) == TOKENS
    assert fallback.get("alice", SERVICE) == TOKENS


def test_failed_aws_is_skipped_until_the_retry_time(pair):
    fallback, fake, _, _, clock = pair
    fake.error = NoCredentialsError()
    fallback.put("alice", SERVICE, TOKENS)
    fake.calls.clear()
    fallback.get("alice", SERVICE)
    fallback.put("alice", SERVICE, TOKENS)
    assert fake.calls == []  # AWS not retried for 60s
    clock.now += 61
    fake.error = None  # AWS is back
    fallback.put("alice", SERVICE, TOKENS.model_copy(update={"access_token": "acc-aws"}))
    assert fake.calls and fallback.get("alice", SERVICE).access_token == "acc-aws"  # preferred again


def test_delete_clears_both_stores(pair):
    fallback, fake, postgres, _, _ = pair
    fallback.put("alice", SERVICE, TOKENS)
    postgres.put("alice", SERVICE, TOKENS)
    fallback.delete("alice", SERVICE)
    assert fake.secrets == {} and postgres.get("alice", SERVICE) is None
    assert fallback.get("alice", SERVICE) is None


def test_broken_postgres_does_not_hide_an_aws_miss(sm):
    store, _, clock = sm

    def broken():
        raise RuntimeError("postgres down")

    fallback = FallbackTokenStore(store, broken, clock=clock)
    assert fallback.get("nobody", SERVICE) is None  # AWS answered "not connected"


def test_both_down_raises(sm):
    store, fake, clock = sm
    fake.error = NoCredentialsError()

    def broken():
        raise RuntimeError("postgres down")

    fallback = FallbackTokenStore(store, broken, clock=clock)
    with pytest.raises(RuntimeError):
        fallback.put("alice", SERVICE, TOKENS)


# ---- factory wiring ----

def test_factory_builds_the_fallback_store_for_secrets(dev3_env):
    dev3_env(TOKEN_PROVIDER="secrets")
    factory.reset()
    assert isinstance(factory.get_token_store(), FallbackTokenStore)
    assert factory.get_token_provider() is not None  # StoreTokenProvider, no RuntimeError
