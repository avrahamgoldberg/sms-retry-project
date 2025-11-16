import boto3
import json
import logging
import os
from typing import List, Optional
from datetime import datetime
from botocore.exceptions import ClientError
from src.models import MessageState, MessageStatus
from src.config import Config
from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)


class S3PersistenceLayer:
    """Handles all S3 operations for message state persistence"""

    def __init__(self, config: Config):
        self.config = config
        # Determine if we're using LocalStack or real S3

        # Create S3 client
        s3_config = {
            'region_name': config.AWS_REGION,
        }
        if config.AWS_ACCESS_KEY_ID and config.AWS_SECRET_ACCESS_KEY:
            s3_config['aws_access_key_id'] = config.AWS_ACCESS_KEY_ID
            s3_config['aws_secret_access_key'] = config.AWS_SECRET_ACCESS_KEY

        if self.config.is_local():
            s3_config['endpoint_url'] = os.getenv('ENDPOINT_URL')

        self.s3_client = boto3.client('s3', **s3_config)
        self.bucket = config.S3_BUCKET
        self.state_prefix = config.S3_STATE_PREFIX
        self.success_prefix = config.S3_SUCCESS_PREFIX
        self.failed_prefix = config.S3_FAILED_PREFIX

        # Ensure bucket exists (for LocalStack)
        self._ensure_bucket_exists()

    def _ensure_bucket_exists(self):
        """Create bucket if it doesn't exist (mainly for LocalStack)"""
        try:
            self.s3_client.head_bucket(Bucket=self.bucket)
            logger.info(f"S3 bucket '{self.bucket}' exists")
        except ClientError as e:
            error_code = e.response['Error']['Code']

            # Possible 'bucket does not exist' codes:
            not_found_errors = {"404", "NoSuchBucket", "NotFound"}
            if error_code in not_found_errors:
                try:
                    self.s3_client.create_bucket(Bucket=self.bucket)
                    logger.info(f"Created S3 bucket '{self.bucket}'")
                except Exception as create_error:
                    logger.error(f"Failed to create bucket: {create_error}")
            else:
                logger.error(f"Error checking bucket: {e}")

    def save_message_state(self, state: MessageState):
        """Persist message state to S3"""
        try:
            key = f"{self.state_prefix}/{state.message_id}.json"
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=state.to_json(),
                ContentType='application/json'
            )
            logger.debug(f"Saved state for message {state.message_id}")
        except Exception as e:
            logger.error(f"Failed to save state for {state.message_id}: {e}")
            raise

    def load_message_state(self, message_id: str) -> Optional[MessageState]:
        """Load message state from S3"""
        try:
            key = f"{self.state_prefix}/{message_id}.json"
            response = self.s3_client.get_object(Bucket=self.bucket, Key=key)
            json_str = response['Body'].read().decode('utf-8')
            return MessageState.from_json(json_str)
        except self.s3_client.exceptions.NoSuchKey:
            return None
        except Exception as e:
            logger.error(f"Failed to load state for {message_id}: {e}")
            return None

    def load_all_pending_states(self) -> List[MessageState]:
        """Load all pending message states from S3 (for recovery)"""
        states = []
        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=self.bucket, Prefix=self.state_prefix)

            for page in pages:
                if 'Contents' not in page:
                    continue

                for obj in page['Contents']:
                    try:
                        response = self.s3_client.get_object(
                            Bucket=self.bucket,
                            Key=obj['Key']
                        )
                        json_str = response['Body'].read().decode('utf-8')
                        state = MessageState.from_json(json_str)

                        if state.status == MessageStatus.PENDING:
                            states.append(state)
                    except Exception as e:
                        logger.error(f"Failed to load state from {obj['Key']}: {e}")
                        continue

            logger.info(f"Loaded {len(states)} pending messages from S3")
            return states
        except Exception as e:
            logger.error(f"Failed to load pending states: {e}")
            return []

    def mark_success(self, message_id: str, state: MessageState):
        """Mark message as successfully sent"""
        try:
            # Write to success log
            timestamp = datetime.utcnow().isoformat()
            key = f"{self.success_prefix}/{timestamp}_{message_id}.json"
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=state.to_json(),
                ContentType='application/json'
            )

            # Delete from state
            self._delete_state(message_id)
            logger.info(f"Marked message {message_id} as SUCCESS")
        except Exception as e:
            logger.error(f"Failed to mark success for {message_id}: {e}")
            raise

    def mark_failed(self, message_id: str, state: MessageState):
        """Mark message as failed after max retries"""
        try:
            # Write to failed log
            timestamp = datetime.utcnow().isoformat()
            key = f"{self.failed_prefix}/{timestamp}_{message_id}.json"
            self.s3_client.put_object(
                Bucket=self.bucket,
                Key=key,
                Body=state.to_json(),
                ContentType='application/json'
            )

            # Delete from state
            self._delete_state(message_id)
            logger.info(f"Marked message {message_id} as FAILED_MAX_RETRIES")
        except Exception as e:
            logger.error(f"Failed to mark failed for {message_id}: {e}")
            raise

    def _delete_state(self, message_id: str):
        """Delete message state from S3"""
        try:
            key = f"{self.state_prefix}/{message_id}.json"
            self.s3_client.delete_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            logger.error(f"Failed to delete state for {message_id}: {e}")

    def get_recent_success(self, limit: int = 100) -> List[dict]:
        """Get last N successful messages"""
        return self._get_recent_from_prefix(self.success_prefix, limit)

    def get_recent_failed(self, limit: int = 100) -> List[dict]:
        """Get last N failed messages"""
        return self._get_recent_from_prefix(self.failed_prefix, limit)

    def _get_recent_from_prefix(self, prefix: str, limit: int) -> List[dict]:
        """Helper to get recent messages from a prefix"""
        try:
            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket,
                Prefix=prefix,
                MaxKeys=limit
            )

            if 'Contents' not in response:
                return []

            # Sort by last modified descending
            objects = sorted(
                response['Contents'],
                key=lambda x: x['LastModified'],
                reverse=True
            )[:limit]

            results = []
            for obj in objects:
                try:
                    response = self.s3_client.get_object(
                        Bucket=self.bucket,
                        Key=obj['Key']
                    )
                    json_str = response['Body'].read().decode('utf-8')
                    results.append(json.loads(json_str))
                except Exception as e:
                    logger.error(f"Failed to load {obj['Key']}: {e}")
                    continue

            return results
        except Exception as e:
            logger.error(f"Failed to get recent from {prefix}: {e}")
            return []