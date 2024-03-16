from sqlalchemy import Column, String, JSON, DateTime, func

from database import Base


class User(Base):
    __tablename__ = 'users'

    user_id = Column(String, primary_key=True)
    tokens = Column(JSON)
    date_created=Column(DateTime,default=func.now())
    def __repr__(self):
        return f"<User(user_id='{self.user_id}', tokens={self.tokens}, date_created={self.date_created})>"
