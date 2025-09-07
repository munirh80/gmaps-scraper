#!/usr/bin/env python3
"""
Enhanced Google Maps Scraper Test Runner

This script demonstrates advanced practices including CLI argument parsing,
configuration file support, progress reporting, concurrent processing, and
comprehensive error handling with custom exceptions.
"""

import argparse
import asyncio
import concurrent.futures
import json
import logging
import signal
import sys
import time
import tracemalloc
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Optional, List, Dict, Any, Union
import yaml

from improved_scraper import GoogleMapsScraper


class ExitCode(Enum):
    """Exit codes for different scenarios."""
    SUCCESS = 0
    CONFIG_ERROR = 1
    NO_RESULTS = 2
    OUTPUT_ERROR = 3
    SAVE_ERROR = 4
    SCRAPING_ERROR = 5
    INTERRUPTED = 130


class ScrapingError(Exception):
    """Custom exception for scraping-related errors."""
    pass


class ConfigurationError(Exception):
    """Custom exception for configuration-related errors."""
    pass


@dataclass
class ScraperConfig:
    """Enhanced configuration class with comprehensive validation and serialization."""
    
    # Core scraping parameters
    headless: bool = True
    max_results_per_search: int = 10
    query: str = 'shooting ranges'
    location: str = 'Washington DC'
    
    # Output settings
    output_filename: str = 'gmaps_results.csv'
    output_format: str = 'csv'  # csv, json, excel
    include_timestamp: bool = True
    
    # Performance settings
    max_concurrent_searches: int = 1
    delay_between_searches: float = 2.0
    timeout_per_search: int = 300  # 5 minutes
    
    # Advanced options
    queries: List[str] = field(default_factory=lambda: ['shooting ranges'])
    locations: List[str] = field(default_factory=lambda: ['Washington DC'])
    custom_selectors: Dict[str, str] = field(default_factory=dict)
    
    # Retry settings
    max_retries: int = 3
    retry_delay: float = 5.0
    
    def __post_init__(self):
        """Post-initialization validation and setup."""
        if self.include_timestamp:
            timestamp = time.strftime('%Y%m%d_%H%M%S')
            base, ext = Path(self.output_filename).stem, Path(self.output_filename).suffix
            if not ext:
                ext = '.csv'
            self.output_filename = f"{base}_{timestamp}{ext}"
    
    def validate(self) -> List[str]:
        """
        Comprehensive validation of configuration parameters.
        
        Returns:
            List of validation error messages (empty if valid)
        """
        errors = []
        
        # Basic parameter validation
        if self.max_results_per_search <= 0:
            errors.append("max_results_per_search must be positive")
        
        if self.max_results_per_search > 100:
            errors.append("max_results_per_search should not exceed 100 for stability")
        
        if not self.query.strip() and not self.queries:
            errors.append("Either 'query' or 'queries' must be provided")
        
        if not self.location.strip() and not self.locations:
            errors.append("Either 'location' or 'locations' must be provided")
        
        if not self.output_filename.strip():
            errors.append("Output filename cannot be empty")
        
        # Format validation
        if self.output_format not in ['csv', 'json', 'excel']:
            errors.append("output_format must be one of: csv, json, excel")
        
        # Performance validation
        if self.max_concurrent_searches < 1:
            errors.append("max_concurrent_searches must be at least 1")
        
        if self.max_concurrent_searches > 5:
            errors.append("max_concurrent_searches should not exceed 5 to avoid rate limiting")
        
        if self.delay_between_searches < 0:
            errors.append("delay_between_searches cannot be negative")
        
        if self.timeout_per_search < 30:
            errors.append("timeout_per_search should be at least 30 seconds")
        
        # Retry validation
        if self.max_retries < 0:
            errors.append("max_retries cannot be negative")
        
        if self.retry_delay < 0:
            errors.append("retry_delay cannot be negative")
        
        return errors
    
    @classmethod
    def from_file(cls, config_path: Union[str, Path]) -> 'ScraperConfig':
        """Load configuration from JSON or YAML file."""
        config_path = Path(config_path)
        
        if not config_path.exists():
            raise ConfigurationError(f"Configuration file not found: {config_path}")
        
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                if config_path.suffix.lower() in ['.yaml', '.yml']:
                    data = yaml.safe_load(f)
                else:
                    data = json.load(f)
            
            return cls(**data)
        
        except (json.JSONDecodeError, yaml.YAMLError) as e:
            raise ConfigurationError(f"Invalid configuration file format: {e}")
        except TypeError as e:
            raise ConfigurationError(f"Invalid configuration parameters: {e}")
    
    def to_file(self, config_path: Union[str, Path]) -> None:
        """Save configuration to JSON or YAML file."""
        config_path = Path(config_path)
        
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                if config_path.suffix.lower() in ['.yaml', '.yml']:
                    yaml.dump(asdict(self), f, default_flow_style=False, indent=2)
                else:
                    json.dump(asdict(self), f, indent=2, ensure_ascii=False)
        
        except Exception as e:
            raise ConfigurationError(f"Failed to save configuration: {e}")


class ProgressReporter:
    """Progress reporting and metrics collection."""
    
    def __init__(self):
        self.start_time = time.time()
        self.searches_completed = 0
        self.total_searches = 0
        self.results_collected = 0
        self.errors_encountered = 0
        self.memory_usage = []
    
    def start_tracking(self, total_searches: int):
        """Initialize progress tracking."""
        self.total_searches = total_searches
        self.start_time = time.time()
        tracemalloc.start()
    
    def update_progress(self, results_count: int = 0, error: bool = False):
        """Update progress metrics."""
        self.searches_completed += 1
        self.results_collected += results_count
        if error:
            self.errors_encountered += 1
        
        # Track memory usage
        if tracemalloc.is_tracing():
            current, peak = tracemalloc.get_traced_memory()
            self.memory_usage.append(current / 1024 / 1024)  # MB
        
        # Report progress
        percent = (self.searches_completed / self.total_searches) * 100
        elapsed = time.time() - self.start_time
        eta = (elapsed / self.searches_completed) * (self.total_searches - self.searches_completed) if self.searches_completed > 0 else 0
        
        logging.info(f"Progress: {percent:.1f}% ({self.searches_completed}/{self.total_searches}) | "
                    f"Results: {self.results_collected} | Errors: {self.errors_encountered} | "
                    f"ETA: {eta:.1f}s")
    
    def get_summary(self) -> Dict[str, Any]:
        """Get comprehensive execution summary."""
        elapsed = time.time() - self.start_time
        avg_memory = sum(self.memory_usage) / len(self.memory_usage) if self.memory_usage else 0
        peak_memory = max(self.memory_usage) if self.memory_usage else 0
        
        return {
            'total_time': elapsed,
            'searches_completed': self.searches_completed,
            'total_searches': self.total_searches,
            'results_collected': self.results_collected,
            'errors_encountered': self.errors_encountered,
            'success_rate': (self.searches_completed - self.errors_encountered) / self.searches_completed if self.searches_completed > 0 else 0,
            'results_per_search': self.results_collected / self.searches_completed if self.searches_completed > 0 else 0,
            'average_memory_mb': avg_memory,
            'peak_memory_mb': peak_memory,
            'searches_per_second': self.searches_completed / elapsed if elapsed > 0 else 0
        }


def setup_logging(level: str = 'INFO', log_file: Optional[str] = None) -> None:
    """Configure comprehensive logging with optional file output."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # Create custom formatter
    formatter = logging.Formatter(
        '%(asctime)s | %(levelname)8s | %(name)s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Console handler with color support (if available)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler if specified
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Set specific logger levels
    logging.getLogger('selenium').setLevel(logging.WARNING)
    logging.getLogger('urllib3').setLevel(logging.WARNING)


@contextmanager
def scraper_session(config: ScraperConfig):
    """Enhanced context manager with timeout and error handling."""
    scraper = None
    start_time = time.time()
    
    try:
        logging.info("Initializing Google Maps scraper...")
        scraper = GoogleMapsScraper(
            headless=config.headless,
            max_results_per_search=config.max_results_per_search
        )
        
        elapsed = time.time() - start_time
        logging.info(f"Scraper initialized in {elapsed:.2f}s "
                    f"(headless={config.headless}, max_results={config.max_results_per_search})")
        
        yield scraper
    
    except Exception as e:
        logging.error(f"Failed to initialize scraper: {e}")
        raise ScrapingError(f"Scraper initialization failed: {e}")
    
    finally:
        if scraper:
            try:
                logging.info("Closing scraper...")
                scraper.close()
                elapsed = time.time() - start_time
                logging.info(f"Scraper session completed in {elapsed:.2f}s")
            except Exception as e:
                logging.warning(f"Error closing scraper: {e}")


async def perform_search_with_timeout(scraper: GoogleMapsScraper, query: str, location: str, timeout: int) -> tuple:
    """Perform search with timeout and return results count."""
    try:
        loop = asyncio.get_event_loop()
        initial_count = len(scraper.results)
        
        # Run search in thread pool to avoid blocking
        await loop.run_in_executor(
            None, 
            lambda: scraper.search_locations(query, location)
        )
        
        final_count = len(scraper.results)
        return final_count - initial_count, None
        
    except asyncio.TimeoutError:
        error_msg = f"Search timeout for '{query}' in '{location}'"
        logging.warning(error_msg)
        return 0, error_msg
    except Exception as e:
        error_msg = f"Search failed for '{query}' in '{location}': {e}"
        logging.error(error_msg)
        return 0, error_msg


def save_results_multiple_formats(scraper: GoogleMapsScraper, config: ScraperConfig) -> None:
    """Save results in multiple formats based on configuration."""
    if not scraper.results:
        logging.warning("No results to save")
        return
    
    base_path = Path(config.output_filename)
    base_name = base_path.stem
    
    try:
        if config.output_format == 'csv':
            scraper.save_to_csv(str(base_path))
        
        elif config.output_format == 'json':
            json_path = base_path.with_suffix('.json')
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(scraper.results, f, indent=2, ensure_ascii=False)
            logging.info(f"Results saved to {json_path}")
        
        elif config.output_format == 'excel':
            excel_path = base_path.with_suffix('.xlsx')
            import pandas as pd
            df = pd.DataFrame(scraper.results)
            df.to_excel(excel_path, index=False)
            logging.info(f"Results saved to {excel_path}")
        
        # Always save a summary JSON
        summary_path = base_path.parent / f"{base_name}_summary.json"
        summary_data = {
            'total_results': len(scraper.results),
            'unique_businesses': len(set((r.get('name', ''), r.get('full_address', '')) for r in scraper.results)),
            'search_queries': list(set(r.get('search_query', '') for r in scraper.results)),
            'search_locations': list(set(r.get('search_area', '') for r in scraper.results)),
            'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
        }
        
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2)
        
        logging.info(f"Summary saved to {summary_path}")
        
    except Exception as e:
        raise ScrapingError(f"Failed to save results: {e}")


async def run_enhanced_scraper(config: ScraperConfig) -> int:
    """
    Enhanced scraper execution with concurrent processing and comprehensive reporting.
    
    Args:
        config: ScraperConfig object with test parameters
        
    Returns:
        int: Exit code from ExitCode enum
    """
    # Validate configuration
    validation_errors = config.validate()
    if validation_errors:
        for error in validation_errors:
            logging.error(f"Configuration error: {error}")
        return ExitCode.CONFIG_ERROR.value
    
    # Setup progress reporting
    progress = ProgressReporter()
    
    # Prepare search combinations
    queries = config.queries if config.queries else [config.query]
    locations = config.locations if config.locations else [config.location]
    search_combinations = [(q, l) for q in queries for l in locations]
    
    progress.start_tracking(len(search_combinations))
    
    try:
        with scraper_session(config) as scraper:
            logging.info(f"Starting {len(search_combinations)} search combinations")
            
            # Process searches with controlled concurrency
            if config.max_concurrent_searches == 1:
                # Sequential processing
                for query, location in search_combinations:
                    try:
                        logging.info(f"Searching: '{query}' in '{location}'")
                        
                        result_count, error = await asyncio.wait_for(
                            perform_search_with_timeout(scraper, query, location, config.timeout_per_search),
                            timeout=config.timeout_per_search
                        )
                        
                        progress.update_progress(result_count, error is not None)
                        
                        if config.delay_between_searches > 0:
                            await asyncio.sleep(config.delay_between_searches)
                            
                    except asyncio.TimeoutError:
                        logging.error(f"Global timeout for '{query}' in '{location}'")
                        progress.update_progress(0, True)
                    except Exception as e:
                        logging.error(f"Unexpected error for '{query}' in '{location}': {e}")
                        progress.update_progress(0, True)
            
            else:
                # Concurrent processing with semaphore
                semaphore = asyncio.Semaphore(config.max_concurrent_searches)
                
                async def bounded_search(query, location):
                    async with semaphore:
                        try:
                            result_count, error = await asyncio.wait_for(
                                perform_search_with_timeout(scraper, query, location, config.timeout_per_search),
                                timeout=config.timeout_per_search
                            )
                            progress.update_progress(result_count, error is not None)
                            
                            if config.delay_between_searches > 0:
                                await asyncio.sleep(config.delay_between_searches)
                                
                        except Exception as e:
                            logging.error(f"Error in bounded search '{query}' in '{location}': {e}")
                            progress.update_progress(0, True)
                
                # Execute all searches concurrently
                await asyncio.gather(
                    *[bounded_search(q, l) for q, l in search_combinations],
                    return_exceptions=True
                )
            
            # Check results
            result_count = len(scraper.results)
            logging.info(f"Search completed. Collected {result_count} total entries")
            
            if result_count == 0:
                logging.warning("No results found for any search queries")
                return ExitCode.NO_RESULTS.value
            
            # Save results
            try:
                save_results_multiple_formats(scraper, config)
                
            except Exception as e:
                logging.error(f"Failed to save results: {e}")
                return ExitCode.SAVE_ERROR.value
    
    except KeyboardInterrupt:
        logging.info("Scraping interrupted by user")
        return ExitCode.INTERRUPTED.value
    
    except Exception as e:
        logging.error(f"Scraping failed: {e}", exc_info=True)
        return ExitCode.SCRAPING_ERROR.value
    
    finally:
        # Report final metrics
        summary = progress.get_summary()
        logging.info("=" * 60)
        logging.info("EXECUTION SUMMARY")
        logging.info("=" * 60)
        logging.info(f"Total execution time: {summary['total_time']:.2f} seconds")
        logging.info(f"Searches completed: {summary['searches_completed']}/{summary['total_searches']}")
        logging.info(f"Results collected: {summary['results_collected']}")
        logging.info(f"Success rate: {summary['success_rate']:.1%}")
        logging.info(f"Results per search: {summary['results_per_search']:.1f}")
        logging.info(f"Average memory usage: {summary['average_memory_mb']:.1f} MB")
        logging.info(f"Peak memory usage: {summary['peak_memory_mb']:.1f} MB")
        logging.info(f"Searches per second: {summary['searches_per_second']:.2f}")
        logging.info("=" * 60)
        
        if tracemalloc.is_tracing():
            tracemalloc.stop()
    
    logging.info("Scraping completed successfully")
    return ExitCode.SUCCESS.value


def create_sample_config(output_path: str = 'scraper_config.yaml') -> None:
    """Create a sample configuration file."""
    sample_config = ScraperConfig(
        headless=True,
        max_results_per_search=10,
        queries=['shooting ranges', 'gun clubs', 'firearms training'],
        locations=['Washington DC', 'Northern Virginia', 'Maryland'],
        output_format='csv',
        max_concurrent_searches=2,
        delay_between_searches=3.0,
        include_timestamp=True
    )
    
    sample_config.to_file(output_path)
    print(f"Sample configuration saved to {output_path}")


def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown."""
    def signal_handler(signum, frame):
        logging.info(f"Received signal {signum}, shutting down gracefully...")
        sys.exit(ExitCode.INTERRUPTED.value)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


def parse_arguments() -> argparse.Namespace:
    """Parse command line arguments with comprehensive options."""
    parser = argparse.ArgumentParser(
        description="Enhanced Google Maps Scraper with advanced features",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --query "shooting ranges" --location "Washington DC"
  %(prog)s --config config.yaml --output results.json --format json
  %(prog)s --queries "shooting ranges,gun clubs" --locations "DC,VA,MD" --concurrent 2
  %(prog)s --create-config sample.yaml
        """
    )
    
    # Configuration options
    config_group = parser.add_argument_group('Configuration')
    config_group.add_argument(
        '--config', '-c', type=str,
        help='Path to configuration file (JSON or YAML)'
    )
    config_group.add_argument(
        '--create-config', type=str, metavar='PATH',
        help='Create sample configuration file and exit'
    )
    
    # Search parameters
    search_group = parser.add_argument_group('Search Parameters')
    search_group.add_argument(
        '--query', '-q', type=str, default='shooting ranges',
        help='Search query (default: shooting ranges)'
    )
    search_group.add_argument(
        '--location', '-l', type=str, default='Washington DC',
        help='Search location (default: Washington DC)'
    )
    search_group.add_argument(
        '--queries', type=str,
        help='Comma-separated list of queries'
    )
    search_group.add_argument(
        '--locations', type=str,
        help='Comma-separated list of locations'
    )
    search_group.add_argument(
        '--max-results', type=int, default=10,
        help='Maximum results per search (default: 10)'
    )
    
    # Output options
    output_group = parser.add_argument_group('Output Options')
    output_group.add_argument(
        '--output', '-o', type=str, default='gmaps_results.csv',
        help='Output filename (default: gmaps_results.csv)'
    )
    output_group.add_argument(
        '--format', '-f', choices=['csv', 'json', 'excel'], default='csv',
        help='Output format (default: csv)'
    )
    output_group.add_argument(
        '--no-timestamp', action='store_true',
        help='Do not include timestamp in output filename'
    )
    
    # Performance options
    perf_group = parser.add_argument_group('Performance Options')
    perf_group.add_argument(
        '--concurrent', type=int, default=1,
        help='Number of concurrent searches (default: 1)'
    )
    perf_group.add_argument(
        '--delay', type=float, default=2.0,
        help='Delay between searches in seconds (default: 2.0)'
    )
    perf_group.add_argument(
        '--timeout', type=int, default=300,
        help='Timeout per search in seconds (default: 300)'
    )
    perf_group.add_argument(
        '--headless', action='store_true', default=True,
        help='Run browser in headless mode (default: True)'
    )
    perf_group.add_argument(
        '--no-headless', action='store_false', dest='headless',
        help='Run browser with GUI (for debugging)'
    )
    
    # Logging options
    log_group = parser.add_argument_group('Logging Options')
    log_group.add_argument(
        '--log-level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], default='INFO',
        help='Logging level (default: INFO)'
    )
    log_group.add_argument(
        '--log-file', type=str,
        help='Log to file in addition to console'
    )
    
    return parser.parse_args()


async def main() -> int:
    """Enhanced main entry point with argument parsing and async support."""
    # Setup signal handlers
    setup_signal_handlers()
    
    # Parse arguments
    args = parse_arguments()
    
    # Handle config creation
    if args.create_config:
        create_sample_config(args.create_config)
        return ExitCode.SUCCESS.value
    
    # Setup logging
    setup_logging(args.log_level, args.log_file)
    
    logger = logging.getLogger(__name__)
    logger.info("Starting Enhanced Google Maps Scraper")
    
    try:
        # Load configuration
        if args.config:
            logger.info(f"Loading configuration from {args.config}")
            config = ScraperConfig.from_file(args.config)
        else:
            # Build config from command line arguments
            config = ScraperConfig(
                headless=args.headless,
                max_results_per_search=args.max_results,
                query=args.query,
                location=args.location,
                output_filename=args.output,
                output_format=args.format,
                include_timestamp=not args.no_timestamp,
                max_concurrent_searches=args.concurrent,
                delay_between_searches=args.delay,
                timeout_per_search=args.timeout,
                queries=args.queries.split(',') if args.queries else [],
                locations=args.locations.split(',') if args.locations else []
            )
        
        # Log effective configuration
        logger.info("Effective configuration:")
        for key, value in asdict(config).items():
            if not key.startswith('_'):
                logger.info(f"  {key}: {value}")
        
        # Run the enhanced scraper
        exit_code = await run_enhanced_scraper(config)
        
        # Log final result
        if exit_code == ExitCode.SUCCESS.value:
            logger.info("Enhanced scraping completed successfully")
        else:
            logger.error(f"Enhanced scraping failed with exit code {exit_code}")
        
        return exit_code
        
    except ConfigurationError as e:
        logger.error(f"Configuration error: {e}")
        return ExitCode.CONFIG_ERROR.value
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=True)
        return ExitCode.SCRAPING_ERROR.value


if __name__ == '__main__':
    # Run async main function
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
