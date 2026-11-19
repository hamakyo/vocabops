#!/usr/bin/env python
"""Classify the fused (Borda) ranking and stop where the vocabulary side fills.

The fused ranking draws from a larger vocabulary than any single-source GH
ranking, so the existing classification files cover only 414 of its first
1,600 terms (vs 1,002 of v6). Reused buckets come from ``ranking-v6`` first,
then ``ranking-v5``, then ``ranking-v3``. Every term those files do not cover
is classified here with the same five buckets, in rank order, until a + c
reaches 500 or the scan depth cap is hit.

Bucket rules applied to the new terms (same buckets as Parts 4-8):

    (a) verbs, adjectives/adverbs, process nouns and people/role nouns --
        transferable SE vocabulary
    (b) concrete technical nouns, components, tools, formats, protocols
    (c) abbreviations and acronyms
    (d) fragments and artifacts (camelCase API identifiers, format/version
        tokens, contractions, non-English remnants)
    (e) other / unclear

The sets below are the review; a term not named in a set is (b). The script
fails if the scan is exhausted before a + c reaches 500, rather than emitting
a short view.

    .venv/bin/python scripts/classify_fused.py
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RANKING = REPO_ROOT / "out/combined-rank-v2-borda/ranking.json"
V6 = REPO_ROOT / "data/ranking-v6-classification.jsonl"
V5 = REPO_ROOT / "data/ranking-v5-classification.jsonl"
V3 = REPO_ROOT / "data/ranking-v3-classification.jsonl"
OUT = REPO_ROOT / "data/ranking-fused-classification.jsonl"
CAP = 1600
TARGET = 500

A = set("""
abort accept access activate actual adjust aggregate aggregation align allocate allocation alter
analytic analyze animate animation apply arbitrary ascend assign assignment associate assume
asynchronous asynchronously attach attempt authentication authorization autogenerate automatically
automation await backward balancer behave behavior behaviour belong bind blank boot build calculate
calculation call cancel cancellation capitalize capture change check clickable clone collapsible
collector combine compatible compilation complete completion compose computation concatenate
concatenation concurrent conditional confirm confuse connect connection constrain construct consume
contain correspond correct correctly cumulative custom customize deactivate declare declaration
decrement dedicate define definition delete delegate delimited deployment describe description
deserialization deselect deserialize detail detect detection detach developer differ disallow
discard disconnect dispatch dispatcher display distinct distribute distinguish documentation
download dump dynamically edit empty enable encapsulate enclose encryption enforce enumeration equal
estimate evaluate exact exceed execute exist expand expect explicit explicitly expose expiration
export extend external extract extraction failure feature fetch filter fix flatten flush fold follow
form format functionality generate generic handler hidden highlight horizontal hover hydrate
identical identify idle ignore implementation implicit imply import inactive incompatible incomplete
incorrect increment indent indentation indicate infer inherit inject injectable insert insertion
inspect install installation instantiate instantiation instruct instruction integration intend
intercept interpolation interpret interrupt intersect invalid invalidate invert iterable iterate
iteration iterator issuer limit linear listener load locally locate lock log logic loop lowercase
maintainer manage manually map mapping mask match migrate migration mock modification modify modifier
multiply mutation naming native navigation nest notification notify numeric numerical observable
observe observation observer occur occurrence offline operation optimization optimize option optional
optionally originate overlap overload overridden pad paging pair parallel partial pause pending
perform permission persist persistence pin plain populate positional precision precede precondition
preference prepend preserve priority process projection propagate provider publish push qualify raise
random raw read realtime receive receiver recipient reconnect recur recursion recursive recursively
reformat register registration reject relate relative remove replicate reply represent request require
requirement reset reshape resolve response restore restrict restriction resume retain retrieve return
revert revoke rewrite rotate rotation run runner satisfy save scaffold scan search seed select
selection sender separate separately serializable serialize setting severity shrink shutdown silently
simulate simulation skip slice solve specification specify specific split spawn splice standalone start
static statically store strict strip submit submission subscribe subscriber subscription substitution
subtract succeed successfully sum suppress swap switch synchronize synchronous terminate tester throw
translate transient traverse trigger trim troubleshoot unaffected unavailable uncheck undefined
uninstall unknown unmodified unpack unresolved unsafe unsubscribe unsigned unused upgrade upload
uppercase usage use using valid verbose virtual visibility visible warn watcher worker write yield
preprocess elapse localize invoke decrypt unwrap compress expire implement update convert add exclude
scroll create setup depend sequentially compatibility print pass simplify digest replace sparse
transform copy bound exit execution count compare sequential integrate handle remote send notation
alignment replication internal comparator assignable activation limitation capability set patch limit
include descend conversion current expression allow repeat identity measurement ping reinstall
compliant redraw unspecified applicable agent coder internally persistent inflate initiate decryption
afterward idiomatic dynamic action adding wrap
""".split())

C = set("""
acl addr admin ajax apk apis arg arn arr ascii ast attr auto aws bool buf cert cfg cf char cls cms cmd
concat conf const coord cp cpp cpu crm crud csv ctrl db dd def dep desc dest df dir div dll dns doc
dom ds dsl dt ec2 err es exc exe expr ext fn fmt fs gz hex href html http iam id idx impl inf info ini
ip ipc ipv4 ipv6 iso jar jdbc jpeg jpg kb kwarg lang lat ldap len lib lon max mb md5 meta mime min mod
mp4 msg mysql nan nav nbsp np ns num obj obs opt orm os pdf pd pem php png pos proc prop proto req res
resp rgb rgba rs s3 sdk seq sha1 sh smtp spi sql ssh ssl stat std str sub sync sys tcp tmp txt udp uid
uri url utc val var vm vms wav ws xml xpath yyyy
substr css int dst gui dev ref regexp contrib rect dim ack prod ide asc exec rel aes exp cl dist
""".split())

D = set("""
1d 2d a1 accord alia appid b1 b2 c1 c2 c3 classcastexception classloader classname
classnotfoundexception cloudformation com contenttype d1 datatype dbname devtool doesn didn don
couldn e1 environ f2 f5 filepath groupid h1 h2 h3 hh httpresponse illegalargumentexception
illegalstateexception inputstream interruptedexception ioexception jsonarray jsonobject keyerror m1
newvalue nullpointerexception objectid orderby org outputstream pagesize pathname println ps1
propertyname r1 r2 runtimeexception s1 servername sqlexception tablename t0 t1 t2 t3 tostring
urlencode userid v7 wasn wouldn
activerecord charsequence
""".split())

E: set[str] = set()


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def main() -> int:
    ranking = json.loads(RANKING.read_text(encoding="utf-8"))
    v6 = {row["term"]: row["bucket"] for row in load_jsonl(V6)}
    v5 = {row["term"]: row["bucket"] for row in load_jsonl(V5)}
    v3 = {row["term"]: row["bucket"] for row in load_jsonl(V3)}

    rows: list[dict] = []
    reused = Counter()
    new = Counter()
    a_c = 0
    for rank, row in enumerate(ranking[:CAP], start=1):
        term = row["term"]
        if term in v6:
            bucket, origin = v6[term], "v6"
        elif term in v5:
            bucket, origin = v5[term], "v5"
        elif term in v3:
            bucket, origin = v3[term], "v3"
        else:
            origin = "new"
            if term in A:
                bucket = "a"
            elif term in C:
                bucket = "c"
            elif term in D:
                bucket = "d"
            elif term in E:
                bucket = "e"
            else:
                bucket = "b"
        rows.append(
            {
                "term": term,
                "rank": rank,
                "tf": row["tf"],
                "df": row["df"],
                "score": round(row["se_specificity"], 6),
                "bucket": bucket,
            }
        )
        (reused if origin != "new" else new)[origin] += 1
        if bucket in ("a", "c"):
            a_c += 1
        if a_c == TARGET:
            break
    else:
        raise SystemExit(
            f"a + c reached only {a_c} within the {CAP}-row scan depth; "
            "the vocabulary view would be short"
        )

    with OUT.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")

    print("rows:", len(rows), "last rank:", rows[-1]["rank"], "a+c:", a_c)
    print("reused:", dict(reused), "new:", dict(new))
    print("buckets:", dict(Counter(row["bucket"] for row in rows)))
    print("top-500 buckets:", dict(Counter(r["bucket"] for r in rows if r["rank"] <= 500)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
