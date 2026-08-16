"""
Standalone entry point for applying the schema to a Supabase/Postgres project.

Use this to bootstrap a brand-new project (e.g. setting up a separate
staging database, or a fresh self-hosted install) : point SUPABASE_DB_URL
at it and run this once. The app itself no longer depends on this script
being run by hand: app.main.lifespan() calls the same
app.schema.ensure_schema_up_to_date() automatically on every startup, so
day-to-day column additions don't need a manual step anymore. This file
stays for the one remaining case that isn't "the app already has a
connection": pointing at a project for the very first time.
"""
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

db_url = os.getenv("SELFHOSTED_DATABASE_URL") or os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
if not db_url and (BASE_DIR / ".env").exists():
    with open(BASE_DIR / ".env", "r", encoding="utf-8") as f:
        env_vars = {}
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                env_vars[k] = v
        db_url = env_vars.get("SELFHOSTED_DATABASE_URL") or env_vars.get("DATABASE_URL") or env_vars.get("SUPABASE_DB_URL")

if not db_url:
    print("❌ ERROR: No database URL (SELFHOSTED_DATABASE_URL / DATABASE_URL / SUPABASE_DB_URL) found in environment or .env")
    sys.exit(1)

import psycopg2
from app.schema import ensure_schema_up_to_date

print("Connecting to PostgreSQL database...")
conn = psycopg2.connect(db_url)
conn.autocommit = True

print("Applying schema (tables, columns, indexes)...")
applied = ensure_schema_up_to_date(conn)
conn.close()
print(f"✅ Schema up to date : {applied} statements applied.")
