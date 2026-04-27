from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from typing import List

from app.api.deps import get_current_officer_user
from app.core.database import get_db
from app.models.user import User
from app.models.fir import FIR
from app.schemas.fir import FIRResponse, FIRStatusUpdate

router = APIRouter()

@router.get("/firs", response_model=List[FIRResponse])
async def get_all_firs(
    db: AsyncSession = Depends(get_db),
    current_officer: User = Depends(get_current_officer_user)
):
    """
    Get all FIRs across the entire system.
    Only accessible by Officers and Admins.
    """
    result = await db.execute(select(FIR).order_by(FIR.created_at.desc()))
    firs = result.scalars().all()
    return firs

@router.put("/firs/{fir_id}/status", response_model=FIRResponse)
async def update_fir_status(
    fir_id: int,
    status_update: FIRStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_officer: User = Depends(get_current_officer_user)
):
    """
    Update the status of a specific FIR.
    Only accessible by Officers and Admins.
    """
    result = await db.execute(select(FIR).where(FIR.id == fir_id))
    db_fir = result.scalars().first()
    
    if not db_fir:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="FIR not found"
        )
        
    db_fir.status = status_update.status
    db_fir.assigned_officer_id = current_officer.id
    
    db.add(db_fir)
    await db.commit()
    await db.refresh(db_fir)
    return db_fir
