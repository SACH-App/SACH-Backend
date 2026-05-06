import uuid
from datetime import datetime, timezone


def generate_tracking_number() -> str:
    """Generate a unique FIR tracking number like SACH-20260507-A1B2C3."""
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    unique_id = uuid.uuid4().hex[:6].upper()
    return f"SACH-{date_str}-{unique_id}"


def generate_reset_token() -> str:
    """Generate a secure random token for password reset."""
    return uuid.uuid4().hex


def generate_file_name(original_filename: str) -> str:
    """Generate a unique filename preserving the original extension."""
    ext = original_filename.rsplit(".", 1)[-1] if "." in original_filename else "bin"
    unique_id = uuid.uuid4().hex
    return f"{unique_id}.{ext}"
