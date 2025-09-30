#!/usr/bin/env python3

"""Module providing deletion queue capabilities"""

import logging
import time
from typing import List, Dict, Any
from queue import Queue
from concurrent.futures import ThreadPoolExecutor
from .ec2_image_manager import EC2ImageManager

logger = logging.getLogger(__name__)


class DeletionQueueManager:
    """
    Manages concurrent deletion of AWS resources using a queue-based system.
    This class can be adapted for deleting different types of AWS resources.
    """

    def __init__(self, image_manager: EC2ImageManager, queue_size: int):
        """
        Initialize the deletion queue manager

        Args:
            image_manager: EC2ImageManager instance for performing deletions
            queue_size: Maximum number of concurrent deletions
        """
        self.image_manager = image_manager
        self.queue_size = queue_size
        self.deletion_queue = Queue()
        self.results = []
        self.completed = 0
        self.total = 0

    def add_images_to_queue(self, images: List[Dict[str, Any]]):
        """Add images to the deletion queue"""
        self.total = len(images)
        for image in images:
            self.deletion_queue.put(image)
        logger.info("Added %i images to deletion queue", {self.total})

    def process_deletions(self, dry_run: bool = False) -> List[Dict[str, Any]]:
        """Process deletions using the queue system"""
        if self.total == 0:
            logger.warning("No images to delete")
            return []

        logger.info("Starting deletion process with queue size: %d", self.queue_size)
        logger.info("Total images to process: %d", self.total)

        with ThreadPoolExecutor(max_workers=self.queue_size) as executor:
            futures = []

            # Start initial batch of deletions
            for _ in range(min(self.queue_size, self.total)):
                if not self.deletion_queue.empty():
                    image = self.deletion_queue.get()
                    future = executor.submit(
                        self.image_manager.delete_image_and_snapshots,
                        image['ImageId'],
                        dry_run
                    )
                    futures.append((future, image))

            # Process completions and start new deletions
            while futures:
                completed_futures = []
                for future, image in futures:
                    if future.done():
                        try:
                            result = future.result()
                            result['image_info'] = image
                            self.results.append(result)
                            self.completed += 1
                            completed_futures.append((future, image))

                            logger.info("Progress: %d/%d completed", self.completed, self.total)

                            # Start next deletion if queue not empty
                            if not self.deletion_queue.empty():
                                next_image = self.deletion_queue.get()
                                next_future = executor.submit(
                                    self.image_manager.delete_image_and_snapshots,
                                    next_image['ImageId'],
                                    dry_run
                                )
                                futures.append((next_future, next_image))

                        except Exception as e:
                            logger.error("Error processing deletion: %s", e)
                            self.completed += 1

                # Remove completed futures
                for completed in completed_futures:
                    futures.remove(completed)

                # Small delay to prevent busy waiting
                if futures:
                    time.sleep(0.1)

        logger.info("Deletion process completed. %d/%d processed", self.completed, self.total)
        return self.results

    def print_summary(self):
        """Print summary of deletion results"""
        if not self.results:
            logger.info("No deletion results to display")
            return

        successful = sum(1 for r in self.results if r['success'])
        failed = len(self.results) - successful
        total_snapshots = sum(len(r['snapshots_deleted']) for r in self.results)

        logger.info(f"\nDeletion Summary:")
        logger.info(f"Total images processed: {len(self.results)}")
        logger.info(f"Successfully deleted: {successful}")
        logger.info(f"Failed deletions: {failed}")
        logger.info(f"Total snapshots deleted: {total_snapshots}")

        if failed > 0:
            logger.info(f"\nFailed deletions:")
            for result in self.results:
                if not result['success']:
                    logger.info(f"  - {result['image_id']}: {result.get('error', 'Unknown error')}")

        if any(r['snapshots_failed'] for r in self.results):
            logger.info(f"\nFailed snapshot deletions:")
            for result in self.results:
                if result['snapshots_failed']:
                    for snap_id in result['snapshots_failed']:
                        logger.info(f"  - Snapshot {snap_id} for AMI {result['image_id']}")


class QueueSizeCalculator:
    """
    Utility class for calculating optimal queue sizes.
    This can be reused across different queue-based operations.
    """

    @staticmethod
    def calculate_queue_size(total_items: int, custom_size: int = None,
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

        calculated_size = max(min_size, min(max_size, int(total_items * fraction)))
        return calculated_size