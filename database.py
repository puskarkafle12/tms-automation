from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config.db_config import DATABASE_URL
from sqlalchemy.ext.declarative import declarative_base

engine = create_engine(DATABASE_URL, echo=True)
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()
db = SessionLocal()
def get_db():
    try:
        return db
    finally:
        db.close()