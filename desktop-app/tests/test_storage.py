import json

from edu_audit import storage


def test_seed_is_idempotent_and_filters_only_school_and_garden(tmp_path):
    db = tmp_path / "audit.sqlite3"
    source = tmp_path / "orgs.json"
    source.write_text(json.dumps([
        {"name": "Школа", "kind": "school", "url": "https://school.example/"},
        {"name": "Детский сад", "kind": "garden", "url": "https://garden.example/"},
        {"name": "Техникум", "kind": "technical", "url": "https://college.example/"},
    ], ensure_ascii=False), encoding="utf-8")
    storage.initialize(db)
    assert storage.seed_organizations(db, source) == 2
    assert storage.seed_organizations(db, source) == 0
    assert len(storage.list_organizations(db)) == 2
    assert len(storage.list_organizations(db, "school")) == 1


def test_run_round_trip_preserves_unicode_evidence(tmp_path):
    db = tmp_path / "audit.sqlite3"
    source = tmp_path / "orgs.json"
    source.write_text(json.dumps([
        {"name": "Магаданская школа", "kind": "school", "url": "https://school.example/"},
    ], ensure_ascii=False), encoding="utf-8")
    storage.initialize(db)
    storage.seed_organizations(db, source)
    org = storage.list_organizations(db)[0]
    report = {
        "organization": org, "status": "completed", "created_at": "2026-11-08T00:00:00+00:00",
        "finished_at": "2026-11-08T00:01:00+00:00",
        "findings": [{"title": "Проверить документы", "evidence": [{"url": org["url"], "snippet": "Русский текст"}]}],
        "pages": [], "meta": {"limited": False},
    }
    run_id = storage.save_run(report, db)
    restored = storage.load_run(run_id, db)
    assert restored["organization"]["name"] == "Магаданская школа"
    assert restored["findings"][0]["evidence"][0]["snippet"] == "Русский текст"
    assert storage.list_history(db)[0]["id"] == run_id
