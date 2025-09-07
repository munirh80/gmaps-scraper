from scraper import GoogleMapsScraper

if __name__ == '__main__':
    s = GoogleMapsScraper(headless=False, max_results_per_search=10)
    # Manually navigate to observe title/url before search_locations logic
    from urllib.parse import quote_plus
    q = quote_plus('shooting ranges in Virginia')
    url = f"https://www.google.com/maps/search/?api=1&hl=en&query={q}"
    # The initial load can sometimes hit a renderer timeout; ignore and continue
    try:
        s.driver.get(url)
    except Exception as e:
        print('Initial driver.get timeout or error, continuing:', e)
    print('Loaded URL:', s.driver.current_url)
    print('Title:', s.driver.title)
    # Now run search logic
    s.search_locations('shooting ranges', 'Virginia')
    # Debug: inspect common selectors counts
    sels = [
        '[data-result-index]',
        'div[role="article"]',
        'a[href^="/maps/place"]',
        'div[role="feed"]',
        'div[aria-label*="Results"]',
        'div[role="feed"] div[role="article"]',
        'div[role="feed"] a[aria-label]',
    ]
    from selenium.webdriver.common.by import By
    counts = {}
    for sel in sels:
        try:
            counts[sel] = len(s.driver.find_elements(By.CSS_SELECTOR, sel))
        except Exception as e:
            counts[sel] = f"error: {e}"
    print('Selector counts:', counts)
    # Show sample anchors
    try:
        anchors = s.driver.find_elements(By.CSS_SELECTOR, 'div[role="feed"] a[aria-label]')
        for a in anchors[:5]:
            try:
                print('Anchor:', a.get_attribute('aria-label'), a.get_attribute('href'))
            except Exception:
                pass
    except Exception:
        pass
    print(f"Collected {len(s.results)} entries")
    if s.results:
        s.save_to_csv('dmv_shooting_ranges_sample.csv')
    s.close()
