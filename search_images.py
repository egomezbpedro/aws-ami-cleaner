#!/usr/bin/env python3

import logging
import sys
from datetime import datetime, timezone
from lib.aws_client import AWSClient
from lib.ec2_image_manager import EC2ImageManager, OutputFormatter
from lib.deletion_queue import DeletionQueueManager, QueueSizeCalculator
from lib.cli_interface import CLIInterface, ConfigurationManager

# Configure logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    datefmt='%Y/%m/%d %I:%M:%S')
logger = logging.getLogger(__name__)


def main():
    """Main entry point for the EC2 Image Search and Deletion tool"""

    # Setup CLI interface
    cli = CLIInterface(
        "Search for EC2 images by keyword with optional batch deletion")
    cli.add_search_arguments()
    cli.add_age_arguments()
    cli.add_deletion_arguments()

    # Parse arguments
    args = cli.parse_args()

    # Setup logging
    cli.setup_logging(args.verbose)

    # Validate arguments
    if not ConfigurationManager.validate_arguments(args):
        sys.exit(1)

    # Safety check for deletion
    if hasattr(args, 'delete') and args.delete:
        age_filter = None if getattr(
            args, 'ignore_age', False) else getattr(args, 'older_than', '4w')
        if not cli.confirm_deletion(args.dry_run, args.confirm, age_filter, getattr(args, 'ignore_age', False)):
            sys.exit(0)

    try:
        # Initialize AWS client with credential validation
        aws_client = AWSClient(region=args.region, profile=args.profile)
        # Initialize EC2 image manager
        image_manager = EC2ImageManager(aws_client)

        # Search for images
        logger.info("Starting image search...")
        images = image_manager.search_images_by_keyword(
            keyword=args.keyword
        )
        if not images:
            logger.info("No images found matching the criteria.")
            sys.exit(1)

        # Apply age filtering in search mode if specified
        if not (hasattr(args, 'delete') and (args.delete or args.dry_run)):
            # Search mode - apply age filtering if specified
            original_count = len(images)

            if args.older_than_threshold or args.newer_than_threshold:
                filtered_images = []
                for image in images:
                    include_image = True

                    # Parse creation date
                    creation_date_str = image.get('CreationDate')
                    if creation_date_str and creation_date_str != 'N/A':
                        try:
                            if isinstance(creation_date_str, str):
                                creation_date_str_clean = creation_date_str.replace(
                                    'T', ' ').replace('Z', '').split('.')[0]
                                creation_date = datetime.strptime(
                                    creation_date_str_clean, '%Y-%m-%d %H:%M:%S')
                                # Make timezone-aware (AWS times are UTC)
                                creation_date = creation_date.replace(
                                    tzinfo=timezone.utc)
                            else:
                                creation_date = creation_date_str

                            # Add age information
                            age_days = (datetime.now(
                                timezone.utc) - creation_date).days
                            image['Age'] = f"{age_days}d"

                            # Apply filters
                            if args.older_than_threshold and creation_date >= args.older_than_threshold:
                                include_image = False

                            if args.newer_than_threshold and creation_date <= args.newer_than_threshold:
                                include_image = False

                        except Exception as e:
                            logger.warning(
                                f"Could not parse creation date '{creation_date_str}' for image {image.get('ImageId', 'unknown')}: {e}")
                            image['Age'] = 'Unknown'
                    else:
                        image['Age'] = 'Unknown'

                    if include_image:
                        filtered_images.append(image)

                images = filtered_images

                if original_count != len(images):
                    logger.info(
                        f"🔍 Filtered {original_count} images to {len(images)} based on age criteria")
                    if args.older_than:
                        logger.info(
                            f"   Showing only images older than {args.older_than}")
                    if args.newer_than:
                        logger.info(
                            f"   Showing only images newer than {args.newer_than}")

            # Check if any images remain after filtering
            if not images:
                logger.info("No images found matching the age criteria.")
                sys.exit(1)

            OutputFormatter.output_results(images, args.format)
        else:
            # Show table format when deleting for better visibility
            OutputFormatter.output_results(images, 'table')

        # Handle deletion if requested
        if hasattr(args, 'delete') and (args.delete or args.dry_run):
            # Apply age filtering if specified and not ignored
            if hasattr(args, 'age_threshold') and args.age_threshold and not getattr(args, 'ignore_age', False):
                images_to_delete, images_too_young = EC2ImageManager.filter_images_by_age(
                    images, args.age_threshold)

                if images_too_young:
                    logger.info(
                        f"\n⏳ Found {len(images_too_young)} images that are too young to delete:")
                    OutputFormatter.output_results(images_too_young, 'table')

                if not images_to_delete:
                    logger.info(
                        f"\n✅ No images found that are older than {args.older_than}. All images are too young for deletion.")
                    sys.exit(0)

                logger.info(
                    f"\n🗑️  Found {len(images_to_delete)} images eligible for deletion (older than {args.older_than}):")
                OutputFormatter.output_results(images_to_delete, 'table')

                # Use the filtered list for deletion
                images = images_to_delete
            elif getattr(args, 'ignore_age', False):
                logger.info(
                    f"\n🚨 WARNING: Age restrictions are DISABLED. All {len(images)} found images will be processed for deletion!")
                # Add age information for display purposes but don't filter
                EC2ImageManager.filter_images_by_age(images, None)
                OutputFormatter.output_results(images, 'table')

            # Calculate optimal queue size
            queue_size = QueueSizeCalculator.calculate_queue_size(
                total_items=len(images),
                custom_size=args.queue_size
            )

            # Print configuration
            ConfigurationManager.print_deletion_config(
                total_items=len(images),
                queue_size=queue_size,
                dry_run=args.dry_run
            )

            # Initialize and run deletion queue
            deletion_manager = DeletionQueueManager(
                image_manager=image_manager,
                queue_size=queue_size
            )

            deletion_manager.add_images_to_queue(images)
            results = deletion_manager.process_deletions(dry_run=args.dry_run)

            # Print summary
            deletion_manager.print_summary()

    except KeyboardInterrupt:
        cli.handle_keyboard_interrupt()
    except Exception as e:
        cli.handle_error(e)


if __name__ == '__main__':
    main()