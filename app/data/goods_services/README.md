Goods/Services Classification Data

Purpose:
- Store a large, static list of goods/services items for search, autocomplete, and metadata lookups.

Suggested file:
- `goods_services.tsv` — UTF-8, tab-separated

Columns (tab-separated):
- nc_class: int (e.g., 1)
- name_ko: string (Korean name)
- name_en: string (English name)
- similar_group_code: string (e.g., G1001)

Example (TSV):
nc_class	name_ko	name_en	similar_group_code
1	2염화주석	stannous chloride	G1001
1	2차 전지용 분상(粉狀) 탄소	powdered carbon for secondary batteries	G1001
1	2차 전지용 분상(粉狀) 흑연	powdered graphite for secondary batteries	G1601
1	2차 전지용 인조흑연	synthetic graphite for secondary batteries	G1601

Notes:
- The header row is required.
- Encoding must be UTF-8.
- Keep one record per line; avoid trailing tabs/spaces.

Accessing from code (example):
```python
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "goods_services.tsv"

def iter_goods_services(path: Path = DATA_PATH):
    with path.open("r", encoding="utf-8") as f:
        header = next(f, None)
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 4:
                continue  # or raise
            nc_class, name_ko, name_en, group_code = parts
            yield int(nc_class), name_ko, name_en, group_code
```
