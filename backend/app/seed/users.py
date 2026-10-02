from ..models.core_sys import User
from ..security import hash_password, new_salt

DEMO_PASSWORD = "demo1234"
USERS = [
    ("jim@resha.group", "Jim Resha", "admin", "SVP / Chief Investment Strategist", "Resha Group"),
    ("maria@resha.group", "Maria Delgado", "manager", "Director of Operations", "Resha Group"),
    ("kevin@resha.group", "Kevin Park", "broker", "Senior Associate, Industrial", "Resha Group"),
    ("dana@resha.group", "Dana Whitfield", "broker", "Associate, Retail", "Resha Group"),
    ("tyler@1880capital.com", "Tyler Brooks", "broker", "Investor Relations", "1880 Capital"),
    ("priya@resha.group", "Priya Nair", "assistant", "Transaction Coordinator", "Resha Group"),
    ("auditor@resha.group", "Sam Auditor", "read_only", "Compliance (read-only)", "Resha Group"),
]


def seed_users(db):
    out = []
    for email, name, role, title, team in USERS:
        salt = new_salt()
        u = User(email=email, name=name, role=role, title=title, team=team, salt=salt,
                 password_hash=hash_password(DEMO_PASSWORD, salt))
        db.add(u)
        out.append(u)
    db.flush()
    return out
