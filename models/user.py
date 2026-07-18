from sqlalchemy import Column, Integer, String, JSON, DateTime, func, event,Boolean, ForeignKey
from database import Base

class User(Base):
    __tablename__ = 'users'

    client_id = Column(String, primary_key=True)
    owner_user_id = Column(Integer, ForeignKey("frontend_users.id"), nullable=True, index=True)
    password = Column(String)
    broker_no = Column(String)
    auto_login=Column(Boolean)
    def __repr__(self):
        return f"<User(client_id='{self.client_id}', broker_no='{self.broker_no}')>"
