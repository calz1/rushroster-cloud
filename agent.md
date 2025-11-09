# Agent Guide for rushroster-cloud

This document provides guidance for AI agents working on this project.

## Project Overview

rushroster-cloud is a FastAPI-based web application for tracking and managing speed monitoring devices. It includes:
- PostgreSQL database
- Local file storage for photos
- HTMX-based web UI
- Public community map with device sharing

## Container Management

This project uses **Podman** (not Docker) with `podman compose` commands.

### Starting the Application
```bash
podman compose up -d
```

### Stopping the Application
```bash
# Stop and remove containers
podman compose down

# Stop without removing (can restart later)
podman compose stop
```

### Checking Container Status
```bash
# List running containers
podman ps

# View logs
podman logs rushroster-app
podman logs rushroster-db
```

### Executing Commands in Containers
```bash
# Execute Python in the app container
podman exec rushroster-app python -c "..."

# Access the database
podman exec rushroster-db psql -U rushroster -d rushroster
```

### Restarting After Changes
When you modify configuration files (`.env`, `docker-compose.yml`), a simple restart won't pick up environment variable changes. You need to recreate:
```bash
podman compose up -d
```

## Development Environment

This project uses **uv** for Python package management (not pip or virtualenv).

### Running Commands Locally (if uv is installed)
```bash
uv run python -c "..."
uv run pytest
```

Note: If `uv` is not available on the host, use the containerized app instead with `podman exec rushroster-app`.

## Database Access

### Querying the Database
Always use the app container to access the database with Python/SQLAlchemy:

```bash
podman exec rushroster-app python -c "
from src.database.session import SessionLocal
from src.database.models import SpeedEvent
from sqlalchemy import select, text

db = SessionLocal()
# Your queries here
db.close()
"
```

### Direct PostgreSQL Access
```bash
podman exec rushroster-db psql -U rushroster -d rushroster -c "SELECT * FROM speed_events LIMIT 5;"
```

## File Storage

### Photo Storage Structure
- **Host location**: `./data/photos/`
- **Container location**: `/app/data/photos/`
- **Storage type**: Local filesystem (bind mount)

The `docker-compose.yml` uses a bind mount:
```yaml
volumes:
  - ./data:/app/data
```

### Photo URL Structure
Photos are served via the storage API:
- Database stores: `/api/storage/files/{device_id}/{year}/{month}/{event_id}.jpg`
- Filesystem location: `/app/data/photos/{device_id}/{year}/{month}/{event_id}.jpg`
- Note: No extra "photos/" prefix in the path - the base path already points to the photos directory

## Configuration

### Environment Variables
Configuration is in `.env` file. Key settings:

```bash
# Application
ENVIRONMENT=production
DEBUG=false

# Database
POSTGRES_DB=rushroster
POSTGRES_USER=rushroster
POSTGRES_PASSWORD=<generated>

# Storage (local filesystem)
STORAGE_PROVIDER=local
STORAGE_LOCAL_PATH=/app/data/photos  # Must be absolute path inside container

# Security
JWT_SECRET_KEY=<generated>
```

### Volumes
- `postgres_data`: Database data (named volume)
- `./data`: Application data including photos (bind mount)

## Project Structure

```
rushroster-cloud/
├── src/
│   ├── api/           # API routes (ingest, web, auth, storage, admin)
│   ├── database/      # Models, CRUD operations, session
│   ├── storage/       # Object storage service (local/S3/GCS)
│   └── config.py      # Application configuration
├── templates/         # Jinja2 HTML templates
├── static/           # Static assets (CSS, JS)
├── data/             # Local data directory (bind mount)
│   └── photos/       # Photo storage
├── main.py           # Application entry point
├── docker-compose.yml
├── Dockerfile
└── .env              # Environment configuration
```

## Common Tasks

### Updating Photo URLs in Database
If photo paths change:
```bash
podman exec rushroster-app python -c "
from src.database.session import SessionLocal
from sqlalchemy import text

db = SessionLocal()
result = db.execute(text('''
    UPDATE speed_events
    SET photo_url = REPLACE(photo_url, 'old_path', 'new_path')
    WHERE photo_url LIKE '%old_path%'
'''))
db.commit()
print(f'Updated {result.rowcount} records')
db.close()
"
```

### Checking Photo Files
```bash
# List photos in container
podman exec rushroster-app ls -la /app/data/photos/

# Check specific device photos
podman exec rushroster-app find /app/data/photos/{device_id} -type f | head -10
```

### Testing Photo URLs
```bash
# Test a photo URL
curl -I http://localhost:8000/api/storage/files/{device_id}/2025/10/photo.jpg
```

## Troubleshooting

### Photos Not Loading
1. Check volume mount: `podman exec rushroster-app ls /app/data/photos/`
2. Verify database URLs match filesystem: Query `photo_url` from `speed_events`
3. Check `STORAGE_LOCAL_PATH` in container: `podman exec rushroster-app env | grep STORAGE`
4. Test photo endpoint returns 200: `curl -I http://localhost:8000/api/storage/files/...`

### Database Connection Issues
1. Check database is running: `podman ps | grep rushroster-db`
2. Check connection string in app: `podman exec rushroster-app env | grep DATABASE_URL`
3. Verify database health: `podman exec rushroster-db pg_isready -U rushroster`

### Container Won't Start
1. Check logs: `podman logs rushroster-app`
2. Verify environment variables are set (especially `JWT_SECRET_KEY`)
3. Ensure database is healthy before app starts (depends_on with healthcheck)

## Important Notes

- Always use `podman compose` (not `docker compose`)
- Environment variable changes require `podman compose up -d` to recreate containers
- Photo paths in database should NOT include extra "photos/" prefix
- The app expects files at: `{STORAGE_LOCAL_PATH}/{key}` where key is like `{device_id}/2025/10/photo.jpg`
- Use `text()` wrapper for raw SQL queries in SQLAlchemy 2.x
