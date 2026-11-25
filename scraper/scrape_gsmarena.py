"""
GSMArena smartphone scraper  (Data Science Project, Q1)
-------------------------------------------------------
Collects specs + launch price for the newest phones of several brands and
writes one row per phone to gsmarena_phones_raw.csv.

* Resumable: if it stops (Ctrl+C, 429 block, internet drop) just run it again,
  it skips phones already saved.
* Polite: random 3-6 s delay between requests, backs off on HTTP 429.
* Run:  pip install requests beautifulsoup4 ; python scrape_gsmarena.py
  (takes roughly 45-75 minutes for the defaults, leave it running)
"""
import csv
import os
import random
import re
import time
from datetime import date

import requests
from bs4 import BeautifulSoup

BASE = "https://www.gsmarena.com/"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT_CSV = os.path.join(HERE, "..", "data", "gsmarena_phones_raw.csv")
BRANDS = ["Samsung", "Apple", "Xiaomi", "Oppo", "Vivo", "OnePlus", "Realme",
          "Motorola", "Google", "Nokia", "Infinix", "Tecno", "Honor",
          "Huawei", "Sony", "Asus"]
MAX_PER_BRAND = 60          # newest N phones per brand (lower = faster)
MIN_DELAY, MAX_DELAY = 5.0, 9.0
SKIP_NAMES = re.compile(r"\b(tab|tablet|pad|band|buds)\b|\bwatch|ipad", re.I)

FIELDS = ["brand", "name", "url", "scraped_on", "year", "status", "weight_g",
          "thickness_mm", "screen_in", "res_w", "res_h", "ppi", "refresh_hz",
          "is_oled", "os", "chipset", "ram_gb", "storage_gb", "has_card_slot",
          "main_cam_mp", "n_rear_cams", "selfie_mp", "battery_mah",
          "charging_w", "has_5g", "has_nfc", "price_raw", "price_value",
          "price_currency"]

session = requests.Session()
session.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept-Language": "en-US,en;q=0.9",
})


def get(url, retries=5):
    """GET a page and return BeautifulSoup (or None). Backs off on 429/503."""
    for attempt in range(1, retries + 1):
        time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
        try:
            r = session.get(url, timeout=30)
        except requests.RequestException as e:
            print(f"   network error ({e}); retry {attempt}/{retries}")
            time.sleep(10 * attempt)
            continue
        if r.status_code == 200:
            return BeautifulSoup(r.text, "html.parser")
        if r.status_code in (429, 503):
            wait = 90 * attempt
            print(f"   HTTP {r.status_code} (rate limited). Sleeping {wait}s ...")
            time.sleep(wait)
            continue
        print(f"   HTTP {r.status_code} for {url}")
        return None
    return None


def find_brand_urls(names):
    soup = get(BASE + "makers.php3")
    found = {}
    if soup is None:
        return found
    for a in soup.select("a[href$='.php']"):
        txt = a.get_text(" ", strip=True)
        m = re.match(r"^(.*?)\s+\d+\s+devices?$", txt)
        if m and m.group(1).lower() in [n.lower() for n in names]:
            found[m.group(1).lower()] = BASE + a["href"]
    return found


def list_phones(brand_url, limit):
    out, url = [], brand_url
    while url and len(out) < limit:
        soup = get(url)
        if soup is None:
            break
        for a in soup.select("div.makers ul li a"):
            name = a.get_text(" ", strip=True)
            if not SKIP_NAMES.search(name):
                out.append((name, BASE + a["href"]))
        nxt = soup.select_one("a.pages-next") or soup.select_one(
            "a.prevnextbutton[title='Next page']")
        url = BASE + nxt["href"] if nxt is not None and nxt.get("href") else None
    return out[:limit]


# ----------------------------------------------------------------- parsing
def read_specs(soup):
    """Turn the spec tables into {'Category|Label': 'value text'}."""
    specs = {}
    for table in soup.select("div#specs-list table"):
        th = table.find("th")
        cat = th.get_text(strip=True) if th else ""
        last = ""
        for tr in table.select("tr"):
            ttl, nfo = tr.select_one("td.ttl"), tr.select_one("td.nfo")
            if nfo is None:
                continue
            label = (ttl.get_text(" ", strip=True) if ttl else "").replace("\xa0", "").strip()
            if label:
                last = label
            else:
                label = last
            key = f"{cat}|{label}"
            val = nfo.get_text(" ", strip=True)
            specs[key] = f"{specs[key]} ; {val}" if key in specs else val
    return specs


def num(pattern, text, cast=float):
    if not text:
        return None
    m = re.search(pattern, text, flags=re.I)
    if not m:
        return None
    try:
        return cast(m.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_price(txt):
    """First price in the text, with its own currency (e.g. '$ 799 / EUR 899' -> 799 USD)."""
    if not txt:
        return None, None
    symbols = {"€": "EUR", "£": "GBP", "₹": "INR", "$": "USD"}
    m = re.search(r"(€|£|₹|\$|EUR|GBP|INR|USD)?\s*([\d,]+(?:\.\d+)?)\s*(EUR|GBP|INR|USD)?", txt)
    if not m:
        return None, None
    cur = m.group(1) or m.group(3)
    cur = symbols.get(cur, cur)
    if not cur:
        return None, None
    return float(m.group(2).replace(",", "")), cur


def extract(brand, name, url, soup):
    s = read_specs(soup)
    row = dict.fromkeys(FIELDS)
    row.update(brand=brand, name=name, url=url, scraped_on=date.today().isoformat())

    row["year"] = num(r"(\d{4})", s.get("Launch|Announced"), int)
    row["status"] = s.get("Launch|Status")
    row["weight_g"] = num(r"(\d+(?:\.\d+)?)\s*g\b", s.get("Body|Weight"))
    dims = s.get("Body|Dimensions", "")
    nums = re.findall(r"\d+(?:\.\d+)?", dims.split("mm")[0]) if dims else []
    row["thickness_mm"] = float(nums[2]) if len(nums) >= 3 else None

    row["screen_in"] = num(r"([\d.]+)\s*inches", s.get("Display|Size"))
    res = s.get("Display|Resolution", "")
    m = re.search(r"(\d+)\s*x\s*(\d+)", res)
    if m:
        row["res_w"], row["res_h"] = int(m.group(1)), int(m.group(2))
    row["ppi"] = num(r"~?(\d+)\s*ppi", res, int)
    dtype = s.get("Display|Type", "")
    row["refresh_hz"] = num(r"(\d+)\s*Hz(?!\s*PWM)", dtype, int)
    row["is_oled"] = int("oled" in dtype.lower())

    row["os"] = s.get("Platform|OS")
    row["chipset"] = s.get("Platform|Chipset")

    mem = s.get("Memory|Internal", "")
    st = None
    for mm in re.finditer(r"(\d+)\s*(GB|TB)(?!\s*RAM)", mem, flags=re.I):
        st = int(mm.group(1)) * (1024 if mm.group(2).upper() == "TB" else 1)
        break
    row["storage_gb"] = st
    row["ram_gb"] = num(r"(\d+)\s*GB\s*RAM", mem, int)
    row["has_card_slot"] = int(bool(s.get("Memory|Card slot")) and
                               not s.get("Memory|Card slot", "").lower().startswith("no"))

    cam_labels = {"Single": 1, "Dual": 2, "Triple": 3, "Quad": 4, "Penta": 5}
    for key, val in s.items():
        cat, _, label = key.partition("|")
        if cat == "Main Camera" and label in cam_labels and row["main_cam_mp"] is None:
            row["main_cam_mp"] = num(r"([\d.]+)\s*MP", val)
            row["n_rear_cams"] = cam_labels[label]
        if cat == "Selfie camera" and label in cam_labels and row["selfie_mp"] is None:
            row["selfie_mp"] = num(r"([\d.]+)\s*MP", val)

    row["battery_mah"] = num(r"(\d[\d,]*)\s*mAh", s.get("Battery|Type"), int)
    row["charging_w"] = num(r"(\d+(?:\.\d+)?)\s*W", s.get("Battery|Charging"))
    row["has_5g"] = int("5G" in s.get("Network|Technology", ""))
    row["has_nfc"] = int(s.get("Comms|NFC", "No").lower().startswith("yes"))

    raw = s.get("Misc|Price")
    row["price_raw"] = raw
    row["price_value"], row["price_currency"] = parse_price(raw)
    return row


# -------------------------------------------------------------------- main
def main():
    done = set()
    if os.path.exists(OUT_CSV):
        with open(OUT_CSV, newline="", encoding="utf-8") as f:
            done = {r["url"] for r in csv.DictReader(f)}
        print(f"Resuming: {len(done)} phones already saved.")
    else:
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()

    brand_urls = find_brand_urls(BRANDS)
    print("Brands found:", sorted(brand_urls))
    for brand in BRANDS:
        if brand.lower() not in brand_urls:
            print(f"!! brand page for {brand} not found, skipping")
            continue
        phones = list_phones(brand_urls[brand.lower()], MAX_PER_BRAND)
        print(f"\n{brand}: {len(phones)} phones listed")
        for i, (name, url) in enumerate(phones, 1):
            if url in done:
                continue
            soup = get(url)
            if soup is None:
                continue
            row = extract(brand, name, url, soup)
            with open(OUT_CSV, "a", newline="", encoding="utf-8") as f:
                csv.DictWriter(f, fieldnames=FIELDS).writerow(row)
            done.add(url)
            print(f"  [{brand} {i}/{len(phones)}] {name} | {row['year']} | "
                  f"{row['price_value']} {row['price_currency']}")
    print(f"\nDone. {len(done)} phones in {OUT_CSV}")


if __name__ == "__main__":
    main()