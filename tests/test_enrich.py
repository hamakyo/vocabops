"""Tests for POS-aware lemmatization and dependency-based collocation enrichment."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from vocabops.enrich import (
    clean_text_for_nlp,
    extract_enrichment,
    load_target_terms,
    record_id,
    run,
)


@dataclass
class FakeToken:
    text: str
    lemma_: str
    pos_: str
    dep_: str = "ROOT"
    is_space: bool = False
    is_punct: bool = False
    head: FakeToken | None = None
    children: list[FakeToken] = field(default_factory=list)

    def add_child(self, child: FakeToken) -> FakeToken:
        child.head = self
        self.children.append(child)
        return child


def _make_doc(tokens: list[FakeToken]) -> list[FakeToken]:
    for tok in tokens:
        if tok.head is None:
            tok.head = tok
    return tokens


class FakeNLP:
    """Deterministic fake spaCy pipeline for offline unit tests."""

    def __init__(self, doc_builder):
        self._doc_builder = doc_builder

    def pipe(self, texts, batch_size: int = 64):
        assert batch_size >= 1
        for text in texts:
            yield self._doc_builder(text)


def test_clean_text_for_nlp_preserves_case_and_strips_code_markup():
    raw = (
        "## Storage layer\n"
        "The Server calls `get(id)` and visits https://example.invalid/docs.\n"
        "Logged at 2026-11-22T10:20:30Z with <p>HTML</p>.\n"
        "```python\n"
        "store.invalidate(cache)\n"
        "```\n"
        "It invalidates the Cache.\n"
    )
    cleaned = clean_text_for_nlp(raw)
    assert "Storage layer" in cleaned
    assert "The Server calls" in cleaned
    assert "It invalidates the Cache." in cleaned
    assert "get(id)" not in cleaned
    assert "https://" not in cleaned
    assert "2026-11-22" not in cleaned
    assert "<p>" not in cleaned
    assert "store.invalidate" not in cleaned
    assert not cleaned.startswith("##")


def test_record_id_matches_vocabops_schema():
    assert record_id("retrieve", "verb") == "retrieve.v"
    assert record_id("fallback", "noun") == "fallback.n"
    assert record_id("canonical", "adjective") == "canonical.adjective"
    assert record_id("recursively", "adverb") == "recursively.adv"


def test_load_target_terms_supports_jsonl_and_text(tmp_path: Path):
    jsonl = tmp_path / "terms.jsonl"
    jsonl.write_text(
        '{"term":"Serialize","rank":1}\n{"lemma":"paginate","rank":2}\n\n',
        encoding="utf-8",
    )
    assert load_target_terms(jsonl) == frozenset({"serialize", "paginate"})

    txt = tmp_path / "terms.txt"
    txt.write_text("# comment\nRetrieve\n\nfallback\n", encoding="utf-8")
    assert load_target_terms(txt) == frozenset({"retrieve", "fallback"})


def test_extract_enrichment_pos_forms_and_all_collocation_patterns():
    # Doc 1: "We invalidated the cache and propagated errors to callers deterministically."
    # plus "underlying cause" (amod) and "fallback path" (compound)
    inv1 = FakeToken("invalidated", "invalidate", "VERB", "ROOT")
    cache1 = inv1.add_child(FakeToken("cache", "cache", "NOUN", "dobj"))

    prop1 = FakeToken("propagated", "propagate", "VERB", "conj")
    err1 = prop1.add_child(FakeToken("errors", "error", "NOUN", "dobj"))
    prep1 = prop1.add_child(FakeToken("to", "to", "ADP", "prep"))
    caller1 = prep1.add_child(FakeToken("callers", "caller", "NOUN", "pobj"))
    det1 = prop1.add_child(
        FakeToken("deterministically", "deterministically", "ADV", "advmod")
    )

    cause1 = FakeToken("cause", "cause", "NOUN", "ROOT")
    under1 = cause1.add_child(FakeToken("underlying", "underlie", "ADJ", "amod"))

    path1 = FakeToken("path", "path", "NOUN", "ROOT")
    fb1 = path1.add_child(FakeToken("fallback", "fallback", "NOUN", "compound"))

    # Noise tokens that must be ignored
    noise_px = FakeToken("390px", "390px", "NOUN", "dep")
    noise_shard = FakeToken("18t02", "18t02", "NOUN", "dep")
    noise_stop = FakeToken("the", "the", "DET", "det")

    doc1 = _make_doc(
        [
            inv1,
            cache1,
            prop1,
            err1,
            prep1,
            caller1,
            det1,
            cause1,
            under1,
            path1,
            fb1,
            noise_px,
            noise_shard,
            noise_stop,
        ]
    )

    # Doc 2: Passive "The cache is invalidated" + "fallback" as verb + "fallback path"
    inv2 = FakeToken("invalidated", "invalidate", "VERB", "ROOT")
    cache2 = inv2.add_child(FakeToken("cache", "cache", "NOUN", "nsubjpass"))
    inv2_again = FakeToken("invalidating", "invalidate", "VERB", "advcl")
    cache2_again = inv2_again.add_child(FakeToken("cache", "cache", "NOUN", "dobj"))

    fb_verb = FakeToken("fallbacks", "fallback", "VERB", "ROOT")
    path2 = FakeToken("path", "path", "NOUN", "ROOT")
    fb2 = path2.add_child(FakeToken("fallback", "fallback", "NOUN", "compound"))

    # Transformer taggers often label prenominal "underlying" as VERB + amod
    store2 = FakeToken("store", "store", "NOUN", "ROOT")
    under2 = store2.add_child(FakeToken("underlying", "underlie", "VERB", "amod"))

    doc2 = _make_doc(
        [inv2, cache2, inv2_again, cache2_again, fb_verb, path2, fb2, store2, under2]
    )

    rows = extract_enrichment(
        ["github", "stackoverflow"],
        [doc1, doc2],
        min_df=1,
        min_collocation_count=1,
    )
    by_id = {row["id"]: row for row in rows}

    # Noise filtered out
    assert "390px.n" not in by_id
    assert "18t02.n" not in by_id

    # Passive + active verb_obj merged cleanly; df counts unique docs (2), count is 3
    inv_row = by_id["invalidate.v"]
    assert inv_row["tf"] == 3
    assert inv_row["df"] == 2
    assert inv_row["pos_share"] == 1.0
    assert inv_row["forms"] == ["invalidated", "invalidating"]
    assert inv_row["by_source"] == {
        "github": {"tf": 1, "df": 1},
        "stackoverflow": {"tf": 2, "df": 1},
    }
    assert inv_row["collocations"] == [
        {"phrase": "invalidate cache", "pattern": "verb_obj", "count": 3, "df": 2}
    ]

    # verb_prep_obj and verb_adv captured on propagate.v and deterministically.adv
    prop_collocs = {
        (c["phrase"], c["pattern"]) for c in by_id["propagate.v"]["collocations"]
    }
    assert ("propagate error", "verb_obj") in prop_collocs
    assert ("propagate to caller", "verb_prep_obj") in prop_collocs
    assert ("propagate deterministically", "verb_adv") in prop_collocs
    assert by_id["deterministically.adv"]["collocations"] == [
        {
            "phrase": "propagate deterministically",
            "pattern": "verb_adv",
            "count": 1,
            "df": 1,
        }
    ]

    # "underlying" adjective kept intact for both ADJ and VERB+amod uses
    assert "underlying.adjective" in by_id
    assert "underlie.v" not in by_id
    assert by_id["underlying.adjective"]["df"] == 2
    assert by_id["underlying.adjective"]["collocations"] == [
        {"phrase": "underlying cause", "pattern": "adj_noun", "count": 1, "df": 1},
        {"phrase": "underlying store", "pattern": "adj_noun", "count": 1, "df": 1},
    ]

    # POS homograph split: fallback.n (2/3) vs fallback.v (1/3)
    fb_n = by_id["fallback.n"]
    fb_v = by_id["fallback.v"]
    assert fb_n["tf"] == 2
    assert fb_n["pos_share"] == round(2 / 3, 4)
    assert fb_n["collocations"] == [
        {"phrase": "fallback path", "pattern": "noun_compound", "count": 2, "df": 2}
    ]
    assert fb_v["tf"] == 1
    assert fb_v["pos_share"] == round(1 / 3, 4)


def test_run_is_byte_identical_across_repeated_runs(tmp_path: Path):
    corpus_jsonl = tmp_path / "docs.jsonl"
    corpus_jsonl.write_text(
        json.dumps(
            {
                "doc_id": "d1",
                "source_family": "github",
                "text": "Invalidate the cache on deploy.",
            }
        )
        + "\n"
        + json.dumps(
            {
                "doc_id": "d2",
                "source_family": "stackoverflow",
                "text": "The cache is invalidated after timeout.",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    terms_file = tmp_path / "terms.jsonl"
    terms_file.write_text('{"term":"invalidate"}\n{"term":"cache"}\n', encoding="utf-8")

    def build_doc(text: str):
        inv = FakeToken("invalidated", "invalidate", "VERB", "ROOT")
        cache = inv.add_child(FakeToken("cache", "cache", "NOUN", "dobj"))
        return _make_doc([inv, cache])

    out_a = tmp_path / "run_a"
    out_b = tmp_path / "run_b"

    meta = {
        "model": "fake-trf",
        "model_version": "0.0.1",
        "spacy_version": "3.8.0",
        "device_requested": "auto",
        "device_used": "gpu",
    }

    manifest_a = run(
        corpus_jsonl,
        out_a,
        "test-snap-01",
        terms_path=terms_file,
        min_df=2,
        min_collocation_count=2,
        nlp=FakeNLP(build_doc),
        model_meta=meta,
    )
    manifest_b = run(
        corpus_jsonl,
        out_b,
        "test-snap-01",
        terms_path=terms_file,
        min_df=2,
        min_collocation_count=2,
        nlp=FakeNLP(build_doc),
        model_meta=meta,
    )

    assert manifest_a == manifest_b
    assert (out_a / "enrichment.jsonl").read_bytes() == (
        out_b / "enrichment.jsonl"
    ).read_bytes()
    assert (out_a / "manifest.json").read_bytes() == (
        out_b / "manifest.json"
    ).read_bytes()

    assert manifest_a["documents"] == 2
    assert manifest_a["sources"] == ["github", "stackoverflow"]
    assert manifest_a["terms_filter_count"] == 2
    assert manifest_a["emitted_entries"] == 2


def test_run_on_fixture_directory_and_validation_errors(tmp_path: Path):
    fixture_dir = Path(__file__).resolve().parent.parent / "data/fixtures/sample_corpus"

    def build_doc(_text: str):
        tok = FakeToken("retrieves", "retrieve", "VERB", "ROOT")
        obj = tok.add_child(FakeToken("session", "session", "NOUN", "dobj"))
        return _make_doc([tok, obj])

    out_dir = tmp_path / "fixture_out"
    manifest = run(
        fixture_dir,
        out_dir,
        "fixture-enrich-proto",
        min_collocation_count=1,
        nlp=FakeNLP(build_doc),
    )
    assert manifest["documents"] == 5
    assert manifest["sources"] == ["fixture"]
    assert manifest["emitted_entries"] == 2

    with pytest.raises(ValueError, match="snapshot_id"):
        run(fixture_dir, out_dir, "   ", nlp=FakeNLP(build_doc))
    with pytest.raises(FileNotFoundError):
        run(tmp_path / "missing", out_dir, "snap", nlp=FakeNLP(build_doc))
