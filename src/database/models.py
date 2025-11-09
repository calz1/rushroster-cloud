"""SQLAlchemy database models.

This module defines the PostgreSQL database schema using SQLAlchemy ORM.
Models correspond to the schema defined in spec.md.
"""

from sqlalchemy import (
    Column, String, Boolean, DateTime, Numeric, Integer,
    ForeignKey, Text, Index, Date, JSON
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship, DeclarativeBase
from sqlalchemy.sql import func
import uuid

# Use JSONB for PostgreSQL, JSON for other databases (like SQLite in tests)
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    """Base class for all database models."""
    pass


class User(Base):
    """User account model."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255), nullable=True)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_login = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    devices = relationship("Device", back_populates="owner")
    reports = relationship("Report", back_populates="user")
    preferences = relationship("UserPreference", back_populates="user", uselist=False)

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email})>"


class Device(Base):
    """Field device model."""
    __tablename__ = "devices"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(String(100), unique=True, nullable=False, index=True)
    owner_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    api_key_hash = Column(String(255), nullable=True)  # Hashed API key for authentication
    latitude = Column(Numeric(10, 8), nullable=True)
    longitude = Column(Numeric(11, 8), nullable=True)
    street_name = Column(String(255), nullable=True)
    speed_limit = Column(Numeric(5, 2), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    share_community = Column(Boolean, default=False, nullable=False)
    registered_at = Column(DateTime(timezone=True), server_default=func.now())
    last_sync = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    owner = relationship("User", back_populates="devices")
    events = relationship("SpeedEvent", back_populates="device")
    reports = relationship("Report", back_populates="device")

    # Indexes
    __table_args__ = (
        Index("ix_devices_owner_active", "owner_id", "is_active"),
        Index("ix_devices_location", "latitude", "longitude"),
    )

    def __repr__(self):
        return f"<Device(id={self.id}, device_id={self.device_id})>"


class SpeedEvent(Base):
    """Speed detection event model."""
    __tablename__ = "speed_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    speed = Column(Numeric(5, 2), nullable=False)
    speed_limit = Column(Numeric(5, 2), nullable=False)
    is_speeding = Column(Boolean, nullable=False)
    photo_url = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    device = relationship("Device", back_populates="events")

    # Indexes for efficient querying
    __table_args__ = (
        Index("ix_speed_events_device_timestamp", "device_id", "timestamp"),
        Index("ix_speed_events_timestamp", "timestamp"),
        Index("ix_speed_events_speeding", "is_speeding", "timestamp"),
        Index("ix_speed_events_device_speeding", "device_id", "is_speeding", "timestamp"),
    )

    def __repr__(self):
        return f"<SpeedEvent(id={self.id}, speed={self.speed}, is_speeding={self.is_speeding})>"


class Report(Base):
    """Generated report model."""
    __tablename__ = "reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    total_vehicles = Column(Integer, nullable=True)
    speeding_vehicles = Column(Integer, nullable=True)
    report_data = Column(JSONType, nullable=True)  # Stores detailed statistics and analysis
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    user = relationship("User", back_populates="reports")
    device = relationship("Device", back_populates="reports")

    # Indexes
    __table_args__ = (
        Index("ix_reports_user_created", "user_id", "created_at"),
        Index("ix_reports_device_dates", "device_id", "start_date", "end_date"),
    )

    def __repr__(self):
        return f"<Report(id={self.id}, device_id={self.device_id}, period={self.start_date} to {self.end_date})>"


class UserPreference(Base):
    """User preferences and settings model."""
    __tablename__ = "user_preferences"

    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True)
    email_notifications = Column(Boolean, default=True, nullable=False)
    share_data_community = Column(Boolean, default=False, nullable=False)
    preferences = Column(JSONType, nullable=True)  # Flexible storage for additional preferences

    # Relationships
    user = relationship("User", back_populates="preferences")

    def __repr__(self):
        return f"<UserPreference(user_id={self.user_id})>"


class DeviceApiKey(Base):
    """
    Device API keys for authentication (optional separate table).

    This could be used instead of storing hashed keys directly in Device table
    to allow for key rotation and better security tracking.
    """
    __tablename__ = "device_api_keys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    device_id = Column(UUID(as_uuid=True), ForeignKey("devices.id"), nullable=False)
    api_key_hash = Column(String(255), nullable=False, unique=True)
    name = Column(String(100), nullable=True)  # Optional key name/description
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    last_used = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)

    # Indexes
    __table_args__ = (
        Index("ix_device_api_keys_hash", "api_key_hash"),
        Index("ix_device_api_keys_device_active", "device_id", "is_active"),
    )

    def __repr__(self):
        return f"<DeviceApiKey(id={self.id}, device_id={self.device_id}, active={self.is_active})>"


class GlobalStatistics(Base):
    """
    Cached global platform statistics.

    This table stores pre-computed statistics that are expensive to calculate,
    updated periodically (e.g., hourly) by a background task.
    """
    __tablename__ = "global_statistics"

    id = Column(Integer, primary_key=True, autoincrement=True)
    total_devices = Column(Integer, nullable=False, default=0)
    community_devices = Column(Integer, nullable=False, default=0)
    total_events = Column(Integer, nullable=False, default=0)
    speeding_events = Column(Integer, nullable=False, default=0)
    recent_events_24h = Column(Integer, nullable=False, default=0)
    recent_speeding_24h = Column(Integer, nullable=False, default=0)
    statistics_data = Column(JSONType, nullable=True)  # Additional computed stats
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    def __repr__(self):
        return f"<GlobalStatistics(id={self.id}, devices={self.total_devices}, updated={self.updated_at})>"


class RegistrationCode(Base):
    """
    Registration codes for controlled user registration.

    Codes have a limited number of uses and can be deactivated.
    """
    __tablename__ = "registration_codes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(100), unique=True, nullable=False, index=True)
    max_uses = Column(Integer, nullable=False, default=1)
    current_uses = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_by_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    description = Column(String(255), nullable=True)  # Optional note about the code

    # Indexes
    __table_args__ = (
        Index("ix_registration_codes_active", "is_active", "code"),
    )

    def __repr__(self):
        return f"<RegistrationCode(code={self.code}, uses={self.current_uses}/{self.max_uses})>"
