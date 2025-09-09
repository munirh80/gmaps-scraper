import re
from improved_scraper import GoogleMapsScraper


def make_scraper_without_driver():
    scraper = GoogleMapsScraper.__new__(GoogleMapsScraper)
    scraper._postal_re = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
    return scraper


def test_parse_address_truncates_zip_plus4():
    scraper = make_scraper_without_driver()
    address = "123 Main St, Washington, DC 20001-1234"
    parts = scraper.parse_address(address)
    assert parts["postal_code"] == "20001"
    assert parts["street"] == "123 Main St, Washington"
