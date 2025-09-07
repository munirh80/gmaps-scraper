# Google Maps Selenium Scraper

Scrape business details from Google Maps using Selenium + Chrome. Includes a robust scraper class, a simple runner, and an enhanced async CLI with YAML/JSON config, progress, and multi-format output.

## Features

- Robust selectors (ARIA/role-first) and popup handling
- Deduped results with consistent CSV schema
- Simple runner (`run_improved_test.py`) and enhanced async CLI (`enhanced_test_runner.py`)
- Multiple formats: CSV (default), JSON, Excel + summary JSON
- Debug helpers and an offline self-test for utilities


## Requirements

- Python 3.10+
- Google Chrome installed
- macOS, Linux, or Windows

Install dependencies:

```bash
pip install -r test/requirements.txt pyyaml
```

## Quick start

### 1) Minimal sync run

Runs a single query/location and writes a CSV.

```bash
python run_improved_test.py
```

- Logs: `scraper_test.log`
- Output: `dmv_shooting_ranges_improved_sample.csv`

### 2) Enhanced async runner

Create a config once, then run with rich options.

```bash
# Create a sample config (YAML)
python enhanced_test_runner.py --create-config sample.yaml

# Run with that config (CSV output, headless)
python enhanced_test_runner.py --config sample.yaml

# Common tweaks
python enhanced_test_runner.py --config sample.yaml --format json
python enhanced_test_runner.py --config sample.yaml --no-headless
python enhanced_test_runner.py --config sample.yaml --concurrent 1 --timeout 300
```

### 3) Programmatic usage

```python
from improved_scraper import GoogleMapsScraper

s = GoogleMapsScraper(headless=True, max_results_per_search=10)
s.search_locations('shooting ranges', 'Washington DC')
s.save_to_csv('results.csv')
s.close()
```

## Configuration (enhanced runner)

See `sample_config.yaml` for all options. Key fields:

- headless: true|false
- max_results_per_search: int (keep ~10–20 for stability)
- query/location or queries/locations (lists)
- output_filename: base name (timestamp auto-added unless disabled)
- output_format: csv|json|excel
- max_concurrent_searches: 1 (recommended) — WebDriver is not thread-safe
- delay_between_searches, timeout_per_search, max_retries, retry_delay
- custom_selectors: reserved for selector overrides

Generate a config programmatically:

```bash
python enhanced_test_runner.py --create-config my_config.yaml
```

## Output

- CSV schema (fixed order):
  `name, website, phone, full_address, street, postal_code, reviews, rating, review_count, photo_count, location_link, search_query, search_area`
- Enhanced runner always writes `{basename}_summary.json` with counts/metadata.

## Troubleshooting

- Chrome/driver mismatch: update Chrome or reinstall `webdriver-manager` cache.
- No results/tiles: run `--no-headless` to observe UI; DOM may have changed.
- Consent popups: handled automatically; if it blocks, try non-headless for a run.
- Timeouts/rate limits: lower `max_results_per_search`, add `delay_between_searches`.
- Concurrency: prefer `--concurrent 1`. For true parallelism, run multiple separate processes/instances (one WebDriver per process).

## Developer notes

- Main class: `improved_scraper.GoogleMapsScraper` (preferred). Earlier variant: `scraper.GoogleMapsScraper`.
- Selector strategy: prefer role/ARIA and stable attributes; use XPath only for text matching.
- Deduplication key: `(name, full_address)`.
- Debug helpers: `quick_maps_probe.py`, `quick_extract_one.py`, `debug_scraper.py`, `quick_run.py`.
- Offline check: `python test/dmv_maps_scraper.py --self-test true` (no Selenium needed).

## Repo layout

- `improved_scraper.py` — robust scraper class
- `enhanced_test_runner.py` — async CLI (YAML/JSON config, progress, multi-format output)
- `run_improved_test.py` — minimal runner
- `sample_config.yaml` — full config example
- `test/dmv_maps_scraper.py` — alternate scraper with self-test mode
- `quick_*` scripts & `debug_scraper.py` — debugging utilities
