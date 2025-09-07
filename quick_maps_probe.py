from improved_scraper import GoogleMapsScraper
from urllib.parse import quote_plus
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

if __name__ == '__main__':
    s = GoogleMapsScraper(headless=True, max_results_per_search=1)
    q = quote_plus('shooting ranges in Washington DC')
    url = f"https://www.google.com/maps/search/?api=1&hl=en&query={q}"
    s.driver.get(url)
    # Try quick popup dismiss and tile count within ~20s
    s._dismiss_popups()
    try:
        WebDriverWait(s.driver, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div[role="feed"]'))
        )
    except Exception:
        pass
    tiles = s._get_result_tiles()
    print('Tiles found:', len(tiles))
    # Print first few aria-labels
    for t in tiles[:3]:
        try:
            print('Tile:', t.get_attribute('aria-label') or t.text[:80])
        except Exception:
            pass
    s.close()
    print('Done')

