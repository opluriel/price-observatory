"""Extraction of the weekly PDF “Consumer Prices of Food Products.”

Why by positions? When a product is not recorded in a department, the cell
is simply absent from the PDF. By reading the text line by line, we lose the information
“which department this number belongs to”. We therefore read the horizontal position (x) of
each number and attach it to the nearest header column.

Usage :
    python -m src.parse.ministry_pdf data/raw/PRIX_A_LA_CONSOMMATION_01_06_AU_07_06_2026.pdf
"""
from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd
import pdfplumber

from src.reference import load_products, load_regions

STAT_COLUMNS = {"mini": "price_min", "maxi": "price_max", "moy": "price_avg"}
EXPECTED_STAT_ORDER = ["mini", "maxi", "moy"]
LINE_TOLERANCE = 3.0          # points : écart vertical max entre deux mots d'une même ligne
COLUMN_MATCH_RATIO = 0.75     # un nombre doit tomber à moins de 0.75 x l'écart entre colonnes
MIN_REGIONS = 20   # le nombre de régions suivies varie d'une semaine à l'autre (23 ou 24)

MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7,
    "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12,
}

# Référentiels lus dans data/reference/*.csv (voir src/reference.py)
REGION_KEYWORDS = [(keyword, row["name"]) for row in load_regions() for keyword in row["keywords"]]
PRODUCT_RULES = [(prefix, row["name"]) for row in load_products() for prefix in row["prefixes"]]


@dataclass
class ParseReport:
    pdf: str
    period_start: date | None = None
    period_end: date | None = None
    pages: int = 0
    blocks: int = 0
    regions_found: set[str] = field(default_factory=set)
    unknown_labels: set[str] = field(default_factory=set)
    unknown_regions: set[str] = field(default_factory=set)
    ambiguous_regions: set[str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
    rows: int = 0

    def problems(self) -> list[str]:
        """Raisons pour lesquelles l'extraction n'est pas jugée fiable (liste vide = OK)."""
        found = []
        if self.rows == 0:
            found.append("aucune observation extraite")
        if len(self.regions_found) < MIN_REGIONS:
            found.append(f"seulement {len(self.regions_found)} régions (minimum {MIN_REGIONS})")
        if self.unknown_regions:
            found.append(f"en-têtes inconnus {sorted(self.unknown_regions)}")
        if self.ambiguous_regions:
            found.append(f"en-têtes ambigus (plusieurs régions possibles) {sorted(self.ambiguous_regions)}")
        if self.unknown_labels:
            found.append(f"produits inconnus {sorted(self.unknown_labels)}")
        return found

    def ok(self) -> bool:
        return not self.problems()

    def summary(self) -> str:
        lines = [
            f"Fichier        : {self.pdf}",
            f"Période        : {self.period_start} -> {self.period_end}",
            f"Pages / blocs  : {self.pages} / {self.blocks}",
            f"Régions        : {len(self.regions_found)} trouvées (minimum attendu : {MIN_REGIONS})",
            f"Observations   : {self.rows}",
        ]
        if self.unknown_regions:
            lines.append(f"En-têtes non reconnus : {sorted(self.unknown_regions)}")
        if self.ambiguous_regions:
            lines.append(f"En-têtes ambigus : {sorted(self.ambiguous_regions)}")
        if self.unknown_labels:
            lines.append(f"Produits non reconnus : {sorted(self.unknown_labels)}")
        lines += [f"Avertissement  : {w}" for w in self.warnings[:15]]
        if len(self.warnings) > 15:
            lines.append(f"... et {len(self.warnings) - 15} autres avertissements")
        lines.append("RÉSULTAT       : OK" if self.ok() else "RÉSULTAT       : À VÉRIFIER")
        return "\n".join(lines)


def norm(text: str) -> str:
    """Minuscule, sans accents ni ponctuation ni espaces (clé de comparaison)."""
    text = text.replace("œ", "oe").replace("Œ", "OE")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def canonical_product(label: str) -> str | None:
    """Produit canonique d'un libellé : le préfixe le plus LONG l'emporte (carpe noire > carpe)."""
    key = norm(label)
    best: dict[str, int] = {}
    for prefix, name in PRODUCT_RULES:
        if key.startswith(prefix):
            best[name] = max(best.get(name, 0), len(prefix))
    if not best:
        return None
    longest = max(best.values())
    winners = [name for name, length in best.items() if length == longest]
    return winners[0] if len(winners) == 1 else None      # égalité : on refuse de deviner


def region_matches(header_text: str) -> set[str]:
    """Toutes les régions dont un mot-clé apparaît dans l'en-tête (en général une seule).

    Un mot-clé contenu dans un mot-clé plus long également présent est ignoré :
    « sassandra » (Gbôklé) ne doit pas déclencher sur « hautsassandra » (Haut-Sassandra).
    """
    key = norm(header_text)
    hits = {(keyword, name) for keyword, name in REGION_KEYWORDS if keyword in key}
    keywords = {keyword for keyword, _ in hits}
    return {name for keyword, name in hits
            if not any(keyword != other and keyword in other for other in keywords)}


def canonical_region(header_text: str) -> str | None:
    matches = region_matches(header_text)
    return next(iter(matches)) if len(matches) == 1 else None


# ---------- Période ----------

def parse_period(text: str, filename: str = "") -> tuple[date, date] | None:
    m = re.search(
        r"DU\s+(\d{1,2})\s*(?:ER)?\s*([A-ZÉÛa-zéû]+)?\s+AU\s+(\d{1,2})\s*(?:ER)?\s+([A-ZÉÛa-zéû]+)\s+(\d{4})",
        text, flags=re.IGNORECASE)
    if m:
        d1, m1, d2, m2, year = m.groups()
        end_month = MONTHS.get(norm(m2))
        start_month = MONTHS.get(norm(m1)) if m1 else end_month
        if end_month and start_month:
            end = date(int(year), end_month, int(d2))
            start_year = int(year) - 1 if start_month > end_month else int(year)
            return date(start_year, start_month, int(d1)), end
    m = re.search(r"(\d{2})_(\d{2})_AU_(\d{2})_(\d{2})_(\d{4})", filename)
    if m:
        d1, mo1, d2, mo2, year = map(int, m.groups())
        start_year = year - 1 if mo1 > mo2 else year
        return date(start_year, mo1, d1), date(year, mo2, d2)
    return None


# ---------- Lecture d'une page ----------

MAX_NAME_LINES = 5  # nombre de LIGNES (pas de hauteurs) remontées au-dessus de « Prix »


def _is_number(word: dict) -> bool:
    return re.fullmatch(r"\d+", word["text"]) is not None


def _group_lines(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= LINE_TOLERANCE:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def _header_rows(words: list[dict]) -> list[list[dict]]:
    """Une ligne d'en-tête = tous les mots « mini / maxi / moy » situés à la même hauteur.

    On ne s'appuie PAS sur le mot SPECULATIONS : il est centré verticalement dans la cellule
    d'en-tête, et les noms de régions peuvent se trouver au-dessus de lui.
    """
    stat_words = sorted((w for w in words if norm(w["text"]) in STAT_COLUMNS), key=lambda w: w["top"])
    rows: list[list[dict]] = []
    for w in stat_words:
        if rows and abs(rows[-1][0]["top"] - w["top"]) <= LINE_TOLERANCE:
            rows[-1].append(w)
        else:
            rows.append([w])
    return rows


def _prix_top(words: list[dict], stat_words: list[dict]) -> float:
    """Hauteur de la ligne « Prix » qui surmonte « mini / maxi / moy » (ou celle de ces derniers)."""
    stat_top = min(w["top"] for w in stat_words)
    above = [w["top"] for w in words if norm(w["text"]) == "prix" and stat_top - 30 < w["top"] < stat_top - 0.5]
    return min(above) if above else stat_top


def _parse_block(words, stat_words, limit_top, report: ParseReport, page_no: int) -> list[dict]:
    stat_words = sorted(stat_words, key=lambda w: (w["x0"] + w["x1"]) / 2)
    centers = [(w["x0"] + w["x1"]) / 2 for w in stat_words]
    stats = [norm(w["text"]) for w in stat_words]
    if len(stat_words) % 3 != 0:
        report.warnings.append(f"page {page_no}: {len(stat_words)} colonnes (pas un multiple de 3)")
    pitch = min(b - a for a, b in zip(centers, centers[1:])) if len(centers) > 1 else 30.0

    header_bottom = max(w["bottom"] for w in stat_words)
    prix_top = _prix_top(words, stat_words)

    # --- noms de régions : on remonte ligne par ligne depuis « Prix » jusqu'à la première
    #     ligne qui contient un nombre (= dernière ligne de données du bloc précédent).
    above = [w for w in words if w["top"] < prix_top - 0.5]
    name_words: list[dict] = []
    for n_lines, line in enumerate(reversed(_group_lines(above))):
        if n_lines >= MAX_NAME_LINES or any(_is_number(w) for w in line):
            break
        name_words += line

    groups: list[dict] = []
    for i in range(0, len(centers) - len(centers) % 3, 3):
        if stats[i:i + 3] != EXPECTED_STAT_ORDER:
            report.warnings.append(f"page {page_no}: ordre inattendu des colonnes {stats[i:i + 3]}")
        left, right = centers[i] - pitch / 2, centers[i + 2] + pitch / 2
        in_group = [w for w in name_words if left <= (w["x0"] + w["x1"]) / 2 <= right
                    and not norm(w["text"]).startswith("speculations")]
        header_text = " ".join(w["text"] for w in sorted(in_group, key=lambda w: (round(w["top"]), w["x0"])))
        matches = region_matches(header_text)
        region = next(iter(matches)) if len(matches) == 1 else None
        if len(matches) > 1:
            report.ambiguous_regions.add(f"{header_text} -> {sorted(matches)}")
        elif region is None:
            report.unknown_regions.add(header_text or f"(vide, page {page_no}, groupe {i // 3})")
        else:
            report.regions_found.add(region)
        groups.append({"region": region, "cols": range(i, i + 3)})

    # --- lignes de données : sous l'en-tête, avant l'en-tête du bloc suivant
    data_words = [w for w in words if header_bottom - 0.5 <= w["top"] < limit_top]
    records: dict[tuple[str, str], dict] = {}
    for line in _group_lines(data_words):
        numbers = [w for w in line if _is_number(w)]
        label = " ".join(w["text"] for w in line if not _is_number(w)).strip()
        if not numbers:
            continue  # titre de catégorie, « Unité : F CFA/Kg », etc.
        if not label:
            if len(numbers) > 1:
                report.warnings.append(f"page {page_no}: ligne de chiffres sans libellé ignorée")
            continue  # un seul nombre isolé = numéro de page
        if norm(label).startswith(("synthese", "unite")):
            continue  # titre répété en pied de page, mention d'unité
        product = canonical_product(label)
        if product is None:
            if len(numbers) > 1:   # un nombre isolé (numéro de page) n'est pas une ligne de données
                report.unknown_labels.add(label)
            continue
        for w in numbers:
            cx = (w["x0"] + w["x1"]) / 2
            idx = min(range(len(centers)), key=lambda k: abs(centers[k] - cx))
            if abs(centers[idx] - cx) > pitch * COLUMN_MATCH_RATIO:
                report.warnings.append(f"page {page_no}: « {label} » valeur {w['text']} hors colonne")
                continue
            group = next((g for g in groups if idx in g["cols"]), None)
            if group is None or group["region"] is None:
                continue
            rec = records.setdefault((product, group["region"]), {
                "product": product, "region": group["region"], "raw_label": label, "page": page_no,
                "price_min": None, "price_max": None, "price_avg": None})
            rec[STAT_COLUMNS[stats[idx]]] = int(w["text"])
    return list(records.values())


def parse_pdf(path: str | Path) -> tuple[pd.DataFrame, ParseReport]:
    path = Path(path)
    report = ParseReport(pdf=path.name)
    records: list[dict] = []
    with pdfplumber.open(path) as pdf:
        report.pages = len(pdf.pages)
        first_text = pdf.pages[0].extract_text() or ""
        period = parse_period(first_text, path.name)
        if period is None:
            raise ValueError("Période introuvable (ni dans le titre, ni dans le nom du fichier)")
        report.period_start, report.period_end = period

        for page_no, page in enumerate(pdf.pages, start=1):
            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            rows = _header_rows(words)
            for k, stat_words in enumerate(rows):
                limit = _prix_top(words, rows[k + 1]) - 0.5 if k + 1 < len(rows) else page.height
                records += _parse_block(words, stat_words, limit, report, page_no)
                report.blocks += 1

    df = pd.DataFrame(records, columns=["product", "region", "price_min", "price_max", "price_avg",
                                         "raw_label", "page"])
    df.insert(0, "period_end", report.period_end)
    df.insert(0, "period_start", report.period_start)
    report.rows = len(df)
    return df, report


if __name__ == "__main__":
    from src.quality.checks import flag_quality

    if len(sys.argv) != 2:
        sys.exit("Usage : python -m src.parse.ministry_pdf chemin/vers/fichier.pdf")
    frame, rep = parse_pdf(sys.argv[1])
    frame = flag_quality(frame)
    out = Path("data/processed")
    out.mkdir(parents=True, exist_ok=True)
    target = out / (Path(sys.argv[1]).stem + ".csv")
    frame.to_csv(target, index=False)
    print(rep.summary())
    print(f"Lignes signalées : {(frame.quality_flag != 'ok').sum()}")
    print(frame[frame.quality_flag != "ok"].to_string(index=False))
    print(f"CSV écrit : {target}")
