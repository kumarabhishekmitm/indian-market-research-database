import os

files_to_inspect = [
    "config.py",
    "ops/init_db.py",
    "ops/validate_db.py",
    "ingest/schema.sql"
]

for file_path in files_to_inspect:
    print("=" * 60)
    print(f"FILE: {file_path}")
    print("=" * 60)
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            print(f.read())
    else:
        print("FILE NOT FOUND")
    print("\n")