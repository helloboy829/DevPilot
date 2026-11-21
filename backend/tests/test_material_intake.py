import pytest
from pydantic import ValidationError

from app.evaluation.material_intake import MaterialBatchCreate, initial_component_states


def test_manifest_requires_components():
    with pytest.raises(ValidationError):
        MaterialBatchCreate.model_validate({"name": "Synthetic", "components": []})


def test_manifest_preserves_component_denominator():
    manifest = MaterialBatchCreate.model_validate(
        {
            "name": "Synthetic",
            "components": [{"component_id": "c1", "name": "LLM", "kind": "llm", "purpose": "QA"}],
        }
    )
    assert initial_component_states(manifest) == [{"component_id": "c1", "status": "pending", "reason": None}]


def test_manifest_rejects_duplicate_component_ids():
    item = {"component_id": "c1", "name": "LLM", "kind": "llm", "purpose": "QA"}
    with pytest.raises(ValidationError):
        MaterialBatchCreate.model_validate({"name": "Synthetic", "components": [item, item]})


def test_manifest_requires_explicit_attachment_mapping():
    with pytest.raises(ValidationError, match="attachment"):
        MaterialBatchCreate.model_validate(
            {
                "name": "Synthetic",
                "components": [
                    {
                        "component_id": "c1",
                        "name": "LLM",
                        "kind": "llm",
                        "purpose": "QA",
                        "attachment_ids": ["att_unknown"],
                    }
                ],
                "attachments": [],
            }
        )


def test_manifest_accepts_fully_authorized_mapped_attachment():
    manifest = MaterialBatchCreate.model_validate(
        {
            "name": "Synthetic",
            "components": [
                {
                    "component_id": "c1",
                    "name": "LLM",
                    "kind": "llm",
                    "purpose": "QA",
                    "attachment_ids": ["att_1"],
                }
            ],
            "attachments": [
                {
                    "attachment_id": "att_1",
                    "file_name": "cases.jsonl",
                    "authorization_basis": "user_provided",
                    "purpose": "evaluation_data",
                    "sensitivity": "internal",
                    "retention_until": "2030-01-01T00:00:00Z",
                }
            ],
        }
    )
    assert manifest.attachments[0].file_name == "cases.jsonl"
    assert manifest.components[0].attachment_ids == ["att_1"]


def test_attachment_requires_authorization_sensitivity_and_retention():
    with pytest.raises(ValidationError):
        MaterialBatchCreate.model_validate(
            {
                "name": "Synthetic",
                "components": [
                    {
                        "component_id": "c1",
                        "name": "LLM",
                        "kind": "llm",
                        "purpose": "QA",
                        "attachment_ids": ["att_1"],
                    }
                ],
                "attachments": [{"attachment_id": "att_1", "file_name": "cases.jsonl"}],
            }
        )


@pytest.mark.parametrize("file_name", ["../cases.jsonl", "folder\\cases.jsonl", "", ".", ".."])
def test_attachment_rejects_non_basename_file_names(file_name):
    with pytest.raises(ValidationError):
        MaterialBatchCreate.model_validate(
            {
                "name": "Synthetic",
                "components": [
                    {
                        "component_id": "c1",
                        "name": "LLM",
                        "kind": "llm",
                        "purpose": "QA",
                        "attachment_ids": ["att_1"],
                    }
                ],
                "attachments": [
                    {
                        "attachment_id": "att_1",
                        "file_name": file_name,
                        "authorization_basis": "user_provided",
                        "purpose": "evaluation_data",
                        "sensitivity": "internal",
                        "retention_until": "2030-01-01T00:00:00Z",
                    }
                ],
            }
        )


@pytest.mark.parametrize("file_name", ["macro.docm", "macro.xlsm", "payload.exe", "archive.zip"])
def test_attachment_rejects_unsupported_file_extensions(file_name):
    with pytest.raises(ValidationError):
        MaterialBatchCreate.model_validate(
            {
                "name": "Synthetic",
                "components": [{"component_id": "c1", "name": "Model", "kind": "llm", "purpose": "QA", "attachment_ids": ["att_1"]}],
                "attachments": [
                    {
                        "attachment_id": "att_1",
                        "file_name": file_name,
                        "authorization_basis": "user_provided",
                        "purpose": "evaluation_data",
                        "sensitivity": "internal",
                        "retention_until": "2099-01-01T00:00:00Z",
                    }
                ],
            }
        )
