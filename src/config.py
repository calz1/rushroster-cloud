"""Application configuration using pydantic-settings.

This module handles configuration from environment variables, .env files, and config.yaml.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import field_validator
from typing import Optional
import yaml
from pathlib import Path
import secrets
import sys


# Weak/default secrets that should never be used in production
INSECURE_DEFAULT_SECRETS = {
    "your-secret-key-change-this-in-production",
    "your-super-secret-key-change-this-in-production-use-256-bits",
    "change-me",
    "changeme",
    "secret",
    "password",
    "default",
    "replace_this_with_a_strong_secret_generated_using_above_command",
    "change-this-in-production-use-long-random-string",
}


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "rushroster-cloud"
    app_version: str = "0.1.0"
    debug: bool = False
    environment: str = "development"  # development, staging, production

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_prefix: str = ""

    # Database - can be set directly or built from components
    database_url: Optional[str] = None
    database_echo: bool = False  # Log SQL queries

    # Database components (used if database_url not provided)
    postgres_db: str = "rushroster"
    postgres_user: str = "rushroster"
    postgres_password: str = "rushroster"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    @property
    def db_url(self) -> str:
        """Get database URL, constructing from components if not explicitly set."""
        if self.database_url:
            return self.database_url
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    # JWT Authentication
    jwt_secret_key: str = "your-secret-key-change-this-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 15  # Short-lived tokens for security
    jwt_refresh_token_expire_days: int = 30

    # Password Hashing
    password_bcrypt_rounds: int = 12

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret_key(cls, v: str) -> str:
        """Validate that JWT secret key is not a weak default value."""
        # Check if the secret is one of the known weak defaults
        if v.lower() in INSECURE_DEFAULT_SECRETS or v.lower().strip() in INSECURE_DEFAULT_SECRETS:
            print("\n" + "=" * 80, file=sys.stderr)
            print("CRITICAL SECURITY ERROR: Weak or default JWT secret detected!", file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print("\nThe application has been configured with a default JWT secret key.", file=sys.stderr)
            print("This is a critical security vulnerability that would allow attackers to", file=sys.stderr)
            print("forge authentication tokens and gain unauthorized access to the system.", file=sys.stderr)
            print("\nTo fix this, generate a strong random secret key:", file=sys.stderr)
            print("\n  python -c 'import secrets; print(secrets.token_urlsafe(32))'", file=sys.stderr)
            print("\nThen set it in your environment or .env file:", file=sys.stderr)
            print("\n  JWT_SECRET_KEY=<your-generated-secret-here>", file=sys.stderr)
            print("\nOr in config.yaml under security.secret_key", file=sys.stderr)
            print("\n" + "=" * 80 + "\n", file=sys.stderr)
            sys.exit(1)

        # Warn if the secret is too short (less than 32 characters)
        if len(v) < 32:
            print("\n" + "=" * 80, file=sys.stderr)
            print("WARNING: JWT secret key is too short!", file=sys.stderr)
            print("=" * 80, file=sys.stderr)
            print(f"\nCurrent length: {len(v)} characters", file=sys.stderr)
            print("Recommended: At least 32 characters (256 bits)", file=sys.stderr)
            print("\nGenerate a stronger secret:", file=sys.stderr)
            print("\n  python -c 'import secrets; print(secrets.token_urlsafe(32))'", file=sys.stderr)
            print("\n" + "=" * 80 + "\n", file=sys.stderr)

        return v

    # Object Storage
    storage_provider: str = "s3"  # s3, gcs, azure, local
    storage_bucket_name: str = "rushroster-photos"
    storage_region: str = "us-east-1"
    storage_access_key: Optional[str] = None
    storage_secret_key: Optional[str] = None
    storage_endpoint_url: Optional[str] = None  # For MinIO, LocalStack, etc.
    storage_local_path: str = "./data/photos"  # For local storage provider

    # AWS Credentials (if using S3)
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None

    # CORS
    cors_origins: list = ["http://localhost:3000", "http://localhost:8080"]
    cors_allow_credentials: bool = True
    cors_allow_methods: list = ["*"]
    cors_allow_headers: list = ["*"]

    # Rate Limiting
    rate_limit_enabled: bool = True
    rate_limit_per_minute: int = 60

    # Community Features
    community_feed_default_limit: int = 50
    community_feed_max_limit: int = 200

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"  # Ignore extra environment variables (like POSTGRES_* used by docker-compose)
    )

    @property
    def access_token_expire_minutes(self) -> int:
        """Alias for JWT access token expire minutes."""
        return self.jwt_access_token_expire_minutes


def load_config_yaml(config_path: str = "config.yaml") -> dict:
    """Load configuration from YAML file if it exists."""
    config_file = Path(config_path)
    if config_file.exists():
        with open(config_file, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def create_settings() -> Settings:
    """Create settings instance with config.yaml overrides."""
    # Load config.yaml
    yaml_config = load_config_yaml()

    # Build kwargs from yaml_config
    kwargs = {}

    # Map database config from yaml
    if "database" in yaml_config:
        db = yaml_config["database"]
        db_url = f"postgresql://{db.get('user', 'rushroster')}:{db.get('password', 'rushroster')}@{db.get('host', 'localhost')}:{db.get('port', 5432)}/{db.get('name', 'rushroster')}"
        kwargs["database_url"] = db_url

    # Map cloud config
    if "cloud" in yaml_config:
        cloud = yaml_config["cloud"]
        if "environment" in cloud:
            kwargs["environment"] = cloud["environment"]
        if "debug" in cloud:
            kwargs["debug"] = cloud["debug"]

    # Map storage config
    if "storage" in yaml_config:
        storage = yaml_config["storage"]
        if "provider" in storage:
            kwargs["storage_provider"] = storage["provider"]
        if "bucket_name" in storage:
            kwargs["storage_bucket_name"] = storage["bucket_name"]
        if "local_path" in storage:
            kwargs["storage_local_path"] = storage["local_path"]

    # Map security config
    if "security" in yaml_config:
        security = yaml_config["security"]
        if "secret_key" in security:
            kwargs["jwt_secret_key"] = security["secret_key"]
        if "algorithm" in security:
            kwargs["jwt_algorithm"] = security["algorithm"]
        if "access_token_expire_minutes" in security:
            kwargs["jwt_access_token_expire_minutes"] = security["access_token_expire_minutes"]

    # Map API config
    if "api" in yaml_config:
        api = yaml_config["api"]
        if "host" in api:
            kwargs["api_host"] = api["host"]
        if "port" in api:
            kwargs["api_port"] = api["port"]

    # Map CORS config
    if "cors" in yaml_config:
        cors = yaml_config["cors"]
        if "origins" in cors:
            kwargs["cors_origins"] = cors["origins"]
        if "allow_credentials" in cors:
            kwargs["cors_allow_credentials"] = cors["allow_credentials"]
        if "allow_methods" in cors:
            kwargs["cors_allow_methods"] = cors["allow_methods"]
        if "allow_headers" in cors:
            kwargs["cors_allow_headers"] = cors["allow_headers"]

    # Create Settings with YAML overrides (env vars will still override these)
    return Settings(**kwargs)


# Global settings instance
settings = create_settings()
