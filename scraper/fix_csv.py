import pandas as pd

p = "data/gsmarena_phones_raw.csv"
d = pd.read_csv(p)
d.to_csv("data/gsmarena_phones_raw_backup.csv", index=False)   # safety copy first

bad = d["refresh_hz"] >= 1000
print(bad.sum(), "rows to re-fetch")
d[~bad].to_csv(p, index=False)