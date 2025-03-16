from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config.db_config import DATABASE_URL
from sqlalchemy.ext.declarative import declarative_base

engine = create_engine(DATABASE_URL, echo=True,    pool_size=50,
    max_overflow=20,       # Increase the overflow
    pool_timeout=60) 
 # Optional: echo for debugging
# Set up session factory with tracking setting
SessionLocal = sessionmaker(bind=engine)
Base = declarative_base()  # Added for model declaration
def get_db():
    db = SessionLocal()
    try:
        return db  # Return the session directly
    finally:
        db.close()

