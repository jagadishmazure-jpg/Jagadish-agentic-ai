"""The optional Azure OpenAI script: dry run by default, never touches the network in tests."""

import builtins
import urllib.request

import pytest

from finetune_lab import azure_finetune as az


@pytest.fixture
def no_network(monkeypatch):
    real_import = builtins.__import__

    def guarded(name, *a, **kw):
        if name == "openai" or name.startswith("openai."):
            raise AssertionError("dry run must not import the OpenAI SDK")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", guarded)
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("network"))


def test_dry_run_plans_every_request_without_network(no_network, capsys):
    assert az.main(["--deploy", "--epochs", "3"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "fine_tuning.jobs.create" in out
    assert "trainingType" in out and "api-version=2024-10-01" in out
    plan = az.plan(az.parser().parse_args(["--epochs", "3"]))
    assert plan["job"]["method"]["supervised"]["hyperparameters"] == {"n_epochs": 3}
    assert plan["files"]["training"]["examples"] >= az.MIN_TRAIN


def test_execute_requires_env_vars(monkeypatch):
    for name in (*az.DATA_ENV, "CI", "PYTEST_CURRENT_TEST"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match="AZURE_OPENAI_ENDPOINT"):
        az.execute(az.parser().parse_args(["--execute"]), {})


def test_execute_refuses_to_run_in_ci_or_tests(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.invalid")
    with pytest.raises(SystemExit, match="refusing"):
        az.execute(az.parser().parse_args(["--execute"]), {})


@pytest.mark.parametrize(
    "argv,msg",
    [(["--model", "o4-mini-2025-04-16"], "not an SFT"), (["--suffix", "v1.2"], "suffix")],
)
def test_invalid_requests_are_rejected_before_anything_is_sent(argv, msg, no_network, capsys):
    assert az.main(argv) == 2
    assert msg in capsys.readouterr().err


def test_upload_copy_is_utf8_with_bom(tmp_path):
    src = tmp_path / "train.jsonl"
    src.write_text('{"messages": []}\n', encoding="utf-8")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    assert az.with_bom(src, out_dir).read_bytes().startswith(b"\xef\xbb\xbf")


class _FakeCredential:
    def __init__(self):
        self.scopes = []

    def get_token(self, *scopes, **kw):
        self.scopes.extend(scopes)
        return type("Token", (), {"token": "fake-arm-token", "expires_on": 0})()


def test_plan_documents_keyless_auth_and_roles(no_network):
    plan = az.plan(az.parser().parse_args(["--deploy"]))
    assert "no API key" in plan["auth"]["method"]
    assert plan["auth"]["data_plane"] == {"scope": az.DATA_SCOPE, "role": az.DATA_ROLE}
    assert plan["auth"]["control_plane"]["scope"] == az.MGMT_SCOPE
    assert not any("KEY" in n or "TOKEN" in n for n in az.DATA_ENV + az.DEPLOY_ENV)


def test_data_client_uses_an_entra_token_provider_not_a_key(monkeypatch):
    import openai

    seen = {}

    class Recorder:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setattr(openai, "OpenAI", Recorder)
    cred = _FakeCredential()
    az.data_client("https://example.invalid/", cred)
    assert seen["base_url"] == "https://example.invalid/openai/v1/"
    assert callable(seen["api_key"])  # a token provider, never a static key
    assert seen["api_key"]() == "fake-arm-token" and cred.scopes == [az.DATA_SCOPE]


def test_deploy_token_comes_from_the_credential_for_the_arm_scope():
    cred = _FakeCredential()
    assert az.management_token(cred) == "fake-arm-token"
    assert cred.scopes == [az.MGMT_SCOPE]
