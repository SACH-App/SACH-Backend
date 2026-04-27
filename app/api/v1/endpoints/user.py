from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.core.security import get_password_hash, verify_password, create_access_token
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse, Token

router = APIRouter()

from app.services.nadra_service import verify_cnic

@router.post("/signup", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    """
    Register a new user.
    """
    # 1. Verify CNIC against Mock NADRA API (will raise 404 if invalid)
    # The nadra_service already handles caching and raising HTTPExceptions
    nadra_data = await verify_cnic(user_in.cnic)

    # 2. Check if user already exists in our database
    result = await db.execute(select(User).where(User.cnic == user_in.cnic))
    if result.scalars().first():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A user with this CNIC already exists in the SACH system.",
        )
    
    hashed_password = get_password_hash(user_in.password)
    db_user = User(
        cnic=user_in.cnic,
        full_name=user_in.full_name,
        phone=user_in.phone,
        role=user_in.role,
        password_hash=hashed_password
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

@router.post("/login", response_model=Token)
async def login_access_token(
    db: AsyncSession = Depends(get_db),
    form_data: OAuth2PasswordRequestForm = Depends()
):
    """
    OAuth2 compatible token login, get an access token for future requests.
    Note: map 'username' field in form to the user's CNIC.
    """
    result = await db.execute(select(User).where(User.cnic == form_data.username))
    user = result.scalars().first()
    
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect CNIC or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    access_token_expires = timedelta(minutes=60 * 24 * 7) # 7 days
    access_token = create_access_token(
        data={"sub": user.cnic}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/profile", response_model=UserResponse)
async def get_user_profile(current_user: User = Depends(get_current_active_user)):
    """
    Get current logged in user's profile information.
    """
    return current_user

from fastapi.security import OAuth2PasswordBearer
from app.core.redis import get_redis
import jwt
from app.core.config import settings

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/user/login")

@router.post("/logout")
async def logout(token: str = Depends(oauth2_scheme)):
    """
    Log out the user by blacklisting their current JWT token in Redis.
    """
    try:
        # Decode token to get expiration time
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=["HS256"])
        exp = payload.get("exp")
        
        # Calculate remaining time until token naturally expires
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).timestamp()
        ttl = int(exp - now)
        
        if ttl > 0:
            # Store the token in Redis with a TTL matching its natural expiration
            redis_client = get_redis()
            if redis_client:
                await redis_client.setex(f"blacklist:{token}", ttl, "revoked")
                
        return {"message": "Successfully logged out"}
    except jwt.PyJWTError:
        # If token is already invalid, just return success
        return {"message": "Successfully logged out"}
