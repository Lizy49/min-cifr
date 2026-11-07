"""Хранение истории проверок в SQLite (файл edumonitor.db в корне проекта)."""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "edumonitor.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS checks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            org_type TEXT NOT NULL,
            score REAL NOT NULL,
            pages_checked INTEGER,
            links_checked INTEGER,
            broken_links INTEGER,
            sections_total INTEGER,
            sections_present INTEGER,
            checked_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            check_id INTEGER NOT NULL,
            section_id TEXT,
            title TEXT,
            severity TEXT,
            kind TEXT,
            description TEXT,
            recommendation TEXT,
            FOREIGN KEY (check_id) REFERENCES checks (id)
        )
    """)
    return conn


def save_report(report):
    """Сохраняет отчёт и все его проблемы в базу, возвращает id записи проверки."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO checks
            (url, org_type, score, pages_checked, links_checked, broken_links,
             sections_total, sections_present, checked_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        report.url, report.org_type, report.score, report.pages_checked,
        report.links_checked, report.broken_links, report.sections_total,
        report.sections_present, report.checked_at,
    ))
    check_id = cur.lastrowid

    for issue in report.issues:
        cur.execute("""
            INSERT INTO issues
                (check_id, section_id, title, severity, kind, description, recommendation)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            check_id, issue.section_id, issue.title, issue.severity,
            issue.kind, issue.description, issue.recommendation,
        ))

    conn.commit()
    conn.close()
    return check_id


def load_history(limit=50):
    """Возвращает последние проверки: (id, url, org_type, score, checked_at)."""
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, url, org_type, score, checked_at
        FROM checks
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    rows = cur.fetchall()
    conn.close()
    return rows


def load_check_with_issues(check_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM checks WHERE id = ?", (check_id,))
    check_row = cur.fetchone()
    cur.execute("SELECT * FROM issues WHERE check_id = ?", (check_id,))
    issue_rows = cur.fetchall()
    conn.close()
    return check_row, issue_rows
