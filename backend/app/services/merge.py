"""Merge and undo (ADR 0006). Child records and associations move to the survivor; absorbed records are soft-deleted."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models.core import (Company, Contact, ContactCompanyRole, ContactEmail, ContactPhone, DuplicateCandidate,
                           ExternalId, MergeLog, Property, PropertyOwnership)

MODELS = {"contact": Contact, "company": Company, "property": Property}

# (model, fk column) pairs re-pointed on merge. Later stages register their own with register_relink().
RELINKS: dict[str, list[tuple[type, str]]] = {
    "contact": [(ContactCompanyRole, "contact_id"), (PropertyOwnership, "contact_id"), (ContactEmail, "contact_id"), (ContactPhone, "contact_id")],
    "company": [(ContactCompanyRole, "company_id"), (PropertyOwnership, "company_id"), (Company, "parent_company_id")],
    "property": [(PropertyOwnership, "property_id")],
}
# polymorphic association tables (activities, notes, documents): (model, type col, id col)
ASSOC_RELINKS: list[tuple[type, str, str]] = []

MERGEABLE_FIELDS = {
    "contact": ["first_name", "last_name", "title", "address", "city", "state", "zip", "lifecycle_stage", "do_not_contact", "do_not_contact_reason"],
    "company": ["name", "kind", "website", "address", "city", "state", "zip"],
    "property": ["name", "address", "city", "zip", "apn", "subtype", "submarket", "building_sf", "land_acres", "units", "year_built", "zoning", "noi", "lender", "loan_maturity_date"],
}


def register_relink(entity: str, model: type, column: str):
    if (model, column) not in RELINKS[entity]:
        RELINKS[entity].append((model, column))


def register_assoc(model: type, type_col: str, id_col: str):
    if (model, type_col, id_col) not in ASSOC_RELINKS:
        ASSOC_RELINKS.append((model, type_col, id_col))


def merge(db: Session, entity: str, survivor_id: int, absorbed_id: int, choices: dict | None, user_id: int | None) -> MergeLog:
    if survivor_id == absorbed_id:
        raise HTTPException(400, "Cannot merge a record into itself")
    M = MODELS[entity]
    surv, absb = db.get(M, survivor_id), db.get(M, absorbed_id)
    if not surv or not absb or surv.deleted_at or absb.deleted_at:
        raise HTTPException(404, "Record not found or already merged")
    choices = choices or {}
    decisions, before = {}, {}
    for f in MERGEABLE_FIELDS[entity]:
        sv, av = getattr(surv, f), getattr(absb, f)
        pick = choices.get(f) or ("absorbed" if sv in (None, "") and av not in (None, "") else "survivor")
        if pick == "absorbed" and av != sv:
            before[f] = sv.isoformat() if hasattr(sv, "isoformat") else sv
            setattr(surv, f, av)
        decisions[f] = {"survivor": str(sv), "absorbed": str(av), "chosen": pick}
    if entity == "contact":
        surv.contact_types = sorted(set(surv.contact_types or []) | set(absb.contact_types or []))
        before["__contact_types"] = list(surv.contact_types)
    surv.tags = sorted(set(surv.tags or []) | set(absb.tags or []))
    if entity == "contact":
        have_e = {e.normalized for e in surv.emails}
        have_p = {p.normalized for p in surv.phones}
    moved = []
    for model, col in RELINKS[entity]:
        rows = db.scalars(select(model).where(getattr(model, col) == absorbed_id)).all()
        for row in rows:
            if entity == "contact" and model is ContactEmail and row.normalized in have_e:
                continue
            if entity == "contact" and model is ContactPhone and row.normalized in have_p:
                continue
            if model is Company and row.id == survivor_id:
                continue
            setattr(row, col, survivor_id)
            if getattr(row, "is_primary", None) and model in (ContactEmail, ContactPhone):
                row.is_primary = False
            moved.append({"table": model.__tablename__, "id": row.id, "column": col})
    for model, tcol, icol in ASSOC_RELINKS:
        for row in db.scalars(select(model).where(getattr(model, tcol) == entity, getattr(model, icol) == absorbed_id)):
            setattr(row, icol, survivor_id)
            moved.append({"table": model.__tablename__, "id": row.id, "column": icol})
    for row in db.scalars(select(ExternalId).where(ExternalId.entity == entity, ExternalId.entity_id == absorbed_id)):
        row.entity_id = survivor_id
        moved.append({"table": "external_ids", "id": row.id, "column": "entity_id"})
    if entity == "contact" and absb.last_contact_at and (not surv.last_contact_at or absb.last_contact_at > surv.last_contact_at):
        surv.last_contact_at = absb.last_contact_at
    absb.deleted_at = utcnow()
    log = MergeLog(entity=entity, survivor_id=survivor_id, absorbed_id=absorbed_id,
                   field_decisions={"fields": decisions, "survivor_before": before}, moved=moved, merged_by=user_id)
    db.add(log)
    for dc in db.scalars(select(DuplicateCandidate).where(DuplicateCandidate.entity == entity, DuplicateCandidate.status == "pending")):
        if {dc.a_id, dc.b_id} & {absorbed_id}:
            dc.status = "merged"
    db.flush()
    return log


def undo(db: Session, log_id: int) -> MergeLog:
    log = db.get(MergeLog, log_id)
    if not log:
        raise HTTPException(404, "Merge not found")
    if log.undone_at:
        raise HTTPException(409, "Merge already undone")
    if (utcnow() - log.created_at).days > 30:
        raise HTTPException(409, "Undo window (30 days) has passed")
    M = MODELS[log.entity]
    tables = {m.__tablename__: m for m, _ in sum(RELINKS.values(), [])}
    tables.update({m.__tablename__: m for m, _, _ in ASSOC_RELINKS})
    tables["external_ids"] = ExternalId
    for mv in log.moved:
        row = db.get(tables[mv["table"]], mv["id"])
        if row is not None:
            setattr(row, mv["column"], log.absorbed_id)
    surv, absb = db.get(M, log.survivor_id), db.get(M, log.absorbed_id)
    for f, val in log.field_decisions.get("survivor_before", {}).items():
        if f.startswith("__"):
            continue
        col = M.__table__.columns[f]
        if val is not None and col.type.python_type.__name__ == "date":
            from datetime import date
            val = date.fromisoformat(val)
        setattr(surv, f, val)
    absb.deleted_at = None
    log.undone_at = utcnow()
    db.flush()
    return log
