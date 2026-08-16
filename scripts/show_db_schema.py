"""
Utility to inspect live database table structures and column types.
Usage: ./venv/bin/python3 scripts/show_db_schema.py
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

from app.database import get_pooled_raw_connection, release_pooled_connection
import psycopg2.extras

conn = get_pooled_raw_connection()
try:
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cursor.execute("""
        SELECT table_name 
        FROM information_schema.tables 
        WHERE table_schema = 'public' 
        ORDER BY table_name;
    """)
    tables = [r["table_name"] for r in cursor.fetchall()]

    print("==================================================")
    print("      LIVE SUPABASE POSTGRESQL DATABASE SCHEMA    ")
    print("==================================================")

    for table in tables:
        cursor.execute("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns 
            WHERE table_schema = 'public' AND table_name = %s
            ORDER BY ordinal_position;
        """, (table,))
        cols = cursor.fetchall()
        print(f"\n📋 Table: {table} ({len(cols)} columns)")
        for c in cols:
            default_str = f" DEFAULT {c['column_default']}" if c['column_default'] else ""
            null_str = " NULL" if c['is_nullable'] == 'YES' else " NOT NULL"
            print(f"  - {c['column_name']:<25} {c['data_type']:<15}{null_str}{default_str}")

    cursor.close()
finally:
    release_pooled_connection(conn)
print("\n==================================================")
