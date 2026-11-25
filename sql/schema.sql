-- Observatoire des prix : schéma PostgreSQL (compatible Supabase / Neon)
-- Principes : on trace chaque collecte, on ne corrige jamais une donnée en silence
-- (on la signale avec quality_flag), et le schéma est multi-pays dès le départ.

-- ---------- Référentiels ----------

CREATE TABLE country (
    code     CHAR(2) PRIMARY KEY,
    name     TEXT    NOT NULL,
    currency CHAR(3) NOT NULL
);

CREATE TABLE region (
    id           INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    country_code CHAR(2) NOT NULL REFERENCES country(code),
    name         TEXT    NOT NULL,
    main_city    TEXT,
    UNIQUE (country_code, name)
);

CREATE TABLE source (
    id               INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code             TEXT NOT NULL UNIQUE,
    name             TEXT NOT NULL,
    url              TEXT,
    kind             TEXT NOT NULL CHECK (kind IN ('official', 'open_data', 'retail')),
    frequency        TEXT,   -- daily, weekly, monthly, irregular
    terms_checked_on DATE,   -- NULL = conditions d'utilisation pas encore vérifiées
    notes            TEXT
);

CREATE TABLE product (
    id       INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE,
    category TEXT NOT NULL,
    unit     TEXT NOT NULL DEFAULT 'kg'
);

-- Un même produit peut changer de libellé d'une semaine à l'autre dans une source.
CREATE TABLE product_alias (
    source_id  INT  NOT NULL REFERENCES source(id),
    raw_name   TEXT NOT NULL,
    product_id INT  NOT NULL REFERENCES product(id),
    PRIMARY KEY (source_id, raw_name)
);

-- ---------- Traçabilité des collectes ----------

CREATE TABLE ingestion_run (
    id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id   INT         NOT NULL REFERENCES source(id),
    started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    file_url    TEXT,
    file_sha256 TEXT,                      -- évite de recharger deux fois le même fichier
    status      TEXT        NOT NULL DEFAULT 'running'
                CHECK (status IN ('running', 'success', 'failed', 'skipped')),
    rows_loaded INT,
    error       TEXT
);

-- ---------- Faits ----------

CREATE TABLE price_observation (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id       BIGINT  NOT NULL REFERENCES ingestion_run(id),
    source_id    INT     NOT NULL REFERENCES source(id),
    product_id   INT     NOT NULL REFERENCES product(id),
    region_id    INT     NOT NULL REFERENCES region(id),
    period_start DATE    NOT NULL,
    period_end   DATE    NOT NULL,
    price_min    NUMERIC(12,2),
    price_max    NUMERIC(12,2),
    price_avg    NUMERIC(12,2),
    unit         TEXT    NOT NULL DEFAULT 'kg',
    currency     CHAR(3) NOT NULL DEFAULT 'XOF',
    quality_flag TEXT    NOT NULL DEFAULT 'ok'
                 CHECK (quality_flag IN ('ok', 'inconsistent_stats', 'suspect_outlier')),
    UNIQUE (source_id, product_id, region_id, period_start, period_end)
);

CREATE INDEX idx_obs_product_period ON price_observation (product_id, period_start);
CREATE INDEX idx_obs_region_period  ON price_observation (region_id, period_start);

-- Prix réglementés : plafonds (riz, sucre, huile...) et carburant.
CREATE TABLE regulated_price (
    id            INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_id     INT     NOT NULL REFERENCES source(id),
    product_label TEXT    NOT NULL,
    pack          TEXT,                    -- ex. 'sac 22,5 kg', 'litre'
    max_price     NUMERIC(12,2) NOT NULL,
    currency      CHAR(3) NOT NULL DEFAULT 'XOF',
    area          TEXT,                    -- ex. 'Abidjan + 30 km', 'national'
    valid_from    DATE    NOT NULL,
    valid_to      DATE,
    legal_ref     TEXT
);

-- ---------- Données de départ ----------

INSERT INTO country (code, name, currency) VALUES ('CI', 'Côte d''Ivoire', 'XOF');

INSERT INTO source (code, name, url, kind, frequency, notes) VALUES
 ('ci_commerce_weekly', 'Ministère du Commerce - prix vivriers (PDF hebdo)', 'https://www.commerce.gouv.ci/publications/sous-categorie/21', 'official', 'weekly', 'min / max / moyenne par département, FCFA/kg'),
 ('ci_cnlvc_caps',      'CNLVC - prix plafonnés',                           'https://www.prixplafond.gouv.ci', 'official', 'irregular', 'Abidjan + 30 km, différentiel ailleurs'),
 ('ci_dgh_fuel',        'DGH - prix maxima carburants',                     NULL, 'official', 'monthly', 'note officielle publiée fin de mois'),
 ('ci_anstat_ihpc',     'ANStat - IHPC',                                    'https://anstat.ci', 'official', 'monthly', 'base 100 en 2023, étalon de validation'),
 ('wfp_hdx_ci',         'WFP via HDX - Côte d''Ivoire Food Prices',          'https://data.humdata.org/dataset/wfp-food-prices-for-cote-d-ivoire', 'open_data', 'monthly', 'licence CC BY-IGO, historique 2005-2024'),
 ('sikafinance_conso',  'Sikafinance - prix de grande consommation',        'https://www.sikafinance.com/conso/liste_des_prix', 'retail', 'irregular', 'conditions à vérifier'),
 ('jumia_ci',           'Jumia Côte d''Ivoire - supermarché',                'https://www.jumia.ci/le-supermarche', 'retail', 'daily', 'conditions et robots.txt à vérifier');

-- 23 départements suivis dans le PDF hebdomadaire du ministère
INSERT INTO region (country_code, name, main_city) VALUES
 ('CI', 'Agnéby-Tiassa', 'Agboville'),   ('CI', 'District d''Abidjan', 'Abidjan'),
 ('CI', 'District de Yamoussoukro', 'Yamoussoukro'), ('CI', 'Folon', 'Minignan'),
 ('CI', 'Gbêkê', 'Bouaké'),              ('CI', 'Grands-Ponts', 'Dabou'),
 ('CI', 'Gôh', 'Gagnoa'),                ('CI', 'Gontougo', 'Bondoukou'),
 ('CI', 'Guémon', 'Duékoué'),            ('CI', 'Haut-Sassandra', 'Daloa'),
 ('CI', 'Indénié-Djuablin', 'Abengourou'), ('CI', 'Kabadougou', 'Odienné'),
 ('CI', 'La Mé', 'Adzopé'),              ('CI', 'Marahoué', 'Bouaflé'),
 ('CI', 'Moronou', 'Bongouanou'),        ('CI', 'Nawa', 'Méagui'),
 ('CI', 'N''Zi', 'Dimbokro'),            ('CI', 'Poro', 'Korhogo'),
 ('CI', 'San-Pédro', 'San-Pédro'),       ('CI', 'Sud-Comoé', 'Aboisso'),
 ('CI', 'Tchologo', 'Ouangolodougou'),   ('CI', 'Tonkpi', 'Man'),
 ('CI', 'Worodougou', 'Séguéla');

-- 28 produits du PDF hebdomadaire
INSERT INTO product (name, category) VALUES
 ('Maïs grain', 'céréales'), ('Mil', 'céréales'),
 ('Riz importé de grande consommation', 'céréales'), ('Riz local blanchi', 'céréales'),
 ('Banane plantain', 'féculents'), ('Igname bêtê-bêtê', 'féculents'),
 ('Igname klinglè', 'féculents'), ('Igname kponan', 'féculents'),
 ('Manioc doux', 'féculents'), ('Pomme de terre', 'féculents'),
 ('Aubergine N''drowa', 'légumes'), ('Aubergine violette', 'légumes'),
 ('Carotte', 'légumes'), ('Chou vert', 'légumes'), ('Gombo frais', 'légumes'),
 ('Oignon violet de Galmi', 'légumes'), ('Oignon Hollande', 'légumes'),
 ('Piment frais ordinaire', 'légumes'), ('Tomate SODEFEL', 'légumes'),
 ('Arachide décortiquée', 'oléagineux'), ('Graine de palme ordinaire', 'oléagineux'),
 ('Viande de bœuf avec os', 'viande'), ('Viande de bœuf sans os', 'viande'),
 ('Poisson congelé carpe noire', 'poisson'), ('Poisson congelé carpe rouge', 'poisson'),
 ('Poisson congelé chinchard', 'poisson'), ('Poisson congelé maquereau', 'poisson'),
 ('Poisson congelé thon', 'poisson');
