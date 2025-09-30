#!/usr/bin/env python3

"""Module providing cli argument parsing"""

import argparse
import logging
import sys
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class CLIInterface:
    """
    Command-line interface handler for AWS tools.
    This class can be reused across different AWS CLI tools.
    """

    def __init__(self, description: str = "AWS CLI Tool"):
        """
        Initialize CLI interface

        Args:
            description: Description for the argument parser
        """
        self.parser = argparse.ArgumentParser(description=description)
        self._setup_base_arguments()

    def _setup_base_arguments(self):
        """Setup common arguments that most AWS tools need"""
        self.parser.add_argument(
            '--region', '-r', required=True, help='AWS region to operate in')
        self.parser.add_argument('--profile', '-p',
                                 help='AWS profile to use for authentication')
        self.parser.add_argument('--verbose', '-v', action='store_true',
                                 help='Enable verbose logging')

    def add_search_arguments(self):
        """Add arguments specific to image search functionality"""
        self.parser.add_argument('keyword', nargs='?',
                                 help='Keyword to search for in image names and descriptions')
        self.parser.add_argument('--keyword', '-k', dest='keyword_flag',
                                 help='Alternative way to specify keyword (useful for keywords starting with -)')
        self.parser.add_argument('--format', choices=['table', 'json', 'csv'], default='json',
                                 help='Output format (default: json)')

    def add_age_arguments(self):
        """Add age filtering arguments (available for both search and deletion)"""
        self.parser.add_argument('--older-than', type=str,
                                 help='Filter images older than specified time. Format: XyXqXmXwXdXhXmin (e.g., 1y, 2q, 3m, 4w, 30d, 12h, 30min, 1w2d12h)')
        self.parser.add_argument('--newer-than', type=str,
                                 help='Filter images newer than specified time. Format: XyXqXmXwXdXhXmin (e.g., 1y, 2q, 3m, 4w, 30d, 12h, 30min, 1w2d12h)')

    def add_deletion_arguments(self):
        """Add arguments specific to deletion functionality"""
        self.parser.add_argument('--delete', '-d', action='store_true',
                                 help='Delete found resources')
        self.parser.add_argument('--dry-run', action='store_true',
                                 help='Show what would be deleted without actually deleting')
        self.parser.add_argument('--ignore-age', action='store_true',
                                 help='Ignore age restrictions and delete all found images (DANGEROUS)')
        self.parser.add_argument('--queue-size', type=int,
                                 help='Maximum concurrent deletions (default: 1/3 of found resources)')
        self.parser.add_argument('--confirm', action='store_true',
                                 help='Skip confirmation prompt for deletions')

    def parse_args(self):
        """Parse command line arguments with input validation"""
        args = self.parser.parse_args()

        # Handle keyword argument resolution and validation
        if hasattr(args, 'keyword') and hasattr(args, 'keyword_flag'):
            args.keyword = self._resolve_keyword(
                args.keyword, args.keyword_flag)

        # Validate and sanitize inputs
        self._validate_inputs(args)

        # Parse and validate age thresholds
        if hasattr(args, 'older_than') and args.older_than:
            args.older_than_threshold = self._parse_age_threshold(
                args.older_than)
        else:
            args.older_than_threshold = None

        if hasattr(args, 'newer_than') and args.newer_than:
            args.newer_than_threshold = self._parse_age_threshold(
                args.newer_than)
        else:
            args.newer_than_threshold = None

        # For deletion compatibility, set age_threshold to older_than_threshold if in deletion mode
        if hasattr(args, 'ignore_age') and getattr(args, 'ignore_age', False):
            args.age_threshold = None
        elif args.older_than_threshold:
            args.age_threshold = args.older_than_threshold
        else:
            args.age_threshold = None

        return args

    def _resolve_keyword(self, positional_keyword: Optional[str], flag_keyword: Optional[str]) -> str:
        """
        Resolve keyword from positional or flag argument

        Args:
            positional_keyword: Keyword from positional argument
            flag_keyword: Keyword from --keyword flag

        Returns:
            Resolved keyword string

        Raises:
            SystemExit: If no keyword is provided or both are provided
        """
        if positional_keyword and flag_keyword:
            logger.info(
                "Error: Cannot specify keyword both as positional argument and --keyword flag")
            logger.info("Use either: 'keyword' or '--keyword keyword'")
            sys.exit(1)

        if not positional_keyword and not flag_keyword:
            logger.info("Error: Keyword is required")
            logger.info("Usage: search_images.py keyword --region REGION")
            logger.info(
                "   or: search_images.py --keyword keyword --region REGION")
            logger.info(
                "\nFor keywords starting with '-', use: --keyword '-BETA-'")
            sys.exit(1)

        return positional_keyword or flag_keyword

    def _validate_inputs(self, args):
        """
        Validate and sanitize input arguments

        Args:
            args: Parsed arguments
        """
        # Validate keyword
        if hasattr(args, 'keyword') and args.keyword:
            args.keyword = self._sanitize_keyword(args.keyword)

        # Validate region format
        if hasattr(args, 'region') and args.region:
            if not self._is_valid_aws_region(args.region):
                logger.warning(
                    "Region %s may not be a valid AWS region format", {args.region})

    @staticmethod
    def _sanitize_keyword(keyword: str) -> str:
        """
        Sanitize keyword input for safe AWS API usage

        Args:
            keyword: Raw keyword input

        Returns:
            Sanitized keyword safe for AWS API calls
        """
        # Remove any null bytes or control characters that could cause issues
        sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', keyword)

        # Trim whitespace
        sanitized = sanitized.strip()

        # Ensure keyword is not empty after sanitization
        if not sanitized:
            logger.info("Error: Keyword cannot be empty after sanitization")
            sys.exit(1)

        # Log if sanitization occurred
        if sanitized != keyword:
            logger.info("Keyword sanitized: %s -> %s", {keyword}, {sanitized})

        return sanitized

    @staticmethod
    def _is_valid_aws_region(region: str) -> bool:
        """
        Check if region string looks like a valid AWS region

        Args:
            region: Region string to validate

        Returns:
            True if region format looks valid
        """
        # AWS regions follow pattern: us-east-1, eu-west-2, ap-southeast-1, etc.
        region_pattern = r'^[a-z]{2,3}-[a-z]+-\d+$'
        return bool(re.match(region_pattern, region))

    @staticmethod
    def _escape_for_aws_filter(value: str) -> str:
        """
        Escape special characters for AWS filter values

        Args:
            value: String to escape

        Returns:
            Escaped string safe for AWS filters
        """
        # AWS filters support wildcards (* and ?) but other chars should be literal
        # No escaping needed for our use case, but method available for future use
        return value

    def _parse_age_threshold(self, age_str: str) -> datetime:
        """
        Parse age threshold string into a datetime object
        Args:
            age_str: Age string (e.g., "4w", "30d", "1w2d", "2h30m")
        Returns:
            datetime object representing the threshold (older than this)
        Raises:
            SystemExit: If age format is invalid
        """
        try:
            # Parse different time units
            total_seconds = 0
            # Pattern to match time components
            patterns = {
                'y': r'(\d+)y',  # year
                'q': r'(\d+)q',  # quarter
                'm': r'(\d+)m',  # month
                'w': r'(\d+)w',  # weeks
                'd': r'(\d+)d',  # days
                'h': r'(\d+)h',  # hours
                'min': r'(\d+)min',  # minutes
            }
            multipliers = {
                'y': 365 * 24 * 3600,  # years to seconds
                'q': 90 * 24 * 3600,   # quarters to seconds
                'm': 30 * 24 * 3600,   # months to seconds
                'w': 7 * 24 * 3600,    # weeks to seconds
                'd': 24 * 3600,        # days to seconds
                'h': 3600,             # hours to seconds
                'min': 60,             # minutes to seconds
            }
            age_str = age_str.lower().strip()
            found_match = False
            for unit, pattern in patterns.items():
                matches = re.findall(pattern, age_str)
                if matches:
                    found_match = True
                    for match in matches:
                        total_seconds += int(match) * multipliers[unit]
            if not found_match:
                raise ValueError("No valid time units found")
            if total_seconds <= 0:
                raise ValueError("Age threshold must be greater than 0")
            # Calculate the threshold datetime
            threshold = datetime.now(timezone.utc) - \
                timedelta(seconds=total_seconds)
            logger.info(
                f"Age threshold set to {age_str} (before {threshold.strftime('%Y-%m-%d %H:%M:%S')} UTC)")

            return threshold

        except Exception as e:
            logger.info("Error: Invalid age format %s", {age_str})
            raise ValueError(e) from e

    @staticmethod
    def setup_logging(verbose: bool = False):
        """Setup logging configuration"""
        level = logging.DEBUG if verbose else logging.INFO
        logging.getLogger().setLevel(level)

    @staticmethod
    def confirm_deletion(dry_run: bool = False, confirm: bool = False, age_filter: str = None, ignore_age: bool = False) -> bool:
        """
        Handle deletion confirmation logic

        Args:
            dry_run: Whether this is a dry run
            confirm: Whether to skip confirmation
            age_filter: Age filter string (e.g., "4w")
            ignore_age: Whether age restrictions are ignored

        Returns:
            True if deletion should proceed, False otherwise
        """
        if dry_run or confirm:
            return True

        logger.info(
            "⚠️  WARNING: This will permanently delete AMIs and their snapshots!")

        if ignore_age:
            logger.info(
                "🚨 DANGER: Age restrictions are DISABLED - ALL found images will be deleted regardless of age!")
            sys.exit(1)
        elif age_filter:
            logger.info(
                f"🛡️  Safety: Only deleting images older than {age_filter}")

        logger.info("Use --dry-run to see what would be deleted first.")
        response = input("Are you sure you want to continue? (yes/no): ")

        if response.lower() not in ['yes', 'y']:
            logger.info("Deletion cancelled.")
            return False

        return True

    @staticmethod
    def handle_keyboard_interrupt():
        """Handle Ctrl+C gracefully"""
        logger.info("Operation interrupted by user")
        sys.exit(1)

    @staticmethod
    def handle_error(error: Exception):
        """Handle general errors"""
        logger.error("An error occurred: %s", {error})
        sys.exit(1)


class ConfigurationManager:
    """
    Manages configuration and validation for AWS operations.
    This class can be reused across different AWS tools.
    """

    @staticmethod
    def calculate_queue_size(total_items: int, custom_size: Optional[int] = None,
                             fraction: float = 1/3, min_size: int = 1, max_size: int = 10) -> int:
        """
        Calculate optimal queue size based on total items

        Args:
            total_items: Total number of items to process
            custom_size: Custom queue size (overrides calculation if provided)
            fraction: Fraction of total items to use as queue size
            min_size: Minimum queue size
            max_size: Maximum queue size

        Returns:
            Calculated queue size
        """
        if custom_size:
            return max(min_size, custom_size)

        calculated_size = max(min_size, min(
            max_size, int(total_items * fraction)))
        return calculated_size

    @staticmethod
    def print_deletion_config(total_items: int, queue_size: int, dry_run: bool = False):
        """Print deletion configuration summary"""
        logger.info(
            f"\n{'DRY RUN - ' if dry_run else ''}Deletion Configuration:")
        logger.info(f"Queue size (concurrent deletions): {queue_size}")

        if dry_run:
            logger.info(
                "This is a dry run - no actual deletions will be performed.")

        logger.info("\nProcessing deletions...")

    @staticmethod
    def validate_arguments(args) -> bool:
        """
        Validate command line arguments

        Args:
            args: Parsed arguments from argparse

        Returns:
            True if arguments are valid, False otherwise
        """
        # Add any cross-argument validation logic here
        if hasattr(args, 'delete') and hasattr(args, 'dry_run'):
            if args.delete and args.dry_run:
                logger.warning(
                    "Both --delete and --dry-run specified. Using dry-run mode.")

        return True
