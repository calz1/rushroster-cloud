"""Data ingestion API for receiving events from field devices.

This module handles:
- Batch upload of speed events from devices
- Photo upload coordination with pre-signed URLs
- Device heartbeat/status updates
"""

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Request
from pydantic import BaseModel, Field
from datetime import datetime
from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session

from src.database.session import get_db
from src.database import crud
from src.database.models import Device, SpeedEvent as SpeedEventModel
from src.api.auth import get_device_from_api_key
from src.storage.object_storage import ObjectStorageService, LocalStorageService
from src.config import settings


router = APIRouter(prefix="/ingest/v1", tags=["ingest"])


# ============================================================================
# Pydantic Models
# ============================================================================

class SpeedEvent(BaseModel):
    """Single speed event from a field device."""
    timestamp: datetime
    speed: float = Field(gt=0, description="Speed in mph")
    speed_limit: float = Field(gt=0, description="Speed limit in mph")
    is_speeding: bool
    has_photo: bool = False


class EventCreated(BaseModel):
    """Information about a created event."""
    event_id: UUID
    timestamp: datetime
    speed: float
    has_photo: bool


class BatchEventsRequest(BaseModel):
    """Batch upload request from a field device."""
    events: List[SpeedEvent] = Field(min_length=1, max_length=1000)


class BatchEventsResponse(BaseModel):
    """Response for batch event upload."""
    status: str
    processed: int
    duplicates_skipped: int
    created_events: List[EventCreated] = []


class PhotoUploadResponse(BaseModel):
    """Pre-signed URL for photo upload."""
    event_id: UUID
    upload_url: str
    photo_key: str
    expires_in: int = 3600


class HeartbeatRequest(BaseModel):
    """Device heartbeat/status update."""
    timestamp: datetime
    status: dict = Field(description="Device status information")


class HeartbeatResponse(BaseModel):
    """Response for heartbeat."""
    status: str
    message: str


# ============================================================================
# Helper Functions
# ============================================================================

def get_storage_service():
    """Get configured storage service (cloud or local)."""
    if settings.storage_provider == "local":
        return LocalStorageService(base_path=settings.storage_local_path)
    else:
        return ObjectStorageService(
            provider=settings.storage_provider,
            bucket_name=settings.storage_bucket_name,
            region=settings.storage_region,
            access_key=settings.storage_access_key or settings.aws_access_key_id,
            secret_key=settings.storage_secret_key or settings.aws_secret_access_key,
            endpoint_url=settings.storage_endpoint_url
        )


# ============================================================================
# Data Ingestion Endpoints
# ============================================================================

@router.post("/events", response_model=BatchEventsResponse)
async def upload_events(
    request: BatchEventsRequest,
    device: Device = Depends(get_device_from_api_key),
    db: Session = Depends(get_db)
):
    """
    Batch upload speed events from device.

    This endpoint:
    1. Validates device authentication via API key header (X-API-Key)
    2. Stores events in PostgreSQL with duplicate detection
    3. Returns event IDs for newly created events
    4. Updates device last_sync timestamp

    Authentication:
        Requires X-API-Key header with valid device API key

    Request body:
        - events: List of speed events (max 1000 per request)

    Returns:
        - Status information
        - Number of events processed
        - Number of duplicates skipped
        - Event IDs for created events (use these to upload photos)

    Photo Upload Workflow:
    1. POST /events with has_photo=true for events with photos
    2. Receive event_id in response
    3. POST /events/{event_id}/photo/url to get upload URL
    4. PUT photo to the pre-signed URL
    5. POST /events/{event_id}/photo/confirm to finalize
    """
    # Convert events to list and track indices
    events_data = []
    event_indices = []  # Track which request events map to which DB events

    for i, event in enumerate(request.events):
        event_dict = {
            "device_id": device.id,
            "timestamp": event.timestamp,
            "speed": event.speed,
            "speed_limit": event.speed_limit,
            "is_speeding": event.is_speeding,
            "photo_url": None
        }
        events_data.append(event_dict)
        event_indices.append((i, event.has_photo))

    # Create events with duplicate detection
    # We need to modify this to return the created event objects, not just counts
    created_count = 0
    skipped_count = 0
    created_events = []

    for i, event_data in enumerate(events_data):
        # Check for duplicates
        is_duplicate = crud.check_duplicate_event(
            db,
            device_id=device.id,
            timestamp=event_data["timestamp"],
            speed=event_data["speed"]
        )

        if is_duplicate:
            skipped_count += 1
            continue

        # Create the event
        event_obj = SpeedEventModel(**event_data)
        db.add(event_obj)
        db.flush()  # Flush to get the ID

        # Track created event
        has_photo = event_indices[i][1]
        created_events.append(
            EventCreated(
                event_id=event_obj.id,
                timestamp=event_obj.timestamp,
                speed=float(event_obj.speed),
                has_photo=has_photo
            )
        )
        created_count += 1

    # Commit all at once
    if created_count > 0:
        db.commit()

    # Update device last sync timestamp
    crud.update_device_last_sync(db, device.id)

    return BatchEventsResponse(
        status="success",
        processed=created_count,
        duplicates_skipped=skipped_count,
        created_events=created_events
    )


@router.post("/events/{event_id}/photo/url", response_model=PhotoUploadResponse)
async def request_photo_upload_url(
    event_id: UUID,
    request: Request,
    device: Device = Depends(get_device_from_api_key),
    db: Session = Depends(get_db)
):
    """
    Request a pre-signed URL for photo upload.

    This endpoint:
    1. Validates the event belongs to the authenticated device
    2. Generates a pre-signed S3/storage URL
    3. Returns the URL with a 1-hour expiration

    Authentication:
        Requires X-API-Key header with valid device API key

    Args:
        event_id: UUID of the speed event

    Returns:
        Pre-signed upload URL and storage key
    """
    # Get the event and verify it belongs to this device
    event = db.get(SpeedEventModel, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )

    if event.device_id != device.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Event does not belong to this device"
        )

    # Generate storage key and pre-signed URL
    storage = get_storage_service()
    photo_key = storage.generate_photo_key(device.id, event_id, extension="jpg")
    upload_url = storage.generate_presigned_upload_url(
        key=photo_key,
        expires_in=3600,
        content_type="image/jpeg"
    )

    # For local storage, convert relative URL to absolute URL
    if settings.storage_provider == "local" and upload_url.startswith("/"):
        # Get the base URL from the request
        base_url = f"{request.url.scheme}://{request.url.netloc}"
        upload_url = f"{base_url}{upload_url}"

    return PhotoUploadResponse(
        event_id=event_id,
        upload_url=upload_url,
        photo_key=photo_key,
        expires_in=3600
    )


@router.post("/events/{event_id}/photo/confirm")
async def confirm_photo_upload(
    event_id: UUID,
    photo_key: str,
    device: Device = Depends(get_device_from_api_key),
    db: Session = Depends(get_db)
):
    """
    Confirm that a photo has been uploaded and update the event record.

    This endpoint is called by the device after successfully uploading
    a photo to the pre-signed URL.

    Authentication:
        Requires X-API-Key header with valid device API key

    Args:
        event_id: UUID of the speed event
        photo_key: Storage key returned from the URL request endpoint

    Returns:
        Confirmation message with the permanent photo URL
    """
    # Get the event and verify it belongs to this device
    event = db.get(SpeedEventModel, event_id)
    if not event:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Event not found"
        )

    if event.device_id != device.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Event does not belong to this device"
        )

    # Generate the permanent URL for the photo
    storage = get_storage_service()
    photo_url = storage.get_storage_url(photo_key)

    # Update the event with the photo URL
    event.photo_url = photo_url
    db.commit()

    return {
        "status": "success",
        "message": "Photo URL updated",
        "photo_url": photo_url
    }


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def device_heartbeat(
    request: HeartbeatRequest,
    device: Device = Depends(get_device_from_api_key),
    db: Session = Depends(get_db)
):
    """
    Update device heartbeat and status.

    Devices send periodic heartbeats to indicate they're online
    and to report status information (disk space, sensor status, etc.).

    Authentication:
        Requires X-API-Key header with valid device API key

    Request body:
        - timestamp: Current device timestamp
        - status: Dict containing device status information

    Returns:
        Confirmation message
    """
    # Update device last sync timestamp
    crud.update_device_last_sync(db, device.id)

    # In the future, we could store status information in a separate table
    # or use it for monitoring/alerting

    return HeartbeatResponse(
        status="success",
        message=f"Heartbeat received from device {device.device_id}"
    )


@router.get("/device/info")
async def get_device_info(
    device: Device = Depends(get_device_from_api_key)
):
    """
    Get information about the authenticated device.

    This endpoint allows devices to verify their authentication
    and retrieve their configuration from the cloud.

    Authentication:
        Requires X-API-Key header with valid device API key

    Returns:
        Device information and configuration
    """
    return {
        "id": device.id,
        "device_id": device.device_id,
        "owner_id": device.owner_id,
        "location": {
            "latitude": float(device.latitude) if device.latitude else None,
            "longitude": float(device.longitude) if device.longitude else None,
            "street_name": device.street_name
        },
        "speed_limit": float(device.speed_limit) if device.speed_limit else None,
        "is_active": device.is_active,
        "share_community": device.share_community,
        "registered_at": device.registered_at,
        "last_sync": device.last_sync
    }


@router.get("/device/stats")
async def get_device_stats(
    device: Device = Depends(get_device_from_api_key),
    db: Session = Depends(get_db),
    hours: int = 24
):
    """
    Get statistics for the authenticated device.

    Authentication:
        Requires X-API-Key header with valid device API key

    Query params:
        hours: Number of hours to look back (default: 24)

    Returns:
        Event statistics for the device
    """
    from datetime import timedelta

    start_date = datetime.utcnow() - timedelta(hours=hours)
    stats = crud.get_device_event_stats(
        db,
        device_id=device.id,
        start_date=start_date
    )

    stats["period_hours"] = hours
    stats["device_id"] = device.device_id

    return stats


@router.get("/events")
async def get_device_events(
    device: Device = Depends(get_device_from_api_key),
    db: Session = Depends(get_db),
    limit: int = 100,
    offset: int = 0,
    speeding_only: bool = False
):
    """
    Get events for the authenticated device.

    This endpoint allows devices to retrieve their event history,
    useful for recovery after data loss or synchronization.

    Authentication:
        Requires X-API-Key header with valid device API key

    Query params:
        limit: Number of events to return per page (default: 100)
        offset: Number of events to skip for pagination (default: 0)
        speeding_only: Only return speeding events (default: false)

    Returns:
        Paginated list of speed events for this device, ordered by timestamp (newest first)

    Example:
        # Get first page (100 events)
        GET /ingest/v1/events?limit=100&offset=0

        # Get second page
        GET /ingest/v1/events?limit=100&offset=100

        # Get only speeding events
        GET /ingest/v1/events?speeding_only=true
    """
    # Validate parameters
    if limit < 1:
        limit = 1

    if offset < 0:
        offset = 0

    # Get events
    events = crud.get_device_events(
        db,
        device_id=device.id,
        limit=limit,
        offset=offset,
        speeding_only=speeding_only
    )

    # Convert to response format
    return {
        "device_id": device.device_id,
        "count": len(events),
        "limit": limit,
        "offset": offset,
        "speeding_only": speeding_only,
        "events": [
            {
                "id": event.id,
                "timestamp": event.timestamp,
                "speed": float(event.speed),
                "speed_limit": float(event.speed_limit),
                "is_speeding": event.is_speeding,
                "photo_url": event.photo_url,
                "created_at": event.created_at
            }
            for event in events
        ]
    }
