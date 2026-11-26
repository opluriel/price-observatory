-- À exécuter UNE fois sur la base existante (l'éditeur SQL de Supabase/Neon).
-- Sans danger si relancé : ON CONFLICT ignore la ligne déjà présente.
INSERT INTO region (country_code, name, main_city)
VALUES ('CI', 'Bélier', 'Toumodi')
ON CONFLICT (country_code, name) DO NOTHING;
