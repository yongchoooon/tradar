Goods/Services Classification Data

Purpose:
- Store a large, static list (≈50k lines) of goods/services items for search, autocomplete, and metadata lookups.

Suggested file:
- `ko_goods_services.tsv` — UTF-8, tab-separated

Columns (tab-separated):
- nice_class: int (e.g., 1)
- item_name: string (Korean name)
- group_code: string (e.g., G1001)

Example (TSV):
1	2염화주석	G1001
1	2차 전지용 분상(粉狀) 탄소	G1001
1	2차 전지용 분상(粉狀) 흑연	G1601
1	2차 전지용 인조흑연	G1601

Notes:
- No header row is required (keep it consistent).
- Encoding must be UTF-8.
- Keep one record per line; avoid trailing tabs/spaces.

Accessing from code (example):
```python
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parent / "ko_goods_services.tsv"

def iter_goods_services(path: Path = DATA_PATH):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) != 3:
                continue  # or raise
            nice_class, item_name, group_code = parts
            yield int(nice_class), item_name, group_code
```

