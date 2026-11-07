-- SQLite schema. Optional manual import; application creates these automatically.

PRAGMA foreign_keys=ON;


CREATE TABLE IF NOT EXISTS organizations (
	id INTEGER NOT NULL, 
	name VARCHAR(600) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	url VARCHAR(512) NOT NULL, 
	source TEXT NOT NULL, 
	reference BOOLEAN NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	schedule_hours INTEGER NOT NULL, 
	next_run DATETIME, 
	fact_sources JSON NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (url)
)

;

CREATE INDEX IF NOT EXISTS ix_organizations_kind ON organizations (kind);


CREATE TABLE IF NOT EXISTS runs (
	id INTEGER NOT NULL, 
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

;

CREATE INDEX IF NOT EXISTS ix_runs_org_id ON runs (org_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_active_run_per_org ON runs (org_id) WHERE status IN ('queued', 'running');

CREATE INDEX IF NOT EXISTS ix_runs_status ON runs (status);


CREATE TABLE IF NOT EXISTS pages (
	id INTEGER NOT NULL, 
	run_id INTEGER NOT NULL, 
	url TEXT NOT NULL, 
	title TEXT NOT NULL, 
	status_code INTEGER NOT NULL, 
	category VARCHAR(40) NOT NULL, 
	fetched_at DATETIME NOT NULL, 
	text TEXT NOT NULL, 
	digest VARCHAR(64) NOT NULL, 
	details JSON NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(run_id) REFERENCES runs (id)
)

;

CREATE INDEX IF NOT EXISTS ix_pages_run_id ON pages (run_id);


CREATE TABLE IF NOT EXISTS results (
	id INTEGER NOT NULL, 
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

;

CREATE INDEX IF NOT EXISTS ix_results_run_id ON results (run_id);