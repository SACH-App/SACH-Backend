from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.core.database import Base


class Evidence(Base):
    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True, index=True)
    fir_id = Column(Integer, ForeignKey("firs.id", ondelete="CASCADE"), nullable=False, index=True)
    uploaded_by = Column(Integer, ForeignKey("users.id"), nullable=False)
    file_url = Column(String(1000), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=False)  # e.g., image/jpeg, application/pdf
    file_size = Column(Integer, nullable=True)       # Size in bytes
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    fir = relationship("FIR", back_populates="evidence")
    uploader = relationship("User")
