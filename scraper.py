import time
import random
import re
from typing import Dict, List, Optional
from urllib.parse import quote_plus

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException,
)

class GoogleMapsScraper:
    def __init__(self, *, headless: bool = True, max_results_per_search: int = 30):
        """Initialize the scraper with Chrome driver

        - headless: run Chrome in headless mode for speed and stability
        - max_results_per_search: cap results per query+area to control runtime
        """
        options = webdriver.ChromeOptions()
        if headless:
            # New headless is faster and more compatible with modern Chrome
            options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--window-size=1366,768')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        # Reduce bandwidth: disable images
        try:
            prefs = {
                'profile.managed_default_content_settings.images': 2,
            }
            options.add_experimental_option('prefs', prefs)
        except Exception:
            pass
        # Set a stable desktop user-agent
        options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
        # Use eager strategy so Selenium continues once DOMContentLoaded fires
        try:
            options.page_load_strategy = 'eager'
        except Exception:
            pass

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        # Reduce detection by scripts checking webdriver flag
        self.driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        # Make WebDriver more tolerant to slow responses
        try:
            # Extend command timeout from default (~120s) to 300s
            self.driver.command_executor.set_timeout(300)
        except Exception:
            pass
        # Cap page load wait so we don't stall excessively on navigation
        try:
            self.driver.set_page_load_timeout(45)
        except Exception:
            pass
        # Small implicit wait to reduce polling churn
        try:
            self.driver.implicitly_wait(2)
        except Exception:
            pass

        self.results: List[Dict[str, str]] = []
        self._seen_identifiers: set = set()
        self.max_results_per_search = max_results_per_search
        # Precompile regex used repeatedly
        self._postal_re = re.compile(r"\b(\d{5})\b$")
    
    def search_locations(self, query: str, area: str) -> None:
        """Search for locations on Google Maps and collect place details."""
        q = quote_plus(f"{query} in {area}")
        search_url = f"https://www.google.com/maps/search/?api=1&hl=en&query={q}"
        print(f"Searching: {query} in {area}")

        self.driver.get(search_url)

        # Best-effort: dismiss any consent or onboarding popups that block results
        self._dismiss_popups()

        # Make sure the query is executed via the search box to force results list
        try:
            search_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input#searchboxinput, input[aria-label*="Search Google Maps"]'))
            )
            search_input.clear()
            search_input.send_keys(f"{query} in {area}")
            # Trigger search
            try:
                btn = self.driver.find_element(By.CSS_SELECTOR, 'button#searchbox-searchbutton')
                btn.click()
            except NoSuchElementException:
                search_input.send_keys(Keys.ENTER)
        except TimeoutException:
            pass

        # Wait for any result tiles to appear
        try:
            WebDriverWait(self.driver, 15).until(
                lambda d: len(self._get_result_tiles()) > 0
            )
        except TimeoutException:
            print(f"No results found for {query} in {area}")
            return

        # Scroll to load more results up to a maximum
        self.scroll_results(self.max_results_per_search)

        # Remember the list page window handle so we can return after each detail view
        try:
            list_handle = self.driver.current_window_handle
        except Exception:
            list_handle = None

        processed = 0
        # Iterate by index and re-query each time to avoid stale references
        while processed < self.max_results_per_search:
            tiles = self._get_result_tiles()
            if processed >= len(tiles):
                break

            try:
                tile = tiles[processed]
                WebDriverWait(self.driver, 10).until(EC.visibility_of(tile))
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tile)
                navigated = False
                new_tab_opened = False
                href = None
                try:
                    # Prefer navigating via href in a new tab so we don't lose the results list
                    if tile.tag_name.lower() == 'a':
                        href = tile.get_attribute('href')
                    if not href:
                        try:
                            link = tile.find_element(By.CSS_SELECTOR, 'a[href^="/maps/place"], a[href^="https://www.google.com/maps/place"]')
                            href = link.get_attribute('href')
                        except Exception:
                            href = None

                    if href:
                        self.driver.execute_script("window.open(arguments[0], '_blank');", href)
                        WebDriverWait(self.driver, 10).until(lambda d: len(d.window_handles) > 1)
                        self.driver.switch_to.window(self.driver.window_handles[-1])
                        new_tab_opened = True
                        navigated = True
                    else:
                        # Fallback to clicking the tile directly
                        try:
                            tile.click()
                            navigated = True
                        except Exception:
                            pass
                except Exception:
                    # As a last resort try clicking
                    try:
                        tile.click()
                        navigated = True
                    except Exception:
                        pass

                # Wait for place title to show on the details pane
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, 'h1'))
                )

                business_data = self.extract_business_info()
                if business_data:
                    business_data['search_query'] = query
                    business_data['search_area'] = area
                    identifier = (
                        business_data.get('name', ''),
                        business_data.get('full_address', ''),
                    )
                    if identifier not in self._seen_identifiers:
                        self._seen_identifiers.add(identifier)
                        self.results.append(business_data)
                        print(f"Extracted: {business_data.get('name', 'Unknown')}")

                # Light jitter between clicks to be polite
                time.sleep(0.5 + random.random() * 0.5)

            except (TimeoutException, StaleElementReferenceException, NoSuchElementException) as e:
                print(f"Error processing business {processed}: {e}")
            finally:
                # Close detail tab or go back to the results list so we can continue
                try:
                    if 'new_tab_opened' in locals() and new_tab_opened:
                        self.driver.close()
                        # Switch back to results list
                        if list_handle:
                            self.driver.switch_to.window(list_handle)
                        else:
                            # Fallback to the first handle
                            self.driver.switch_to.window(self.driver.window_handles[0])
                    else:
                        # If we navigated in the same tab, try to go back to list
                        try:
                            self.driver.back()
                            # Wait for results to be visible again
                            WebDriverWait(self.driver, 10).until(
                                lambda d: len(self._get_result_tiles()) > 0
                            )
                        except Exception:
                            pass
                except Exception:
                    pass
                processed += 1
    
    def _find_results_panel(self):
        """Try multiple selectors to find the left results panel."""
        selectors = [
            'div[role="feed"]',
            'div[aria-label*="Results"]',
            'div[aria-label*="results"]',
            '[role="main"]',
        ]
        for sel in selectors:
            try:
                panel = self.driver.find_element(By.CSS_SELECTOR, sel)
                if panel:
                    return panel
            except NoSuchElementException:
                continue
        # Fallback to body; scrolling it is usually a no-op but avoids crashing
        return self.driver.find_element(By.TAG_NAME, 'body')

    def _get_result_tiles(self):
        """Return list of result tile elements using multiple selector fallbacks."""
        selectors = [
            'div[role="feed"] a[aria-label]',
            'div[role="feed"] [data-result-index]',
            'div[role="feed"] div[role="article"]',
            '[data-result-index]',
            'div[role="article"]',
            'a[href^="/maps/place"]',
        ]
        last_error = None
        for sel in selectors:
            for attempt in range(3):
                try:
                    tiles = self.driver.find_elements(By.CSS_SELECTOR, sel)
                    if tiles:
                        return tiles
                    # If empty, small pause then retry in case of late render
                    time.sleep(0.2)
                except Exception as e:
                    last_error = e
                    # Intermittent driver timeouts can happen; retry a couple of times
                    time.sleep(0.3)
            # After attempts, if still failing/empty, log once and try next selector
            try:
                count = len(self.driver.find_elements(By.CSS_SELECTOR, sel))
            except Exception as e:
                count = f"error: {e}"
            print(f"Selector '{sel}' yielded: {count}")
        if last_error:
            print(f"_get_result_tiles encountered errors; last error: {last_error}")
        return []

    def scroll_results(self, max_to_load: int = 30) -> None:
        """Scroll through results to load more businesses up to max_to_load."""
        panel = self._find_results_panel()

        prev_count = 0
        stagnant_rounds = 0
        max_stagnant_rounds = 4

        while True:
            try:
                tiles = self._get_result_tiles()
            except Exception as e:
                print(f"Failed to get result tiles during scroll: {e}")
                tiles = []
            count = len(tiles)
            if count >= max_to_load:
                break
            if count == prev_count:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0
            if stagnant_rounds >= max_stagnant_rounds:
                break

            # Scroll to bottom of panel to load more
            try:
                self.driver.execute_script(
                    "arguments[0].scrollTop = arguments[0].scrollHeight", panel
                )
            except Exception:
                # Fallback to page scroll
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            prev_count = count
            time.sleep(0.8 + random.random() * 0.6)

    def _dismiss_popups(self) -> None:
        """Attempt to close common consent or onboarding popups on Maps."""
        # Selenium CSS does not support :has or :contains; use XPath for text search
        xpaths = [
            "//button[contains(., 'I agree')]",
            "//button//*[contains(., 'I agree')]/ancestor::button",
            "//button[contains(., 'Accept all')]",
            "//button//*[contains(., 'Accept all')]/ancestor::button",
            "//button[contains(., 'Accept')]",
            "//button//*[contains(., 'Accept')]/ancestor::button",
            "//button[contains(., 'Reject all')]",
            "//button//*[contains(., 'Reject all')]/ancestor::button",
        ]

        def try_clicks():
            for xp in xpaths:
                try:
                    els = self.driver.find_elements(By.XPATH, xp)
                    for el in els:
                        if el.is_displayed():
                            try:
                                el.click()
                                time.sleep(0.2)
                            except Exception:
                                pass
                except Exception:
                    pass

        # Try on main document
        try_clicks()
        # Try inside iframes (consent often lives in iframes)
        try:
            frames = self.driver.find_elements(By.TAG_NAME, 'iframe')
            for i, fr in enumerate(frames):
                try:
                    self.driver.switch_to.frame(fr)
                    try_clicks()
                except Exception:
                    pass
                finally:
                    self.driver.switch_to.default_content()
        except Exception:
            pass
    
    def extract_business_info(self) -> Optional[Dict[str, str]]:
        """Extract detailed information from a business page."""
        business_data: Dict[str, str] = {}

        try:
            # Name
            name_element = WebDriverWait(self.driver, 12).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'h1'))
            )
            name_text = (name_element.text or '').strip()
            if not name_text:
                # Try common inner span class used by Maps for titles
                try:
                    name_text = self.driver.find_element(By.CSS_SELECTOR, 'h1 .DUwDvf').text.strip()
                except NoSuchElementException:
                    pass
            if not name_text:
                # Last resort: use page title before the trailing label
                title = self.driver.title
                if title and ' - Google Maps' in title:
                    name_text = title.split(' - Google Maps', 1)[0].strip()
            business_data['name'] = name_text

            # Address
            try:
                # Primary selector
                address_element = self.driver.find_element(
                    By.CSS_SELECTOR, '[data-item-id="address"] .fontBodyMedium'
                )
            except NoSuchElementException:
                # Fallback: alternative text container near address icon
                try:
                    address_element = self.driver.find_element(
                        By.CSS_SELECTOR, 'button[data-item-id="address"] ~ div .fontBodyMedium'
                    )
                except NoSuchElementException:
                    address_element = None

            if address_element:
                full_address = address_element.text.strip()
                business_data['full_address'] = full_address
                business_data.update(self.parse_address(full_address))
            else:
                business_data['full_address'] = 'N/A'
                business_data['street'] = 'N/A'
                business_data['postal_code'] = 'N/A'

            # Phone
            try:
                phone_element = self.driver.find_element(
                    By.CSS_SELECTOR, '[data-item-id*="phone"] .fontBodyMedium'
                )
                business_data['phone'] = phone_element.text.strip()
            except NoSuchElementException:
                business_data['phone'] = 'N/A'

            # Website
            try:
                website_element = self.driver.find_element(
                    By.CSS_SELECTOR, '[data-item-id="authority"] .fontBodyMedium a'
                )
                business_data['website'] = website_element.get_attribute('href') or 'N/A'
            except NoSuchElementException:
                business_data['website'] = 'N/A'

            # Reviews - Fixed extraction
            rating = 'N/A'
            review_count = 'N/A'
            
            # Try multiple selectors for rating
            rating_selectors = [
                '.fontDisplayLarge',
                'span[role="img"][aria-label*="star"]',
                '.F7nice span:first-child',
                '[jsaction*="review"] span[role="img"]'
            ]
            
            for selector in rating_selectors:
                try:
                    rating_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    rating_text = rating_element.text.strip()
                    
                    # Check if it's a valid rating number
                    if rating_text and re.match(r'^\d+\.?\d*$', rating_text):
                        rating = rating_text
                        break
                    
                    # Try extracting from aria-label
                    aria_label = rating_element.get_attribute('aria-label') or ""
                    if aria_label:
                        rating_match = re.search(r'(\d+\.?\d*)\s*star', aria_label.lower())
                        if rating_match:
                            rating = rating_match.group(1)
                            break
                            
                except NoSuchElementException:
                    continue
            
            # Try multiple selectors for review count
            review_selectors = [
                '.fontBodyMedium .fontBodySmall',
                'button[aria-label*="review"] .fontBodySmall',
                '.F7nice .fontBodySmall',
                '[jsaction*="review"] span'
            ]
            
            for selector in review_selectors:
                try:
                    review_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    review_text = review_element.text.strip()
                    
                    # Extract numbers from review text
                    review_match = re.search(r'(\d+(?:,\d+)*)', review_text)
                    if review_match:
                        review_count = review_match.group(1)
                        break
                        
                except NoSuchElementException:
                    continue
            
            business_data['rating'] = rating
            business_data['review_count'] = review_count
            
            # Properly format the reviews field
            if rating != 'N/A' and review_count != 'N/A':
                business_data['reviews'] = f"{rating} stars ({review_count} reviews)"
            elif rating != 'N/A':
                business_data['reviews'] = f"{rating} stars"
            elif review_count != 'N/A':
                business_data['reviews'] = f"({review_count} reviews)"
            else:
                business_data['reviews'] = 'N/A'

            # Photos (count)
            try:
                photo_elements = self.driver.find_elements(By.CSS_SELECTOR, '[data-photo-index]')
                business_data['photo_count'] = len(photo_elements)
            except Exception:
                business_data['photo_count'] = 0

            # Location link (current URL)
            business_data['location_link'] = self.driver.current_url

            return business_data

        except Exception as e:
            print(f"Error extracting business info: {e}")
            return None
    
    def parse_address(self, address: str) -> Dict[str, str]:
        """Parse address into components (simple US-centric heuristic)."""
        parts: Dict[str, str] = {}

        postal_match = self._postal_re.search(address)
        if postal_match:
            parts['postal_code'] = postal_match.group(1)
            street_part = re.sub(r',\s*[A-Z]{2}\s*\d{5}$', '', address)
            parts['street'] = street_part.strip()
        else:
            parts['postal_code'] = 'N/A'
            parts['street'] = address

        return parts
    
    def scrape_dmv_shooting_ranges(self) -> None:
        """Main method to scrape shooting ranges and gun clubs in DMV area"""
        queries = [
            "shooting ranges",
            "gun clubs",
            "indoor shooting ranges",
            "outdoor shooting ranges",
            "firearms training"
        ]
        
        areas = [
            "Washington DC",
            "Maryland",
            "Virginia",
            "Northern Virginia",
            "Montgomery County MD",
            "Prince George's County MD",
            "Fairfax County VA",
            "Arlington VA"
        ]
        
        for query in queries:
            for area in areas:
                try:
                    self.search_locations(query, area)
                    # polite short pause between searches
                    time.sleep(1.0 + random.random() * 0.5)
                except Exception as e:
                    print(f"Error searching {query} in {area}: {e}")
                    continue
        
        print(f"\nTotal businesses found: {len(self.results)}")
    
    def save_to_csv(self, filename: str = 'dmv_shooting_ranges.csv') -> None:
        """Save results to CSV file"""
        if not self.results:
            print("No data to save")
            return
        
        # Results have been de-duplicated during scraping using _seen_identifiers
        df = pd.DataFrame(self.results)
        
        # Reorder columns to match requirements
        column_order = [
            'name', 'website', 'phone', 'full_address', 'street', 
            'postal_code', 'reviews', 'rating', 'review_count', 
            'photo_count', 'location_link', 'search_query', 'search_area'
        ]
        
        # Ensure all columns exist
        for col in column_order:
            if col not in df.columns:
                df[col] = 'N/A'
        
        df = df[column_order]
        df.to_csv(filename, index=False, encoding='utf-8')
        print(f"Data saved to {filename}")
        print(f"Unique businesses: {len(df)}")
    
    def close(self):
        """Close the browser"""
        self.driver.quit()

# Main execution
if __name__ == "__main__":
    # Narrow default run for quick validation: single query/area, headless, small cap.
    scraper = GoogleMapsScraper(headless=True, max_results_per_search=5)

    try:
        print("Starting DMV Shooting Ranges Scraper (quick test)...")
        # Run a single small search instead of the full DMV sweep
        scraper.search_locations("shooting ranges", "Washington DC")

    except KeyboardInterrupt:
        print("\nScraping interrupted by user")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        # Save whatever has been collected so far to a sample CSV
        try:
            scraper.save_to_csv('dmv_shooting_ranges_sample.csv')
        except Exception as save_err:
            print(f"Failed to save CSV: {save_err}")
        scraper.close()
        print("Scraper finished (quick test)")
