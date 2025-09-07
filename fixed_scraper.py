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
        """Initialize the scraper with Chrome driver"""
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument('--headless=new')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled')
        options.add_argument('--window-size=1366,768')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # Reduce bandwidth: disable images
        prefs = {
            'profile.managed_default_content_settings.images': 2,
        }
        options.add_experimental_option('prefs', prefs)
        
        options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
        options.page_load_strategy = 'normal'  # More stable than 'eager'

        service = Service(ChromeDriverManager().install())
        self.driver = webdriver.Chrome(service=service, options=options)
        
        # Reduce detection
        self.driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        
        # Set reasonable timeouts
        self.driver.set_page_load_timeout(45)
        self.driver.implicitly_wait(3)

        self.results: List[Dict[str, str]] = []
        self._seen_identifiers: set = set()
        self.max_results_per_search = max_results_per_search
        self._postal_re = re.compile(r"\b(\d{5})\b$")
    
    def search_locations(self, query: str, area: str) -> None:
        """Search for locations on Google Maps and collect place details."""
        q = quote_plus(f"{query} in {area}")
        search_url = f"https://www.google.com/maps/search/?api=1&hl=en&query={q}"
        print(f"Searching: {query} in {area}")

        self.driver.get(search_url)
        time.sleep(3)

        # Dismiss popups
        self._dismiss_popups()

        # Execute search via input box to ensure results load
        try:
            search_input = WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input#searchboxinput'))
            )
            search_input.clear()
            search_input.send_keys(f"{query} in {area}")
            search_input.send_keys(Keys.ENTER)
            time.sleep(3)
        except TimeoutException:
            print("Search input not found, continuing...")

        # Wait for results with multiple selector attempts
        result_found = False
        for attempt in range(3):
            try:
                WebDriverWait(self.driver, 10).until(
                    lambda d: len(self._get_result_tiles()) > 0
                )
                result_found = True
                break
            except TimeoutException:
                if attempt < 2:
                    print(f"Results not found on attempt {attempt + 1}, retrying...")
                    time.sleep(2)
                    continue
        
        if not result_found:
            print(f"No results found for {query} in {area}")
            return

        # Scroll to load more results
        self.scroll_results(self.max_results_per_search)

        # Process results with better error handling
        processed = 0
        tiles = self._get_result_tiles()
        print(f"Found {len(tiles)} result tiles to process")
        
        for i in range(min(len(tiles), self.max_results_per_search)):
            try:
                # Re-fetch tiles to avoid stale references
                current_tiles = self._get_result_tiles()
                if i >= len(current_tiles):
                    break
                    
                tile = current_tiles[i]
                
                # Scroll tile into view
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", tile)
                time.sleep(0.5)
                
                # Click the tile
                try:
                    tile.click()
                    time.sleep(2)
                except Exception as e:
                    print(f"Failed to click tile {i}: {e}")
                    continue

                # Wait for detail panel
                try:
                    WebDriverWait(self.driver, 10).until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, 'h1'))
                    )
                    time.sleep(1)  # Let content fully load
                except TimeoutException:
                    print(f"Detail panel not loaded for tile {i}")
                    continue

                business_data = self.extract_business_info()
                if business_data and business_data.get('name'):
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

                processed += 1
                time.sleep(0.5 + random.random() * 0.5)

            except (StaleElementReferenceException, NoSuchElementException) as e:
                print(f"Stale/missing element for business {i}: {e}")
                continue
            except Exception as e:
                print(f"Error processing business {i}: {e}")
                continue

        print(f"Processed {processed} businesses for {query} in {area}")

    def _get_result_tiles(self):
        """Return list of result tile elements using multiple selector fallbacks."""
        selectors = [
            'div[role="feed"] a[aria-label]',
            'div[role="feed"] div[jsaction*="click"]',
            '.hfpxzc',  # Common Maps result class
            '[data-result-index]',
            'a[href*="/maps/place/"]',
        ]
        
        for sel in selectors:
            try:
                tiles = self.driver.find_elements(By.CSS_SELECTOR, sel)
                if tiles:
                    # Filter out tiles without text or valid content
                    valid_tiles = []
                    for tile in tiles:
                        try:
                            if tile.is_displayed() and (tile.text.strip() or tile.get_attribute('aria-label')):
                                valid_tiles.append(tile)
                        except:
                            continue
                    if valid_tiles:
                        return valid_tiles
            except Exception:
                continue
        return []

    def scroll_results(self, max_to_load: int = 30) -> None:
        """Scroll through results to load more businesses."""
        try:
            panel = self.driver.find_element(By.CSS_SELECTOR, 'div[role="feed"]')
        except NoSuchElementException:
            panel = self.driver.find_element(By.TAG_NAME, 'body')

        prev_count = 0
        stagnant_rounds = 0

        for scroll_attempt in range(10):  # Limit scroll attempts
            tiles = self._get_result_tiles()
            count = len(tiles)
            
            print(f"Scroll attempt {scroll_attempt + 1}: {count} tiles found")
            
            if count >= max_to_load:
                break
                
            if count == prev_count:
                stagnant_rounds += 1
                if stagnant_rounds >= 3:
                    break
            else:
                stagnant_rounds = 0

            try:
                self.driver.execute_script(
                    "arguments[0].scrollTop = arguments[0].scrollHeight", panel
                )
            except Exception:
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

            prev_count = count
            time.sleep(1.2)

    def _dismiss_popups(self) -> None:
        """Dismiss common popups."""
        # Try common popup selectors
        popup_selectors = [
            'button[aria-label*="Accept"]',
            'button[aria-label*="I agree"]',
            'button[aria-label*="Got it"]',
        ]
        
        for selector in popup_selectors:
            try:
                buttons = self.driver.find_elements(By.CSS_SELECTOR, selector)
                for button in buttons:
                    if button.is_displayed():
                        button.click()
                        time.sleep(1)
                        break
            except Exception:
                continue
    
    def extract_business_info(self) -> Optional[Dict[str, str]]:
        """Extract detailed information from a business page with improved selectors."""
        business_data: Dict[str, str] = {}

        try:
            # Name extraction with multiple fallbacks
            name_text = ""
            name_selectors = [
                'h1[data-attrid="title"]',
                'h1 span[class*="fontTitle"]',
                'h1 .DUwDvf',
                'h1',
            ]
            
            for selector in name_selectors:
                try:
                    name_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    name_text = name_element.text.strip()
                    if name_text:
                        break
                except NoSuchElementException:
                    continue
            
            if not name_text:
                # Last resort: use page title
                title = self.driver.title
                if title and ' - Google Maps' in title:
                    name_text = title.split(' - Google Maps', 1)[0].strip()
            
            business_data['name'] = name_text or 'Unknown'

            # Address extraction
            address_selectors = [
                '[data-item-id="address"] .fontBodyMedium',
                'button[data-item-id="address"] .fontBodyMedium',
                '[data-item-id="address"] span[class*="fontBody"]',
            ]
            
            full_address = ""
            for selector in address_selectors:
                try:
                    address_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    full_address = address_element.text.strip()
                    if full_address:
                        break
                except NoSuchElementException:
                    continue
            
            if full_address:
                business_data['full_address'] = full_address
                business_data.update(self.parse_address(full_address))
            else:
                business_data['full_address'] = 'N/A'
                business_data['street'] = 'N/A'
                business_data['postal_code'] = 'N/A'

            # Phone extraction
            phone_selectors = [
                '[data-item-id*="phone"] .fontBodyMedium',
                'button[data-item-id*="phone"] .fontBodyMedium',
                '[data-item-id*="phone"] span[class*="fontBody"]',
            ]
            
            phone_text = ""
            for selector in phone_selectors:
                try:
                    phone_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    phone_text = phone_element.text.strip()
                    if phone_text:
                        break
                except NoSuchElementException:
                    continue
            
            business_data['phone'] = phone_text or 'N/A'

            # Website extraction
            website_selectors = [
                '[data-item-id="authority"] .fontBodyMedium a',
                '[data-item-id="authority"] a',
                'a[data-value*="website"]',
            ]
            
            website_url = ""
            for selector in website_selectors:
                try:
                    website_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                    website_url = website_element.get_attribute('href') or ""
                    if website_url and 'google.com' not in website_url:
                        break
                except NoSuchElementException:
                    continue
            
            business_data['website'] = website_url or 'N/A'

            # Reviews and Rating - FIXED extraction
            rating = 'N/A'
            review_count = 'N/A'
            
            try:
                # Look for rating number
                rating_selectors = [
                    '.fontDisplayLarge',
                    'span[role="img"][aria-label*="star"]',
                    '.F7nice span:first-child',
                ]
                
                for selector in rating_selectors:
                    try:
                        rating_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                        rating_text = rating_element.text.strip()
                        
                        # Check if it's a valid rating (number with optional decimal)
                        if re.match(r'^\d+\.?\d*$', rating_text):
                            rating = rating_text
                            break
                        
                        # Try extracting from aria-label
                        aria_label = rating_element.get_attribute('aria-label') or ""
                        rating_match = re.search(r'(\d+\.?\d*)\s*star', aria_label.lower())
                        if rating_match:
                            rating = rating_match.group(1)
                            break
                            
                    except NoSuchElementException:
                        continue
                
                # Look for review count
                review_selectors = [
                    '.fontBodyMedium .fontBodySmall',
                    'button[aria-label*="review"] .fontBodySmall',
                    '.F7nice .fontBodySmall',
                ]
                
                for selector in review_selectors:
                    try:
                        review_element = self.driver.find_element(By.CSS_SELECTOR, selector)
                        review_text = review_element.text.strip()
                        
                        # Extract numbers from review text (handle commas)
                        review_match = re.search(r'(\d+(?:,\d+)*)', review_text)
                        if review_match:
                            review_count = review_match.group(1)
                            break
                            
                    except NoSuchElementException:
                        continue
                
            except Exception as e:
                print(f"Error extracting reviews: {e}")

            business_data['rating'] = rating
            business_data['review_count'] = review_count
            
            # Combine rating and reviews properly
            if rating != 'N/A' and review_count != 'N/A':
                business_data['reviews'] = f"{rating} stars ({review_count} reviews)"
            elif rating != 'N/A':
                business_data['reviews'] = f"{rating} stars"
            elif review_count != 'N/A':
                business_data['reviews'] = f"({review_count} reviews)"
            else:
                business_data['reviews'] = 'N/A'

            # Photos count
            try:
                photo_elements = self.driver.find_elements(By.CSS_SELECTOR, '[data-photo-index]')
                business_data['photo_count'] = len(photo_elements)
            except Exception:
                business_data['photo_count'] = 0

            # Location link
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
        ]
        
        areas = [
            "Washington DC",
            "Northern Virginia",
            "Maryland",
        ]
        
        for query in queries:
            for area in areas:
                try:
                    self.search_locations(query, area)
                    time.sleep(1.5 + random.random() * 0.5)  # Pause between searches
                except Exception as e:
                    print(f"Error searching {query} in {area}: {e}")
                    continue
        
        print(f"\nTotal businesses found: {len(self.results)}")
    
    def save_to_csv(self, filename: str = 'dmv_shooting_ranges_fixed.csv') -> None:
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
        self.driver.quit()

# Main execution
if __name__ == "__main__":
    # Start with a smaller test
    scraper = GoogleMapsScraper(headless=True, max_results_per_search=5)
    
    try:
        print("Starting Fixed DMV Shooting Ranges Scraper (Test)...")
        
        # Test with just one query and area first
        scraper.search_locations("shooting ranges", "Washington DC")
        
    except KeyboardInterrupt:
        print("\nScraping interrupted by user")
    except Exception as e:
        print(f"An error occurred: {e}")
    finally:
        try:
            scraper.save_to_csv('test_results.csv')
        except Exception as save_err:
            print(f"Failed to save CSV: {save_err}")
        scraper.close()
        print("Scraper finished")
