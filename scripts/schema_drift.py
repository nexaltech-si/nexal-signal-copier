#!/usr/bin/env python3
"""
Schema drift check: every table and column the Prisma schemas expect must exist
in the SQLite database. A field added to schema.prisma without a migration
compiles fine and only fails at runtime ("column ... does not exist", P2022) —
this catches that before it ships.

  python scripts/schema_drift.py <database.db> <schema.prisma> [<schema.prisma> ...]

Exit 0 = no drift, 1 = missing tables/columns (listed). Extra DB columns are fine.
"""
import re
import sqlite3
import sys

SCALARS = {"String", "Int", "Float", "Boolean", "DateTime", "Json", "BigInt", "Decimal", "Bytes"}


def expected(schema_path):
    text = open(schema_path, encoding="utf-8").read()
    enums = set(re.findall(r"^enum\s+(\w+)", text, re.M))
    tables = {}
    for name, body in re.findall(r"^model\s+(\w+)\s*\{(.*?)^\}", text, re.M | re.S):
        mapped = re.search(r'@@map\("([^"]+)"\)', body)
        cols = set()
        for line in body.splitlines():
            line = line.split("//", 1)[0].strip()
            m = re.match(r"(\w+)\s+(\w+)(\[\])?\??", line)
            if not m or line.startswith("@@"):
                continue
            field, ftype, is_list = m.groups()
            if ftype not in SCALARS and ftype not in enums:
                continue  # relation field — no column
            if is_list:
                continue
            col = re.search(r'@map\("([^"]+)"\)', line)
            cols.add(col.group(1) if col else field)
        tables[mapped.group(1) if mapped else name] = cols
    return tables


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    db = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
    actual = {t: {r[1] for r in db.execute(f'PRAGMA table_info("{t}")')}
              for (t,) in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    problems = []
    for schema in sys.argv[2:]:
        for table, cols in sorted(expected(schema).items()):
            if table not in actual:
                problems.append(f"{schema}: table {table} missing")
                continue
            for col in sorted(cols - actual[table]):
                problems.append(f"{schema}: column {table}.{col} missing")
    for p in problems:
        print(f"  ❌ {p}")
    if not problems:
        print("  ✅ database has every table and column both schemas expect")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
