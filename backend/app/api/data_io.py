from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import log_event
from app.core.database import get_db
from app.core.deps import get_current_user, has_permission
from app.models import ImportBatch, User
from app.services import data_io

router = APIRouter(prefix="/data", tags=["import & export"])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
# which permission each data type needs
PERMS = {"products": "inventory", "customers": "customers", "suppliers": "purchasing", "expenses": "finance", "invoices": "sales", "sales": "sales"}


def _check(user: User, entity: str, action: str) -> None:
    if entity not in PERMS:
        raise HTTPException(404, "Unknown data type")
    if not has_permission(user, f"{PERMS[entity]}:{action}"):
        raise HTTPException(403, f"Missing permission: {PERMS[entity]}:{action}")


def _file(name: str, content: bytes) -> Response:
    media = "text/csv" if name.endswith(".csv") else XLSX
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/template/{entity}")
def template(entity: str, lang: str = "en", user: User = Depends(get_current_user)):
    if entity not in data_io.ENTITIES:
        raise HTTPException(404, "Unknown data type")
    return _file(*data_io.template(entity, lang))


@router.post("/import/{entity}")
async def import_data(entity: str, dry_run: bool = True, lang: str = "en", file: UploadFile = File(...), user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """dry_run=true validates and shows what would happen without saving anything."""
    if entity not in data_io.ENTITIES:
        raise HTTPException(404, "Unknown data type")
    _check(user, entity, "write")
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(413, "File too large (max 10MB)")
    rows = data_io.read_rows(file.filename or "", content)
    records, errors = data_io.parse(entity, rows, lang)
    created, updated, apply_errors, created_ids, side_effects = data_io.apply(db, user.company_id, entity, records)
    batch_id = None
    if dry_run:
        db.rollback()
    else:
        if created_ids:
            batch = ImportBatch(company_id=user.company_id, entity=entity, user_id=user.id, user_name=user.full_name,
                                filename=file.filename, created_count=created, updated_count=updated, created_ids=created_ids,
                                side_effect_ids=side_effects)
            db.add(batch)
            db.flush()
            batch_id = batch.id
        log_event(db, user.company_id, "import", entity, file.filename, {"created": created, "updated": updated}, user.id, user.full_name)
        db.commit()
    errors = sorted(errors + apply_errors, key=lambda e: e["row"])
    return {"dry_run": dry_run, "rows": len(records) + len(errors), "created": created, "updated": updated, "errors": errors,
            "preview": [r for _, r in records[:15]], "batch_id": batch_id}


@router.get("/import/batches")
def list_batches(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Recent imports, so a mistake can be found and undone."""
    rows = db.scalars(select(ImportBatch).where(ImportBatch.company_id == user.company_id).order_by(ImportBatch.id.desc()).limit(30)).all()
    return [{"id": b.id, "entity": b.entity, "filename": b.filename, "user": b.user_name, "created_count": b.created_count,
             "updated_count": b.updated_count, "created_at": b.created_at, "rolled_back_at": b.rolled_back_at,
             "rollback_report": b.rollback_report} for b in rows]


@router.post("/import/batches/{batch_id}/rollback")
def rollback_batch(batch_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Undo an import: deletes the rows it created that nothing else has used since. Updated rows are never
    touched (their previous values weren't kept). Rows already in use are reported, not force-deleted."""
    b = db.get(ImportBatch, batch_id)
    if not b or b.company_id != user.company_id:
        raise HTTPException(404, "Import not found")
    _check(user, b.entity, "write")
    if b.rolled_back_at:
        raise HTTPException(400, "This import was already rolled back")
    report = data_io.rollback(db, user.company_id, b)
    b.rolled_back_at, b.rollback_report = datetime.utcnow(), report
    log_event(db, user.company_id, "import_rollback", b.entity, b.filename, report, user.id, user.full_name)
    db.commit()
    return {"removed": len(report["removed"]), "kept_in_use": report["kept_in_use"]}


@router.get("/export/{entity}")
def export(entity: str, lang: str = "en", format: str = "xlsx", user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if format not in ("xlsx", "csv"):
        raise HTTPException(400, "format must be xlsx or csv")
    _check(user, entity, "read")
    return _file(*data_io.export(db, user.company_id, entity, lang, format))
