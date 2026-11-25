"""Génère un PDF factice qui imite la mise en page du vrai PDF du ministère.

Particularités reproduites (observées sur le vrai fichier) :
- les noms de départements sont AU-DESSUS du mot SPECULATIONS (cellule d'en-tête haute) ;
- certains noms passent à la ligne ;
- les cases sans relevé sont absentes ;
- un pied de page répète le titre (avec des chiffres) et le numéro de page ;
- plusieurs blocs peuvent être empilés sur une même page.
"""
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

FIRST_COL_X = 200
PITCH = 38
STATS = ["mini", "maxi", "moy"]
FOOTER = ("SYNTHESE DES PRIX A LA CONSOMMATION COLLECTES AU COURS DE LA SEMAINE "
          "ALLANT DU 01 AU 07 JUIN 2026 SUR L'ENSEMBLE DES MARCHES SUIVIS EN CÔTE D'IVOIRE")


def _col_x(k: int, first_x: float = FIRST_COL_X, pitch: float = PITCH) -> float:
    return first_x + pitch * k


def _block(c, top_y, district_names, rows, first_x=FIRST_COL_X, pitch=PITCH, jitter=False):
    """district_names : liste de listes de lignes. rows : (libellé, {indice: (min, max, moy)} | None)."""
    c.setFont("Helvetica-Bold", 7)
    c.drawString(30, top_y - 14, "SPECULATIONS")          # centré verticalement : sous les noms
    c.setFont("Helvetica", 7)
    for d, lines in enumerate(district_names):
        base = top_y - 4.5 if len(lines) == 1 else top_y     # nom sur 1 ligne : centré dans la cellule
        for n, text in enumerate(lines):
            wobble = ((d * 7 + n * 3) % 3 - 1) * 0.8 if jitter else 0   # hauteurs légèrement différentes
            c.drawCentredString(_col_x(d * 3 + 1, first_x, pitch), base - 9 * n + wobble, text)
        for s, stat in enumerate(STATS):
            x = _col_x(d * 3 + s, first_x, pitch)
            c.drawCentredString(x, top_y - 26, "Prix")
            c.drawCentredString(x, top_y - 35, stat)
    y = top_y - 52
    for label, values in rows:
        c.drawString(30, y, label)
        for d, triple in (values or {}).items():
            for s, value in enumerate(triple):
                c.drawCentredString(_col_x(d * 3 + s, first_x, pitch), y, str(value))
        y -= 11
    return y


def _footer(c, page_no):
    c.setFont("Helvetica", 6)
    c.drawString(30, 30, FOOTER)
    c.drawString(300, 20, str(page_no))
    c.drawString(30, 20, "Unité : F CFA/Kg")


def build(path: Path) -> Path:
    c = canvas.Canvas(str(path), pagesize=A4)
    c.setFont("Helvetica", 8)
    c.drawString(30, 800, "PRIX A LA CONSOMMATION DES PRODUITS VIVRIERS SUIVIS SUR LES MARCHES AU COURS "
                          "DE LA SEMAINE ALLANT DU 01 AU 07 JUIN 2026")
    c.showPage()                                             # page de garde, sans tableau

    c.setFont("Helvetica", 8)
    c.drawString(30, 800, "1- PRODUITS VIVRIERS D'ORIGINE VEGETALE")
    _block(c, 760, [["AGNEBYE TIASSA", "(Agboville)"], ["DISTRICT D'ABIDJAN"], ["GBÊKÊ (Bouaké)"]], [
        ("CEREALES", None),
        ("Maïs grain", {0: (500, 500, 500), 1: (350, 500, 410), 2: (400, 400, 400)}),
        ("Riz importé de grande consommation", {0: (600, 600, 600), 2: (500, 500, 500)}),
        ("LEGUMES", None),
        ("Aubergine N'drowa", {0: (600, 700, 650), 1: (700, 800, 750), 2: (1290, 13330, 3330)}),
        ('Gombo frais "dioula"', {1: (960, 2270, 1490)}),
    ])
    _footer(c, 2)
    c.showPage()

    c.setFont("Helvetica", 8)
    c.drawString(30, 800, "2- PRODUITS VIVRIERS D'ORIGINE ANIMALE")
    _block(c, 770, [["AGNEBYE TIASSA", "(Agboville)"], ["DISTRICT D'ABIDJAN"], ["GBÊKÊ (Bouaké)"]], [
        ("PRODUITS ANIMAUX", None),
        ("Viande de bœuf avec os", {0: (3000, 3000, 3000), 1: (2800, 3800, 3550), 2: (3000, 3000, 3000)}),
        ("Viande de bœuf sans os", {1: (3500, 4000, 3880)}),
    ])
    _block(c, 600, [["GÔH (Gagnoa)"], ["GONTOUGO", "(Bondoukou)"],
                    ["INDENIE DJUABLIN", "(AbengourouAgnibilekro)"]], [
        ("PRODUITS ANIMAUX", None),
        ("Viande de bœuf avec os", {0: (3000, 3000, 3000), 1: (2800, 2800, 2800), 2: (3000, 3000, 3000)}),
        ("Viande de bœuf sans os", {0: (3500, 3800, 3580), 2: (3000, 3000, 3000)}),
    ])
    _footer(c, 3)
    c.save()
    return path


WIDE_NAMES = [["AGNEBYE TIASSA", "(Agboville)"], ["DISTRICT D'ABIDJAN"], ["DISTRICT DE", "YAMOUSSOUKRO"],
              ["FOLON", "(Minignan)"], ["GBÊKÊ (Bouaké)"], ["GRANDS-PONTS", "(Dabou)"]]


def build_wide(path: Path) -> Path:
    """Page paysage avec 6 départements (18 colonnes), noms sur 1 ou 2 lignes, hauteurs irrégulières."""
    from reportlab.lib.pagesizes import landscape
    c = canvas.Canvas(str(path), pagesize=landscape(A4))
    c.setFont("Helvetica", 8)
    c.drawString(30, 570, "DU 01 AU 07 JUIN 2026")
    c.showPage()
    c.setFont("Helvetica", 7)
    rows = [
        ("CEREALES", None),
        ("Maïs grain", {d: (100 + d, 200 + d, 150 + d) for d in range(6)}),
        ("Mil", {1: (500, 700, 560), 4: (300, 300, 300)}),
    ]
    _block(c, 540, WIDE_NAMES, rows, first_x=150, pitch=26, jitter=True)
    c.save()
    return path
