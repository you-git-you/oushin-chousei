-- 手動確定の往診実施記録（正本の取込先）
-- 人間可読の正本: records/*.md + records/data/*.json

PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_pause_current;
DROP VIEW IF EXISTS v_confirmed_deadlines;
DROP TABLE IF EXISTS pause_resume_records;
DROP TABLE IF EXISTS pause_import_log;
DROP TABLE IF EXISTS confirmed_visits;
DROP TABLE IF EXISTS confirmed_sessions;
DROP TABLE IF EXISTS confirmed_deferred;
DROP TABLE IF EXISTS import_log;

CREATE TABLE confirmed_sessions (
    session_id TEXT PRIMARY KEY,
    performed_date TEXT NOT NULL,
    doctor TEXT NOT NULL,
    driver TEXT,
    departure TEXT,
    visit_minutes INTEGER,
    note TEXT,
    source_file TEXT,
    imported_at TEXT NOT NULL
);

CREATE TABLE confirmed_visits (
    visit_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    route_order INTEGER NOT NULL,
    patient_id TEXT,
    patient_name TEXT NOT NULL,
    time_window TEXT,
    address TEXT,
    eta TEXT,
    insurance_type TEXT,
    status TEXT NOT NULL DEFAULT 'completed',
    note TEXT,
    FOREIGN KEY (session_id) REFERENCES confirmed_sessions(session_id)
);

CREATE INDEX idx_confirmed_visits_date ON confirmed_visits(session_id);
CREATE INDEX idx_confirmed_visits_patient ON confirmed_visits(patient_id);
CREATE UNIQUE INDEX idx_confirmed_visits_dedupe
    ON confirmed_visits(session_id, route_order, patient_name);

CREATE TABLE confirmed_deferred (
    defer_id TEXT PRIMARY KEY,
    planned_date TEXT,
    patient_id TEXT,
    patient_name TEXT NOT NULL,
    doctor TEXT,
    status TEXT NOT NULL,
    reason TEXT,
    follow_up TEXT,
    note TEXT
);

CREATE TABLE import_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    sessions INTEGER NOT NULL,
    visits INTEGER NOT NULL,
    deferred INTEGER NOT NULL
);

CREATE VIEW v_confirmed_deadlines AS
SELECT
    cv.patient_id,
    cv.patient_name,
    cs.performed_date AS last_performed,
    cv.insurance_type,
    cv.session_id,
    cs.doctor
FROM confirmed_visits cv
JOIN confirmed_sessions cs ON cs.session_id = cv.session_id
WHERE cv.status = 'completed'
  AND cv.patient_id IS NOT NULL;

-- 休止・再開（手動スナップショット）
CREATE TABLE pause_resume_records (
    record_id TEXT PRIMARY KEY,
    patient_id TEXT,
    patient_name TEXT NOT NULL,
    main_staff TEXT,
    pause_date TEXT,
    resume_date TEXT,
    end_date TEXT,
    current_status TEXT NOT NULL,
    reason TEXT,
    slot_released INTEGER,
    note TEXT,
    source_file TEXT,
    imported_at TEXT NOT NULL
);

CREATE INDEX idx_pause_patient ON pause_resume_records(patient_id);
CREATE INDEX idx_pause_status ON pause_resume_records(current_status);

CREATE TABLE pause_import_log (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    record_count INTEGER NOT NULL
);

CREATE VIEW v_pause_current AS
SELECT * FROM pause_resume_records
ORDER BY current_status, pause_date DESC;
