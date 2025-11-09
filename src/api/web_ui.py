"""Web UI routes using HTMX for interactive dashboard.

This module provides HTML-based routes for:
- Authentication (login, register, logout)
- Dashboard homepage with device list
- Device management
- Event browsing with filtering
- Statistics and charts
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Form
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime, timedelta, date
from uuid import UUID
import secrets

from ..database.session import get_db
from ..database import crud
from ..database.models import User, Device
from ..auth_utils import verify_password, hash_password, create_access_token, verify_token
from ..config import settings

router = APIRouter(tags=["web-ui"])
templates = Jinja2Templates(directory="templates")

# Session cookie name
SESSION_COOKIE_NAME = "rushroster_session"


# ============================================================================
# Authentication Dependencies
# ============================================================================

async def get_current_user_from_cookie(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[User]:
    """Get current user from session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None

    try:
        payload = verify_token(token)
        user_id = payload.get("sub")
        if not user_id:
            return None

        user = crud.get_user_by_id(db, UUID(user_id))
        return user
    except Exception:
        return None


async def require_auth(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """Require authentication for protected routes."""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
    return user


async def require_admin(
    request: Request,
    db: Session = Depends(get_db)
) -> User:
    """Require admin privileges for protected routes."""
    user = await get_current_user_from_cookie(request, db)
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/auth/login"})
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user


# ============================================================================
# Authentication Routes
# ============================================================================

@router.get("/auth/login", response_class=HTMLResponse)
async def login_page(request: Request, db: Session = Depends(get_db)):
    """Display login page."""
    user = await get_current_user_from_cookie(request, db)
    if user:
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse("auth/login.html", {
        "request": request,
        "current_user": None
    })


@router.post("/auth/login")
async def login(
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle login form submission."""
    # Find user by email
    user = crud.get_user_by_email(db, email)
    if not user or not verify_password(password, user.password_hash):
        return JSONResponse(
            {"success": False, "message": "Invalid email or password"},
            status_code=401
        )

    # Update last login
    crud.update_user_last_login(db, user.id)

    # Create JWT token with extended expiration for cookie-based sessions
    # Use refresh token expiration time for the cookie to persist sessions longer
    from datetime import timedelta
    extended_token = create_access_token(
        {"sub": str(user.id)},
        expires_delta=timedelta(days=settings.jwt_refresh_token_expire_days)
    )

    # Return success response - cookie will be set by browser
    response = JSONResponse({
        "success": True,
        "message": "Login successful"
    })
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=extended_token,
        httponly=True,
        max_age=settings.jwt_refresh_token_expire_days * 24 * 60 * 60,  # 30 days default
        samesite="lax",
        secure=settings.environment == "production"  # Only use secure in production
    )
    return response


@router.get("/auth/register", response_class=HTMLResponse)
async def register_page(request: Request, db: Session = Depends(get_db)):
    """Display registration page."""
    user = await get_current_user_from_cookie(request, db)
    if user:
        return RedirectResponse(url="/", status_code=302)

    return templates.TemplateResponse("auth/register.html", {
        "request": request,
        "current_user": None
    })


@router.post("/auth/register")
async def register(
    email: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    registration_code: str = Form(...),
    db: Session = Depends(get_db)
):
    """Handle registration form submission."""
    # Validate registration code
    if not crud.validate_and_use_registration_code(db, registration_code):
        return JSONResponse(
            {"success": False, "message": "Invalid, expired, or fully-used registration code"},
            status_code=400
        )

    # Validate passwords match
    if password != confirm_password:
        return JSONResponse(
            {"success": False, "message": "Passwords do not match"},
            status_code=400
        )

    # Check password length
    if len(password) < 8:
        return JSONResponse(
            {"success": False, "message": "Password must be at least 8 characters"},
            status_code=400
        )

    # Check if user already exists
    existing_user = crud.get_user_by_email(db, email)
    if existing_user:
        return JSONResponse(
            {"success": False, "message": "Email already registered"},
            status_code=400
        )

    # Create user
    password_hash = hash_password(password)
    user = crud.create_user(db, email, password_hash)

    # Create default preferences
    crud.create_user_preferences(db, user.id)

    return JSONResponse({
        "success": True,
        "message": "Account created successfully"
    })


@router.get("/logout")
async def logout():
    """Handle logout."""
    response = RedirectResponse(url="/auth/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE_NAME)
    return response


# ============================================================================
# Public Routes (No Authentication Required)
# ============================================================================

@router.get("/", response_class=HTMLResponse)
async def public_home(
    request: Request,
    db: Session = Depends(get_db)
):
    """Display public homepage with community map."""
    # Check if user is logged in - if so, redirect to dashboard
    user = await get_current_user_from_cookie(request, db)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)

    # Get global statistics
    global_stats = crud.get_global_statistics(db)

    # If no stats exist, create initial stats
    if not global_stats:
        global_stats = crud.update_global_statistics(db)

    return templates.TemplateResponse("public/home.html", {
        "request": request,
        "current_user": None,
        "global_stats": global_stats
    })


@router.get("/public", response_class=HTMLResponse)
async def public_map(
    request: Request,
    db: Session = Depends(get_db)
):
    """Display public map page (accessible to authenticated users too)."""
    # Check if user is logged in
    user = await get_current_user_from_cookie(request, db)

    # Get global statistics
    global_stats = crud.get_global_statistics(db)

    # If no stats exist, create initial stats
    if not global_stats:
        global_stats = crud.update_global_statistics(db)

    return templates.TemplateResponse("public/home.html", {
        "request": request,
        "current_user": user,
        "global_stats": global_stats
    })


@router.get("/api/public/map-data", response_class=JSONResponse)
async def public_map_data(db: Session = Depends(get_db)):
    """API endpoint to get anonymized device map data."""
    map_data = crud.get_community_device_map_data(db)
    return JSONResponse({"devices": map_data})


@router.get("/public/location/{device_id}/speeders", response_class=HTMLResponse)
async def location_speeders(
    device_id: UUID,
    request: Request,
    db: Session = Depends(get_db)
):
    """Display recent speeders for a specific location."""
    # Check if user is logged in (optional)
    user = await get_current_user_from_cookie(request, db)

    # Get the device
    device = crud.get_device_by_id(db, device_id)

    # Check if device exists and is shared with community
    if not device or not device.share_community or not device.is_active:
        raise HTTPException(status_code=404, detail="Location not found")

    # Get recent speeders (last 10)
    speeders = crud.get_device_recent_speeders(db, device_id, limit=10)

    return templates.TemplateResponse("public/speeders.html", {
        "request": request,
        "current_user": user,
        "device": device,
        "speeders": speeders
    })


# ============================================================================
# Dashboard Routes
# ============================================================================

@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_home(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """Display dashboard homepage with device list."""
    # Get user's devices
    devices = crud.get_user_devices(db, current_user.id)

    # Get statistics for each device (last 24 hours)
    device_stats = []
    now = datetime.utcnow()
    yesterday = now - timedelta(days=1)

    for device in devices:
        stats = crud.get_device_event_stats(db, device.id, yesterday, now)
        device_stats.append({
            "device": device,
            "stats": stats
        })

    return templates.TemplateResponse("dashboard/home.html", {
        "request": request,
        "current_user": current_user,
        "device_stats": device_stats
    })


# ============================================================================
# Device Management Routes
# ============================================================================

@router.get("/devices", response_class=HTMLResponse)
async def devices_list(
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """Display device list page."""
    devices = crud.get_user_devices(db, current_user.id)

    return templates.TemplateResponse("devices/list.html", {
        "request": request,
        "current_user": current_user,
        "devices": devices
    })


@router.get("/devices/{device_id}", response_class=HTMLResponse)
async def device_detail(
    device_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """Display device detail page."""
    device = crud.get_device_by_id(db, device_id)
    if not device or device.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Device not found")

    # Get device statistics (last 30 days)
    now = datetime.utcnow()
    thirty_days_ago = now - timedelta(days=30)
    stats = crud.get_device_event_stats(db, device.id, thirty_days_ago, now)

    # Get recent events
    recent_events = crud.get_device_events(db, device.id, limit=10)

    # Get API keys
    api_keys = crud.get_device_api_keys(db, device.id)

    return templates.TemplateResponse("devices/detail.html", {
        "request": request,
        "current_user": current_user,
        "device": device,
        "stats": stats,
        "recent_events": recent_events,
        "api_keys": api_keys
    })


@router.get("/devices/register/form", response_class=HTMLResponse)
async def device_register_form(
    request: Request,
    current_user: User = Depends(require_auth)
):
    """Display device registration form (HTMX modal)."""
    return templates.TemplateResponse("devices/register_form.html", {
        "request": request,
        "current_user": current_user
    })


@router.post("/devices/register")
async def device_register(
    device_id: str = Form(...),
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    street_name: Optional[str] = Form(None),
    speed_limit: Optional[float] = Form(None),
    share_community: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """Handle device registration form submission."""
    # Check if device_id already exists
    existing = crud.get_device_by_device_id(db, device_id)
    if existing:
        return JSONResponse(
            {"success": False, "message": "Device ID already registered"},
            status_code=400
        )

    # Generate API key
    from ..auth_utils import generate_api_key, hash_api_key
    api_key = generate_api_key()
    api_key_hash = hash_api_key(api_key)

    # Create device
    device = crud.create_device(
        db,
        device_id=device_id,
        owner_id=current_user.id,
        api_key_hash=api_key_hash,
        latitude=latitude,
        longitude=longitude,
        street_name=street_name,
        speed_limit=speed_limit,
        share_community=share_community
    )

    # Create API key record
    crud.create_device_api_key(db, device.id, api_key_hash, name="Primary API Key")

    return JSONResponse({
        "success": True,
        "message": "Device registered successfully",
        "device_id": str(device.id),
        "api_key": api_key
    })


@router.post("/devices/{device_id}/update")
async def device_update(
    device_id: UUID,
    latitude: Optional[float] = Form(None),
    longitude: Optional[float] = Form(None),
    street_name: Optional[str] = Form(None),
    speed_limit: Optional[float] = Form(None),
    share_community: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """Update device settings."""
    device = crud.get_device_by_id(db, device_id)
    if not device or device.owner_id != current_user.id:
        return JSONResponse(
            {"success": False, "message": "Device not found"},
            status_code=404
        )

    # Update device
    crud.update_device(
        db,
        device_id,
        latitude=latitude,
        longitude=longitude,
        street_name=street_name,
        speed_limit=speed_limit,
        share_community=share_community
    )

    return JSONResponse({
        "success": True,
        "message": "Device updated successfully"
    })


# ============================================================================
# Event Browsing Routes
# ============================================================================

@router.get("/events", response_class=HTMLResponse)
async def events_list(
    request: Request,
    device_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    speeding_only: bool = False,
    page: int = 1,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """Display event list page with filtering."""
    # Get user's devices
    devices = crud.get_user_devices(db, current_user.id)

    # Parse dates
    start_dt = datetime.fromisoformat(start_date) if start_date else None
    end_dt = datetime.fromisoformat(end_date) if end_date else None

    # Get events for selected device or all devices
    events = []
    if device_id:
        device_uuid = UUID(device_id)
        device = crud.get_device_by_id(db, device_uuid)
        if device and device.owner_id == current_user.id:
            events = crud.get_device_events(
                db,
                device_uuid,
                limit=50,
                offset=(page - 1) * 50,
                start_date=start_dt,
                end_date=end_dt,
                speeding_only=speeding_only
            )
    else:
        # Get events from all user devices
        for device in devices[:5]:  # Limit to first 5 devices for performance
            device_events = crud.get_device_events(
                db,
                device.id,
                limit=10,
                offset=0,
                start_date=start_dt,
                end_date=end_dt,
                speeding_only=speeding_only
            )
            events.extend(device_events)

        # Sort by timestamp
        events.sort(key=lambda e: e.timestamp, reverse=True)

    return templates.TemplateResponse("events/list.html", {
        "request": request,
        "current_user": current_user,
        "devices": devices,
        "events": events,
        "selected_device_id": device_id,
        "start_date": start_date,
        "end_date": end_date,
        "speeding_only": speeding_only,
        "page": page
    })


@router.post("/events/delete-all")
async def delete_all_events(
    device_id: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """
    Delete all events for the authenticated user.

    If device_id is provided, only delete events for that device.
    Otherwise, delete all events from all user's devices.
    """
    from sqlalchemy import select, delete
    from ..database.models import SpeedEvent

    # Get user's devices
    devices = crud.get_user_devices(db, current_user.id)
    device_ids = [d.id for d in devices]

    if not device_ids:
        return JSONResponse({
            "success": False,
            "message": "No devices found"
        }, status_code=400)

    # Build delete query
    if device_id:
        # Delete events for specific device only
        device_uuid = UUID(device_id)

        # Verify device belongs to user
        if device_uuid not in device_ids:
            return JSONResponse({
                "success": False,
                "message": "Device not found or access denied"
            }, status_code=403)

        # Count events to be deleted
        count_stmt = select(func.count(SpeedEvent.id)).where(SpeedEvent.device_id == device_uuid)
        count = db.scalar(count_stmt) or 0

        # Delete events
        delete_stmt = delete(SpeedEvent).where(SpeedEvent.device_id == device_uuid)
    else:
        # Delete events for all user's devices
        from sqlalchemy import func

        # Count events to be deleted
        count_stmt = select(func.count(SpeedEvent.id)).where(SpeedEvent.device_id.in_(device_ids))
        count = db.scalar(count_stmt) or 0

        # Delete events
        delete_stmt = delete(SpeedEvent).where(SpeedEvent.device_id.in_(device_ids))

    # Execute deletion
    db.execute(delete_stmt)
    db.commit()

    return JSONResponse({
        "success": True,
        "message": f"Successfully deleted {count} event(s)",
        "count": count
    })


# ============================================================================
# Statistics Routes
# ============================================================================

@router.get("/stats", response_class=HTMLResponse)
async def stats_dashboard(
    request: Request,
    device_id: Optional[str] = None,
    period: str = "7d",
    db: Session = Depends(get_db),
    current_user: User = Depends(require_auth)
):
    """Display statistics dashboard with charts."""
    # Get user's devices
    devices = crud.get_user_devices(db, current_user.id)

    # Parse period
    now = datetime.utcnow()
    period_map = {
        "24h": timedelta(hours=24),
        "7d": timedelta(days=7),
        "30d": timedelta(days=30),
        "90d": timedelta(days=90)
    }
    period_delta = period_map.get(period, timedelta(days=7))
    start_date = now - period_delta

    # Get statistics for selected device or all devices
    if device_id:
        device_uuid = UUID(device_id)
        device = crud.get_device_by_id(db, device_uuid)
        if not device or device.owner_id != current_user.id:
            raise HTTPException(status_code=404, detail="Device not found")

        stats = crud.get_device_event_stats(db, device_uuid, start_date, now)
        device_list = [device]
    else:
        # Aggregate stats from all devices
        stats = {
            "total_events": 0,
            "speeding_events": 0,
            "avg_speed": 0.0,
            "max_speed": 0.0,
            "min_speed": 999.0
        }
        avg_speeds = []

        for device in devices:
            device_stats = crud.get_device_event_stats(db, device.id, start_date, now)
            stats["total_events"] += device_stats["total_events"]
            stats["speeding_events"] += device_stats["speeding_events"]
            stats["max_speed"] = max(stats["max_speed"], device_stats["max_speed"])
            if device_stats["min_speed"] > 0:
                stats["min_speed"] = min(stats["min_speed"], device_stats["min_speed"])
            if device_stats["avg_speed"] > 0:
                avg_speeds.append(device_stats["avg_speed"])

        if avg_speeds:
            stats["avg_speed"] = sum(avg_speeds) / len(avg_speeds)
        if stats["min_speed"] == 999.0:
            stats["min_speed"] = 0.0

        device_list = devices

    return templates.TemplateResponse("stats/dashboard.html", {
        "request": request,
        "current_user": current_user,
        "devices": device_list,
        "stats": stats,
        "selected_device_id": device_id,
        "period": period
    })


# ============================================================================
# Admin Routes
# ============================================================================

@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """Display admin dashboard."""
    from sqlalchemy import select, func

    # Get statistics
    total_users = db.scalar(select(func.count(User.id))) or 0
    admin_users = db.scalar(select(func.count(User.id)).where(User.is_admin == True)) or 0
    total_devices = db.scalar(select(func.count(Device.id))) or 0
    active_devices = db.scalar(select(func.count(Device.id)).where(Device.is_active == True)) or 0

    return templates.TemplateResponse("admin/dashboard.html", {
        "request": request,
        "current_user": admin_user,
        "stats": {
            "total_users": total_users,
            "admin_users": admin_users,
            "total_devices": total_devices,
            "active_devices": active_devices
        }
    })


@router.get("/admin/users", response_class=HTMLResponse)
async def admin_users_list(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """Display user management page."""
    users = crud.get_all_users(db, limit=100)

    # Add device count for each user
    user_data = []
    for user in users:
        user_devices = crud.get_user_devices(db, user.id)
        user_data.append({
            "user": user,
            "device_count": len(user_devices)
        })

    return templates.TemplateResponse("admin/users.html", {
        "request": request,
        "current_user": admin_user,
        "user_data": user_data
    })


@router.post("/admin/users/{user_id}/admin")
async def admin_toggle_admin_status(
    user_id: UUID,
    is_admin: bool = Form(...),
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """Toggle admin status for a user."""
    # Prevent self-demotion
    if user_id == admin_user.id and not is_admin:
        return JSONResponse(
            {"success": False, "message": "Cannot remove your own admin privileges"},
            status_code=400
        )

    user = crud.set_user_admin_status(db, user_id, is_admin)
    if not user:
        return JSONResponse(
            {"success": False, "message": "User not found"},
            status_code=404
        )

    return JSONResponse({
        "success": True,
        "message": f"User {'promoted to' if is_admin else 'demoted from'} admin"
    })


@router.delete("/admin/users/{user_id}")
async def admin_delete_user(
    user_id: UUID,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """Delete a user."""
    # Prevent self-deletion
    if user_id == admin_user.id:
        return JSONResponse(
            {"success": False, "message": "Cannot delete your own account"},
            status_code=400
        )

    success = crud.delete_user(db, user_id)
    if not success:
        return JSONResponse(
            {"success": False, "message": "User not found"},
            status_code=404
        )

    return JSONResponse({
        "success": True,
        "message": "User deleted successfully"
    })


@router.get("/admin/devices", response_class=HTMLResponse)
async def admin_devices_list(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """Display device management page."""
    devices = crud.get_all_devices(db, limit=100)

    # Add owner information
    device_data = []
    for device in devices:
        device_data.append({
            "device": device,
            "owner_email": device.owner.email if device.owner else "Unknown"
        })

    return templates.TemplateResponse("admin/devices.html", {
        "request": request,
        "current_user": admin_user,
        "device_data": device_data
    })


@router.delete("/admin/devices/{device_id}")
async def admin_delete_device(
    device_id: UUID,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """Delete a device."""
    success = crud.delete_device(db, device_id)
    if not success:
        return JSONResponse(
            {"success": False, "message": "Device not found"},
            status_code=404
        )

    return JSONResponse({
        "success": True,
        "message": "Device deleted successfully"
    })


@router.get("/admin/registration-codes", response_class=HTMLResponse)
async def admin_registration_codes_list(
    request: Request,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """Display registration code management page."""
    codes = crud.get_all_registration_codes(db, limit=100, include_inactive=True)

    return templates.TemplateResponse("admin/registration_codes.html", {
        "request": request,
        "current_user": admin_user,
        "codes": codes
    })


@router.post("/admin/registration-codes")
async def admin_create_registration_code(
    code: str = Form(...),
    max_uses: int = Form(1),
    description: Optional[str] = Form(None),
    expires_at: Optional[str] = Form(None),
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """Create a new registration code."""
    # Check if code already exists
    existing_code = crud.get_registration_code_by_code(db, code)
    if existing_code:
        return JSONResponse(
            {"success": False, "message": "Registration code already exists"},
            status_code=400
        )

    # Parse expiration date if provided
    expires_at_datetime = None
    if expires_at:
        try:
            from datetime import datetime
            expires_at_datetime = datetime.fromisoformat(expires_at)
        except ValueError:
            return JSONResponse(
                {"success": False, "message": "Invalid expiration date format"},
                status_code=400
            )

    # Create the code
    new_code = crud.create_registration_code(
        db,
        code=code,
        max_uses=max_uses,
        expires_at=expires_at_datetime,
        created_by_id=admin_user.id,
        description=description
    )

    return JSONResponse({
        "success": True,
        "message": "Registration code created successfully"
    })


@router.patch("/admin/registration-codes/{code_id}/toggle")
async def admin_toggle_registration_code(
    code_id: UUID,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """Toggle active status of a registration code."""
    from src.database.models import RegistrationCode
    code = db.get(RegistrationCode, code_id)
    if not code:
        return JSONResponse(
            {"success": False, "message": "Registration code not found"},
            status_code=404
        )

    code.is_active = not code.is_active
    db.commit()

    return JSONResponse({
        "success": True,
        "message": f"Registration code {'activated' if code.is_active else 'deactivated'}"
    })


@router.delete("/admin/registration-codes/{code_id}")
async def admin_delete_registration_code(
    code_id: UUID,
    db: Session = Depends(get_db),
    admin_user: User = Depends(require_admin)
):
    """Delete a registration code."""
    success = crud.delete_registration_code(db, code_id)
    if not success:
        return JSONResponse(
            {"success": False, "message": "Registration code not found"},
            status_code=404
        )

    return JSONResponse({
        "success": True,
        "message": "Registration code deleted successfully"
    })
