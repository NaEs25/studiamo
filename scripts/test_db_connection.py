"""
Script to test Supabase PostgreSQL database connection using SUPABASE_DB_URL from .env
"""
import os
import sys
from pathlib import Path

# Add project root to path
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

try:
    from dotenv import load_dotenv
    load_dotenv(BASE_DIR / ".env")
except ImportError:
    pass

db_url = os.getenv("SUPABASE_DB_URL")

# Fallback: manual parsing of .env if load_dotenv didn't load it
if not db_url:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("SUPABASE_DB_URL="):
                    val = line.split("=", 1)[1].strip()
                    # Strip leading/trailing quotes
                    if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                        val = val[1:-1]
                    db_url = val
                    os.environ["SUPABASE_DB_URL"] = db_url
                    break

if not db_url:
    print("❌ ERROR: SUPABASE_DB_URL is not set in .env")
    sys.exit(1)

print("Found SUPABASE_DB_URL in environment.")
print("Testing connection to Supabase PostgreSQL...")

connected = False

# Try psycopg2
try:
    import psycopg2
    print("Testing via psycopg2...")
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    cur.execute("SELECT version();")
    version = cur.fetchone()[0]
    print(f"✅ SUCCESS! Connected to Supabase PostgreSQL via psycopg2.\n   Version: {version[:60]}...")
    conn.close()
    connected = True
except Exception as e:
    print(f"⚠️ psycopg2 connection test: {e}")

if not connected:
    # Try sqlalchemy
    try:
        from sqlalchemy import create_engine, text
        print("Testing via SQLAlchemy...")
        engine = create_engine(db_url)
        with engine.connect() as conn:
            res = conn.execute(text("SELECT version();")).fetchone()
            print(f"✅ SUCCESS! Connected to Supabase PostgreSQL via SQLAlchemy.\n   Version: {res[0][:60]}...")
            connected = True
    except Exception as e:
        print(f"⚠️ SQLAlchemy connection test: {e}")

if not connected:
    # Try psycopg (v3)
    try:
        import psycopg
        print("Testing via psycopg (v3)...")
        conn = psycopg.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()[0]
        print(f"✅ SUCCESS! Connected to Supabase PostgreSQL via psycopg (v3).\n   Version: {version[:60]}...")
        conn.close()
        connected = True
    except Exception as e:
        print(f"⚠️ psycopg v3 connection test: {e}")

if not connected:
    print("\n❌ Could not connect to Supabase PostgreSQL.")
    print("Please check:")
    print(" 1. Is the password correct in SUPABASE_DB_URL?")
    print(" 2. Are psycopg2, psycopg, or sqlalchemy installed in your Python environment?")
    print(" 3. Is network access to port 5432 / 6543 open?")
    sys.exit(1)
