from sqlalchemy import Column, Integer, String

from database import Base


class FrontendUser(Base):
    __tablename__ = 'frontend_users'

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)

    @classmethod
    def authenticate(cls, username: str, password: str, session):
        user = session.query(cls).filter(cls.username == username).first()
        if not user or user.password != password:
            return None
        return user