from sqlalchemy import Column, String, JSON, DateTime, func,INTEGER

from database import Base


class LoggedInUsers(Base):
    __tablename__ = 'logged_in_users'

    client_id = Column(String, primary_key=True)
    tokens = Column(JSON)
    date_created=Column(DateTime,default=func.now())
    expires=Column(INTEGER)
    broker_no=Column(String)
    def __repr__(self):
        return f"<User(client_id='{self.client_id}', tokens={self.tokens}, date_created={self.date_created}, expires={self.expires}, broker_no={self.broker_no})>"
