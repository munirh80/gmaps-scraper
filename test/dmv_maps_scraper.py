#!/usr/bin/env python3
"""
DMV Google Maps Scraper — Shooting Ranges & Gun Clubs
(Updated: allows --self-test without Selenium installed)
"""

from __future__ import annotations
import argparse
import csv
import os
import random
import re
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import List, Dict, Optional, Tuple, Set

import pandas as pd

# Try to import Selenium lazily so --self-test can run without it.
SELENIUM_AVAILABLE = True
try:
    from selenium import webdriver
    from selenium.common.exceptions import (
        TimeoutException, NoSuchElementException, StaleElementReferenceException,
        ElementClickInterceptedException, WebDriverException
    )
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from webdriver_manager.chrome import ChromeDriverManager
except Exception:
    SELENIUM_AVAILABLE = False

# ------------------------------ Configuration ------------------------------ #

DEFAULT_KEYWORDS = [
    "shooting range", "gun range", "gun club", "pistol range", "rifle range",
    "indoor range", "outdoor range", "firearms training", "NRA training",
]

DEFAULT_PLACES = [
    "Washington DC",
    "Bethesda MD", "Silver Spring MD", "Rockville MD", "Gaithersburg MD",
    "Wheaton MD", "Chevy Chase MD", "Takoma Park MD", "College Park MD",
    "Greenbelt MD", "Laurel MD", "Bowie MD", "Hyattsville MD",
    "Upper Marlboro MD", "Waldorf MD", "Oxon Hill MD", "Lanham MD",
    "Arlington VA", "Alexandria VA", "Fairfax VA", "Tysons VA",
    "Falls Church VA", "McLean VA", "Vienna VA", "Reston VA",
    "Herndon VA", "Springfield VA", "Annandale VA", "Burke VA",
    "Woodbridge VA", "Manassas VA", "Lorton VA", "Dale City VA", "Dumfries VA",
]

SLEEP_BOUNDS = (1.5, 3.0)
SCROLL_PAUSE = (1.5, 2.5)
WAIT_SECS_PAGE = 20

# ------------------------------ Data Model --------------------------------- #

@dataclass
class PlaceRecord:
    name: str = ""
    category: str = ""
    rating: str = ""
    reviews_count: str = ""
    address: str = ""
    phone: str = ""
    website: str = ""
    hours_summary: str = ""
    latitude: str = ""
    longitude: str = ""
    place_url: str = ""
    query: str = ""
    scraped_at: str = ""

# ------------------------------ Helpers ------------------------------------ #

def human_delay(bounds: Tuple[float, float] = SLEEP_BOUNDS) -> None:
    time.sleep(random.uniform(*bounds))

def scrape_timestamp() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ")

def ensure_dir(path: str) -> None:
    d = os.path.dirname(os.path.abspath(path))
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def parse_lat_lng_from_url(url: str) -> Tuple[str, str]:
    m = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
    if m:
        return m.group(1), m.group(2)
    return "", ""

# Selenium-dependent helpers are defined only if Selenium is available
if SELENIUM_AVAILABLE:
    def text_or_empty(driver, by, value: str) -> str:
        try:
            el = driver.find_element(by, value)
            return el.text.strip()
        except Exception:
            return ""

    def aria_value_or_empty(driver, xpath: str, prefix: str) -> str:
        try:
            el = driver.find_element(By.XPATH, xpath)
            aria = el.get_attribute("aria-label") or ""
            if aria and prefix in aria:
                return aria.split(prefix, 1)[-1].strip()
            return ""
        except Exception:
            return ""

    def safe_get_attribute(driver, by, value: str, attr: str) -> str:
        try:
            el = driver.find_element(by, value)
            out = el.get_attribute(attr) or ""
            return out.strip()
        except Exception:
            return ""

    def try_click(driver, element) -> bool:
        try:
            ActionChains(driver).move_to_element(element).pause(0.2).click().perform()
            return True
        except Exception:
            try:
                driver.execute_script("arguments[0].click();", element)
                return True
            except Exception:
                return False

    def wait_for(driver, condition, timeout: int = WAIT_SECS_PAGE):
        return WebDriverWait(driver, timeout).until(condition)

    def setup_driver(headless: bool = True):
        options = ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1280,1000")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        # Performance: disable images & notifications to speed things up
        prefs = {
            "profile.managed_default_content_settings.images": 2,
            "profile.default_content_setting_values.notifications": 2,
        }
        options.add_experimental_option("prefs", prefs)

        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        driver.set_page_load_timeout(60)
        return driver

    def open_maps_and_search(driver, query: str) -> None:
        driver.get("https://www.google.com/maps")
        try:
            box = wait_for(driver, _EC.presence_of_element_located((By.ID, "searchboxinput")))
        except NameError:
            # Handle case where EC wasn't resolved due to lazy import scoping
            from selenium.webdriver.support import expected_conditions as EC
            globals()["_EC"] = EC
            box = wait_for(driver, _EC.presence_of_element_located((By.ID, "searchboxinput")))

        box.clear()
        box.send_keys(query)
        human_delay()
        submit = driver.find_element(By.ID, "searchbox-searchbutton")
        try_click(driver, submit)

        try:
            wait_for(driver, _EC.presence_of_element_located((By.XPATH, "//div[@role='feed']")))
        except Exception:
            pass

    def collect_result_items(driver, max_items: int | None = None):
        results = []
        seen = set()
        last_len = -1
        try:
            feed = driver.find_element(By.XPATH, "//div[@role='feed']")
        except Exception:
            return results

        while True:
            cards = feed.find_elements(By.XPATH, ".//a[contains(@href, '/maps/place/')]")
            for card in cards:
                href = card.get_attribute("href") or ""
                if not href:
                    continue
                if href in seen:
                    continue
                if "gmm" in href and "ad" in href:
                    continue
                results.append(card)
                seen.add(href)
                if max_items and len(results) >= max_items:
                    return results
            if len(results) == last_len:
                break
            last_len = len(results)
            driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", feed)
            human_delay(SCROLL_PAUSE)
        return results

    def open_card_and_extract(driver, card, query_str: str):
        if card is not None:
            try:
                if not try_click(driver, card):
                    return None
            except Exception:
                return None
        try:
            wait_for(driver, _EC.presence_of_element_located((By.XPATH, "//h1[contains(@class,'DUwDvf')]")))
        except Exception:
            return None
        human_delay()
        name = text_or_empty(driver, By.XPATH, "//h1[contains(@class,'DUwDvf')]")

        rating = ""
        reviews_count = ""
        try:
            rating_el = driver.find_element(By.XPATH, "//span[contains(@aria-label,'stars')]")
            rating = (rating_el.get_attribute("aria-label") or "").strip()
        except Exception:
            pass
        try:
            reviews_btn = driver.find_element(By.XPATH, "//button[contains(.,'review')]")
            reviews_count = reviews_btn.text.strip()
        except Exception:
            pass

        category = ""
        try:
            cat_candidates = driver.find_elements(By.XPATH, "//button[contains(@class,'DkEaL')]")
            for c in cat_candidates:
                t = c.text.strip()
                if t and len(t) < 60 and not any(s in t.lower() for s in ["directions", "call", "website", "save", "nearby"]):
                    category = t
                    break
        except Exception:
            pass

        address = aria_value_or_empty(driver, "//button[@data-item-id='address']", "Address: ")
        phone = aria_value_or_empty(driver, "//button[starts-with(@data-item-id,'phone:tel:')]", "Phone: ")
        website = ""
        try:
            a = driver.find_element(By.XPATH, "//a[@data-item-id='authority']")
            website = a.get_attribute("href") or ""
        except Exception:
            website = aria_value_or_empty(driver, "//button[@data-item-id='authority']", "Website: ")

        hours_summary = ""
        try:
            hours_el = driver.find_element(By.XPATH, "//div[contains(@aria-label,'Open') or contains(@aria-label,'Closed')]")
            hours_summary = hours_el.get_attribute("aria-label") or ""
        except Exception:
            try:
                hours_el2 = driver.find_element(By.XPATH, "//div[contains(., 'Open ⋅') or contains(., 'Closed ⋅')]")
                hours_summary = hours_el2.text.strip()
            except Exception:
                pass

        current_url = driver.current_url
        lat, lng = parse_lat_lng_from_url(current_url)

        record = PlaceRecord(
            name=name,
            category=category,
            rating=rating,
            reviews_count=reviews_count,
            address=address,
            phone=phone,
            website=website,
            hours_summary=hours_summary,
            latitude=lat,
            longitude=lng,
            place_url=current_url,
            query=query_str,
            scraped_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M:%SZ"),
        )
        return record

    def dedupe_records(records: List[PlaceRecord]) -> List[PlaceRecord]:
        seen_urls = set()
        seen_phones = set()
        out = []
        for r in records:
            key_url = r.place_url.split("&", 1)[0]
            if key_url and key_url in seen_urls:
                continue
            if r.phone and r.phone in seen_phones:
                continue
            out.append(r)
            if key_url:
                seen_urls.add(key_url)
            if r.phone:
                seen_phones.add(r.phone)
        return out

    def write_csv_incremental(path: str, records: List[PlaceRecord]) -> None:
        ensure_dir(path)
        is_new = not os.path.exists(path)
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(asdict(records[0]).keys()))
            if is_new:
                writer.writeheader()
            for r in records:
                writer.writerow(asdict(r))

    def run_scrape(out_path: str,
                   keywords: List[str],
                   places: List[str],
                   headless: bool = True,
                   max_per_query: Optional[int] = None) -> None:
        driver = setup_driver(headless=headless)
        all_records: List[PlaceRecord] = []
        try:
            for place in places:
                for kw in keywords:
                    q = f"{kw} near {place}"
                    print(f"[INFO] Searching: {q}")
                    open_maps_and_search(driver, q)
                    human_delay()

                    cards = collect_result_items(driver, max_items=max_per_query)
                    print(f"[INFO] Found {len(cards)} list items for query: {q}")

                    q_records: List[PlaceRecord] = []

                    if not cards:
                        rec = open_card_and_extract(driver, card=None, query_str=q)  # type: ignore[arg-type]
                        if rec and rec.name:
                            q_records.append(rec)
                    else:
                        for idx, card in enumerate(cards, 1):
                            try:
                                rec = open_card_and_extract(driver, card, q)
                                if rec and rec.name:
                                    q_records.append(rec)
                                    write_csv_incremental(out_path, [rec])
                                    print(f"  [{idx}/{len(cards)}] Saved: {rec.name}")
                            except WebDriverException as e:
                                print(f"  [WARN] Skipped a card due to WebDriverException: {e}")
                            human_delay()

                    q_records = dedupe_records(q_records)
                    all_records.extend(q_records)
                    human_delay((2.0, 4.0))

            if all_records:
                clean = dedupe_records(all_records)
                df = pd.DataFrame([asdict(r) for r in clean])
                df.to_csv(out_path, index=False, encoding="utf-8")
                print(f"[DONE] Wrote {len(clean)} unique records to {out_path}")
            else:
                print("[DONE] No records captured.")
        finally:
            driver.quit()

def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DMV Google Maps scraper for shooting ranges & gun clubs.")
    p.add_argument("--out", type=str, default="dmv_ranges.csv", help="Output CSV path.")
    p.add_argument("--headless", type=lambda v: str(v).lower() in ("1","true","yes","y"), default=True,
                   help="Run Chrome in headless mode (true/false).")
    p.add_argument("--max-per-query", type=int, default=40, help="Max results to collect per query.")
    p.add_argument("--keywords", type=str, nargs="*", default=DEFAULT_KEYWORDS, help="Override keywords list.")
    p.add_argument("--places", type=str, nargs="*", default=DEFAULT_PLACES, help="Override places list.")
    p.add_argument("--self-test", type=lambda v: str(v).lower() in ("1","true","yes","y"), default=False,
                   help="Run lightweight offline tests without Selenium.")
    return p

def self_test():
    samples = [
        ("https://www.google.com/maps/place/ABC/@38.9072,-77.0369,15z/data=!3m1!4b1", ("38.9072","-77.0369")),
        ("https://www.google.com/maps?hl=en", ("","")),
        ("https://www.google.com/maps/@39.0458,-76.6413,10z", ("39.0458","-76.6413")),
    ]
    for url, expect in samples:
        got = parse_lat_lng_from_url(url)
        assert got == expect, f"parse_lat_lng_from_url failed: {url} -> {got} != {expect}"
    print("[SELF-TEST] parse_lat_lng_from_url passed.")

def main():
    args = build_arg_parser().parse_args()
    if args.self_test:
        self_test()
        return
    if not SELENIUM_AVAILABLE:
        raise SystemExit("Selenium and webdriver-manager are required for scraping. Install dependencies from requirements.txt.")
    run_scrape(
        out_path=args.out,
        keywords=args.keywords,
        places=args.places,
        headless=args.headless,
        max_per_query=args.max_per_query or None,
    )

if __name__ == "__main__":
    main()
