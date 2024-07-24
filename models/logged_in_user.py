from sqlalchemy import Column, String, JSON, DateTime, func, Integer
from database import Base  # Import the Base from your database module

class LoggedInUsers(Base):
    __tablename__ = 'logged_in_users'

    client_id = Column(String, primary_key=True)
    tokens = Column(JSON)
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now())
    expires = Column(Integer)
    broker_no = Column(String)
    status = Column(String)
    message = Column(String)
    
    def __repr__(self):
        return (f"<LoggedInUsers(client_id='{self.client_id}', tokens={self.tokens}, "
                f"last_updated={self.last_updated}, expires={self.expires}, "
                f"broker_no='{self.broker_no}', status='{self.status}', "
                f"message='{self.message}')>")
