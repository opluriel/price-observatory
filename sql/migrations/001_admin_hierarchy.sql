-- Administrative hierarchy: district -> region -> department.
-- Idempotent: can be safely rerun (python -m src.admin migrate).

CREATE TABLE IF NOT EXISTS district (
    id           INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    country_code CHAR(2) NOT NULL REFERENCES country(code),
    name         TEXT    NOT NULL,
    UNIQUE (country_code, name)
);

-- The region table contains the 31 regions + the 2 autonomous districts (Abidjan, Yamoussoukro),
-- as these are the "zones" that the ministry's PDF treats at the same level.
ALTER TABLE region ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'region'
    CHECK (kind IN ('region', 'district_autonome'));
ALTER TABLE region ADD COLUMN IF NOT EXISTS district_id INT REFERENCES district(id);

CREATE TABLE IF NOT EXISTS department (
    id        INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    region_id INT  NOT NULL REFERENCES region(id),
    name      TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_department_region ON department (region_id);
