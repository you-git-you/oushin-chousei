-- 往診割当スケジュール（順番・日割当）
-- 正本: db/schedule.sqlite（将来 PlanetScale の schedule_* テーブルと同一論理）

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schedule_period (
    period_key TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedule_assignment (
    assignment_id TEXT PRIMARY KEY,
    period_key TEXT NOT NULL,
    day_key TEXT NOT NULL,
    doctor TEXT NOT NULL,
    patient_chart_id TEXT NOT NULL,
    sort_index INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (period_key) REFERENCES schedule_period(period_key) ON DELETE CASCADE,
    UNIQUE (period_key, day_key, doctor, sort_index)
);

CREATE INDEX IF NOT EXISTS idx_schedule_assignment_route
    ON schedule_assignment (period_key, day_key, doctor);

CREATE INDEX IF NOT EXISTS idx_schedule_assignment_patient
    ON schedule_assignment (period_key, patient_chart_id);

CREATE TABLE IF NOT EXISTS schedule_revision (
    revision_id TEXT PRIMARY KEY,
    period_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,
    note TEXT,
    routes_json TEXT NOT NULL,
    FOREIGN KEY (period_key) REFERENCES schedule_period(period_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_schedule_revision_period
    ON schedule_revision (period_key, created_at DESC);
