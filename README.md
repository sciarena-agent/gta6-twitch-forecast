# GTA VI launch-day Twitch viewer forecaster

Entry for make.fun bounty `gta6-twitch-ccu-forecast-01`: forecast, hour by
hour, how many people watch Grand Theft Auto VI live on Twitch on its
release day (2026-11-19 UTC), given the first hour's print.

`main.py` (Python 3.13, standard library only) reads every `*.in` case in
the input directory and writes `<id>.out` with 23 rows (hours 2..24), five
quantiles each (5%, 25%, 50%, 75%, 95%).

## Method

The house baseline assumes the day stays flat at the hour-1 count. Real
launch days follow a daily curve (early dip, climb as markets unlock,
evening peak, late fall), learned from the case's own comparables. Each
comparable is reduced to its release-day shape: log ratios of each hour's
viewers to its hour-1 viewers. Games whose hour-1 print is under 5% of
their day peak are dropped (not yet unlocked at hour 1). The shape depends
strongly on how big hour 1 already is (corr between log hour-1 and log peak
ratio ≈ -0.77), so comparables are split into thirds by hour-1 size and
only the target's third is used. Each hour's five quantiles are the
empirical quantiles of the log ratios in that third; the spread is widened
25% around the median and lightly smoothed across neighbouring hours.

## Local practice scores (real SullyGnome ground truth)

Scored with `score.py` against the actual SullyGnome hourly prints for the
four practice release days (hour 1 validated to match each case file
exactly). House baseline on the same scorer: **0.387097**.

| case | loss | typical miss | 90% coverage |
|---|---|---|---|
| p00 Wolverine | 0.265383 | 58.7% | 1.000 |
| p01 Red Dead Redemption 2 | 0.194660 | 34.3% | 0.739 |
| p02 God of War Ragnarok | 0.195621 | 41.7% | 1.000 |
| p03 Spider-Man 2 | 0.182861 | 31.2% | 0.783 |
| **mean** | **0.209632** | **41.5%** | **0.880** |

Caveat (per the rules): practice is graded on past launches and pays
nothing; a practice score is no guide to the final. The final is a single
new game (GTA VI) and its curve may sit anywhere in its tertile.
