# Reference Data

Single source of reference data. Any modification must go through these files, followed by `python -m src.admin setup`.

| File | Content | Count |
| :--- | :--- | :--- |
| `districts.csv` | districts (12 districts + 2 autonomous districts) | 14 |
| `regions.csv` | 31 regions + the 2 autonomous districts of Abidjan and Yamoussoukro (same level in the PDFs) | 33 |
| `departments.csv` | departments, each linked to its region | 111 |
| `products.csv` | tracked products, with recognized label prefixes | 32 |

### Official figures (and why other numbers are sometimes seen)
- 31 regions: Decree 2011-263 (30 regions), Decree 2012-612 (creation of Moronou), Decree 2013-294.
- There is no 32nd region; "33" is obtained by adding the 2 autonomous districts.
- 111 departments since 2020 (Decree 2020-692: Ouellé, plus Bonon and Gohitafla).
- The figure of 108 is from before 2020, still widely repeated.
- 510 sub-prefectures: not loaded.

`departments.csv` has been cross-checked with the official alphabetical list of the 111 departments.

The `keywords` in `regions.csv` are used solely to recognize PDF headers (normalized text: no accents, lowercase, no spaces or punctuation).