"""Stage 8 seed: import history (real CSV files on disk, per-row results, provenance on the imported records)."""
import csv
import hashlib
import io
import random
from datetime import datetime, timedelta

from sqlalchemy import select

from .. import config
from ..models.core import ExternalId, Property
from ..models.imports import ImportJob, ImportRow


def _store(content: bytes) -> str:
    digest = hashlib.sha256(content).hexdigest()
    path = config.STORAGE_DIR / "imports" / digest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return str(path)


def seed(db, ctx):
    now = datetime.utcnow()
    admin = ctx["users"][0]
    # 1. CoStar property export (the first 60 properties carry CoStar external ids from the core seed)
    props = list(db.scalars(select(Property).order_by(Property.id).limit(60)))
    header = ["CoStar ID", "Address", "City", "Type", "SF", "Value", "Loan Maturity", "Lender"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for i, p in enumerate(props):
        w.writerow([f"CS-{100000 + i}", p.address, p.city, p.property_type.title(), p.building_sf or "", p.estimated_value or "", p.loan_maturity_date or "", p.lender or ""])
    w.writerow(["CS-199999", props[0].address, props[0].city, "Retail", "", "", "", ""])  # duplicate of an existing property
    w.writerow(["CS-199998", "12 Nowhere Pkwy", "Irvine", "Hotel", "", "", "", ""])  # invalid property type
    content = buf.getvalue().encode()
    t0 = now - timedelta(days=random.randint(200, 260))
    job = ImportJob(file_name="costar-orange-county-retail-industrial.csv", file_path=_store(content), entity="property", mode="create_or_update", source_name="CoStar export", status="completed",
                    mapping={"external_id": "CoStar ID", "address": "Address", "city": "City", "property_type": "Type", "building_sf": "SF", "estimated_value": "Value", "loan_maturity_date": "Loan Maturity", "lender": "Lender"},
                    headers=header, total_rows=len(props) + 2, counts={"create": len(props), "update": 0, "skip": 0, "duplicate": 1, "error": 1},
                    summary={"records_created": {"contacts": 0, "companies": 0, "properties": len(props), "ownerships": 0}}, created_by=admin.id, started_at=t0, finished_at=t0 + timedelta(seconds=9), created_at=t0, updated_at=t0)
    db.add(job)
    db.flush()
    for i, p in enumerate(props):
        p.import_job_id, p.imported_at, p.source = job.id, t0, "CoStar export"
        db.add(ImportRow(job_id=job.id, row_no=i + 2, raw={"CoStar ID": f"CS-{100000 + i}", "Address": p.address, "City": p.city}, action="create", message="Creates a property", details={}, created_ids={"property": [p.id]}, processed=True))
    db.add(ImportRow(job_id=job.id, row_no=len(props) + 2, raw={"CoStar ID": "CS-199999", "Address": props[0].address, "City": props[0].city}, action="duplicate", message=f"Already exists: {props[0].address}, {props[0].city} (same same address)", processed=True))
    db.add(ImportRow(job_id=job.id, row_no=len(props) + 3, raw={"CoStar ID": "CS-199998", "Address": "12 Nowhere Pkwy", "City": "Irvine"}, action="error", message="Property type must be retail or industrial (or a known synonym), got 'Hotel'", processed=True))
    # 2. Outlook contacts export with a few bad rows
    contacts = random.sample(ctx["all_contacts"], 50)
    header2 = ["First Name", "Last Name", "E-mail Address", "Mobile Phone", "Company"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header2)
    for c in contacts:
        w.writerow([c.first_name, c.last_name, c.emails[0].email if c.emails else "", c.phones[0].phone if c.phones else "", ""])
    w.writerow(["Bad", "Address", "not-an-email", "", ""])
    w.writerow(["Short", "Phone", "short@example.com", "12", ""])
    t1 = now - timedelta(days=random.randint(90, 150))
    job2 = ImportJob(file_name="outlook-contacts-export.csv", file_path=_store(buf.getvalue().encode()), entity="contact", mode="create_or_update", source_name="Outlook contacts", status="completed",
                     mapping={"first_name": "First Name", "last_name": "Last Name", "email": "E-mail Address", "phone": "Mobile Phone", "company_name": "Company"}, headers=header2, total_rows=len(contacts) + 2,
                     counts={"create": len(contacts), "update": 0, "skip": 0, "duplicate": 0, "error": 2}, summary={"records_created": {"contacts": len(contacts), "companies": 0, "properties": 0, "ownerships": 0}},
                     created_by=ctx["users"][1].id, started_at=t1, finished_at=t1 + timedelta(seconds=6), created_at=t1, updated_at=t1)
    db.add(job2)
    db.flush()
    for i, c in enumerate(contacts):
        c.import_job_id, c.imported_at, c.source = job2.id, t1, "Outlook contacts"
        db.add(ImportRow(job_id=job2.id, row_no=i + 2, raw={"First Name": c.first_name, "Last Name": c.last_name}, action="create", message="Creates a contact", created_ids={"contact": [c.id]}, processed=True))
    db.add(ImportRow(job_id=job2.id, row_no=len(contacts) + 2, raw={"First Name": "Bad", "Last Name": "Address", "E-mail Address": "not-an-email"}, action="error", message="Invalid email: not-an-email", processed=True))
    db.add(ImportRow(job_id=job2.id, row_no=len(contacts) + 3, raw={"First Name": "Short", "Last Name": "Phone", "Mobile Phone": "12"}, action="error", message="Invalid phone: 12", processed=True))
    db.flush()
