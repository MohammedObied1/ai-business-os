from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "AI Business Operating System"
    ENV: str = "development"
    DATABASE_URL: str = "sqlite:///./bizos.db"
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12
    CORS_ORIGINS: str = "http://localhost:3000"

    # Multi-company: only the platform admin creates companies unless public signup is enabled
    ALLOW_PUBLIC_SIGNUP: bool = False
    PLATFORM_ADMIN_EMAIL: str = "admin@bizos.local"
    PLATFORM_ADMIN_PASSWORD: str = "admin1234"  # used only to create the first admin; change it from the admin panel

    # AI
    ANTHROPIC_API_KEY: str | None = None
    AI_MODEL: str = "claude-opus-5"

    # Automation
    AUTOMATION_INTERVAL_MINUTES: int = 15
    UPLOAD_DIR: str = "./uploads"

    # Backups (default folder: %LOCALAPPDATA%\BizOS\backups, outside OneDrive)
    BACKUP_DIR: str | None = None
    BACKUP_KEEP: int = 30  # kept for compatibility; retention is now tiered (daily/weekly/monthly), see services/backup.py
    BACKUP_DAILY_KEEP: int = 7
    BACKUP_WEEKLY_KEEP: int = 8
    BACKUP_MONTHLY_KEEP: int = 12
    BACKUP_ENCRYPTION_KEY: str | None = None  # Fernet key (44 chars, urlsafe base64); unset = backups are stored unencrypted

    # Public address of the web app, used in links sent to customers (WhatsApp invoice links)
    PUBLIC_APP_URL: str = "http://localhost:3000"

    # Email (leave SMTP_HOST empty to keep emails in the outbox only)
    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str | None = None
    SMTP_TLS: bool = True

    # Login protection
    LOGIN_MAX_ATTEMPTS: int = 5
    LOGIN_LOCK_MINUTES: int = 15

    # Error monitoring (optional): https://sentry.io DSN
    SENTRY_DSN: str | None = None

    # Run the background scheduler in this process (with several API workers, enable it in exactly one of them)
    SCHEDULER_ENABLED: bool = True
    # JSON log lines (recommended on servers); plain text locally
    JSON_LOGS: bool = False


settings = Settings()
