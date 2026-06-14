from sqlalchemy import Column, String, JSON, DateTime, func, Integer, Index
from database import Base  # Import the Base from your database module

class LoggedInUsers(Base):
    __tablename__ = 'logged_in_users'

    client_id = Column(String, primary_key=True)
    tokens = Column(JSON)
    last_updated = Column(DateTime, default=func.now(), onupdate=func.now())
    last_login_at = Column(DateTime, nullable=True)
    broker_no = Column(String)
    status = Column(String)
    message = Column(String)

    __table_args__ = (
        Index("ix_logged_in_users_status_last_updated", "status", "last_updated"),
    )
    
    def __repr__(self):
        return (f"<LoggedInUsers(client_id='{self.client_id}', tokens={self.tokens}, "
                f"last_updated={self.last_updated} "
                f"last_login_at={self.last_login_at} "
                f"broker_no='{self.broker_no}', status='{self.status}', "
                f"message='{self.message}')>")
