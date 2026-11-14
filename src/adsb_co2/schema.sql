CREATE TABLE IF NOT EXISTS passes (
    id bigserial PRIMARY KEY,
    hex text NOT NULL,
    callsign text,
    reg text,
    type text,
    operator text,
    category text,
    entered_at timestamptz NOT NULL,
    exited_at timestamptz,          -- open passes: time of the last stored point
    status text NOT NULL,           -- open | complete | incomplete
    distance_km real,
    duration_s int,
    n_points int,
    max_gap_s int,
    tier text,
    model_type text,
    openap_version text,
    model_rev text,
    fuel_kg real,
    co2_kg real,
    co2_low_kg real,
    co2_high_kg real
);
CREATE INDEX IF NOT EXISTS passes_entered_at ON passes (entered_at);
CREATE INDEX IF NOT EXISTS passes_hex_entered_at ON passes (hex, entered_at);

CREATE TABLE IF NOT EXISTS track_points (
    pass_id bigint NOT NULL REFERENCES passes (id),
    ts timestamptz NOT NULL,
    lat double precision,
    lon double precision,
    alt_ft int,
    gs_kt real,
    vs_fpm int,
    co2_kg real,                    -- central CO2 since the previous stored point
    PRIMARY KEY (pass_id, ts)
);
CREATE INDEX IF NOT EXISTS track_points_ts ON track_points (ts);

-- Time totals attribute CO2 to when it was burned. Buckets use the session time zone.
-- Low/high scale each point by its pass's low/central and high/central ratio.
CREATE OR REPLACE VIEW co2_points AS
SELECT t.ts, t.pass_id, t.co2_kg,
       t.co2_kg * coalesce(p.co2_low_kg / nullif(p.co2_kg, 0), 0) AS co2_low_kg,
       t.co2_kg * coalesce(p.co2_high_kg / nullif(p.co2_kg, 0), 0) AS co2_high_kg,
       p.tier
FROM track_points t JOIN passes p ON p.id = t.pass_id;

CREATE OR REPLACE VIEW co2_hourly AS
SELECT date_trunc('hour', ts) AS bucket, sum(co2_kg) AS co2_kg, sum(co2_low_kg) AS co2_low_kg,
       sum(co2_high_kg) AS co2_high_kg, count(DISTINCT pass_id) AS passes
FROM co2_points GROUP BY 1;

CREATE OR REPLACE VIEW co2_daily AS
SELECT date_trunc('day', ts) AS bucket, sum(co2_kg) AS co2_kg, sum(co2_low_kg) AS co2_low_kg,
       sum(co2_high_kg) AS co2_high_kg, count(DISTINCT pass_id) AS passes
FROM co2_points GROUP BY 1;

CREATE OR REPLACE VIEW co2_weekly AS
SELECT date_trunc('week', ts) AS bucket, sum(co2_kg) AS co2_kg, sum(co2_low_kg) AS co2_low_kg,
       sum(co2_high_kg) AS co2_high_kg, count(DISTINCT pass_id) AS passes
FROM co2_points GROUP BY 1;

CREATE OR REPLACE VIEW co2_monthly AS
SELECT date_trunc('month', ts) AS bucket, sum(co2_kg) AS co2_kg, sum(co2_low_kg) AS co2_low_kg,
       sum(co2_high_kg) AS co2_high_kg, count(DISTINCT pass_id) AS passes
FROM co2_points GROUP BY 1;

DO $$
BEGIN
    IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_ro') THEN
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_ro;
    END IF;
END $$;
