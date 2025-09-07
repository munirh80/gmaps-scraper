#!/usr/bin/env python3
"""
Improved Google Maps Scraper Test Runner

This script demonstrates best practices for using the GoogleMapsScraper class,
including proper resource management, error handling, logging, and configuration.
"""

import logging
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import pandas as pd  # type: ignore[import-untyped]

from improved_scraper import GoogleMapsScraper


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('scraper_test.log')
    ]
)
logger = logging.getLogger(__name__)


class ScraperConfig:
    """Configuration class for scraper parameters."""
    
    def __init__(
        self,
        headless: bool = True,
        max_results_per_search: int = 5,
        query: str = 'shooting ranges',
        location: str = 'Washington DC',
        output_filename: str = 'dmv_shooting_ranges_improved_sample.csv'
    ):
        self.headless = headless
        self.max_results_per_search = max_results_per_search
        self.query = query
        self.location = location
        self.output_filename = output_filename
    
    def validate(self) -> bool:
        """Validate configuration parameters."""
        if self.max_results_per_search <= 0:
            logger.error("max_results_per_search must be positive")
            return False
        
        if not self.query or not self.query.strip():
            logger.error("Query cannot be empty")
            return False
        
        if not self.location or not self.location.strip():
            logger.error("Location cannot be empty")
            return False
        
        if not self.output_filename or not self.output_filename.strip():
            logger.error("Output filename cannot be empty")
            return False
        
        return True


@contextmanager
def scraper_session(config: ScraperConfig):
    """Context manager for GoogleMapsScraper to ensure proper resource cleanup."""
    scraper = None
    try:
        logger.info("Initializing Google Maps scraper...")
        scraper = GoogleMapsScraper(
            headless=config.headless,
            max_results_per_search=config.max_results_per_search
        )
        logger.info(f"Scraper initialized (headless={config.headless}, max_results={config.max_results_per_search})")
        yield scraper
    
    except Exception as e:
        logger.error(f"Failed to initialize scraper: {e}")
        raise
    
    finally:
        if scraper:
            try:
                logger.info("Closing scraper...")
                scraper.close()
                logger.info("Scraper closed successfully")
            except Exception as e:
                logger.warning(f"Error closing scraper: {e}")


def run_scraper_test(config: ScraperConfig) -> int:
    """
    Run the scraper test with the given configuration.
    
    Args:
        config: ScraperConfig object with test parameters
        
    Returns:
        int: Exit code (0 for success, non-zero for failure)
    """
    if not config.validate():
        return 1
    
    start_time = time.time()
    
    try:
        with scraper_session(config) as scraper:
            logger.info(f"Starting search: '{config.query}' in '{config.location}'")
            
            # Perform the search
            scraper.search_locations(config.query, config.location)
            
            # Check results
            result_count = len(scraper.results)
            logger.info(f"Search completed. Collected {result_count} entries")
            
            if result_count == 0:
                logger.warning("No results found for the search query")
                return 2  # Special exit code for no results
            
            # Save results if any were found
            try:
                output_path = Path(config.output_filename)
                scraper.save_to_csv(str(output_path))
                
                if output_path.exists():
                    file_size = output_path.stat().st_size
                    logger.info(f"Results saved to '{output_path}' ({file_size} bytes)")

                    # Validate CSV contents
                    try:
                        df = pd.read_csv(output_path)
                        expected_headers = [
                            'name', 'website', 'phone', 'full_address', 'street',
                            'postal_code', 'reviews', 'rating', 'review_count',
                            'photo_count', 'location_link', 'search_query',
                            'search_area'
                        ]
                        missing = [h for h in expected_headers if h not in df.columns]
                        if missing or df.empty:
                            logger.error(
                                "CSV validation failed: missing headers %s or no data rows",
                                missing
                            )
                            return 6
                    except Exception as e:
                        logger.error(f"Failed to validate CSV: {e}")
                        return 6
                else:
                    logger.warning(f"Output file '{output_path}' was not created")
                    return 3
                    
            except Exception as e:
                logger.error(f"Failed to save results: {e}")
                return 4
    
    except KeyboardInterrupt:
        logger.info("Scraping interrupted by user")
        return 130  # Standard exit code for SIGINT
    
    except Exception as e:
        logger.error(f"Scraping failed: {e}", exc_info=True)
        return 5
    
    finally:
        elapsed_time = time.time() - start_time
        logger.info(f"Total execution time: {elapsed_time:.2f} seconds")
    
    logger.info("Scraping completed successfully")
    return 0


def main() -> int:
    """Main entry point for the script."""
    logger.info("Starting Google Maps Scraper Test")
    
    # Create configuration (could be extended to read from config file or CLI args)
    config = ScraperConfig(
        headless=True,
        max_results_per_search=5,
        query='shooting ranges',
        location='Washington DC',
        output_filename='dmv_shooting_ranges_improved_sample.csv'
    )
    
    # Log configuration
    logger.info(f"Configuration: query='{config.query}', location='{config.location}', "
                f"max_results={config.max_results_per_search}, headless={config.headless}")
    
    # Run the test
    exit_code = run_scraper_test(config)
    
    # Log final result
    if exit_code == 0:
        logger.info("Test completed successfully")
    else:
        logger.error(f"Test failed with exit code {exit_code}")
    
    return exit_code


if __name__ == '__main__':
    sys.exit(main())
