-- Generated from audit/models.py; MySQL 8.0 / 8.4. No passwords.

CREATE DATABASE IF NOT EXISTS education_audit CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE education_audit;


CREATE TABLE IF NOT EXISTS organizations (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	name VARCHAR(600) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	url VARCHAR(512) NOT NULL, 
	source TEXT NOT NULL, 
	reference BOOL NOT NULL, 
	enabled BOOL NOT NULL, 
	schedule_hours INTEGER NOT NULL, 
	next_run DATETIME, 
	fact_sources JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (url)
)

 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX ix_organizations_kind ON organizations (kind);


CREATE TABLE IF NOT EXISTS runs (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	org_id INTEGER NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	started_at DATETIME, 
	finished_at DATETIME, 
	heartbeat_at DATETIME, 
	pages_done INTEGER NOT NULL, 
	error TEXT NOT NULL, 
	meta JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(org_id) REFERENCES organizations (id)
)

 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX ix_runs_org_id ON runs (org_id);

CREATE INDEX ix_runs_status ON runs (status);


CREATE TABLE IF NOT EXISTS pages (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	run_id INTEGER NOT NULL, 
	url TEXT NOT NULL, 
	title TEXT NOT NULL, 
	status_code INTEGER NOT NULL, 
	category VARCHAR(40) NOT NULL, 
	fetched_at DATETIME NOT NULL, 
	text LONGTEXT NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	details JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES runs (id)
)

 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX ix_pages_run_id ON pages (run_id);


CREATE TABLE IF NOT EXISTS results (
	id INTEGER NOT NULL AUTO_INCREMENT, 
	run_id INTEGER NOT NULL, 
	rule VARCHAR(100) NOT NULL, 
	section VARCHAR(200) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	priority VARCHAR(20) NOT NULL, 
	title TEXT NOT NULL, 
	explanation TEXT NOT NULL, 
	recommendation TEXT NOT NULL, 
	evidence JSON NOT NULL, 
	review VARCHAR(20) NOT NULL, 
	review_note TEXT NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES runs (id)
)

 ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE INDEX ix_results_run_id ON results (run_id);