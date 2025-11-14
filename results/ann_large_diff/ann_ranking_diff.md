# ANN Ranking Diff (Tuned vs Extended)

Extended source: `C:\Users\Asus\Desktop\g6_reorganized\results\ann_large_extended\combined\ann_ranking.csv`
Tuned source: `C:\Users\Asus\Desktop\g6_reorganized\results\ann_large_tuned\combined\ann_ranking.csv`

## Top Tuned Config Deltas

| index | tag | off | win | hor | k | mode | Δspeedup | Δprune | ΔMAD | Δlat | Δeffect_adj | Δscore |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| NIFTY | this_week | 0 | 60 | 60 | 15 | retrieval | +0.0000 | -0.1667 | +0.0000 | +0.9300 | +0.0000 | +0.1547 |
| NIFTY | next_week | 0 | 60 | 60 | 15 | hybrid | +0.1586 | +0.0000 | +0.0000 | +0.2100 | +0.0000 | +0.1584 |
| NIFTY | this_week | 0 | 120 | 60 | 15 | retrieval | +0.0443 | -0.1304 | +0.0000 | -0.5300 | +0.1320 | +0.1681 |
| NIFTY | this_week | 0 | 120 | 60 | 15 | hybrid | +0.0065 | -0.1304 | +0.1861 | -1.8000 | +0.0000 | +0.0987 |
| NIFTY | this_week | +50 | 120 | 60 | 15 | retrieval | -0.0001 | -0.1304 | +0.0000 | +11.7300 | +0.1320 | +0.1115 |
| NIFTY | this_week | +50 | 120 | 60 | 15 | hybrid | +0.0422 | -0.1304 | +0.1572 | +0.7400 | +0.0000 | +0.1359 |
| NIFTY | this_week | 0 | 60 | 60 | 10 | retrieval | +0.0334 | -0.1667 | +0.0000 | +0.4000 | +0.0000 | +0.1830 |
| NIFTY | this_week | +50 | 60 | 60 | 10 | hybrid | +0.0445 | -0.1667 | +0.1978 | -0.7300 | +0.0000 | +0.1613 |
| NIFTY | this_week | +50 | 60 | 60 | 15 | auto | +0.0000 | -0.1667 | +0.2005 | -0.6700 | +0.0000 | +0.1162 |
| NIFTY | this_week | +50 | 60 | 60 | 15 | hybrid | -0.0222 | -0.1667 | +0.2005 | -1.0700 | +0.0000 | +0.0944 |
| NIFTY | this_week | 0 | 60 | 60 | 10 | auto | +0.0389 | -0.1667 | +0.2394 | -1.7300 | +0.0000 | +0.1484 |
| NIFTY | this_week | 0 | 60 | 60 | 15 | hybrid | -0.0055 | -0.1667 | +0.2399 | -0.6600 | +0.0000 | +0.1028 |
| NIFTY | this_week | +50 | 60 | 60 | 10 | auto | -0.0222 | -0.1667 | +0.1978 | -0.9300 | +0.0000 | +0.0921 |
| NIFTY | this_week | +50 | 120 | 60 | 10 | auto | +0.0056 | -0.1304 | +0.1567 | -0.4600 | +0.0000 | +0.0965 |
| NIFTY | this_week | +50 | 120 | 60 | 15 | auto | +0.0387 | -0.1304 | +0.1572 | +0.3400 | +0.0000 | +0.1288 |
| NIFTY | this_week | 0 | 120 | 60 | 10 | hybrid | +0.0056 | -0.1304 | +0.1876 | -2.0000 | +0.0000 | +0.0919 |
| NIFTY | this_week | +50 | 60 | 60 | 15 | retrieval | -0.0334 | -0.1667 | +0.0000 | -0.3300 | +0.0000 | +0.1115 |
| NIFTY | this_week | 0 | 60 | 60 | 15 | auto | -0.0322 | -0.1667 | +0.2399 | +0.4700 | +0.0000 | +0.0705 |
| NIFTY | this_week | +50 | 120 | 60 | 10 | retrieval | -0.0555 | -0.1304 | +0.0000 | -1.0000 | +0.1242 | +0.0615 |
| NIFTY | this_week | 0 | 120 | 60 | 10 | retrieval | -0.0389 | -0.1304 | +0.0000 | -2.4600 | +0.1242 | +0.0797 |