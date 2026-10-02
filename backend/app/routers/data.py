import io
import json

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..audit import log_event
from ..db import get_db
from ..models.core_sys import User
from ..models.imports import IMPORT_ENTITIES, IMPORT_MODES, ImportJob, ImportRow
from ..models.platform import ListDef, SavedView
from ..security import require
from ..services import exports as exp
from ..services import filters as flt
from ..services import imports as svc
from ..services.common import user_names

router = APIRouter(prefix="/api", tags=["import-export"])


def job_out(db: Session, j: ImportJob, names: dict) -> dict:
    return {"id": j.id, "file_name": j.file_name, "entity": j.entity, "mode": j.mode, "source_name": j.source_name, "mapping": j.mapping, "headers": j.headers, "status": j.status,
            "total_rows": j.total_rows, "counts": j.counts, "summary": j.summary, "created_by": names.get(j.created_by), "created_at": j.created_at, "started_at": j.started_at, "finished_at": j.finished_at,
            "rolled_back_at": j.rolled_back_at, "processed": db.query(ImportRow).filter(ImportRow.job_id == j.id, ImportRow.processed.is_(True)).count() if j.status == "running" else None}


def _job(db, jid) -> ImportJob:
    j = db.get(ImportJob, jid)
    if not j:
        raise HTTPException(404, "Import not found")
    return j


@router.get("/imports/templates")
def templates(entity: str, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    if entity not in IMPORT_ENTITIES:
        raise HTTPException(422, f"entity must be one of {IMPORT_ENTITIES}")
    t = svc.targets_meta(entity, db)
    return {"entity": entity, "fields": t, "csv_header": ",".join(x["label"] for x in t)}


@router.get("/imports")
def list_imports(db: Session = Depends(get_db), _: User = Depends(require("view"))):
    names = user_names(db)
    return {"items": [job_out(db, j, names) for j in db.scalars(select(ImportJob).order_by(ImportJob.id.desc()).limit(50))]}


@router.post("/imports", status_code=201)
async def create_import(file: UploadFile = File(...), entity: str = Form(...), source_name: str = Form(...), mode: str = Form("create"), mapping: str | None = Form(None),
                        db: Session = Depends(get_db), user: User = Depends(require("import"))):
    if entity not in IMPORT_ENTITIES:
        raise HTTPException(422, f"entity must be one of {IMPORT_ENTITIES}")
    if mode not in IMPORT_MODES:
        raise HTTPException(422, f"mode must be one of {IMPORT_MODES}")
    if not source_name.strip():
        raise HTTPException(422, "source_name is required (it is stored as provenance on every record)")
    content = await file.read(svc.MAX_BYTES + 1)
    headers, rows = svc.parse_file(file.filename or "upload", content)
    try:
        m = json.loads(mapping) if mapping else svc.suggest_mapping(entity, headers, db)
    except json.JSONDecodeError:
        raise HTTPException(422, "mapping must be JSON")
    svc.validate_mapping(entity, m, headers, db)
    import hashlib
    digest = hashlib.sha256(content).hexdigest()
    path = config.STORAGE_DIR / "imports" / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    job = ImportJob(file_name=file.filename or "upload", file_path=str(path), entity=entity, mode=mode, source_name=source_name.strip(), mapping=m, headers=headers, created_by=user.id)
    db.add(job)
    db.flush()
    svc.run_preview(db, job, rows, user.id)
    db.commit()
    return {**job_out(db, job, user_names(db)), "suggested_mapping": svc.suggest_mapping(entity, headers, db)}


@router.get("/imports/{jid}")
def get_import(jid: int, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    return job_out(db, _job(db, jid), user_names(db))


@router.put("/imports/{jid}")
def update_import(jid: int, body: dict, db: Session = Depends(get_db), user: User = Depends(require("import"))):
    """Change mapping, mode or source while still in preview; the dry run is recomputed."""
    j = _job(db, jid)
    if j.status != "previewed":
        raise HTTPException(409, f"Only previewed imports can be changed (this one is {j.status})")
    if "mode" in body:
        if body["mode"] not in IMPORT_MODES:
            raise HTTPException(422, f"mode must be one of {IMPORT_MODES}")
        j.mode = body["mode"]
    if body.get("source_name"):
        j.source_name = body["source_name"].strip()
    if "mapping" in body:
        svc.validate_mapping(j.entity, body["mapping"], j.headers, db)
        j.mapping = body["mapping"]
    from pathlib import Path
    _, rows = svc.parse_file(j.file_name, Path(j.file_path).read_bytes())
    svc.run_preview(db, j, rows, user.id)
    db.commit()
    return job_out(db, j, user_names(db))


@router.get("/imports/{jid}/rows")
def import_rows(jid: int, action: str | None = None, page: int = Query(1, ge=1), limit: int = Query(50, le=200), db: Session = Depends(get_db), _: User = Depends(require("view"))):
    _job(db, jid)
    stmt = select(ImportRow).where(ImportRow.job_id == jid)
    if action:
        stmt = stmt.where(ImportRow.action == action)
    from sqlalchemy import func
    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = db.scalars(stmt.order_by(ImportRow.row_no).offset((page - 1) * limit).limit(limit)).all()
    return {"total": total, "items": [{"row_no": r.row_no, "action": r.action, "message": r.message, "details": r.details, "raw": r.raw, "processed": r.processed} for r in rows]}


@router.post("/imports/{jid}/commit", status_code=202)
def commit_import(jid: int, background: BackgroundTasks, db: Session = Depends(get_db), user: User = Depends(require("import"))):
    j = _job(db, jid)
    if j.status not in ("previewed", "running", "failed"):
        raise HTTPException(409, f"Cannot commit an import that is {j.status}")
    if j.status == "previewed" and j.counts.get("error", 0) == j.total_rows and j.total_rows > 0:
        raise HTTPException(422, "Every row has an error; fix the file or mapping first")
    j.status = "running"
    db.commit()
    background.add_task(svc.commit_job, j.id, user.id, user.name)
    return {"id": j.id, "status": "running"}


@router.get("/imports/{jid}/errors.csv")
def errors_csv(jid: int, db: Session = Depends(get_db), _: User = Depends(require("view"))):
    j = _job(db, jid)
    rows = db.scalars(select(ImportRow).where(ImportRow.job_id == jid, ImportRow.action.in_(("error", "duplicate", "skip"))).order_by(ImportRow.row_no)).all()
    header = ["row", "result", "reason", *j.headers]
    body = [[r.row_no, r.action, r.message, *[r.raw.get(h, "") for h in j.headers]] for r in rows]
    return Response(exp.to_csv(header, body), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="import-{jid}-errors.csv"'})


@router.post("/imports/{jid}/rollback")
def rollback(jid: int, db: Session = Depends(get_db), user: User = Depends(require("delete"))):
    j = _job(db, jid)
    db.info["actor"], db.info["actor_id"] = user.name, user.id
    r = svc.rollback_job(db, j)
    log_event(db, "import_rollback", "import_jobs", j.id, {"removed": r["removed"], "kept": len(r["kept"])})
    db.commit()
    return r


# ---------------- export ----------------
@router.get("/export/{entity}")
def export_entity(entity: str, format: str = "csv", view_id: int | None = None, list_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(require("export"))):
    if entity not in flt.ENTITY_MODELS:
        raise HTTPException(422, f"entity must be one of {list(flt.ENTITY_MODELS)}")
    if format not in ("csv", "xlsx"):
        raise HTTPException(422, "format must be csv or xlsx")
    columns = flt_def = restrict = sort_field = None
    sort_dir = "asc"
    if view_id:
        v = db.get(SavedView, view_id)
        if not v or (v.visibility == "private" and v.owner_user_id != user.id) or v.entity != entity:
            raise HTTPException(404, "View not found")
        columns, flt_def, sort_field, sort_dir = v.columns or None, v.filter, v.sort_field, v.sort_dir
    if list_id:
        l = db.get(ListDef, list_id)
        if not l or (l.visibility == "private" and l.owner_user_id != user.id) or l.entity != entity:
            raise HTTPException(404, "List not found")
        if l.kind == "dynamic":
            flt_def = l.filter
        else:
            restrict = l.members or []
    exp.check_export_allowed(user)
    header, rows = exp.table_for(db, entity, user, columns, flt_def, restrict, sort_field, sort_dir)
    db.info["actor"], db.info["actor_id"] = user.name, user.id
    log_event(db, "export", entity, None, {"rows": len(rows), "format": format, "view_id": view_id, "list_id": list_id})
    db.commit()
    if format == "xlsx":
        return Response(exp.to_xlsx({entity.title(): (header, rows)}), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{entity}.xlsx"'})
    return Response(exp.to_csv(header, rows), media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="{entity}.csv"'})


@router.get("/export-full")
def export_full(db: Session = Depends(get_db), user: User = Depends(require("export"))):
    exp.check_export_allowed(user)
    sheets = exp.full_export(db, user)
    db.info["actor"], db.info["actor_id"] = user.name, user.id
    log_event(db, "export", "full", None, {"sheets": {k: len(v[1]) for k, v in sheets.items()}})
    db.commit()
    return Response(exp.to_xlsx(sheets), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="trg-full-export.xlsx"'})
