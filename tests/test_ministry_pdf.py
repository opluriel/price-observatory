from datetime import date

import pytest

from src.parse.ministry_pdf import canonical_product, canonical_region, parse_pdf, parse_period
from src.quality.checks import flag_quality
from tests.make_fixture import build, build_wide


@pytest.fixture(scope="module")
def parsed(tmp_path_factory):
    pdf = build(tmp_path_factory.mktemp("pdf") / "PRIX_A_LA_CONSOMMATION_01_06_AU_07_06_2026.pdf")
    return parse_pdf(pdf)


def test_period_from_title(parsed):
    _, report = parsed
    assert (report.period_start, report.period_end) == (date(2026, 6, 1), date(2026, 6, 7))


def test_period_across_months():
    assert parse_period("DU 29 JUIN AU 05 JUILLET 2026") == (date(2026, 6, 29), date(2026, 7, 5))
    assert parse_period("", "PRIX_A_LA_CONSOMMATION_29_12_AU_04_01_2026.pdf") == (date(2025, 12, 29), date(2026, 1, 4))


def test_all_regions_and_blocks_found(parsed):
    _, report = parsed
    assert report.regions_found == {"Agnéby-Tiassa", "District d'Abidjan", "Gbêkê",
                                    "Gôh", "Gontougo", "Indénié-Djuablin"}
    assert report.blocks == 3
    assert not report.unknown_labels and not report.unknown_regions


def test_missing_cell_is_not_shifted(parsed):
    df, _ = parsed
    rice = df[df["product"] == "Riz importé de grande consommation"].set_index("region")
    assert set(rice.index) == {"Agnéby-Tiassa", "Gbêkê"}          # Abidjan absent : pas de décalage
    assert rice.loc["Gbêkê", "price_avg"] == 500


def test_values_land_in_right_district(parsed):
    df, _ = parsed
    row = df[(df["product"] == "Maïs grain") & (df["region"] == "District d'Abidjan")].iloc[0]
    assert (row.price_min, row.price_max, row.price_avg) == (350, 500, 410)
    okra = df[df["product"] == "Gombo frais"]
    assert list(okra["region"]) == ["District d'Abidjan"]


def test_multiple_blocks_on_one_page(parsed):
    df, _ = parsed
    beef = df[(df["product"] == "Viande de bœuf sans os") & (df["region"] == "Gôh")].iloc[0]
    assert beef.price_avg == 3580


def test_outlier_is_flagged_not_corrected(parsed):
    df, _ = parsed
    flagged = flag_quality(df)
    row = flagged[(flagged["product"] == "Aubergine N'drowa") & (flagged["region"] == "Gbêkê")].iloc[0]
    assert row.price_max == 13330 and row.quality_flag == "suspect_outlier"
    assert (flagged["quality_flag"] == "ok").sum() > 0


def test_name_normalisation():
    assert canonical_product('Gombo frais "dioula"') == canonical_product('Gombo frais "baoulé"') == "Gombo frais"
    assert canonical_product("Poisson congelé THON") == "Poisson congelé thon"
    assert canonical_region("MORONOU (BongouanouKotobi)") == "Moronou"
    assert canonical_region("INDENIE DJUABLIN (AbengourouAgnibilekro)") == "Indénié-Djuablin"


def test_footer_and_page_number_are_ignored(parsed):
    _, report = parsed
    assert not report.unknown_labels
    assert not [w for w in report.warnings if "sans libellé" in w]
    assert report.ok() is False          # 6 départements sur 23 : le rapport doit rester prudent


def test_two_line_names_with_irregular_heights(tmp_path):
    """Régression : un nom sur deux lignes (hauteurs irrégulières) doit être lu en entier."""
    df, report = parse_pdf(build_wide(tmp_path / "PRIX_A_LA_CONSOMMATION_01_06_AU_07_06_2026.pdf"))
    assert report.regions_found == {"Agnéby-Tiassa", "District d'Abidjan", "District de Yamoussoukro",
                                    "Folon", "Gbêkê", "Grands-Ponts"}
    assert not report.unknown_regions
    maize = df[df["product"] == "Maïs grain"].set_index("region")
    assert maize.loc["Folon", "price_avg"] == 153
    assert set(df[df["product"] == "Mil"]["region"]) == {"District d'Abidjan", "Gbêkê"}


def test_problems_explain_why_a_week_is_rejected(parsed):
    _, report = parsed
    assert report.problems() == ["6/23 départements"]
    report.unknown_labels.add("Produit nouveau")
    assert any("Produit nouveau" in p for p in report.problems())
