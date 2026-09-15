-- 往診調整DB スキーマ
-- 正本: db/oushin.sqlite

PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_deadlines;
DROP TABLE IF EXISTS notes;
DROP TABLE IF EXISTS status_changes;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS staff;
DROP TABLE IF EXISTS patients;

-- 患者マスタ
CREATE TABLE patients (
    patient_id TEXT PRIMARY KEY,          -- 正規化ID（例: b075）
    chart_id TEXT,                        -- 台帳元ID（例: b75）
    visit_code TEXT,                      -- 往診履歴ID（例: 000075）
    notion_page_id TEXT,                  -- NotionページID
    name TEXT NOT NULL,
    name_kana TEXT,
    birth_date TEXT,                      -- YYYY-MM-DD
    sex TEXT,
    insurance_type TEXT NOT NULL,         -- kaigo|iryo|jihi|unknown
    care_level TEXT,                      -- 要介護2 など
    status TEXT NOT NULL DEFAULT 'active', -- active|paused|ended|scheduled
    address TEXT,
    postal_code TEXT,
    tel TEXT,
    main_staff TEXT,
    primary_doctor TEXT,
    care_manager TEXT,
    care_office TEXT,
    hospital_name TEXT,
    start_date TEXT,
    end_date TEXT,
    end_reason TEXT,
    public_expense TEXT,
    copay_rate TEXT,
    self_pay_type TEXT,
    limit_amount TEXT,
    limit_note TEXT,
    limit_expire TEXT,
    tags TEXT,
    note TEXT,
    updated_at TEXT,
    matched INTEGER NOT NULL DEFAULT 1    -- 0=台帳未突合の仮患者
);

CREATE INDEX idx_patients_visit_code ON patients(visit_code);
CREATE INDEX idx_patients_chart_id ON patients(chart_id);
CREATE INDEX idx_patients_name ON patients(name);

-- 往診・受診イベント（期限計算の正本）
CREATE TABLE events (
    event_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    event_type TEXT NOT NULL,             -- home_visit|clinic_visit|phone
    scheduled_at TEXT,                    -- YYYY-MM-DD
    performed_at TEXT,                    -- YYYY-MM-DD（実施日）
    status TEXT NOT NULL,                 -- scheduled|completed|cancelled|needs_review
    doctor_name TEXT,
    driver_name TEXT,
    area TEXT,
    note TEXT,
    source TEXT NOT NULL,                 -- oushin_rireki|yoyaku|clinic
    source_row_id TEXT,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
);

CREATE INDEX idx_events_patient ON events(patient_id);
CREATE INDEX idx_events_performed ON events(performed_at);
CREATE INDEX idx_events_dedupe ON events(patient_id, performed_at, event_type, source);

-- 休止・再開などの状態変更
CREATE TABLE status_changes (
    change_id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL,
    change_type TEXT NOT NULL,            -- pause|resume
    effective_date TEXT,
    planned_resume_date TEXT,
    resume_date TEXT,
    reason TEXT,
    staff TEXT,
    slot_released INTEGER,                -- 1/0/NULL
    source_row TEXT,
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
);

-- 運用メモ（期限計算には使わない）
CREATE TABLE notes (
    note_id TEXT PRIMARY KEY,
    patient_id TEXT,                      -- NULL可（全体メモ）
    title TEXT,
    category TEXT,
    staff TEXT,
    doctor_name TEXT,
    planned_at TEXT,
    body TEXT,
    posted_at TEXT,
    edited INTEGER,
    source TEXT NOT NULL DEFAULT 'homecare_ops',
    FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
);

-- 医師・ドライバー
CREATE TABLE staff (
    staff_id TEXT PRIMARY KEY,
    role TEXT NOT NULL,                   -- doctor|driver
    name TEXT NOT NULL,
    name_kana TEXT,
    note TEXT
);

-- 最終実施日ビュー（期限そのものは区分ルールがあるため scripts/export_deadlines.py で算出）
CREATE VIEW v_last_performed AS
SELECT
    p.patient_id,
    p.name,
    p.insurance_type,
    p.care_level,
    p.status AS patient_status,
    p.main_staff,
    p.matched,
    MAX(e.performed_at) AS last_performed_at
FROM patients p
LEFT JOIN events e
  ON e.patient_id = p.patient_id
 AND e.status IN ('completed', 'needs_review')
 AND e.performed_at IS NOT NULL
GROUP BY p.patient_id;
