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
