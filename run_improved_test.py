from improved_scraper import GoogleMapsScraper

if __name__ == '__main__':
    s = GoogleMapsScraper(headless=True, max_results_per_search=5)
    try:
        s.search_locations('shooting ranges', 'Washington DC')
    except Exception as e:
        print('Search error:', e)
    print(f'Collected {len(s.results)} entries')
    if s.results:
        s.save_to_csv('dmv_shooting_ranges_improved_sample.csv')
    s.close()
    print('Done')

