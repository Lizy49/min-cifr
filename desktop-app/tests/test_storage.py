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


def test_registry_search_is_russian_case_insensitive_and_normalized(tmp_path):
    db = tmp_path / "search.sqlite3"
    source = tmp_path / "orgs.json"
    source.write_text(json.dumps([
        {"name": "МБОУ Школа № 21 имени Ёлки", "kind": "school", "url": "https://school.example/"},
        {"name": "Детский сад Ромашка", "kind": "garden", "url": "https://garden.example/"},
    ], ensure_ascii=False), encoding="utf-8")
    storage.initialize(db)
    storage.seed_organizations(db, source)

    assert [row["name"] for row in storage.list_organizations(db, query="школа № 21")] == [
        "МБОУ Школа № 21 имени Ёлки"
    ]
    assert [row["name"] for row in storage.list_organizations(db, query="ЕЛКИ")] == [
        "МБОУ Школа № 21 имени Ёлки"
    ]
    assert [row["name"] for row in storage.list_organizations(db, query="РОМАШКА")] == [
        "Детский сад Ромашка"
    ]
    assert storage.list_organizations(db, query="%_") == []


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



def test_reference_is_unique_per_kind_and_latest_report_can_be_loaded(tmp_path):
    db = tmp_path / "audit.sqlite3"
    source = tmp_path / "orgs.json"
    source.write_text(json.dumps([
        {"name": "Школа 1", "kind": "school", "url": "https://school1.example/"},
        {"name": "Школа 2", "kind": "school", "url": "https://school2.example/"},
        {"name": "Сад 1", "kind": "garden", "url": "https://garden.example/"},
    ], ensure_ascii=False), encoding="utf-8")
    storage.initialize(db)
    storage.seed_organizations(db, source)
    orgs = {item["url"]: item for item in storage.list_organizations(db)}
    school1 = orgs["https://school1.example/"]
    school2 = orgs["https://school2.example/"]
    garden = orgs["https://garden.example/"]
    storage.set_reference(school1["id"], db)
    storage.set_reference(school2["id"], db)
    assert storage.get_reference("school", db)["id"] == school2["id"]
    storage.set_reference(garden["id"], db)
    assert storage.get_reference("garden", db)["id"] == garden["id"]
    assert storage.get_reference("school", db)["id"] == school2["id"]


def test_latest_reports_returns_only_latest_completed_run_per_organization(tmp_path):
    db = tmp_path / "latest.sqlite3"
    source = tmp_path / "orgs.json"
    source.write_text(json.dumps([
        {"name": "Школа", "kind": "school", "url": "https://school.example/"},
        {"name": "Детский сад", "kind": "garden", "url": "https://garden.example/"},
    ], ensure_ascii=False), encoding="utf-8")
    storage.initialize(db)
    storage.seed_organizations(db, source)
    organizations = storage.list_organizations(db)
    for org, status, stamp in ((organizations[0], "completed", "2026-11-07"),
                               (organizations[0], "failed", "2026-11-08"),
                               (organizations[1], "completed", "2026-11-08")):
        storage.save_run({"organization": org, "status": status, "created_at": stamp,
                          "findings": [], "pages": [], "meta": {}}, db)
    latest = storage.list_latest_reports(db)
    assert len(latest) == 2
    assert {report["organization"]["name"] for report in latest} == {"Школа", "Детский сад"}
    assert all(report["status"] == "completed" for report in latest)



def test_initialize_migrates_database_without_reference_column(tmp_path):
    import sqlite3
    db = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute("""
            CREATE TABLE organizations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                kind TEXT NOT NULL CHECK(kind IN ('school','garden')),
                url TEXT NOT NULL UNIQUE,
                source TEXT NOT NULL DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1
            )
        """)
    storage.initialize(db)
    with sqlite3.connect(db) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(organizations)")}
    assert "is_reference" in columns



def test_fact_sources_are_persisted_and_limited_to_five(tmp_path):
    db = tmp_path / "audit.sqlite3"
    source = tmp_path / "orgs.json"
    source.write_text(json.dumps([
        {"name": "Школа", "kind": "school", "url": "https://school.example/"},
    ], ensure_ascii=False), encoding="utf-8")
    storage.initialize(db)
    storage.seed_organizations(db, source)
    org = storage.list_organizations(db)[0]
    storage.set_fact_sources(org["id"], [
        "https://regional.example/news/",
        "https://ministry.example/press/",
    ], db)
    restored = storage.list_organizations(db)[0]
    assert restored["fact_sources"] == [
        "https://regional.example/news/",
        "https://ministry.example/press/",
    ]
    import pytest
    with pytest.raises(ValueError):
        storage.set_fact_sources(org["id"], [
            "https://one.example", "https://two.example", "https://three.example",
            "https://four.example", "https://five.example", "https://six.example",
        ], db)



def test_application_settings_round_trip(tmp_path):
    storage.initialize(tmp_path / "settings.sqlite3")
    value = {"source_name": "requirements.docx", "requirements": [{"id": "REQ-001"}]}
    storage.set_setting("active_specification", value, tmp_path / "settings.sqlite3")
    assert storage.get_setting("active_specification", tmp_path / "settings.sqlite3") == value
    assert storage.get_setting("missing", tmp_path / "settings.sqlite3") is None
