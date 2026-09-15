-- PlanetScale / MySQL 用（schedule.sqlite と同一論理）
-- 外部キーはアプリ側で検証する運用も可

CREATE TABLE schedule_period (
    period_key VARCHAR(16) NOT NULL PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'draft',
    created_at VARCHAR(32) NOT NULL,
    updated_at VARCHAR(32) NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE schedule_assignment (
    assignment_id CHAR(36) NOT NULL PRIMARY KEY,
    period_key VARCHAR(16) NOT NULL,
    day_key VARCHAR(16) NOT NULL,
    doctor VARCHAR(16) NOT NULL,
    patient_chart_id VARCHAR(16) NOT NULL,
    sort_index INT NOT NULL,
    updated_at VARCHAR(32) NOT NULL,
    UNIQUE KEY uq_route_sort (period_key, day_key, doctor, sort_index),
    KEY idx_route (period_key, day_key, doctor),
    KEY idx_patient (period_key, patient_chart_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE schedule_revision (
    revision_id CHAR(36) NOT NULL PRIMARY KEY,
    period_key VARCHAR(16) NOT NULL,
    created_at VARCHAR(32) NOT NULL,
    source VARCHAR(64) NOT NULL,
    note TEXT,
    routes_json LONGTEXT NOT NULL,
    KEY idx_revision_period (period_key, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
