import time
import random
import re
from typing import Dict, List, Optional
from urllib.parse import quote_plus

import pandas as pd  # type: ignore[import-untyped]
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
    WebDriverException,
)

class GoogleMapsScraper:
    def __init__(self, *, headless: bool = True, max_results_per_search: int = 20):
        """Initialize the scraper with Chrome driver"""
        self.results: List[Dict[str, str]] = []
        self._seen_identifiers: set = set()
        self.max_results_per_search = max_results_per_search
        # Accept 5-digit or 5+4 ZIP codes anywhere near the end
        self._postal_re = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
        self.driver = None
        self.headless = headless
        self._setup_driver()
    
    def _setup_driver(self):
        """Setup Chrome driver with improved stability"""
        options = webdriver.ChromeOptions()
        if self.headless:
            options.add_argument('--headless=new')
        
        # Stability improvements
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-extensions')
        options.add_argument('--window-size=1366,768')
        
        # Anti-detection
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
        
        # Performance settings
        prefs = {
            'profile.managed_default_content_settings.images': 2,
            'profile.default_content_setting_values.notifications': 2,
        }
        options.add_experimental_option('prefs', prefs)
        options.page_load_strategy = 'normal'  # Changed from 'eager' for stability
        
        try:
            service = Service(ChromeDriverManager().install())
            self.driver = webdriver.Chrome(service=service, options=options)
            
            # Set timeouts
            self.driver.set_page_load_timeout(60)
            self.driver.implicitly_wait(10)
            
            # Anti-detection script
            self.driver.execute_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            print("Chrome driver initialized successfully")
            
        except Exception as e:
            print(f"Failed to initialize Chrome driver: {e}")
            raise
    
    def _restart_driver(self):
        """Restart the driver if it crashes"""
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        time.sleep(2)
        self._setup_driver()
        print("Driver restarted")
    
    def search_locations(self, query: str, area: str) -> None:
        """Search for locations on Google Maps and collect place details."""
        max_retries = 3
        
        for attempt in range(max_retries):
            try:
                self._perform_search(query, area)
                break
            except WebDriverException as e:
                print(f"Driver error on attempt {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    self._restart_driver()
                    time.sleep(3)
                else:
                    print(f"Failed to complete search after {max_retries} attempts")
    
    def _perform_search(self, query: str, area: str) -> None:
        """Perform the actual search"""
        q = quote_plus(f"{query} in {area}")
        search_url = f"https://www.google.com/maps/search/?api=1&hl=en&query={q}"
        print(f"Searching: {query} in {area}")

        self.driver.get(search_url)
        time.sleep(3)

        # Dismiss popups
        self._dismiss_popups()

        # Execute search
        try:
            if not self.driver:
                raise WebDriverException("Driver not initialized")
            search_input = WebDriverWait(self.driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, 'input#searchboxinput'))
            )
            search_input.clear()
            search_input.send_keys(f"{query} in {area}")
            search_input.send_keys(Keys.ENTER)
            time.sleep(3)
        except TimeoutException:
            print("Could not find search input")
            return

        # Wait for results
        try:
            if not self.driver:
                raise WebDriverException("Driver not initialized")
            WebDriverWait(self.driver, 20).until(
                lambda d: len(self._get_result_tiles()) > 0
            )
        except TimeoutException:
            print(f"No results found for {query} in {area}")
            return

        # Scroll to load more results
        self.scroll_results(min(self.max_results_per_search, 15))  # Limit for stability

        # Process results with better error handling
        processed = 0
        max_failures = 5
        consecutive_failures = 0
        
        while processed < self.max_results_per_search and consecutive_failures < max_failures:
            tiles = self._get_result_tiles()
            if processed >= len(tiles):
                break

            try:
                success = self._process_single_result(tiles[processed], query, area)
                if success:
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
                
                time.sleep(0.5 + random.random() * 1.0)  # Longer delays for stability
                
            except Exception as e:
                print(f"Error processing business {processed}: {e}")
                consecutive_failures += 1
                
            processed += 1
    
    def _process_single_result(self, tile, query: str, area: str) -> bool:
        """Process a single result tile"""
        try:
            # Scroll into view
            if not self.driver:
                raise WebDriverException("Driver not initialized")
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tile)
            time.sleep(0.5)
            
            # Determine a reliable clickable element inside the tile
            click_target = tile
            try:
                # Prefer the place anchor inside the tile when available
                inner_link = tile.find_element(By.CSS_SELECTOR, 'a[href*="/maps/place/"]')
                if inner_link:
                    click_target = inner_link
            except Exception:
                pass

            # Wait until the target is visible, then click safely
            if not self.driver:
                raise WebDriverException("Driver not initialized")
            WebDriverWait(self.driver, 10).until(EC.visibility_of(click_target))
            self._safe_click(click_target)
            
            # Wait for detail panel to load and become visible
            if not self.driver:
                raise WebDriverException("Driver not initialized")
            WebDriverWait(self.driver, 15).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, 'h1'))
            )
            time.sleep(2)  # Extra time for content to load

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
                    return True
            
            return False
            
        except Exception as e:
            print(f"Failed to process result: {e}")
            return False

    def _safe_click(self, element) -> None:
        """Attempt to click an element, with JS fallback if intercepted."""
        try:
            element.click()
        except Exception:
            try:
                if not self.driver:
                    raise WebDriverException("Driver not initialized")
                self.driver.execute_script("arguments[0].click();", element)
            except Exception:
                raise
    
    def _get_result_tiles(self):
        """Return list of result tile elements using robust selectors.

        Google Maps updates classnames frequently. Prefer role/aria markers
        and attributes that tend to be stable.
        """
        css_candidates = [
            # Primary: the results feed with items that have an aria-label and index
            'div[role="feed"] div[aria-label][data-result-index]',
            # Many map result tiles are anchors with aria-label inside the feed
            'div[role="feed"] a[aria-label]',
            # Known tile class used often
            'div[role="feed"] a.hfpxzc',
            # Fallback: any place link
            'a[href*="/maps/place/"]',
        ]

        for sel in css_candidates:
            try:
                tiles = self.driver.find_elements(By.CSS_SELECTOR, sel)
                if tiles:
                    return tiles
            except Exception:
                continue
        return []

    def scroll_results(self, max_to_load: int = 15) -> None:
        """Scroll through results to load more businesses."""
        try:
            if not self.driver:
                raise WebDriverException("Driver not initialized")
            results_panel = self.driver.find_element(By.CSS_SELECTOR, 'div[role="feed"]')
        except NoSuchElementException:
            if not self.driver:
                raise WebDriverException("Driver not initialized")
            results_panel = self.driver.find_element(By.TAG_NAME, 'body')

        prev_count = 0
        stagnant_rounds = 0

        while True:
            tiles = self._get_result_tiles()
            count = len(tiles)
            
            if count >= max_to_load or stagnant_rounds >= 3:
                break
                
            if count == prev_count:
                stagnant_rounds += 1
            else:
                stagnant_rounds = 0

            try:
                if not self.driver:
                    raise WebDriverException("Driver not initialized")
                self.driver.execute_script(
                    "arguments[0].scrollTop = arguments[0].scrollHeight", results_panel
                )
            except Exception:
                if not self.driver:
                    raise WebDriverException("Driver not initialized")
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            prev_count = count
            time.sleep(1.5)

    def _dismiss_popups(self) -> None:
        """Dismiss common popups with improved detection.

        Avoid unsupported CSS ':contains' by using XPath for text matching.
        """
        # First try ARIA-label driven buttons via CSS
        aria_css = [
            'button[aria-label*="Accept"]',
            'button[aria-label*="I agree"]',
        ]
        for selector in aria_css:
            try:
                if not self.driver:
                    raise WebDriverException("Driver not initialized")
                for btn in self.driver.find_elements(By.CSS_SELECTOR, selector):
                    if btn.is_displayed():
                        btn.click()
                        time.sleep(1)
                        break
            except Exception:
                pass

        # Then try text-based labels via XPath contains()
        xpaths = [
            "//button[normalize-space()='Accept']",
            "//button[contains(., 'Accept')]",
            "//button[contains(., 'I agree')]",
            "//button[contains(., 'Got it')]",
            "//div[@role='dialog']//button[contains(., 'OK')]",
        ]
        for xp in xpaths:
            try:
                if not self.driver:
                    raise WebDriverException("Driver not initialized")
                elems = self.driver.find_elements(By.XPATH, xp)
                for el in elems:
                    if el.is_displayed():
                        el.click()
                        time.sleep(1)
                        break
            except Exception:
                pass
    
    def extract_business_info(self) -> Optional[Dict[str, str]]:
        """Extract detailed information from a business page with improved selectors."""
        business_data: Dict[str, str] = {}

        try:
            # Name - try multiple approaches
            name_found = False
            name_selectors = [
                'h1 span',
                'h1',
                '[role="main"] h1',
            ]
            
            for selector in name_selectors:
                try:
                    if not self.driver:
                        raise WebDriverException("Driver not initialized")
                    name_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    name_text = name_element.text.strip()
                    if name_text and not name_found:
                        business_data['name'] = name_text
                        name_found = True
                        break
                except NoSuchElementException:
                    continue
            
            if not name_found:
                # Fallback to page title
                if not self.driver:
                    raise WebDriverException("Driver not initialized")
                title = self.driver.title
                if title and ' - Google Maps' in title:
                    business_data['name'] = title.split(' - Google Maps', 1)[0].strip()
                else:
                    business_data['name'] = 'Unknown'

            # Address - improved selectors
            address_selectors = [
                '[data-item-id="address"] .fontBodyMedium',
                'button[data-item-id="address"] span[class*="fontBody"]',
                '[data-value="Address"]',
                'button[aria-label*="Address"]',
            ]
            
            address_found = False
            for selector in address_selectors:
                try:
                    if not self.driver:
                        raise WebDriverException("Driver not initialized")
                    address_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    full_address = address_element.text.strip()
                    if full_address and not address_found:
                        business_data['full_address'] = full_address
                        business_data.update(self.parse_address(full_address))
                        address_found = True
                        break
                except NoSuchElementException:
                    continue
            
            if not address_found:
                business_data['full_address'] = 'N/A'
                business_data['street'] = 'N/A'
                business_data['postal_code'] = 'N/A'

            # Phone
            phone_selectors = [
                '[data-item-id*="phone"] .fontBodyMedium',
                'button[data-item-id*="phone"] span[class*="fontBody"]',
                'button[aria-label*="Phone"]',
            ]
            
            phone_found = False
            for selector in phone_selectors:
                try:
                    if not self.driver:
                        raise WebDriverException("Driver not initialized")
                    phone_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    phone_text = phone_element.text.strip()
                    if phone_text and not phone_found:
                        business_data['phone'] = phone_text
                        phone_found = True
                        break
                except NoSuchElementException:
                    continue
            
            if not phone_found:
                business_data['phone'] = 'N/A'

            # Website
            website_selectors = [
                '[data-item-id="authority"] a',
                'a[data-value*="website"]',
                'a[aria-label*="Website"]',
                'a[href]:not([href*="google.com"]):not([href*="maps"])',
            ]
            
            website_found = False
            for selector in website_selectors:
                try:
                    if not self.driver:
                        raise WebDriverException("Driver not initialized")
                    website_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    href = website_element.get_attribute('href')
                    if href and 'google.com' not in href and not website_found:
                        business_data['website'] = href
                        website_found = True
                        break
                except NoSuchElementException:
                    continue
            
            if not website_found:
                business_data['website'] = 'N/A'

            # Reviews and Rating - improved extraction
            try:
                # Try to find rating number
                rating_selectors = [
                    '.fontDisplayLarge',
                    'span[role="img"][aria-label*="stars"]',
                    '.F7nice span'
                ]
                
                rating = 'N/A'
                for selector in rating_selectors:
                    try:
                        if not self.driver:
                            raise WebDriverException("Driver not initialized")
                        rating_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                        rating_text = rating_element.text.strip()
                        # Extract number from rating text
                        if rating_text and rating_text.replace('.', '').replace(',', '').isdigit():
                            rating = rating_text
                            break
                        # Try getting from aria-label
                        aria_label = rating_element.get_attribute('aria-label')
                        if aria_label:
                            rating_match = re.search(r'(\d+\.?\d*)', aria_label)
                            if rating_match:
                                rating = rating_match.group(1)
                                break
                    except NoSuchElementException:
                        continue

                # Try to find review count
                review_count = 'N/A'
                # Use CSS where possible and fallback to XPath for text lookup
                review_count = 'N/A'
                review_css = [
                    '.F7nice .fontBodySmall',
                    'button[aria-label*="reviews"]',
                ]
                for selector in review_css:
                    try:
                        if not self.driver:
                            raise WebDriverException("Driver not initialized")
                        el = self.driver.find_element(By.CSS_SELECTOR, selector)
                        txt = el.text.strip()
                        m = re.search(r'(\d{1,3}(?:,\d{3})*|\d+)', txt)
                        if m:
                            review_count = m.group(1)
                            break
                    except NoSuchElementException:
                        continue
                if review_count == 'N/A':
                    try:
                        if not self.driver:
                            raise WebDriverException("Driver not initialized")
                        el = self.driver.find_element(By.XPATH, "//span[contains(translate(., 'REVIEWS', 'reviews'), 'reviews')]")
                        txt = el.text.strip()
                        m = re.search(r'(\d{1,3}(?:,\d{3})*|\d+)', txt)
                        if m:
                            review_count = m.group(1)
                    except Exception:
                        pass

                business_data['rating'] = rating
                business_data['review_count'] = review_count
                
                if rating != 'N/A' or review_count != 'N/A':
                    business_data['reviews'] = f"{rating} stars ({review_count} reviews)"
                else:
                    business_data['reviews'] = 'N/A'
                    
            except Exception as e:
                print(f"Error extracting reviews: {e}")
                business_data['rating'] = 'N/A'
                business_data['review_count'] = 'N/A'
                business_data['reviews'] = 'N/A'

            # Photos count
            try:
                if not self.driver:
                    raise WebDriverException("Driver not initialized")
                photo_elements = self.driver.find_elements(By.CSS_SELECTOR, '[data-photo-index]')
                business_data['photo_count'] = str(len(photo_elements))
            except Exception:
                business_data['photo_count'] = '0'

            # Location link
            if not self.driver:
                raise WebDriverException("Driver not initialized")
            business_data['location_link'] = self.driver.current_url

            return business_data

        except Exception as e:
            print(f"Error extracting business info: {e}")
            return None
    
    def parse_address(self, address: str) -> Dict[str, str]:
        """Parse address into components."""
        parts: Dict[str, str] = {}

        postal_match = self._postal_re.search(address)
        if postal_match:
            parts['postal_code'] = postal_match.group(0)
            # Remove trailing state + ZIP (supports ZIP+4) if present
            street_part = re.sub(r',\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?\s*$', '', address)
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
        ]
        
        # Reduced areas for testing
        areas = [
            "Washington DC",
            "Northern Virginia",
            "Maryland"
        ]
        
        for query in queries:
            for area in areas:
                try:
                    print(f"\n--- Searching: {query} in {area} ---")
                    self.search_locations(query, area)
                    # Longer pause between searches for stability
                    time.sleep(2.0 + random.random())
                except Exception as e:
                    print(f"Error searching {query} in {area}: {e}")
                    # Try to restart driver if there was a critical error
                    try:
                        self._restart_driver()
                        time.sleep(3)
                    except Exception:
                        pass
                    continue
        
        print(f"\nTotal businesses found: {len(self.results)}")
    
    def save_to_csv(self, filename: str = 'dmv_shooting_ranges_improved.csv') -> None:
        """Save results to CSV file"""
        if not self.results:
            print("No data to save")
            return
        
        df = pd.DataFrame(self.results)
        
        column_order = [
            'name', 'website', 'phone', 'full_address', 'street', 
            'postal_code', 'reviews', 'rating', 'review_count', 
            'photo_count', 'location_link', 'search_query', 'search_area'
        ]
        
        for col in column_order:
            if col not in df.columns:
                df[col] = 'N/A'
        
        df = df[column_order]
        df.to_csv(filename, index=False, encoding='utf-8')
        print(f"Data saved to {filename}")
        print(f"Unique businesses: {len(df)}")
    
    def close(self):
        """Close the browser"""
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass

# Main execution
if __name__ == "__main__":
    scraper = GoogleMapsScraper(headless=False, max_results_per_search=10)  # Non-headless for debugging
    
    try:
        print("Starting Improved DMV Shooting Ranges Scraper...")
        print("This may take several minutes...")
        
        scraper.scrape_dmv_shooting_ranges()
        
    except KeyboardInterrupt:
        print("\nScraping interrupted by user")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        try:
            scraper.save_to_csv('dmv_shooting_ranges_improved.csv')
        except Exception as save_err:
            print(f"Failed to save CSV: {save_err}")
        scraper.close()
        print("Scraper finished")
