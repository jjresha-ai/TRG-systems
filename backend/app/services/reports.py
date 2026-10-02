"""Fixed catalog of backend-defined reports (ADR 0021). Reports apply the same field-level restrictions as the API (ADR 0017)."""
import csv
import io
from collections import defaultdict
from datetime import date, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models.core import Company, Contact, Property
from ..models.core_sys import User
from ..models.deals import CommissionSplit, Deal, DealStageHistory, Pipeline, PipelineSnapshot, Stage
from ..models.investors import COMMITMENT_STATUSES, Commitment, Fund
from ..models.pipeline import BuyerInterest, Lead, LeadSource, Listing
from ..models.reports import Goal
from ..models.work import Activity
from ..security import can_see_commission
from . import deals as deals_svc
from .common import user_names
from .jobs import job

QUARTER_START = {1: 1, 2: 1, 3: 1, 4: 4, 5: 4, 6: 4, 7: 7, 8: 7, 9: 7, 10: 10, 11: 10, 12: 10}


def parse_period(period: str | None, start: date | None, end: date | None, today: date | None = None) -> tuple[date, date, str]:
    today = today or date.today()
    if start and end:
        if end < start:
            raise HTTPException(422, "end must not be before start")
        return start, end, "custom"
    p = period or "ytd"
    if p == "ytd":
        return date(today.year, 1, 1), today, "ytd"
    if p == "12m":
        return today - timedelta(days=364), today, "12m"
    if p == "quarter":
        s = date(today.year, QUARTER_START[today.month], 1)
        return s, today, "quarter"
    if p == "month":
        return date(today.year, today.month, 1), today, "month"
    if p.startswith("year:"):
        y = int(p[5:])
        return date(y, 1, 1), min(date(y, 12, 31), today), f"year:{y}"
    raise HTTPException(422, "period must be ytd, 12m, quarter, month, year:YYYY or start+end")


def gci_allocation(d: Deal) -> dict[int, int]:
    """Internal brokers' share of a deal's gross commission by recipient (splits, else the deal owner)."""
    g = deals_svc.gross_of(d) or 0
    out: dict[int, int] = defaultdict(int)
    internal = [s for s in d.splits if s.recipient_user_id]
    if not internal:
        if d.owner_user_id:
            out[d.owner_user_id] += g
        return out
    for s in internal:
        out[s.recipient_user_id] += s.amount if s.split_type == "amount" else round(g * (s.pct or 0) / 100)
    return out


def won_deals(db: Session, start: date, end: date, pipeline: str | None = None):
    stmt = select(Deal).where(Deal.status == "won", Deal.deleted_at.is_(None), Deal.actual_close_date >= start, Deal.actual_close_date <= end)
    if pipeline:
        stmt = stmt.where(Deal.pipeline_id == deals_svc.get_pipeline(db, pipeline).id)
    return db.scalars(stmt).all()


def listings_taken(db: Session, start: date, end: date):
    return db.scalars(select(Listing).where(Listing.deleted_at.is_(None), Listing.agreement_date >= start, Listing.agreement_date <= end, Listing.listing_type == "sale")).all()


# ---------------- production ----------------
def production(db: Session, user: User, period=None, start=None, end=None, group_by="broker", property_type: str | None = None, owner_id: int | None = None) -> dict:
    s, e, label = parse_period(period, start, end)
    show = can_see_commission(user)
    names = user_names(db)
    rows: dict = defaultdict(lambda: {"listings_taken": 0, "closed_deals": 0, "closed_volume": 0, "gci": 0})
    won = [d for d in won_deals(db, s, e) if (not property_type or (d.property and d.property.property_type == property_type)) and (not owner_id or d.owner_user_id == owner_id)]
    taken = [l for l in listings_taken(db, s, e) if (not property_type or l.property.property_type == property_type) and (not owner_id or l.owner_user_id == owner_id)]

    def key_deal(d):
        if group_by == "month":
            return d.actual_close_date.strftime("%Y-%m")
        if group_by == "property_type":
            return d.property.property_type if d.property else "n/a"
        return None

    def key_listing(l):
        if group_by == "month":
            return l.agreement_date.strftime("%Y-%m")
        if group_by == "property_type":
            return l.property.property_type
        return names.get(l.owner_user_id, "Unassigned")

    if group_by not in ("broker", "month", "property_type"):
        raise HTTPException(422, "group_by must be broker, month or property_type")
    for d in won:
        if group_by == "broker":
            alloc = gci_allocation(d) or {d.owner_user_id: 0}
            tot_g = sum(alloc.values()) or 1
            for uid, g in alloc.items():
                k = names.get(uid, "Unassigned")
                rows[k]["closed_deals"] += 1 if uid == d.owner_user_id or len(alloc) == 1 else 0
                share = (g / tot_g) if tot_g else 0
                rows[k]["closed_volume"] += round((d.price or 0) * share)
                rows[k]["gci"] += g
        else:
            k = key_deal(d)
            rows[k]["closed_deals"] += 1
            rows[k]["closed_volume"] += d.price or 0
            rows[k]["gci"] += deals_svc.gross_of(d) or 0
    for l in taken:
        rows[key_listing(l)]["listings_taken"] += 1
    data = [{"group": k, **v} for k, v in sorted(rows.items(), key=lambda kv: (kv[0] if group_by == "month" else -kv[1]["closed_volume"]))]
    total = {"listings_taken": len(taken), "closed_deals": len(won), "closed_volume": sum(d.price or 0 for d in won), "gci": sum(deals_svc.gross_of(d) or 0 for d in won)}
    goals = goal_progress(db, s, e, total, names) if group_by != "x" and not owner_id and not property_type else []
    if not show:
        for r in data:
            r.pop("gci", None)
        total.pop("gci", None)
        goals = [g for g in goals if g["metric"] != "gci"]
    cols = ["group", "listings_taken", "closed_deals", "closed_volume"] + (["gci"] if show else [])
    return {"report": "production", "period": {"start": s, "end": e, "label": label}, "group_by": group_by, "columns": cols, "rows": data, "totals": total, "goals": goals, "commission_visible": show}


def goal_period(g: Goal) -> tuple[date, date]:
    s = g.period_start
    if g.period_type == "year":
        return s, date(s.year, 12, 31)
    if g.period_type == "quarter":
        return s, date(s.year + (1 if s.month == 10 else 0), (s.month + 3 - 1) % 12 + 1, 1) - timedelta(days=1)
    return s, date(s.year + (1 if s.month == 12 else 0), s.month % 12 + 1, 1) - timedelta(days=1)


def goal_progress(db: Session, s: date, e: date, firm_total: dict, names: dict) -> list[dict]:
    """Firm goals whose period is the reported period (a period-to-date report matches the goal it is in the middle of)."""
    today = date.today()
    out = []
    for g in db.scalars(select(Goal).where(Goal.user_id.is_(None), Goal.period_start == s)):
        gs, ge = goal_period(g)
        if not (e == ge or (e == today and today <= ge)):
            continue
        actual = firm_total.get(g.metric, 0)
        out.append({"metric": g.metric, "period_type": g.period_type, "target": g.target, "actual": actual, "pct": round(actual / g.target * 100, 1) if g.target else 0})
    return out


# ---------------- pipeline ----------------
def pipeline_report(db: Session, user: User, group_by="stage", pipeline: str | None = None) -> dict:
    show = can_see_commission(user)
    names = user_names(db)
    stmt = select(Deal).where(Deal.status == "open", Deal.deleted_at.is_(None))
    if pipeline:
        stmt = stmt.where(Deal.pipeline_id == deals_svc.get_pipeline(db, pipeline).id)
    rows: dict = defaultdict(lambda: {"deals": 0, "volume": 0, "weighted_volume": 0, "commission": 0, "weighted_commission": 0})
    order: dict = {}
    if group_by not in ("stage", "owner", "property_type", "market", "close_month"):
        raise HTTPException(422, "group_by must be stage, owner, property_type, market or close_month")
    for d in db.scalars(stmt):
        prob = deals_svc.effective_probability(d) / 100
        g = deals_svc.gross_of(d) or 0
        if group_by == "stage":
            k = f"{d.pipeline.name}: {d.stage.name}" if not pipeline else d.stage.name
            order[k] = (d.pipeline_id, d.stage.position)
        elif group_by == "owner":
            k = names.get(d.owner_user_id, "Unassigned")
        elif group_by == "property_type":
            k = d.property.property_type if d.property else "n/a"
        elif group_by == "market":
            k = d.property.market if d.property and d.property.market else "n/a"
        else:
            k = d.expected_close_date.strftime("%Y-%m") if d.expected_close_date else "unscheduled"
        r = rows[k]
        r["deals"] += 1
        r["volume"] += d.price or 0
        r["weighted_volume"] += round((d.price or 0) * prob)
        r["commission"] += g
        r["weighted_commission"] += round(g * prob)
    items = [{"group": k, **v} for k, v in rows.items()]
    items.sort(key=lambda r: order.get(r["group"], (0, 0)) if group_by == "stage" else (r["group"] if group_by == "close_month" else -r["weighted_commission"]))
    totals = {k: sum(r[k] for r in items) for k in ("deals", "volume", "weighted_volume", "commission", "weighted_commission")}
    cols = ["group", "deals", "volume", "weighted_volume"] + (["commission", "weighted_commission"] if show else [])
    if not show:
        for r in [*items, totals]:
            r.pop("commission", None)
            r.pop("weighted_commission", None)
    return {"report": "pipeline", "group_by": group_by, "columns": cols, "rows": items, "totals": totals, "commission_visible": show}


# ---------------- listings ----------------
def listings_report(db: Session, user: User, expiring_within_days: int = 60) -> dict:
    today = date.today()
    names = user_names(db)
    by_status: dict = {}
    for l in db.scalars(select(Listing).where(Listing.deleted_at.is_(None), Listing.listing_type == "sale")):
        b = by_status.setdefault(l.status, {"status": l.status, "listings": 0, "value": 0, "dom_total": 0, "dom_n": 0})
        b["listings"] += 1
        b["value"] += (l.sold_price if l.status == "closed" else l.list_price) or 0
        dom = (( l.closed_date if l.status == "closed" and l.closed_date else today) - l.active_date).days if l.active_date else None
        if dom is not None:
            b["dom_total"] += dom
            b["dom_n"] += 1
    rows = [{"status": s["status"], "listings": s["listings"], "value": s["value"], "avg_days_on_market": round(s["dom_total"] / s["dom_n"]) if s["dom_n"] else None} for s in by_status.values()]
    expiring = []
    for l in db.scalars(select(Listing).where(Listing.status == "active", Listing.deleted_at.is_(None), Listing.expiration_date >= today, Listing.expiration_date <= today + timedelta(days=expiring_within_days)).order_by(Listing.expiration_date)):
        expiring.append({"listing_id": l.id, "address": l.property.address, "city": l.property.city, "broker": names.get(l.owner_user_id), "expires": l.expiration_date, "days_left": (l.expiration_date - today).days, "list_price": l.list_price})
    return {"report": "listings", "columns": ["status", "listings", "value", "avg_days_on_market"], "rows": rows, "expiring": expiring, "expiring_within_days": expiring_within_days}


# ---------------- buyer interest ----------------
def buyer_interest_report(db: Session, user: User, status: str = "active") -> dict:
    rows = []
    for l in db.scalars(select(Listing).where(Listing.deleted_at.is_(None), Listing.status == status if status else Listing.status.is_not(None)).order_by(Listing.id)):
        reached = defaultdict(int)
        interests = db.scalars(select(BuyerInterest).where(BuyerInterest.listing_id == l.id)).all()
        for i in interests:
            seen = {e.stage for e in i.events}
            for st in seen:
                reached[st] += 1
        best = max((i.offer_amount or 0 for i in interests), default=0)
        rows.append({"listing_id": l.id, "address": l.property.address, "city": l.property.city, "status": l.status, "inquiries": len(interests), "ca_sent": reached["ca_sent"], "ca_signed": reached["ca_signed"],
                     "om_sent": reached["om_sent"], "tours": reached["tour"], "offers": reached["offer"], "declined": reached["declined"], "best_offer": best or None})
    rows.sort(key=lambda r: -r["inquiries"])
    return {"report": "buyer_interest", "columns": ["address", "city", "status", "inquiries", "ca_sent", "ca_signed", "om_sent", "tours", "offers", "declined", "best_offer"], "rows": rows}


# ---------------- prospecting ----------------
def prospecting(db: Session, user: User, period=None, start=None, end=None) -> dict:
    s, e, label = parse_period(period, start, end)
    names = user_names(db)
    sources = []
    for sid, name in db.execute(select(LeadSource.id, LeadSource.name)):
        leads = db.scalars(select(Lead).where(Lead.source_id == sid, Lead.created_at >= datetime.combine(s, datetime.min.time()), Lead.created_at <= datetime.combine(e, datetime.max.time()))).all()
        if leads:
            conv = sum(1 for l in leads if l.status == "converted")
            sources.append({"source": name, "leads": len(leads), "converted": conv, "conversion_rate": round(conv / len(leads) * 100, 1)})
    sources.sort(key=lambda r: -r["leads"])
    acts: dict = defaultdict(lambda: defaultdict(int))
    for a in db.scalars(select(Activity).where(Activity.status == "completed", Activity.completed_at >= datetime.combine(s, datetime.min.time()), Activity.completed_at <= datetime.combine(e, datetime.max.time()))):
        acts[names.get(a.assignee_user_id, "Unassigned")][a.type] += 1
        acts[names.get(a.assignee_user_id, "Unassigned")]["total"] += 1
    activity_rows = [{"user": u, "calls": v["call"], "emails": v["email"], "meetings": v["meeting"], "site_visits": v["site_visit"], "total": v["total"]} for u, v in acts.items()]
    activity_rows.sort(key=lambda r: -r["total"])
    return {"report": "prospecting", "period": {"start": s, "end": e, "label": label}, "columns": ["source", "leads", "converted", "conversion_rate"], "rows": sources, "activity_by_user": activity_rows}


def recency(db: Session, user: User, days: int = 90, entity: str = "contact", owner_id: int | None = None, limit: int = 100) -> dict:
    cutoff = utcnow() - timedelta(days=days)
    names = user_names(db)
    M = {"contact": Contact, "company": Company, "property": Property}.get(entity)
    if not M:
        raise HTTPException(422, "entity must be contact, company or property")
    stmt = select(M).where(M.deleted_at.is_(None), (M.last_contact_at.is_(None)) | (M.last_contact_at < cutoff))
    if entity == "contact":
        stmt = stmt.where(M.contact_types.like('%"owner"%'))
    if owner_id:
        stmt = stmt.where(M.owner_user_id == owner_id)
    rows = db.scalars(stmt.order_by(M.last_contact_at.asc().nulls_first())).all()
    out = [{"id": r.id, "name": getattr(r, "full_name", None) or getattr(r, "name", None) or r.address, "broker": names.get(r.owner_user_id), "last_contact_at": r.last_contact_at,
            "days_since": (utcnow() - r.last_contact_at).days if r.last_contact_at else None} for r in rows[:limit]]
    return {"report": "owner_recency", "entity": entity, "threshold_days": days, "total": len(rows), "columns": ["name", "broker", "last_contact_at", "days_since"], "rows": out}


# ---------------- time in stage ----------------
def time_in_stage(db: Session, user: User, pipeline: str = "seller") -> dict:
    pipe = deals_svc.get_pipeline(db, pipeline)
    stages = {s.id: s for s in pipe.stages}
    durations: dict = defaultdict(list)
    for d in db.scalars(select(Deal).where(Deal.pipeline_id == pipe.id, Deal.deleted_at.is_(None))):
        hist = db.scalars(select(DealStageHistory).where(DealStageHistory.deal_id == d.id).order_by(DealStageHistory.at, DealStageHistory.id)).all()
        for i, h in enumerate(hist):
            st = stages[h.to_stage_id]
            if st.is_won or st.is_lost:
                continue
            end = hist[i + 1].at if i + 1 < len(hist) else utcnow()
            durations[st.id].append(max((end - h.at).days, 0))
    rows = [{"stage": s.name, "rotting_days": s.rotting_days, "deals_observed": len(durations[s.id]), "avg_days": round(sum(durations[s.id]) / len(durations[s.id]), 1) if durations[s.id] else None,
             "max_days": max(durations[s.id]) if durations[s.id] else None} for s in pipe.stages if not (s.is_won or s.is_lost)]
    names = user_names(db)
    stalled = [{"deal_id": d.id, "name": d.name, "stage": d.stage.name, "days_in_stage": deals_svc.days_in_stage(d), "rotting_days": d.stage.rotting_days, "owner": names.get(d.owner_user_id)}
               for d in db.scalars(select(Deal).where(Deal.pipeline_id == pipe.id, Deal.status == "open", Deal.deleted_at.is_(None))) if deals_svc.is_rotting(d)]
    stalled.sort(key=lambda r: -(r["days_in_stage"] - (r["rotting_days"] or 0)))
    return {"report": "time_in_stage", "pipeline": pipeline, "columns": ["stage", "rotting_days", "deals_observed", "avg_days", "max_days"], "rows": rows, "stalled": stalled}


# ---------------- investor capital ----------------
def investor_capital(db: Session, user: User) -> dict:
    rows = []
    for f in db.scalars(select(Fund).where(Fund.deleted_at.is_(None)).order_by(Fund.id)):
        by = {s: 0 for s in COMMITMENT_STATUSES}
        for c in db.scalars(select(Commitment).where(Commitment.fund_id == f.id, Commitment.deleted_at.is_(None))):
            by[c.status] += c.amount
        firm = by["committed"] + by["funded"]
        rows.append({"fund": f.name, "status": f.status, "target_raise": f.target_raise, **by, "committed_or_funded": firm, "pct_of_target": round(firm / f.target_raise * 100, 1)})
    return {"report": "investor_capital", "columns": ["fund", "status", "target_raise", *COMMITMENT_STATUSES, "committed_or_funded", "pct_of_target"], "rows": rows,
            "totals": {k: sum(r[k] for r in rows) for k in ("target_raise", *COMMITMENT_STATUSES, "committed_or_funded")}}


# ---------------- snapshots and trend ----------------
@job("pipeline_snapshot", "Store today's pipeline totals so past forecasts can be compared with outcomes")
def _job_snapshot(db: Session) -> dict:
    return take_snapshot(db)


def take_snapshot(db: Session, on: date | None = None) -> dict:
    on = on or date.today()
    deals_svc.ensure_default_pipelines(db)
    made = 0
    for p in db.scalars(select(Pipeline)):
        if db.scalar(select(PipelineSnapshot).where(PipelineSnapshot.taken_on == on, PipelineSnapshot.pipeline_id == p.id)):
            continue
        n = vol = wv = wc = 0
        for d in db.scalars(select(Deal).where(Deal.pipeline_id == p.id, Deal.status == "open", Deal.deleted_at.is_(None))):
            prob = deals_svc.effective_probability(d) / 100
            n += 1
            vol += d.price or 0
            wv += round((d.price or 0) * prob)
            wc += round((deals_svc.gross_of(d) or 0) * prob)
        db.add(PipelineSnapshot(taken_on=on, pipeline_id=p.id, open_deals=n, volume=vol, weighted_volume=wv, weighted_commission=wc))
        made += 1
    db.flush()
    return {"snapshots_created": made, "date": on.isoformat()}


def pipeline_trend(db: Session, user: User, weeks: int = 52) -> dict:
    show = can_see_commission(user)
    since = date.today() - timedelta(weeks=weeks)
    agg: dict = defaultdict(lambda: {"open_deals": 0, "volume": 0, "weighted_volume": 0, "weighted_commission": 0})
    for s in db.scalars(select(PipelineSnapshot).where(PipelineSnapshot.taken_on >= since)):
        a = agg[s.taken_on]
        a["open_deals"] += s.open_deals
        a["volume"] += s.volume
        a["weighted_volume"] += s.weighted_volume
        a["weighted_commission"] += s.weighted_commission
    series = [{"date": d, **v} for d, v in sorted(agg.items())]
    if not show:
        for r in series:
            r.pop("weighted_commission", None)
    out = {"report": "pipeline_trend", "series": series, "commission_visible": show}
    # forecast vs outcome: what the snapshot ~90 days ago expected vs GCI actually closed since
    if show and series:
        target = date.today() - timedelta(days=90)
        past = min(series, key=lambda r: abs((r["date"] - target).days))
        actual = sum(deals_svc.gross_of(d) or 0 for d in won_deals(db, past["date"], date.today()))
        out["forecast_vs_outcome"] = {"snapshot_date": past["date"], "weighted_commission_then": past["weighted_commission"], "gci_closed_since": actual,
                                      "ratio": round(actual / past["weighted_commission"], 2) if past["weighted_commission"] else None}
    return out


# ---------------- goals ----------------
def goals_actuals(db: Session, user: User, year: int | None = None) -> dict:
    year = year or date.today().year
    names = user_names(db)
    out = []
    for g in db.scalars(select(Goal).where(Goal.period_start >= date(year, 1, 1), Goal.period_start <= date(year, 12, 31)).order_by(Goal.period_start, Goal.id)):
        if g.metric == "gci" and not can_see_commission(user):
            continue
        s, e = goal_period(g)
        e = min(e, date.today())
        won = [d for d in won_deals(db, s, e) if not g.user_id or g.user_id in gci_allocation(d) or d.owner_user_id == g.user_id]
        taken = [l for l in listings_taken(db, s, e) if not g.user_id or l.owner_user_id == g.user_id]
        if g.user_id:
            vol = sum(d.price or 0 for d in won if d.owner_user_id == g.user_id)
            gci = sum(gci_allocation(d).get(g.user_id, 0) for d in won)
            cnt = sum(1 for d in won if d.owner_user_id == g.user_id)
        else:
            vol, gci, cnt = sum(d.price or 0 for d in won), sum(deals_svc.gross_of(d) or 0 for d in won), len(won)
        actual = {"closed_volume": vol, "gci": gci, "closed_deals": cnt, "listings_taken": len(taken)}[g.metric]
        out.append({"id": g.id, "user_id": g.user_id, "user": names.get(g.user_id, "Firm"), "metric": g.metric, "period_type": g.period_type, "period_start": g.period_start, "target": g.target,
                    "actual": actual, "pct": round(actual / g.target * 100, 1) if g.target else 0})
    return {"year": year, "items": out}


# ---------------- dashboard ----------------
def dashboard(db: Session, user: User) -> dict:
    today = date.today()
    show = can_see_commission(user)
    ytd = production(db, user, period="ytd", group_by="month")
    t12 = production(db, user, period="12m", group_by="month")
    open_p = pipeline_report(db, user, group_by="stage")
    active = db.execute(select(func.count(), func.coalesce(func.sum(Listing.list_price), 0)).where(Listing.status == "active", Listing.deleted_at.is_(None))).one()
    uc = db.execute(select(func.count(), func.coalesce(func.sum(Listing.list_price), 0)).where(Listing.status == "under_contract", Listing.deleted_at.is_(None))).one()
    overdue = db.scalar(select(func.count()).select_from(Activity).where(Activity.status == "planned", Activity.assignee_user_id == user.id, Activity.due_at < datetime.combine(today, datetime.min.time())))
    new_leads = db.scalar(select(func.count()).select_from(Lead).where(Lead.status == "new"))
    hot = db.scalar(select(func.count()).select_from(Lead).where(Lead.status == "new", Lead.score >= 60))
    expiring = db.scalar(select(func.count()).select_from(Listing).where(Listing.status == "active", Listing.expiration_date >= today, Listing.expiration_date <= today + timedelta(days=60)))
    stalled = sum(1 for d in db.scalars(select(Deal).where(Deal.status == "open", Deal.deleted_at.is_(None))) if deals_svc.is_rotting(d))
    cutoff = utcnow() - timedelta(days=90)
    untouched = db.scalar(select(func.count()).select_from(Contact).where(Contact.deleted_at.is_(None), Contact.contact_types.like('%"owner"%'), (Contact.last_contact_at.is_(None)) | (Contact.last_contact_at < cutoff)))
    top_leads = [{"id": l.id, "name": l.name, "score": l.score, "address": l.property.address if l.property else None, "city": l.property.city if l.property else None,
                  "reason": ((l.trigger_reason or {}).get("matches") or [{}])[0].get("rule")} for l in db.scalars(select(Lead).where(Lead.status == "new").order_by(Lead.score.desc()).limit(5))]
    trend = pipeline_trend(db, user, 26)
    kpis = {"ytd_closed_volume": ytd["totals"]["closed_volume"], "ytd_closed_deals": ytd["totals"]["closed_deals"], "ytd_listings_taken": ytd["totals"]["listings_taken"],
            "active_listings": {"count": active[0], "value": int(active[1])}, "under_contract": {"count": uc[0], "value": int(uc[1])},
            "open_pipeline": {"deals": open_p["totals"]["deals"], "volume": open_p["totals"]["volume"], "weighted_volume": open_p["totals"]["weighted_volume"]},
            "overdue_tasks": overdue, "new_leads": new_leads, "hot_leads": hot, "expiring_listings_60": expiring, "stalled_deals": stalled, "owners_untouched_90": untouched}
    if show:
        kpis["ytd_gci"] = ytd["totals"]["gci"]
        kpis["open_pipeline"]["weighted_commission"] = open_p["totals"]["weighted_commission"]
    return {"kpis": kpis, "goals": ytd["goals"], "production_by_month": t12["rows"], "pipeline_trend": trend["series"], "top_leads": top_leads, "commission_visible": show}


# ---------------- CSV ----------------
def to_csv(report: dict) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    cols = report["columns"]
    w.writerow(cols)
    for r in report["rows"]:
        w.writerow(["" if r.get(c) is None else r.get(c) for c in cols])
    return buf.getvalue()
