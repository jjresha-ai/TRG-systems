import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ENV = os.environ.get("TRG_ENV", "development")
DATABASE_URL = os.environ.get("TRG_DATABASE_URL", f"sqlite:///{BASE_DIR / 'trg.db'}")
STORAGE_DIR = Path(os.environ.get("TRG_STORAGE_DIR", BASE_DIR / "storage"))
SECRET = os.environ.get("TRG_SECRET", "dev-only-secret-change-me")
TOKEN_TTL_SECONDS = int(os.environ.get("TRG_TOKEN_TTL", 60 * 60 * 12))

if ENV == "production" and SECRET == "dev-only-secret-change-me":
    raise RuntimeError("TRG_SECRET must be set in production")
