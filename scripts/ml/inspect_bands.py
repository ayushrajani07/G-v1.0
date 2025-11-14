from __future__ import annotations

import csv
import sys
from pathlib import Path
from datetime import datetime

def main(argv: list[str] | None = None) -> int:
    index = 'NIFTY'
    day = '2025-11-04'
    if argv and len(argv) >= 1:
        index = argv[0]
    if argv and len(argv) >= 2:
        day = argv[1]
    p = Path('data/ml/path_forecasts')/index/f'{day}_bands.csv'
    if not p.exists():
        print({'error':'bands_not_found','path':str(p)})
        return 2
    gens = []
    with p.open('r',encoding='utf-8') as f:
        rd = csv.DictReader(f)
        for r in rd:
            g = r.get('gen_time_iso')
            if g:
                gens.append(g)
    if not gens:
        print({'error':'no_rows'})
        return 3
    uniq = sorted(set(gens))
    print({'total_rows':len(gens),'unique_gen_count':len(uniq),'min_gen':uniq[0],'max_gen':uniq[-1]})
    # Sample the first 3 unique gens
    for s in uniq[:3]:
        print({'sample_gen':s})
    # Sample the last 3 unique gens
    for s in uniq[-3:]:
        print({'sample_gen':s})
    return 0

if __name__=='__main__':
    raise SystemExit(main(sys.argv[1:]))
