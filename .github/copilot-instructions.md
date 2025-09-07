# Copilot agent instructions for gmaps-scraper

Purpose: Give AI agents the essentials to be productive in this Google Maps Selenium scraper repo.

## Big picture
- Core class: `GoogleMapsScraper` in `improved_scraper.py` (preferred) and `scraper.py` (earlier variant). Produces list[dict] in `scraper.results`.
- Runners: `enhanced_test_runner.py` (async CLI + YAML/JSON config, progress, multi-format output) and `run_improved_test.py` (minimal sync).
- Debug helpers: `quick_run.py`, `quick_maps_probe.py`, `quick_extract_one.py`, `debug_scraper.py`.
- Alternate scraper: `test/dmv_maps_scraper.py` (own helpers; supports `--self-test` without Selenium).

## Data flow
- `search_locations(query, area)` → go to Maps, `_dismiss_popups()` → load/scroll result tiles (`div[role="feed"]`) → open detail → `extract_business_info()`.
- Record dedupe key: `(name, full_address)`. Appended to `self.results`.
- Save via `save_to_csv(...)`; enhanced runner also writes JSON/Excel + a `{basename}_summary.json`.

## Key files and patterns
- `improved_scraper.py`:
  - Chrome setup: anti-detection flags, `headless=new`, timeouts, implicit waits; navigator.webdriver undefined.
  - Stable selectors: prefer role/ARIA and attributes over brittle classes (see `_get_result_tiles`, `extract_business_info`). XPath only for text matches.
  - Scrolling via `div[role="feed"]`; retries and `_restart_driver()` for resilience.
- `enhanced_test_runner.py`:
  - `ScraperConfig` dataclass: load/save YAML/JSON (`from_file`, `to_file`), validation, auto-timestamped `output_filename`.
  - Async execution with per-search timeouts, progress/metrics, and `save_results_multiple_formats`.
  - CLI: `--config`, `--create-config`, `--queries/--locations`, `--format {csv,json,excel}`, `--headless/--no-headless`, `--concurrent`, `--timeout`, `--delay`, `--log-*`.
- `run_improved_test.py`: simple context-managed session, basic logging, CSV save.

## Conventions
- CSV schema (order enforced): `name, website, phone, full_address, street, postal_code, reviews, rating, review_count, photo_count, location_link, search_query, search_area`.
- Popups: try ARIA-labeled buttons then XPath text contains; iframe handling exists in `test/dmv_maps_scraper.py`.
- Config-first: prefer YAML/JSON with `ScraperConfig`; `custom_selectors` is available for future wiring if selector overrides are needed.

## Developer workflows
- Requirements: Python 3.10+, Google Chrome. Install deps: `pip install -r test/requirements.txt pyyaml`.
- Quick sync run: see `run_improved_test.py` (logs to `scraper_test.log`, writes CSV).
- Enhanced async run: `enhanced_test_runner.py --create-config sample.yaml` then `--config sample.yaml --format csv --no-headless` as needed.
- Debug UI/selectors: run non-headless (`--no-headless`) or use `quick_maps_probe.py` / `quick_extract_one.py`.
- Offline check: `python test/dmv_maps_scraper.py --self-test true` validates helpers without Selenium.

## Caveats
- Concurrency: WebDriver is not thread-safe. `run_enhanced_scraper` shares a single driver; prefer `--concurrent 1`. For true parallelism, use multiple `GoogleMapsScraper` instances.
- DOM churn: Google Maps updates frequently—follow role/ARIA-first approach; avoid CSS `:contains`.
- Stability: keep `max_results_per_search` modest (≈10–20). Retries and `_restart_driver()` help but heavy loads may hit rate limits/timeouts.

## Extending safely
- Adding fields: update `extract_business_info()` and the `column_order` before saving.
- Selector changes: mirror patterns in `_get_result_tiles`/`_dismiss_popups`; consider adding config-driven overrides if needed.

If any guidance conflicts with current behavior (e.g., desired concurrency), call it out in your PR and propose updates here.
