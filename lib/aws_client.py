#!/usr/bin/env python3

"""Module providing aws client authentication handling"""

import logging
from typing import Optional
import boto3

logger = logging.getLogger(__name__)


class AWSClient:
    """
    AWS client wrapper that handles sessions and credential validation.
    This class can be reused across different AWS tools.
    """

    def __init__(self, region: str, profile: Optional[str] = None):
        """
        Initialize AWS client with region and optional profile

        Args:
            region: AWS region to operate in
            profile: AWS profile name to use (optional)
        """
        self.region = region
        self.profile = profile
        self.session = self._create_session()
        self.validate_credentials()

    def _create_session(self) -> boto3.Session:
        """Create boto3 session with optional profile"""
        if self.profile:
            logger.info("Using AWS profile: %s", {self.profile})
            return boto3.Session(profile_name=self.profile)
        else:
            return boto3.Session()

    def validate_credentials(self):
        """Validate that AWS credentials are properly configured"""
        try:
            # Try to create an STS client using the session to test credentials
            sts = self.session.client('sts')

            # Call get_caller_identity to verify credentials work
            response = sts.get_caller_identity()

            profile_info = f" (profile: {self.profile})" if self.profile else ""
            logger.info("AWS credentials validated successfully: %s", {profile_info})
            logger.info("Account ID: %s", {response.get('Account', 'N/A')})
            logger.info("User/Role ARN: %s", {response.get('Arn', 'N/A')})

        except Exception as e:
            logger.error(e)
            # Provide helpful troubleshooting information
            raise ValueError(e) from e

    def get_ec2_client(self):
        """Get EC2 client for the configured region"""
        return self.session.client('ec2', region_name=self.region)

    def get_sts_client(self):
        """Get STS client"""
        return self.session.client('sts')

    def get_client(self, service_name: str, region_name: Optional[str] = None):
        """
        Get a client for any AWS service

        Args:
            service_name: AWS service name (e.g., 'ec2', 's3', 'lambda')
            region_name: Override region (uses instance region if not provided)

        Returns:
            boto3 client for the specified service
        """
        return self.session.client(
            service_name,
            region_name=region_name or self.region
        )