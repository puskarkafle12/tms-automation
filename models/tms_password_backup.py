from sqlalchemy import Column, DateTime, Integer, String, func
from database import Base


class TmsPasswordBackup(Base):
    __tablename__ = "tms_password_backups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    client_id = Column(String, index=True)
    broker_no = Column(String)
    password = Column(String)
    rotation_label = Column(String)
    created_at = Column(DateTime, default=func.now())
