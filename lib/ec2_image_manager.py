#!/usr/bin/env python3

"""Module providing ami search, deletion capabilities"""

import logging
import json
import csv
import sys
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from .aws_client import AWSClient

logger = logging.getLogger(__name__)


class EC2ImageManager:
    """
    EC2 Image management operations including search and deletion.
    This class can be reused across different EC2 image tools.
    """

    def __init__(self, aws_client: AWSClient):
        """
        Initialize EC2 Image Manager

        Args:
            aws_client: Configured AWSClient instance
        """
        self.aws_client = aws_client
        self.ec2 = aws_client.get_ec2_client()

    def search_images_by_keyword(self, keyword: str) -> List[Dict[str, Any]]:
        """
        Search for EC2 images that match the given keyword in their name or description

        Args:
            keyword: The keyword to search for in image names and descriptions
        Returns:
            List of matching images with their details
        """
        all_images = []
        logger.info(
            f"Searching for images matching keyword: '{keyword}' in region: {self.aws_client.region}")

        try:
            # Search by name pattern
            name_filters = [
                {'Name': 'name', 'Values': [f'*{keyword}*']},
                {'Name': 'state', 'Values': ['available']}
            ]

            # Search by description pattern
            desc_filters = [
                {'Name': 'description', 'Values': [f'*{keyword}*']},
                {'Name': 'state', 'Values': ['available']}
            ]

            # Search in both name and description
            for filters in [name_filters, desc_filters]:
                try:
                    response = self.ec2.describe_images(Filters=filters)

                    for image in response['Images']:
                        # Avoid duplicates
                        image_id = image['ImageId']
                        if not any(img['ImageId'] == image_id for img in all_images):
                            image_info = {
                                'Region': self.aws_client.region,
                                'ImageId': image_id,
                                'Name': image.get('Name', 'N/A'),
                                'Description': image.get('Description', 'N/A'),
                                'CreationDate': image.get('CreationDate', 'N/A'),
                                'Architecture': image.get('Architecture', 'N/A'),
                                'Platform': image.get('Platform', 'Linux'),
                                'State': image.get('State', 'N/A')
                            }
                            all_images.append(image_info)

                except Exception as e:
                    logger.warning(
                        f"Error searching in {self.aws_client.region} with filters: {e}")

        except Exception as e:
            logger.error(
                f"Failed to search in region {self.aws_client.region}: {e}")

        # Sort by creation date (newest first)
        all_images.sort(key=lambda x: x['CreationDate'], reverse=True)

        return all_images

    def get_image_snapshots(self, image_id: str) -> List[str]:
        """Get all snapshot IDs associated with an AMI"""
        try:
            response = self.ec2.describe_images(ImageIds=[image_id])

            snapshots = []
            if response['Images']:
                image = response['Images'][0]
                for block_device in image.get('BlockDeviceMappings', []):
                    if 'Ebs' in block_device and 'SnapshotId' in block_device['Ebs']:
                        snapshots.append(block_device['Ebs']['SnapshotId'])

            return snapshots
        except Exception as e:
            logger.error(
                "Failed to get snapshots for image %s: %s", image_id, e)
            return []

    def delete_image_and_snapshots(self, image_id: str, dry_run: bool = False) -> Dict[str, Any]:
        """Delete an AMI and its associated snapshots"""
        result = {
            'image_id': image_id,
            'success': False,
            'snapshots_deleted': [],
            'snapshots_failed': [],
            'error': None
        }

        try:
            # Get snapshots before deleting the image
            snapshots = self.get_image_snapshots(image_id)
            logger.info(
                f"Found {len(snapshots)} snapshots for image {image_id}: {snapshots}")

            if dry_run:
                logger.info(
                    f"[DRY RUN] Would delete AMI {image_id} and {len(snapshots)} snapshots")
                result['success'] = True
                result['snapshots_deleted'] = snapshots
                return result

            # Delete the AMI
            logger.info("Deleting AMI: %s", image_id)
            self.ec2.deregister_image(ImageId=image_id)

            # Delete associated snapshots
            for snapshot_id in snapshots:
                try:
                    logger.info("Deleting snapshot: %s", snapshot_id)
                    self.ec2.delete_snapshot(SnapshotId=snapshot_id)
                    result['snapshots_deleted'].append(snapshot_id)
                except Exception as snap_error:
                    logger.error("Failed to delete snapshot %s: %s",
                                 snapshot_id, snap_error)
                    result['snapshots_failed'].append(snapshot_id)

            result['success'] = True
            logger.info("Successfully deleted AMI %s and %d snapshots",
                        image_id, len(result['snapshots_deleted']))

        except Exception as e:
            logger.error("Failed to delete AMI %s: %s", image_id, e)
            result['error'] = str(e)

        return result

    @staticmethod
    def filter_images_by_age(images: List[Dict[str, Any]], age_threshold: Optional[datetime] = None) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Filter images by age threshold

        Args:
            images: List of image dictionaries
            age_threshold: DateTime threshold - images older than this will be included for deletion

        Returns:
            Tuple of (images_to_delete, images_too_young)
        """
        if not age_threshold:
            return images, []

        images_to_delete = []
        images_too_young = []
        current_time = datetime.now(timezone.utc)

        for image in images:
            creation_date_str = image.get('CreationDate')

            if creation_date_str and creation_date_str != 'N/A':
                try:
                    # Parse AWS datetime format (ISO 8601)
                    if isinstance(creation_date_str, str):
                        # Remove timezone info for comparison (AWS returns UTC)
                        creation_date_str = creation_date_str.replace(
                            'T', ' ').replace('Z', '').split('.')[0]
                        creation_date = datetime.strptime(
                            creation_date_str, '%Y-%m-%d %H:%M:%S')
                        # Make timezone-aware (AWS times are UTC)
                        creation_date = creation_date.replace(
                            tzinfo=timezone.utc)
                    else:
                        # If already a datetime object
                        creation_date = creation_date_str

                    # Add age information to image
                    age_days = (current_time - creation_date).days
                    image['Age'] = f"{age_days}d"

                    if creation_date < age_threshold:
                        images_to_delete.append(image)
                        logger.debug(
                            "Image %s is %d days old - ELIGIBLE for deletion", image['ImageId'], age_days)
                    else:
                        images_too_young.append(image)
                        logger.debug(
                            "Image %s is %d days old - TOO YOUNG for deletion", image['ImageId'], age_days)

                except Exception as e:
                    logger.warning("Could not parse creation date '%s' for image %s: %s",
                                   creation_date_str, image.get('ImageId', 'unknown'), e)
                    # If we can't parse the date, err on the side of caution and don't delete
                    image['Age'] = 'Unknown'
                    images_too_young.append(image)
            else:
                logger.warning(
                    "No creation date found for image %s - skipping deletion", image.get('ImageId', 'unknown'))
                image['Age'] = 'Unknown'
                images_too_young.append(image)

        threshold_str = age_threshold.strftime(
            '%Y-%m-%d %H:%M:%S') if age_threshold else "N/A"
        logger.info("Age filtering results: %d eligible for deletion, %d too young (threshold: %s UTC)", len(
            images_to_delete), len(images_too_young), threshold_str)

        return images_to_delete, images_too_young


class OutputFormatter:
    """
    Handles different output formats for EC2 image data.
    This class can be reused for formatting any tabular data.
    """

    @staticmethod
    def output_results(images: List[Dict[str, Any]], output_format: str):
        """Output results in the specified format"""
        if not images:
            logger.info("No images found matching the keyword.")
            return

        if output_format == 'table':
            OutputFormatter._output_table(images)
        elif output_format == 'csv':
            OutputFormatter._output_csv(images)
        else:
            OutputFormatter._output_json(images)

    @staticmethod
    def _output_json(images: List[Dict[str, Any]]):
        """Output results in JSON format"""
        logger.info(json.dumps(images, indent=2, default=str))

    @staticmethod
    def _output_csv(images: List[Dict[str, Any]]):
        """Output results in CSV format"""
        if not images:
            return

        writer = csv.DictWriter(sys.stdout, fieldnames=images[0].keys())
        writer.writeheader()
        writer.writerows(images)

    @staticmethod
    def _output_table(images: List[Dict[str, Any]]):
        """Print results in a formatted table"""
        if not images:
            return

        # Check if images have age information
        has_age_info = any('Age' in image for image in images)

        # Define column widths
        col_widths = {
            'Region': 15,
            'ImageId': 21,
            'Name': 35,
            'CreationDate': 20,
            'Age': 8 if has_age_info else 0,
            'Architecture': 12,
            'Platform': 10
        }

        # Build header
        header_parts = []
        header_parts.append(f"{'Region':<{col_widths['Region']}}")
        header_parts.append(f"{'ImageId':<{col_widths['ImageId']}}")
        header_parts.append(f"{'Name':<{col_widths['Name']}}")
        header_parts.append(f"{'CreationDate':<{col_widths['CreationDate']}}")
        if has_age_info:
            header_parts.append(f"{'Age':<{col_widths['Age']}}")
        header_parts.append(f"{'Architecture':<{col_widths['Architecture']}}")
        header_parts.append(f"{'Platform':<{col_widths['Platform']}}")

        header = " ".join(header_parts)
        logger.info(header)
        logger.info("-" * len(header))

        # Print rows
        for image in images:
            name = image['Name'][:col_widths['Name']-3] + \
                "..." if len(
                    image['Name']) > col_widths['Name'] else image['Name']
            creation_date = str(image['CreationDate'])[
                :col_widths['CreationDate']]

            row_parts = []
            row_parts.append(f"{image['Region']:<{col_widths['Region']}}")
            row_parts.append(f"{image['ImageId']:<{col_widths['ImageId']}}")
            row_parts.append(f"{name:<{col_widths['Name']}}")
            row_parts.append(f"{creation_date:<{col_widths['CreationDate']}}")
            if has_age_info:
                age = image.get('Age', 'N/A')
                row_parts.append(f"{age:<{col_widths['Age']}}")
            row_parts.append(
                f"{image['Architecture']:<{col_widths['Architecture']}}")
            row_parts.append(f"{image['Platform']:<{col_widths['Platform']}}")

            row = " ".join(row_parts)
            logger.info(row)
