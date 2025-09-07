from improved_scraper import GoogleMapsScraper
from urllib.parse import quote_plus
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
import time

if __name__ == '__main__':
    s = GoogleMapsScraper(headless=True, max_results_per_search=1)
    q = quote_plus('shooting ranges in Washington DC')
    url = f"https://www.google.com/maps/search/?api=1&hl=en&query={q}"
    s.driver.get(url)
    s._dismiss_popups()
    WebDriverWait(s.driver, 15).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, 'div[role="feed"]'))
    )
    tiles = s._get_result_tiles()
    print('Tiles:', len(tiles))
    if tiles:
        t = tiles[0]
        try:
            s.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", t)
            time.sleep(0.5)
            try:
                t.click()
            except Exception:
                s.driver.execute_script("arguments[0].click();", t)
            WebDriverWait(s.driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'h1'))
            )
            time.sleep(1.5)
            data = s.extract_business_info() or {}
            print('Extracted:', data)
        except Exception as e:
            print('Click/extract error:', e)
    s.close()
    print('Done')

