"""Stage 6 seed: production goals (firm and per broker). Snapshots were derived from real stage history in the deals seed."""
from datetime import date

from ..models.reports import Goal


def seed(db, ctx):
    y = date.today().year
    firm = {"closed_volume": 420_000_000, "gci": 9_500_000, "listings_taken": 60, "closed_deals": 45}
    for m, t in firm.items():
        db.add(Goal(user_id=None, metric=m, period_type="year", period_start=date(y, 1, 1), target=t))
    for q, month in enumerate((1, 4, 7, 10)):
        for m, t in firm.items():
            db.add(Goal(user_id=None, metric=m, period_type="quarter", period_start=date(y, month, 1), target=t // 4))
    per = {"Jim Resha": (120_000_000, 2_600_000, 18), "Kevin Park": (110_000_000, 2_300_000, 16), "Dana Whitfield": (90_000_000, 2_000_000, 14), "Tyler Brooks": (40_000_000, 900_000, 6)}
    for b in ctx["brokers"]:
        if b.name in per:
            vol, gci, lst = per[b.name]
            db.add(Goal(user_id=b.id, metric="closed_volume", period_type="year", period_start=date(y, 1, 1), target=vol))
            db.add(Goal(user_id=b.id, metric="gci", period_type="year", period_start=date(y, 1, 1), target=gci))
            db.add(Goal(user_id=b.id, metric="listings_taken", period_type="year", period_start=date(y, 1, 1), target=lst))
    db.flush()
