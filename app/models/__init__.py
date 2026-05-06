"""
Database models package.
Contains SQLAlchemy declarative models used to generate the database schema.
"""
from app.core.database import Base
from app.models.user import User
from app.models.fir import FIR
from app.models.police_station import PoliceStation
from app.models.fir_comment import FIRComment
from app.models.evidence import Evidence
from app.models.notification import Notification
from app.models.fcm_token import FCMToken
