import os
from dataclasses import dataclass

from dotenv import load_dotenv
load_dotenv()


@dataclass
class Config:
    """Application configuration from environment variables"""

    # AWS Configuration
    AWS_REGION: str = os.getenv('AWS_REGION', 'us-east-1')
    AWS_ACCESS_KEY_ID: str = os.getenv('AWS_ACCESS_KEY_ID')
    AWS_SECRET_ACCESS_KEY: str = os.getenv('AWS_SECRET_ACCESS_KEY')

    # S3 Configuration
    S3_BUCKET: str = os.getenv('S3_BUCKET')
    S3_STATE_PREFIX: str = os.getenv('S3_STATE_PREFIX', 'state')
    S3_SUCCESS_PREFIX: str = os.getenv('S3_SUCCESS_PREFIX', 'success')
    S3_FAILED_PREFIX: str = os.getenv('S3_FAILED_PREFIX', 'failed')

    # API Configuration
    API_HOST: str = os.getenv('API_HOST', '0.0.0.0')
    API_PORT: int = int(os.getenv('API_PORT', '8080'))

    # Logging
    LOG_LEVEL: str = os.getenv('LOG_LEVEL', 'INFO')

    @classmethod
    def from_env(cls):
        """Create config from environment variables"""
        return cls()

    def is_local(self) -> bool:
        """Check if running in local development mode"""
        return os.getenv('ENDPOINT_URL') is not None

    def validate(self):
        """Validate required configuration"""
        if not self.S3_BUCKET:
            raise ValueError("S3_BUCKET must be set")

        # In production (not LocalStack), AWS credentials should be available
        if not self.is_local():
            # AWS SDK will handle credentials via IAM roles, env vars, or ~/.aws/credentials
            pass

        return True