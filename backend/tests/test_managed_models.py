import pytest

from deerflow.config.managed_models import ManagedModel, ModelCatalog


def model(**changes):
    return ManagedModel.model_validate(dict(name="demo", model="synthetic", base_url="https://models.example.test/v1", api_key="synthetic-secret", **changes))


def test_encrypted_registry_and_write_only_credentials(tmp_path):
    catalog = ModelCatalog(tmp_path)
    catalog.save_model(model(), actor="synthetic-admin")
    assert b"synthetic-secret" not in (tmp_path / "registry.sqlite3").read_bytes()
    public = catalog.public()
    assert "api_key" not in str(public)
    assert public["models"][0]["has_credential"] is True
    assert catalog.config_models()[0]["api_key"] == "synthetic-secret"
    catalog.save_model(ManagedModel(name="demo", model="changed", base_url="https://models.example.test/v1"), actor="synthetic-admin")
    assert catalog.config_models()[0]["api_key"] == "synthetic-secret"
    assert ModelCatalog(tmp_path).public()["revision"] == 2


def test_roles_prevent_dangling_or_disabled_models(tmp_path):
    catalog = ModelCatalog(tmp_path)
    catalog.save_model(model(), actor="admin")
    catalog.assign({"report_advisor": "demo", "general_agent": "demo"}, actor="admin")
    with pytest.raises(ValueError):
        catalog.delete("demo", actor="admin")
    with pytest.raises(ValueError):
        catalog.save_model(ManagedModel(name="demo", model="demo", base_url="https://models.example.test", enabled=False), actor="admin")
    with pytest.raises(ValueError):
        catalog.assign({"arbitrary_code": "demo"}, actor="admin")
    catalog.assign({"report_advisor": None, "general_agent": None}, actor="admin")
    catalog.delete("demo", actor="admin")
    assert catalog.public()["models"] == []


def test_no_arbitrary_import_or_url_credentials():
    with pytest.raises(ValueError):
        ManagedModel(name="demo", model="x", base_url="https://example.test", use="os.system")
    with pytest.raises(ValueError):
        ManagedModel(name="demo", model="x", base_url="https://secret@example.test")


@pytest.mark.parametrize(
    "protocol,adapter",
    [
        ("openai_compatible", "langchain_openai:ChatOpenAI"),
        ("openai_responses", "langchain_openai:ChatOpenAI"),
        ("anthropic", "langchain_anthropic:ChatAnthropic"),
        ("gemini", "langchain_google_genai:ChatGoogleGenerativeAI"),
    ],
)
def test_four_protocol_profiles_construct_real_sdk_without_network(tmp_path, protocol, adapter):
    from deerflow.config.app_config import AppConfig
    from deerflow.config.model_config import ModelConfig
    from deerflow.models import create_chat_model

    catalog = ModelCatalog(tmp_path)
    profile = ManagedModel(
        name="demo", provider=protocol, provider_name="Synthetic gateway", model="synthetic-model", base_url="https://models.example.test", api_key="synthetic-key", parameters={"temperature": 0.5, "max_tokens": 100, "timeout_seconds": 30.0}
    )
    catalog.save_model(profile, actor="admin")
    settings = catalog.config_models()[0]
    assert settings["use"] == adapter
    config = AppConfig.model_validate({"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "models": [ModelConfig(**settings)]})
    client = create_chat_model(name="demo", app_config=config, attach_tracing=False)
    assert client is not None
    assert client.temperature == 0.5
    if protocol.startswith("openai"):
        assert client.use_responses_api is (protocol == "openai_responses")
    if protocol == "openai_responses":
        assert client.store is False
    if protocol == "gemini":
        assert client.vertexai is False
    public = catalog.public()["models"][0]
    assert public["provider_name"] == "Synthetic gateway"
    assert public["parameters"]["max_tokens"] == 100


def test_profile_parameters_are_bounded_and_not_an_arbitrary_sdk_escape_hatch():
    for parameters in [{"temperature": 3.0}, {"temperature": float("nan")}, {"timeout_seconds": 1000}, {"max_retries": 3}, {"max_tokens": -1}, {"callbacks": []}, {"default_headers": {"Authorization": "synthetic"}}]:
        with pytest.raises(ValueError):
            ManagedModel(name="demo", model="demo", base_url="https://example.test", parameters=parameters)


def test_endpoint_or_protocol_change_requires_explicit_credential_decision(tmp_path):
    catalog = ModelCatalog(tmp_path)
    catalog.save_model(model(), actor="admin")
    with pytest.raises(ValueError, match="credential"):
        catalog.save_model(ManagedModel(name="demo", model="new", base_url="https://other.example.test"), actor="admin")
    with pytest.raises(ValueError, match="credential"):
        catalog.save_model(ManagedModel(name="demo", model="new", provider="anthropic", base_url="https://models.example.test/v1"), actor="admin")
    catalog.save_model(ManagedModel(name="demo", model="new", base_url="https://other.example.test", clear_credential=True), actor="admin")
    assert catalog.public()["models"][0]["has_credential"] is False
    assert "clear_credential" not in catalog.state()["models"][0]


def test_old_profiles_get_defaults_without_catalog_rewrite(tmp_path):
    catalog = ModelCatalog(tmp_path)
    catalog.save_model(model(), actor="admin")
    catalog._update(lambda state: [row.pop(key, None) for row in state["models"] for key in ("parameters", "provider_name")], actor="admin")
    assert catalog.public()["models"][0]["parameters"]["max_retries"] == 0
    assert catalog.public()["models"][0]["provider_name"] == ""
    assert catalog.config_models()[0]["use_responses_api"] is False


@pytest.mark.parametrize("protocol", ["openai_compatible", "openai_responses", "anthropic", "gemini"])
def test_managed_profile_overlay_preserves_operator_models_and_routes_roles(tmp_path, monkeypatch, protocol):
    from deerflow.config.managed_models import catalog_from_env, catalog_signature, overlay_models

    monkeypatch.setenv("DEVPILOT_MODEL_CATALOG_DIR", str(tmp_path))
    catalog = catalog_from_env()
    catalog.save_model(model(provider=protocol), actor="synthetic-admin")
    catalog.assign({"general_agent": "demo", "report_advisor": "demo"}, actor="synthetic-admin")
    operator = {"name": "operator", "model": "synthetic", "use": "langchain_openai:ChatOpenAI"}
    config = {"models": [operator], "reports_agent": {"enabled": False}}
    overlay_models(config)
    assert config["models"][0]["name"] == "demo"
    assert config["models"][1] == operator
    assert config["reports_agent"]["model_name"] == "demo"
    assert config["reports_agent"]["enabled"] is True
    assert catalog_signature() is not None
    with pytest.raises(ValueError, match="conflict"):
        overlay_models({"models": [{"name": "demo"}]})
