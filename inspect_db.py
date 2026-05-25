import psycopg2

conn = psycopg2.connect(
    dbname='postgres',
    user='admin',
    password='[PASSWORD]',
    host='localhost',
    port=5432
)
cur = conn.cursor()

# 1. List all tables
cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
print("=" * 60)
print("ALL TABLES IN olist-ecommerce-db")
print("=" * 60)
for r in cur.fetchall():
    print(f"  - {r[0]}")

# 2. Data Dictionary table - schema
print("\n" + "=" * 60)
print("DATA_DICTIONARY — COLUMNS")
print("=" * 60)
cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'data_dictionary' 
    ORDER BY ordinal_position
""")
for r in cur.fetchall():
    print(f"  {r[0]:30s} | {r[1]}")

# 3. Data Dictionary — row count + sample rows
cur.execute("SELECT COUNT(*) FROM data_dictionary")
print(f"\nTotal rows: {cur.fetchone()[0]}")

print("\n--- Sample rows (first 10) ---")
cur.execute("SELECT * FROM data_dictionary LIMIT 10")
cols = [desc[0] for desc in cur.description]
print("  " + " | ".join(cols))
print("  " + "-" * 120)
for r in cur.fetchall():
    print("  " + " | ".join(str(v)[:40] for v in r))

# 4. Join Metadata table - schema
print("\n" + "=" * 60)
print("JOIN_METADATA — COLUMNS")
print("=" * 60)
cur.execute("""
    SELECT column_name, data_type 
    FROM information_schema.columns 
    WHERE table_name = 'join_metadata' 
    ORDER BY ordinal_position
""")
for r in cur.fetchall():
    print(f"  {r[0]:30s} | {r[1]}")

# 5. Join Metadata — row count + all rows
cur.execute("SELECT COUNT(*) FROM join_metadata")
print(f"\nTotal rows: {cur.fetchone()[0]}")

print("\n--- All join_metadata rows ---")
cur.execute("SELECT * FROM join_metadata")
cols = [desc[0] for desc in cur.description]
print("  " + " | ".join(cols))
print("  " + "-" * 120)
for r in cur.fetchall():
    print("  " + " | ".join(str(v)[:50] for v in r))

# 6. Distinct tables in data dictionary
print("\n" + "=" * 60)
print("DISTINCT TABLES IN DATA_DICTIONARY")
print("=" * 60)
cur.execute("SELECT DISTINCT table_name FROM data_dictionary ORDER BY table_name")
for r in cur.fetchall():
    print(f"  - {r[0]}")

conn.close()
print("\nDone.")
