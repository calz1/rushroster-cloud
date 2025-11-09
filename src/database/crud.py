"""CRUD (Create, Read, Update, Delete) operations for database models.

This module provides reusable database operations for each model,
following best practices for SQLAlchemy usage.
"""

from typing import List, Optional, Dict, Any
from datetime import datetime, date, timedelta
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select, and_, or_, func

from .models import User, Device, SpeedEvent, Report, UserPreference, DeviceApiKey, GlobalStatistics, RegistrationCode


# ============================================================================
# User CRUD Operations
# ============================================================================

def create_user(
    db: Session,
    email: str,
    password_hash: str,
    full_name: Optional[str] = None,
    is_admin: bool = False
) -> User:
    """Create a new user."""
    # If this is the first user, make them admin
    if not is_admin:
        user_count = db.scalar(select(func.count(User.id)))
        if user_count == 0:
            is_admin = True

    user = User(
        email=email,
        password_hash=password_hash,
        full_name=full_name,
        is_admin=is_admin
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_by_id(db: Session, user_id: UUID) -> Optional[User]:
    """Get user by ID."""
    return db.get(User, user_id)


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    """Get user by email."""
    stmt = select(User).where(User.email == email)
    return db.scalar(stmt)


def update_user_last_login(db: Session, user_id: UUID) -> None:
    """Update user's last login timestamp."""
    user = db.get(User, user_id)
    if user:
        user.last_login = datetime.now()
        db.commit()


def update_user_profile(
    db: Session,
    user_id: UUID,
    full_name: Optional[str] = None
) -> Optional[User]:
    """Update user profile information."""
    user = db.get(User, user_id)
    if user:
        if full_name is not None:
            user.full_name = full_name
        db.commit()
        db.refresh(user)
    return user


def get_all_users(
    db: Session,
    limit: int = 100,
    offset: int = 0
) -> List[User]:
    """Get all users (admin only)."""
    stmt = select(User).order_by(User.created_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt))


def set_user_admin_status(
    db: Session,
    user_id: UUID,
    is_admin: bool
) -> Optional[User]:
    """Update user admin status (admin only)."""
    user = db.get(User, user_id)
    if user:
        user.is_admin = is_admin
        db.commit()
        db.refresh(user)
    return user


def delete_user(db: Session, user_id: UUID) -> bool:
    """Delete a user and all their data (admin only)."""
    user = db.get(User, user_id)
    if user:
        # Delete user preferences
        prefs = db.get(UserPreference, user_id)
        if prefs:
            db.delete(prefs)

        # Delete user reports
        reports = get_user_reports(db, user_id, limit=1000)
        for report in reports:
            db.delete(report)

        # Delete user devices and their data
        devices = get_user_devices(db, user_id, include_inactive=True)
        for device in devices:
            # Delete device events
            events_stmt = select(SpeedEvent).where(SpeedEvent.device_id == device.id)
            events = list(db.scalars(events_stmt))
            for event in events:
                db.delete(event)

            # Delete device API keys
            api_keys = get_device_api_keys(db, device.id, include_inactive=True)
            for api_key in api_keys:
                db.delete(api_key)

            # Delete device
            db.delete(device)

        # Finally delete the user
        db.delete(user)
        db.commit()
        return True
    return False


# ============================================================================
# Device CRUD Operations
# ============================================================================

def create_device(
    db: Session,
    device_id: str,
    owner_id: UUID,
    api_key_hash: Optional[str] = None,
    **kwargs
) -> Device:
    """Create a new device."""
    device = Device(
        device_id=device_id,
        owner_id=owner_id,
        api_key_hash=api_key_hash,
        **kwargs
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


def get_device_by_id(db: Session, device_id: UUID) -> Optional[Device]:
    """Get device by UUID."""
    return db.get(Device, device_id)


def get_device_by_device_id(db: Session, device_id: str) -> Optional[Device]:
    """Get device by device_id string."""
    stmt = select(Device).where(Device.device_id == device_id)
    return db.scalar(stmt)


def get_user_devices(
    db: Session,
    user_id: UUID,
    include_inactive: bool = False
) -> List[Device]:
    """Get all devices owned by a user."""
    stmt = select(Device).where(Device.owner_id == user_id)
    if not include_inactive:
        stmt = stmt.where(Device.is_active == True)
    return list(db.scalars(stmt))


def update_device(
    db: Session,
    device_id: UUID,
    **kwargs
) -> Optional[Device]:
    """Update device information."""
    device = db.get(Device, device_id)
    if device:
        for key, value in kwargs.items():
            if hasattr(device, key):
                setattr(device, key, value)
        db.commit()
        db.refresh(device)
    return device


def update_device_last_sync(db: Session, device_id: UUID) -> None:
    """Update device's last sync timestamp."""
    device = db.get(Device, device_id)
    if device:
        device.last_sync = datetime.now()
        db.commit()


def get_community_devices(
    db: Session,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius_km: Optional[float] = None
) -> List[Device]:
    """
    Get devices that have opted into community sharing.

    If location and radius are provided, filters to devices within that area.
    """
    stmt = select(Device).where(
        and_(
            Device.is_active == True,
            Device.share_community == True
        )
    )

    # TODO: Add geographic filtering using PostGIS or similar
    # This would require additional setup for spatial queries

    return list(db.scalars(stmt))


def get_all_devices(
    db: Session,
    limit: int = 100,
    offset: int = 0
) -> List[Device]:
    """Get all devices (admin only)."""
    stmt = select(Device).order_by(Device.registered_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt))


def delete_device(db: Session, device_id: UUID) -> bool:
    """Delete a device and all its data (admin only)."""
    device = db.get(Device, device_id)
    if device:
        # Delete device events
        events_stmt = select(SpeedEvent).where(SpeedEvent.device_id == device_id)
        events = list(db.scalars(events_stmt))
        for event in events:
            db.delete(event)

        # Delete device API keys
        api_keys = get_device_api_keys(db, device_id, include_inactive=True)
        for api_key in api_keys:
            db.delete(api_key)

        # Delete device reports
        reports = get_device_reports(db, device_id, limit=1000)
        for report in reports:
            db.delete(report)

        # Delete device
        db.delete(device)
        db.commit()
        return True
    return False


# ============================================================================
# Speed Event CRUD Operations
# ============================================================================

def create_speed_event(
    db: Session,
    device_id: UUID,
    timestamp: datetime,
    speed: float,
    speed_limit: float,
    is_speeding: bool,
    photo_url: Optional[str] = None
) -> SpeedEvent:
    """Create a new speed event."""
    event = SpeedEvent(
        device_id=device_id,
        timestamp=timestamp,
        speed=speed,
        speed_limit=speed_limit,
        is_speeding=is_speeding,
        photo_url=photo_url
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def create_speed_events_batch(
    db: Session,
    events: List[Dict[str, Any]]
) -> int:
    """
    Create multiple speed events in a batch.

    Args:
        db: Database session
        events: List of event dictionaries

    Returns:
        Number of events created
    """
    event_objects = [SpeedEvent(**event) for event in events]
    db.add_all(event_objects)
    db.commit()
    return len(event_objects)


def get_device_events(
    db: Session,
    device_id: UUID,
    limit: int = 100,
    offset: int = 0,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    speeding_only: bool = False
) -> List[SpeedEvent]:
    """Get events for a specific device."""
    stmt = select(SpeedEvent).where(SpeedEvent.device_id == device_id)

    if start_date:
        stmt = stmt.where(SpeedEvent.timestamp >= start_date)
    if end_date:
        stmt = stmt.where(SpeedEvent.timestamp <= end_date)
    if speeding_only:
        stmt = stmt.where(SpeedEvent.is_speeding == True)

    stmt = stmt.order_by(SpeedEvent.timestamp.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt))


def get_device_event_stats(
    db: Session,
    device_id: UUID,
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None
) -> Dict[str, Any]:
    """Get aggregate statistics for a device's events."""
    stmt = select(
        func.count(SpeedEvent.id).label("total_events"),
        func.count(SpeedEvent.id).filter(SpeedEvent.is_speeding == True).label("speeding_events"),
        func.avg(SpeedEvent.speed).label("avg_speed"),
        func.max(SpeedEvent.speed).label("max_speed"),
        func.min(SpeedEvent.speed).label("min_speed")
    ).where(SpeedEvent.device_id == device_id)

    if start_date:
        stmt = stmt.where(SpeedEvent.timestamp >= start_date)
    if end_date:
        stmt = stmt.where(SpeedEvent.timestamp <= end_date)

    result = db.execute(stmt).first()

    return {
        "total_events": result.total_events or 0,
        "speeding_events": result.speeding_events or 0,
        "avg_speed": float(result.avg_speed) if result.avg_speed else 0.0,
        "max_speed": float(result.max_speed) if result.max_speed else 0.0,
        "min_speed": float(result.min_speed) if result.min_speed else 0.0
    }


def get_community_events(
    db: Session,
    limit: int = 50,
    offset: int = 0,
    hours: int = 24
) -> List[SpeedEvent]:
    """Get recent speeding events from community-sharing devices."""
    cutoff_time = datetime.now() - timedelta(hours=hours)

    stmt = select(SpeedEvent).join(Device).where(
        and_(
            Device.share_community == True,
            Device.is_active == True,
            SpeedEvent.is_speeding == True,
            SpeedEvent.timestamp >= cutoff_time
        )
    ).order_by(SpeedEvent.timestamp.desc()).offset(offset).limit(limit)

    return list(db.scalars(stmt))


# ============================================================================
# Report CRUD Operations
# ============================================================================

def create_report(
    db: Session,
    user_id: UUID,
    device_id: UUID,
    start_date: date,
    end_date: date,
    total_vehicles: int,
    speeding_vehicles: int,
    report_data: Optional[Dict] = None
) -> Report:
    """Create a new report."""
    report = Report(
        user_id=user_id,
        device_id=device_id,
        start_date=start_date,
        end_date=end_date,
        total_vehicles=total_vehicles,
        speeding_vehicles=speeding_vehicles,
        report_data=report_data
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def get_report_by_id(db: Session, report_id: UUID) -> Optional[Report]:
    """Get report by ID."""
    return db.get(Report, report_id)


def get_user_reports(
    db: Session,
    user_id: UUID,
    limit: int = 50,
    offset: int = 0
) -> List[Report]:
    """Get all reports for a user."""
    stmt = select(Report).where(Report.user_id == user_id)\
        .order_by(Report.created_at.desc())\
        .offset(offset)\
        .limit(limit)
    return list(db.scalars(stmt))


def get_device_reports(
    db: Session,
    device_id: UUID,
    limit: int = 50,
    offset: int = 0
) -> List[Report]:
    """Get all reports for a device."""
    stmt = select(Report).where(Report.device_id == device_id)\
        .order_by(Report.created_at.desc())\
        .offset(offset)\
        .limit(limit)
    return list(db.scalars(stmt))


# ============================================================================
# User Preference CRUD Operations
# ============================================================================

def create_user_preferences(db: Session, user_id: UUID) -> UserPreference:
    """Create default preferences for a new user."""
    prefs = UserPreference(user_id=user_id)
    db.add(prefs)
    db.commit()
    db.refresh(prefs)
    return prefs


def get_user_preferences(db: Session, user_id: UUID) -> Optional[UserPreference]:
    """Get user preferences."""
    return db.get(UserPreference, user_id)


def update_user_preferences(
    db: Session,
    user_id: UUID,
    **kwargs
) -> Optional[UserPreference]:
    """Update user preferences."""
    prefs = db.get(UserPreference, user_id)
    if prefs:
        for key, value in kwargs.items():
            if hasattr(prefs, key):
                setattr(prefs, key, value)
        db.commit()
        db.refresh(prefs)
    return prefs


# ============================================================================
# Device API Key CRUD Operations
# ============================================================================

def create_device_api_key(
    db: Session,
    device_id: UUID,
    api_key_hash: str,
    name: Optional[str] = None,
    expires_at: Optional[datetime] = None
) -> DeviceApiKey:
    """Create a new device API key."""
    api_key = DeviceApiKey(
        device_id=device_id,
        api_key_hash=api_key_hash,
        name=name,
        expires_at=expires_at
    )
    db.add(api_key)
    db.commit()
    db.refresh(api_key)
    return api_key


def get_device_api_key_by_hash(db: Session, api_key_hash: str) -> Optional[DeviceApiKey]:
    """Get device API key by hash."""
    stmt = select(DeviceApiKey).where(
        and_(
            DeviceApiKey.api_key_hash == api_key_hash,
            DeviceApiKey.is_active == True
        )
    )
    return db.scalar(stmt)


def get_device_by_api_key_hash(db: Session, api_key_hash: str) -> Optional[Device]:
    """
    Get device associated with an API key hash.

    This also validates that the API key is active and not expired.
    """
    stmt = select(Device).join(DeviceApiKey).where(
        and_(
            DeviceApiKey.api_key_hash == api_key_hash,
            DeviceApiKey.is_active == True,
            or_(
                DeviceApiKey.expires_at == None,
                DeviceApiKey.expires_at > datetime.utcnow()
            ),
            Device.is_active == True
        )
    )
    return db.scalar(stmt)


def update_api_key_last_used(db: Session, api_key_hash: str) -> None:
    """Update the last_used timestamp for an API key."""
    stmt = select(DeviceApiKey).where(DeviceApiKey.api_key_hash == api_key_hash)
    api_key = db.scalar(stmt)
    if api_key:
        api_key.last_used = datetime.utcnow()
        db.commit()


def deactivate_device_api_key(db: Session, api_key_id: UUID) -> bool:
    """Deactivate a device API key."""
    api_key = db.get(DeviceApiKey, api_key_id)
    if api_key:
        api_key.is_active = False
        db.commit()
        return True
    return False


def get_device_api_keys(db: Session, device_id: UUID, include_inactive: bool = False) -> List[DeviceApiKey]:
    """Get all API keys for a device."""
    stmt = select(DeviceApiKey).where(DeviceApiKey.device_id == device_id)
    if not include_inactive:
        stmt = stmt.where(DeviceApiKey.is_active == True)
    stmt = stmt.order_by(DeviceApiKey.created_at.desc())
    return list(db.scalars(stmt))


# ============================================================================
# Speed Event Advanced Operations
# ============================================================================

def check_duplicate_event(
    db: Session,
    device_id: UUID,
    timestamp: datetime,
    speed: float,
    tolerance_seconds: int = 5
) -> bool:
    """
    Check if a similar event already exists (duplicate detection).

    Args:
        db: Database session
        device_id: Device UUID
        timestamp: Event timestamp
        speed: Event speed
        tolerance_seconds: Time window for duplicate detection (default: 5 seconds)

    Returns:
        True if duplicate found, False otherwise
    """
    time_window_start = timestamp - timedelta(seconds=tolerance_seconds)
    time_window_end = timestamp + timedelta(seconds=tolerance_seconds)

    stmt = select(SpeedEvent).where(
        and_(
            SpeedEvent.device_id == device_id,
            SpeedEvent.timestamp >= time_window_start,
            SpeedEvent.timestamp <= time_window_end,
            SpeedEvent.speed == speed
        )
    ).limit(1)

    result = db.scalar(stmt)
    return result is not None


def create_speed_events_batch_safe(
    db: Session,
    device_id: UUID,
    events: List[Dict[str, Any]],
    check_duplicates: bool = True
) -> Dict[str, int]:
    """
    Create multiple speed events with optional duplicate checking.

    Args:
        db: Database session
        device_id: Device UUID
        events: List of event dictionaries
        check_duplicates: Whether to check for duplicates (default: True)

    Returns:
        Dictionary with counts: {"created": N, "skipped": M}
    """
    created = 0
    skipped = 0

    for event_data in events:
        # Add device_id to event data
        event_data["device_id"] = device_id

        # Check for duplicates if enabled
        if check_duplicates:
            is_duplicate = check_duplicate_event(
                db,
                device_id,
                event_data["timestamp"],
                event_data["speed"]
            )
            if is_duplicate:
                skipped += 1
                continue

        # Create the event
        event = SpeedEvent(**event_data)
        db.add(event)
        created += 1

    # Commit all at once for better performance
    if created > 0:
        db.commit()

    return {"created": created, "skipped": skipped}


# ============================================================================
# Global Statistics Operations
# ============================================================================

def update_global_statistics(db: Session) -> GlobalStatistics:
    """
    Compute and update global platform statistics.

    This should be called periodically (e.g., hourly) by a background task.
    """
    import random
    import math

    # Count all active devices
    total_devices_stmt = select(func.count(Device.id)).where(Device.is_active == True)
    total_devices = db.scalar(total_devices_stmt) or 0

    # Count community-sharing devices
    community_devices_stmt = select(func.count(Device.id)).where(
        and_(
            Device.is_active == True,
            Device.share_community == True
        )
    )
    community_devices = db.scalar(community_devices_stmt) or 0

    # Count all events
    total_events_stmt = select(func.count(SpeedEvent.id))
    total_events = db.scalar(total_events_stmt) or 0

    # Count speeding events
    speeding_events_stmt = select(func.count(SpeedEvent.id)).where(
        SpeedEvent.is_speeding == True
    )
    speeding_events = db.scalar(speeding_events_stmt) or 0

    # Get recent event stats (last 24 hours)
    cutoff_time = datetime.now() - timedelta(hours=24)
    recent_events_stmt = select(func.count(SpeedEvent.id)).where(
        SpeedEvent.timestamp >= cutoff_time
    )
    recent_events_24h = db.scalar(recent_events_stmt) or 0

    recent_speeding_stmt = select(func.count(SpeedEvent.id)).where(
        and_(
            SpeedEvent.timestamp >= cutoff_time,
            SpeedEvent.is_speeding == True
        )
    )
    recent_speeding_24h = db.scalar(recent_speeding_stmt) or 0

    # Generate anonymized device map data
    devices = get_community_devices(db)
    map_data = []

    for device in devices:
        # Skip devices without location
        if device.latitude is None or device.longitude is None:
            continue

        # Get device statistics (last 30 days)
        thirty_days_ago = datetime.now() - timedelta(days=30)
        stats = get_device_event_stats(db, device.id, thirty_days_ago, datetime.now())

        # Anonymize location by adding random offset within ~100m radius
        # Using approximate conversion: 1 degree latitude ≈ 111km
        # 100m = 0.0009 degrees latitude
        radius_degrees = 0.0009

        # Generate random offset
        angle = random.uniform(0, 2 * math.pi)
        distance = random.uniform(0, radius_degrees)

        lat_offset = distance * math.cos(angle)
        lng_offset = distance * math.sin(angle) / math.cos(math.radians(float(device.latitude)))

        anonymized_lat = float(device.latitude) + lat_offset
        anonymized_lng = float(device.longitude) + lng_offset

        map_data.append({
            "id": str(device.id),
            "device_id": device.device_id,
            "latitude": anonymized_lat,
            "longitude": anonymized_lng,
            "original_latitude": float(device.latitude),  # For radius circle
            "original_longitude": float(device.longitude),
            "street_name": device.street_name,
            "speed_limit": float(device.speed_limit) if device.speed_limit else None,
            "total_events": stats["total_events"],
            "speeding_events": stats["speeding_events"],
            "last_sync": device.last_sync.isoformat() if device.last_sync else None
        })

    # Store in statistics_data as JSON
    statistics_data = {
        "map_data": map_data,
        "generated_at": datetime.now().isoformat()
    }

    # Get or create statistics record (we only keep one row)
    stats_record = db.scalar(select(GlobalStatistics).limit(1))

    if stats_record:
        # Update existing record
        stats_record.total_devices = total_devices
        stats_record.community_devices = community_devices
        stats_record.total_events = total_events
        stats_record.speeding_events = speeding_events
        stats_record.recent_events_24h = recent_events_24h
        stats_record.recent_speeding_24h = recent_speeding_24h
        stats_record.statistics_data = statistics_data
        stats_record.updated_at = datetime.now()
    else:
        # Create new record
        stats_record = GlobalStatistics(
            total_devices=total_devices,
            community_devices=community_devices,
            total_events=total_events,
            speeding_events=speeding_events,
            recent_events_24h=recent_events_24h,
            recent_speeding_24h=recent_speeding_24h,
            statistics_data=statistics_data
        )
        db.add(stats_record)

    db.commit()
    db.refresh(stats_record)
    return stats_record


def get_global_statistics(db: Session) -> Optional[GlobalStatistics]:
    """Get the latest global statistics record."""
    return db.scalar(select(GlobalStatistics).limit(1))


def get_community_device_map_data(db: Session) -> List[Dict[str, Any]]:
    """
    Get anonymized device data for public map display.

    Returns cached map data from global statistics.
    """
    stats = get_global_statistics(db)
    if stats and stats.statistics_data:
        return stats.statistics_data.get("map_data", [])
    return []


def get_device_recent_speeders(
    db: Session,
    device_id: UUID,
    limit: int = 10
) -> List[SpeedEvent]:
    """
    Get the most recent speeding events for a device (for public display).

    Only includes events where the vehicle was going >5 mph over the speed limit.

    Args:
        db: Database session
        device_id: Device UUID
        limit: Number of events to return (default: 10)

    Returns:
        List of recent speeding events with photos (>5 mph over limit)
    """
    stmt = select(SpeedEvent).where(
        and_(
            SpeedEvent.device_id == device_id,
            SpeedEvent.is_speeding == True,
            (SpeedEvent.speed - SpeedEvent.speed_limit) > 5
        )
    ).order_by(SpeedEvent.timestamp.desc()).limit(limit)

    return list(db.scalars(stmt))


# ============================================================================
# Registration Code CRUD Operations
# ============================================================================

def create_registration_code(
    db: Session,
    code: str,
    max_uses: int = 1,
    expires_at: Optional[datetime] = None,
    created_by_id: Optional[UUID] = None,
    description: Optional[str] = None
) -> RegistrationCode:
    """Create a new registration code."""
    reg_code = RegistrationCode(
        code=code,
        max_uses=max_uses,
        expires_at=expires_at,
        created_by_id=created_by_id,
        description=description
    )
    db.add(reg_code)
    db.commit()
    db.refresh(reg_code)
    return reg_code


def get_registration_code_by_code(db: Session, code: str) -> Optional[RegistrationCode]:
    """Get a registration code by its code string."""
    stmt = select(RegistrationCode).where(RegistrationCode.code == code)
    return db.scalar(stmt)


def validate_and_use_registration_code(db: Session, code: str) -> bool:
    """
    Validate a registration code and increment its use count.

    Returns True if code is valid and was successfully used, False otherwise.
    """
    stmt = select(RegistrationCode).where(
        and_(
            RegistrationCode.code == code,
            RegistrationCode.is_active == True,
            RegistrationCode.current_uses < RegistrationCode.max_uses,
            or_(
                RegistrationCode.expires_at == None,
                RegistrationCode.expires_at > datetime.now()
            )
        )
    )
    reg_code = db.scalar(stmt)

    if reg_code:
        reg_code.current_uses += 1
        db.commit()
        return True
    return False


def get_all_registration_codes(
    db: Session,
    limit: int = 100,
    offset: int = 0,
    include_inactive: bool = False
) -> List[RegistrationCode]:
    """Get all registration codes (admin only)."""
    stmt = select(RegistrationCode)
    if not include_inactive:
        stmt = stmt.where(RegistrationCode.is_active == True)
    stmt = stmt.order_by(RegistrationCode.created_at.desc()).offset(offset).limit(limit)
    return list(db.scalars(stmt))


def update_registration_code(
    db: Session,
    code_id: UUID,
    **kwargs
) -> Optional[RegistrationCode]:
    """Update a registration code."""
    reg_code = db.get(RegistrationCode, code_id)
    if reg_code:
        for key, value in kwargs.items():
            if hasattr(reg_code, key) and key not in ['id', 'code', 'current_uses', 'created_at']:
                setattr(reg_code, key, value)
        db.commit()
        db.refresh(reg_code)
    return reg_code


def deactivate_registration_code(db: Session, code_id: UUID) -> bool:
    """Deactivate a registration code."""
    reg_code = db.get(RegistrationCode, code_id)
    if reg_code:
        reg_code.is_active = False
        db.commit()
        return True
    return False


def delete_registration_code(db: Session, code_id: UUID) -> bool:
    """Delete a registration code."""
    reg_code = db.get(RegistrationCode, code_id)
    if reg_code:
        db.delete(reg_code)
        db.commit()
        return True
    return False
