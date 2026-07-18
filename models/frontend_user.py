from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, JSON, String, func
from database import Base

class FrontendUser(Base):
    __tablename__ = 'frontend_users'

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)
    role = Column(String, nullable=False, default="user")
    permissions = Column(JSON, nullable=False, default=list)
    managed_by_user_id = Column(Integer, ForeignKey("frontend_users.id"), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    token_version = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    last_login_at = Column(DateTime, nullable=True)

    @classmethod
    def authenticate(cls, username: str, password: str, session):
        from utils.auth import verify_password
        user = session.query(cls).filter(cls.username == username).first()
        if not user or not user.is_active or not verify_password(password, user.password):
            return None
        return user
