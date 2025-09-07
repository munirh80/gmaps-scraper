import time
import random
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.common.exceptions import TimeoutException, NoSuchElementException

def setup_driver():
    """Setup Chrome driver with anti-detection measures"""
    options = webdriver.ChromeOptions()
    # Don't run headless for debugging
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--window-size=1366,768')
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)
    options.add_argument('--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def test_basic_search():
    """Test basic Google Maps search functionality"""
    driver = setup_driver()
    
    try:
        print("1. Opening Google Maps...")
        driver.get("https://www.google.com/maps/search/shooting+ranges+in+Washington+DC")
        time.sleep(3)
        
        print("2. Looking for search results...")
        # Try different selectors to find results
        selectors_to_try = [
            'div[role="feed"] a',
            '[data-result-index]',
            'div[role="article"]',
            'a[href*="/maps/place/"]',
            '.hfpxzc'  # Common class for map result items
        ]
        
        found_results = False
        for selector in selectors_to_try:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                if elements:
                    print(f"   ✓ Found {len(elements)} elements with selector: {selector}")
                    found_results = True
                else:
                    print(f"   ✗ No elements found with selector: {selector}")
            except Exception as e:
                print(f"   ✗ Error with selector {selector}: {e}")
        
        if not found_results:
            print("3. No results found - checking page source...")
            # Save page source for inspection
            with open('debug_page_source.html', 'w', encoding='utf-8') as f:
                f.write(driver.page_source)
            print("   Page source saved to debug_page_source.html")
        
        print("4. Looking for specific elements...")
        
        # Check for common Google Maps elements
        elements_to_check = [
            ('Search input', 'input#searchboxinput'),
            ('Results panel', 'div[role="main"]'),
            ('Feed container', 'div[role="feed"]'),
            ('Any links', 'a'),
            ('Any buttons', 'button')
        ]
        
        for name, selector in elements_to_check:
            try:
                elements = driver.find_elements(By.CSS_SELECTOR, selector)
                print(f"   {name}: {len(elements)} found")
            except Exception as e:
                print(f"   {name}: Error - {e}")
        
        # Try to click on first result if found
        try:
            first_result = driver.find_element(By.CSS_SELECTOR, 'div[role="feed"] a')
            print("5. Trying to click first result...")
            driver.execute_script("arguments[0].scrollIntoView();", first_result)
            time.sleep(1)
            first_result.click()
            time.sleep(3)
            
            print("6. Testing data extraction...")
            test_data_extraction(driver)
            
        except Exception as e:
            print(f"5. Could not click first result: {e}")
    
    finally:
        input("Press Enter to close browser...")
        driver.quit()

def test_data_extraction(driver):
    """Test extracting business information"""
    data = {}
    
    # Test name extraction
    try:
        name_selectors = [
            'h1',
            'h1 .DUwDvf',
            '[data-attrid="title"]'
        ]
        for selector in name_selectors:
            try:
                name_elem = driver.find_element(By.CSS_SELECTOR, selector)
                if name_elem.text.strip():
                    data['name'] = name_elem.text.strip()
                    print(f"   ✓ Name found with {selector}: {data['name']}")
                    break
            except NoSuchElementException:
                continue
    except Exception as e:
        print(f"   ✗ Name extraction error: {e}")
    
    # Test address extraction
    try:
        address_selectors = [
            '[data-item-id="address"] .fontBodyMedium',
            'button[data-item-id="address"]',
            '[data-value="Address"]'
        ]
        for selector in address_selectors:
            try:
                addr_elem = driver.find_element(By.CSS_SELECTOR, selector)
                if addr_elem.text.strip():
                    data['address'] = addr_elem.text.strip()
                    print(f"   ✓ Address found with {selector}: {data['address']}")
                    break
            except NoSuchElementException:
                continue
    except Exception as e:
        print(f"   ✗ Address extraction error: {e}")
    
    # Test rating extraction
    try:
        rating_selectors = [
            '.fontDisplayLarge',
            '[data-value="Rating"]',
            '.F7nice span'
        ]
        for selector in rating_selectors:
            try:
                rating_elem = driver.find_element(By.CSS_SELECTOR, selector)
                if rating_elem.text.strip():
                    data['rating'] = rating_elem.text.strip()
                    print(f"   ✓ Rating found with {selector}: {data['rating']}")
                    break
            except NoSuchElementException:
                continue
    except Exception as e:
        print(f"   ✗ Rating extraction error: {e}")
    
    # Print all found data
    print("   Extracted data:", data)

if __name__ == "__main__":
    test_basic_search()
