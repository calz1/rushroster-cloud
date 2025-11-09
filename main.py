"""Main application entry point for rushroster-cloud.

This module creates and configures the FastAPI application.
"""

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from contextlib import asynccontextmanager

from src.config import settings
from src.api import ingest, web, auth, web_ui, storage, admin
from src.api.web_ui import get_current_user_from_cookie
from src.database.session import engine, get_db
from src.database.models import Base, User
from src.database import crud
from src import auth_utils
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan context manager for startup and shutdown events.
    """
    # Startup
    print(f"Starting {settings.app_name} v{settings.app_version}")
    print(f"Environment: {settings.environment}")

    # Create database tables (in production, use Alembic migrations instead)
    if settings.environment == "development":
        print("Creating database tables...")
        Base.metadata.create_all(bind=engine)

    yield

    # Shutdown
    print("Shutting down application...")


# Create FastAPI application with docs disabled (we'll add them back with auth)
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Central cloud platform for speed monitoring system",
    lifespan=lifespan,
    docs_url=None,  # Disable default /docs
    redoc_url=None,  # Disable default /redoc
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allow_methods,
    allow_headers=settings.cors_allow_headers,
)


# Exception handlers
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Custom HTTP exception handler to ensure proper status codes."""
    # For 302 redirects, preserve the Location header
    if exc.status_code == 302:
        from fastapi.responses import RedirectResponse
        return RedirectResponse(
            url=exc.headers.get("Location", "/"),
            status_code=302
        )

    # For 403 errors, always return the proper status code
    if exc.status_code == 403:
        # Check if request accepts JSON
        accept = request.headers.get("accept", "")
        if "application/json" in accept or request.url.path.startswith("/api/"):
            return JSONResponse(
                status_code=403,
                content={"detail": exc.detail}
            )
        else:
            # For HTML requests, return plain text error
            return PlainTextResponse(
                status_code=403,
                content=f"403 Forbidden: {exc.detail}"
            )

    # For other HTTP exceptions, use default handler
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail}
    )


# Security for Bearer token (optional)
security = HTTPBearer(auto_error=False)


# Authentication helper for docs (supports both cookie and Bearer token)
async def get_authenticated_user_for_docs(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Get authenticated user from either cookie or Bearer token."""
    # Try cookie authentication first (for web UI users)
    user = await get_current_user_from_cookie(request, db)
    if user:
        return user

    # Try Bearer token authentication (for API users)
    if credentials:
        try:
            token = credentials.credentials
            payload = auth_utils.validate_access_token(token)
            user_id = UUID(payload.get("sub"))

            user = crud.get_user_by_id(db, user_id)
            if user:
                return user
        except:
            pass

    # No valid authentication found
    raise HTTPException(
        status_code=401,
        detail="Authentication required. Please login or provide a valid Bearer token."
    )


# Protected OpenAPI documentation endpoints
@app.get("/docs", include_in_schema=False)
async def get_swagger_documentation(
    request: Request,
    current_user: User = Depends(get_authenticated_user_for_docs)
):
    """Swagger UI documentation (requires authentication)."""
    return get_swagger_ui_html(openapi_url="/openapi.json", title=f"{settings.app_name} - Docs")


@app.get("/redoc", include_in_schema=False)
async def get_redoc_documentation(
    request: Request,
    current_user: User = Depends(get_authenticated_user_for_docs)
):
    """ReDoc documentation (requires authentication)."""
    return get_redoc_html(openapi_url="/openapi.json", title=f"{settings.app_name} - ReDoc")


@app.get("/openapi.json", include_in_schema=False)
async def get_openapi_schema(
    request: Request,
    current_user: User = Depends(get_authenticated_user_for_docs)
):
    """OpenAPI schema (requires authentication)."""
    return app.openapi()


# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment
    }


# Include routers
app.include_router(auth.router, prefix="/api")
app.include_router(admin.router, prefix="/api")
app.include_router(ingest.router, prefix="/api")
app.include_router(web.router, prefix="/api")
app.include_router(storage.router, prefix="/api")

# Include web UI router (no prefix - it handles HTML routes)
app.include_router(web_ui.router)

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")


def main():
    """Run the application using uvicorn."""
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug
    )


if __name__ == "__main__":
    main()
