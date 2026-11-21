"""Owner-scoped metadata API for project-external evaluation materials."""

import asyncio
import hashlib
import json
import logging
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, File, HTTPException, Query, Request, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from app.evaluation.material_artifact_store import MaterialArtifactConflict, MaterialArtifactStorageError, MaterialArtifactTooLarge
from app.evaluation.material_intake import MaterialBatchCreate
from app.evaluation.material_parser import parse_material
from app.evaluation.repository import Conflict, NotFound
from app.gateway.authz import require_permission
from app.gateway.deps import get_optional_user_from_request
from app.gateway.private_route import PrivateValidationRoute
from app.gateway.routers.evaluation_projects import _require_human

logger = logging.getLogger(__name__)
MATERIAL_PARSER_VERSION = "material-parser-v1"
MAX_MATERIAL_FILE_SIZE_BYTES = 100 * 1024 * 1024
MAX_MULTIPART_OVERHEAD_BYTES = 64 * 1024


class MaterialPreviewRequest(BaseModel):
    operation_id: UUID
    open_content: Literal[True]


class MaterialMetadataRoute(PrivateValidationRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def bounded(request):
            if request.method == "POST" and request.url.path.rstrip("/") == "/api/evaluation/material-batches":
                chunks, size = [], 0
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 3_100_000:
                        raise HTTPException(413, "Material manifest is too large", headers={"Cache-Control": "private, no-store"})
                    chunks.append(chunk)
                request._body = b"".join(chunks)
            elif request.method == "POST" and "/attachments/" in request.url.path and not request.url.path.endswith("/preview"):
                store = getattr(request.app.state, "evaluation_material_store", None)
                max_file_size = getattr(store, "max_file_size_bytes", MAX_MATERIAL_FILE_SIZE_BYTES)
                max_body_size = max_file_size + MAX_MULTIPART_OVERHEAD_BYTES
                try:
                    content_length = int(request.headers.get("content-length", "0"))
                except ValueError:
                    content_length = 0
                if content_length > max_body_size:
                    raise HTTPException(413, "Material attachment request is too large", headers={"Cache-Control": "private, no-store"})

                receive = request._receive
                received = 0

                async def limited_receive():
                    nonlocal received
                    message = await receive()
                    if message["type"] == "http.request":
                        received += len(message.get("body", b""))
                        if received > max_body_size:
                            raise HTTPException(413, "Material attachment request is too large", headers={"Cache-Control": "private, no-store"})
                    return message

                request._receive = limited_receive
            return await handler(request)

        return bounded


router = APIRouter(
    prefix="/api/evaluation/material-batches",
    tags=["evaluation-materials"],
    route_class=MaterialMetadataRoute,
)


async def _context(request: Request):
    user = await get_optional_user_from_request(request)
    if user is None:
        raise HTTPException(401, "Authentication required")
    _require_human(request)
    if user.needs_setup:
        raise HTTPException(403, "Complete account initialization first")
    repo = getattr(request.app.state, "evaluation_material_repo", None)
    if repo is None:
        raise HTTPException(503, "Persistent material database is unavailable")
    return str(user.id), repo


@router.get("")
@require_permission("evaluation_projects", "read")
async def list_batches(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    owner, repo = await _context(request)
    return {"batches": await repo.list(owner, limit=limit, offset=offset)}


@router.post("")
@require_permission("evaluation_projects", "write")
async def create_batch(payload: MaterialBatchCreate, request: Request):
    owner, repo = await _context(request)
    return await repo.create(owner, payload)


@router.get("/{batch_id}")
@require_permission("evaluation_projects", "read")
async def get_batch(batch_id: str, request: Request):
    owner, repo = await _context(request)
    try:
        return await repo.get(owner, batch_id)
    except NotFound:
        raise HTTPException(404, "Material batch not found") from None


@router.post("/{batch_id}/attachments/{artifact_id}")
@require_permission("evaluation_projects", "write")
async def upload_attachment(batch_id: str, artifact_id: str, request: Request, file: UploadFile = File(...)):
    owner, repo = await _context(request)
    store = getattr(request.app.state, "evaluation_material_store", None)
    if store is None:
        raise HTTPException(503, "Material file storage is not configured", headers={"Cache-Control": "private, no-store"})
    try:
        target = await repo.get_upload_target(owner, batch_id, artifact_id)
    except NotFound:
        raise HTTPException(404, "Material attachment not found") from None
    if target["status"] not in {"pending_upload", "uploaded"}:
        raise HTTPException(409, "Material attachment is not eligible for upload")
    try:
        retention_until = datetime.fromisoformat(target["retention_until"])
    except (TypeError, ValueError):
        raise HTTPException(503, "Material attachment retention metadata is invalid") from None
    if retention_until.astimezone(UTC) <= datetime.now(UTC):
        raise HTTPException(410, "Material attachment retention period has expired")
    if file.filename and file.filename != target["file_name"]:
        raise HTTPException(422, "Uploaded filename does not match the declared attachment")
    try:
        await file.seek(0)
        receipt = await asyncio.to_thread(store.write, artifact_id, file.file)
        await repo.record_upload(owner, batch_id, artifact_id, sha256=receipt["sha256"], size_bytes=receipt["size_bytes"])
        return await repo.get(owner, batch_id)
    except MaterialArtifactTooLarge:
        raise HTTPException(413, "Material attachment exceeds the configured size limit") from None
    except (MaterialArtifactConflict, Conflict):
        raise HTTPException(409, "Material attachment conflicts with previously stored content") from None
    except MaterialArtifactStorageError:
        logger.warning("Material attachment storage operation failed")
        raise HTTPException(503, "Material attachment storage is unavailable") from None
    except SQLAlchemyError:
        logger.warning("Material attachment metadata persistence failed; details suppressed")
        raise HTTPException(503, "Material attachment state could not be confirmed; reload before retrying") from None
    finally:
        await file.close()


@router.post("/{batch_id}/attachments/{artifact_id}/preview")
@require_permission("evaluation_projects", "read")
async def preview_attachment(
    batch_id: str,
    artifact_id: str,
    payload: MaterialPreviewRequest,
    request: Request,
    response: Response,
):
    response.headers["Cache-Control"] = "private, no-store"
    owner, repo = await _context(request)
    operation_id = str(payload.operation_id)
    try:
        await repo.get_preview_receipt(owner, operation_id)
    except NotFound:
        pass
    else:
        raise HTTPException(409, "Preview operation already has a receipt", headers={"Cache-Control": "private, no-store"})

    store = getattr(request.app.state, "evaluation_material_store", None)
    if store is None:
        raise HTTPException(503, "Material file storage is not configured", headers={"Cache-Control": "private, no-store"})
    try:
        target = await repo.get_preview_target(owner, batch_id, artifact_id)
    except NotFound:
        raise HTTPException(404, "Material attachment not found", headers={"Cache-Control": "private, no-store"}) from None
    if target["artifact_status"] != "uploaded" or not target["storage_key"] or not target["sha256"] or target["size_bytes"] is None:
        raise HTTPException(409, "Material attachment is not ready for preview", headers={"Cache-Control": "private, no-store"})
    try:
        retention_until = datetime.fromisoformat(target["retention_until"])
    except (TypeError, ValueError):
        raise HTTPException(503, "Material attachment retention metadata is invalid", headers={"Cache-Control": "private, no-store"}) from None
    if retention_until.astimezone(UTC) <= datetime.now(UTC):
        raise HTTPException(410, "Material attachment retention period has expired", headers={"Cache-Control": "private, no-store"})
    try:
        data = await asyncio.to_thread(
            store.read,
            target["storage_key"],
            expected_sha256=target["sha256"],
            expected_size_bytes=target["size_bytes"],
        )
        parsed = await asyncio.to_thread(parse_material, target["file_name"], data)
    except MaterialArtifactConflict:
        raise HTTPException(409, "Stored material does not match its upload receipt", headers={"Cache-Control": "private, no-store"}) from None
    except MaterialArtifactStorageError:
        logger.warning("Material artifact could not be read for preview")
        raise HTTPException(503, "Material attachment is unavailable", headers={"Cache-Control": "private, no-store"}) from None

    blocks = [{"text": block.text, "source_location": block.source_location} for block in parsed.blocks]
    result_document = {
        "parse_status": parsed.status,
        "parser_version": MATERIAL_PARSER_VERSION,
        "blocks": blocks,
        "reason": parsed.reason,
    }
    result_hash = hashlib.sha256(json.dumps(result_document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    try:
        await repo.record_preview(
            owner,
            batch_id,
            artifact_id,
            operation_id=operation_id,
            parse_status=parsed.status,
            parser_version=MATERIAL_PARSER_VERSION,
            result_hash=result_hash,
            block_count=len(blocks),
            reason=parsed.reason,
        )
    except NotFound:
        raise HTTPException(404, "Material attachment not found", headers={"Cache-Control": "private, no-store"}) from None
    except Conflict:
        raise HTTPException(409, "Preview operation or material state conflicts with an existing receipt", headers={"Cache-Control": "private, no-store"}) from None
    except SQLAlchemyError:
        logger.warning("Material preview receipt persistence failed; details suppressed")
        raise HTTPException(503, "Preview receipt could not be confirmed; query the operation receipt before retrying", headers={"Cache-Control": "private, no-store"}) from None
    return {"operation_id": operation_id, **result_document, "result_hash": result_hash}


@router.get("/previews/{operation_id}")
@require_permission("evaluation_projects", "read")
async def get_preview_receipt(operation_id: UUID, request: Request, response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    owner, repo = await _context(request)
    try:
        return await repo.get_preview_receipt(owner, str(operation_id))
    except NotFound:
        raise HTTPException(404, "Preview receipt not found", headers={"Cache-Control": "private, no-store"}) from None
