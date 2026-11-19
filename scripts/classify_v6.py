"""Write data/ranking-v6-classification.jsonl from the v6 ranking.

Buckets are reused by term from the v5 classification first, then v3; the six
terms new to the scan prefix are classified here (all verbs -> bucket a). The
scan runs in rank order and stops when the vocabulary side (a + c) reaches 500.
"""

import json
from collections import Counter
from pathlib import Path

NEW = {
    "untrack": "a",
    "unassign": "a",
    "unpublish": "a",
    "precompute": "a",
    "predefine": "a",
    "repoint": "a",
}

CAP = 1600
TARGET = 500
OUT = Path("data/ranking-v6-classification.jsonl")

rows = json.load(open("out/gharchive-rank-day-v6-df10/ranking.json", encoding="utf-8"))
v5c = {r["term"]: r["bucket"] for r in map(json.loads, open("data/ranking-v5-classification.jsonl", encoding="utf-8"))}
v3c = {r["term"]: r["bucket"] for r in map(json.loads, open("data/ranking-v3-classification.jsonl", encoding="utf-8"))}

out = []
a_c = 0
reused = {"v5": 0, "v3": 0, "new": 0}
for rank, row in enumerate(rows[:CAP], start=1):
    term = row["term"]
    if term in v5c:
        bucket = v5c[term]
        reused["v5"] += 1
    elif term in v3c:
        bucket = v3c[term]
        reused["v3"] += 1
    else:
        bucket = NEW[term]
        reused["new"] += 1
    out.append({
        "term": term,
        "rank": rank,
        "tf": row["tf"],
        "df": row["df"],
        "score": round(row["se_specificity"], 6),
        "bucket": bucket,
    })
    if bucket in ("a", "c"):
        a_c += 1
    if a_c == TARGET:
        break

with OUT.open("w", encoding="utf-8", newline="\n") as handle:
    for row in out:
        handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")

print("rows:", len(out), "last rank:", out[-1]["rank"], "a+c:", a_c)
print("source:", reused)
print("buckets:", Counter(r["bucket"] for r in out))
print("top-500 buckets:", Counter(r["bucket"] for r in out if r["rank"] <= 500))
