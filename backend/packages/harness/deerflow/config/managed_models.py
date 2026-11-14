"""Optional encrypted, administrator-managed model overlay; no application imports.

SQLite serializes writers. The entire catalog is encrypted; public metadata is
constructed explicitly. Protect/back up the separate local key, or supply a
Fernet key through DEVPILOT_MODEL_ENCRYPTION_KEY (recommended for deployment).
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROLES = ("general_agent", "report_advisor", "dataset_generator", "evaluator_judge", "review_assistant")
# Stable wire protocols, not a closed list of commercial providers.
# Preserve openai_compatible for existing encrypted catalogs.
PROVIDERS = {
    "openai_compatible": "langchain_openai:ChatOpenAI",
    "openai_responses": "langchain_openai:ChatOpenAI",
    "anthropic": "langchain_anthropic:ChatAnthropic",
    "gemini": "langchain_google_genai:ChatGoogleGenerativeAI",
}


class ModelParameters(BaseModel):
    """Allowlisted sampling/transport settings, never executable SDK kwargs."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    max_tokens: int | None = Field(default=None, ge=1, le=65536)
    timeout_seconds: float = Field(default=60.0, ge=1, le=300)
    max_retries: int = Field(default=0, ge=0, le=2)


class ManagedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(pattern=r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")
    display_name: str = Field(default="", max_length=100)
    provider: str = "openai_compatible"
    provider_name: str = Field(default="", max_length=100)
    parameters: ModelParameters = Field(default_factory=ModelParameters)
    clear_credential: bool = Field(default=False, exclude=True)
    model: str = Field(min_length=1, max_length=200)
    base_url: str = Field(min_length=1, max_length=2048)
    api_key: str | None = Field(default=None, min_length=1, max_length=4096, repr=False, exclude=True)
    enabled: bool = True

    @model_validator(mode="after")
    def credential_intent(self):
        if self.clear_credential and self.api_key is not None:
            raise ValueError("Supply a new credential OR clear the credential, not both")
        return self

    @field_validator("provider")
    @classmethod
    def provider_allowed(cls, value):
        if value not in PROVIDERS:
            raise ValueError("Unsupported provider")
        return value

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        try:
            url = urlsplit(value)
            _ = url.port
        except ValueError:
            raise ValueError("Invalid endpoint") from None
        if url.scheme not in {"http", "https"} or not url.hostname or url.username is not None or url.password is not None or url.query or url.fragment or any(c.isspace() for c in value):
            raise ValueError("Endpoint must be HTTP(S), without credentials, query or fragment")
        return value.rstrip("/")


class ModelCatalog:
    def __init__(self, directory: Path):
        self.directory = Path(directory)

    def _cipher(self):
        key = os.environ.get("DEVPILOT_MODEL_ENCRYPTION_KEY")
        if key:
            return Fernet(key.encode("ascii"))
        target = self.directory / "catalog.key"
        if not target.exists():
            try:
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(Fernet.generate_key())
            except FileExistsError:
                pass
        return Fernet(target.read_bytes())

    @contextmanager
    def _connect(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        db = sqlite3.connect(self.directory / "registry.sqlite3", timeout=5)
        db.execute("CREATE TABLE IF NOT EXISTS catalog (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)")
        try:
            with db:
                yield db
        finally:
            db.close()

    def _load(self, db):
        row = db.execute("SELECT payload FROM catalog WHERE id=1").fetchone()
        if row is None:
            return {"revision": 0, "models": [], "roles": {}, "last_change": None}
        return json.loads(self._cipher().decrypt(row[0]))

    def state(self):
        with self._connect() as db:
            return self._load(db)

    def _update(self, change, *, actor, expected_revision=None):
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            state = self._load(db)
            if expected_revision is not None and state["revision"] != expected_revision:
                raise ValueError("Catalog changed; reload before saving")
            change(state)
            state["revision"] += 1
            state["last_change"] = {"actor": actor, "revision": state["revision"]}
            payload = self._cipher().encrypt(json.dumps(state, ensure_ascii=False).encode())
            db.execute("INSERT INTO catalog(id,payload) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (payload,))
        return self.public()

    def public(self):
        state = self.state()
        return {"revision": state["revision"], "roles": state["roles"], "protocols": list(PROVIDERS), "models": [ManagedModel.model_validate(row).model_dump() | {"has_credential": bool(row.get("api_key"))} for row in state["models"]]}

    def save_model(self, model: ManagedModel, *, actor, expected_revision=None):
        def change(state):
            old = next((row for row in state["models"] if row["name"] == model.name), None)
            if not model.enabled and model.name in state["roles"].values():
                raise ValueError("Unassign roles before disabling this model")
            if old and old.get("api_key") and (old["base_url"] != model.base_url or old["provider"] != model.provider) and model.api_key is None and not model.clear_credential:
                raise ValueError("Endpoint/protocol changed: re-enter or explicitly clear the credential")
            row = model.model_dump()
            row["api_key"] = None if model.clear_credential else model.api_key if model.api_key is not None else (old or {}).get("api_key")
            state["models"] = [entry for entry in state["models"] if entry["name"] != model.name] + [row]
            if len(state["models"]) > 50:
                raise ValueError("At most 50 managed models")

        return self._update(change, actor=actor, expected_revision=expected_revision)

    def assign(self, assignments, *, actor, expected_revision=None):
        def change(state):
            active = {row["name"] for row in state["models"] if row["enabled"]}
            if not isinstance(assignments, dict) or any(role not in ROLES or (name is not None and name not in active) for role, name in assignments.items()):
                raise ValueError("Unknown role or unavailable model")
            state["roles"].update(assignments)

        return self._update(change, actor=actor, expected_revision=expected_revision)

    def delete(self, name, *, actor, expected_revision=None):
        def change(state):
            if name in state["roles"].values():
                raise ValueError("Unassign roles before deleting this model")
            if not any(row["name"] == name for row in state["models"]):
                raise ValueError("Model does not exist")
            state["models"] = [row for row in state["models"] if row["name"] != name]

        return self._update(change, actor=actor, expected_revision=expected_revision)

    def config_models(self, state=None):
        state = state or self.state()
        models = []
        for row in state["models"]:
            profile = ManagedModel.model_validate(row)
            if not profile.enabled:
                continue
            parameters = profile.parameters.model_dump(exclude_none=True)
            parameters["timeout"] = parameters.pop("timeout_seconds")
            config = {
                "name": profile.name,
                "display_name": profile.display_name or profile.name,
                "use": PROVIDERS[profile.provider],
                "model": profile.model,
                "base_url": profile.base_url,
                "api_key": profile.api_key or "not-required",
                **parameters,
            }
            if profile.provider in {"openai_compatible", "openai_responses"}:
                config["use_responses_api"] = profile.provider == "openai_responses"
                if profile.provider == "openai_responses":
                    config.update(output_version="responses/v1", store=False)
            elif profile.provider == "gemini":
                # Explicitly use the API-key Developer API, never ambient Vertex credentials.
                config["vertexai"] = False
            models.append(config)
        return models


def catalog_from_env():
    directory = os.environ.get("DEVPILOT_MODEL_CATALOG_DIR")
    return ModelCatalog(Path(directory)) if directory else None


def catalog_signature():
    catalog = catalog_from_env()
    if catalog is None:
        return None
    target = catalog.directory / "registry.sqlite3"
    try:
        stat = target.stat()
        return (str(target), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
    except FileNotFoundError:
        return (str(target), None)


def overlay_models(config_data):
    catalog = catalog_from_env()
    if catalog is None or not (catalog.directory / "registry.sqlite3").exists():
        return
    state = catalog.state()
    managed = catalog.config_models(state)
    names = {row["name"] for row in state["models"]}
    # Names are reserved by the managed catalog even when disabled.
    operator_models = config_data.get("models") or []
    if names.intersection(row["name"] for row in operator_models):
        raise ValueError("Managed and operator model identifiers conflict; rename the operator entry")
    config_data["models"] = operator_models + managed
    default = state["roles"].get("general_agent")
    if default:
        config_data["models"].sort(key=lambda row: row["name"] != default)
    advisor = state["roles"].get("report_advisor")
    if advisor:
        config_data["reports_agent"] = {**config_data.get("reports_agent", {}), "enabled": True, "model_name": advisor}
