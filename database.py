from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from models import Base
import os

DATABASE_URL = "sqlite:///./ccsu_competition.db"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def init_db():
    """初始化数据库，创建所有表"""
    Base.metadata.create_all(bind=engine)

def get_db() -> Session:
    """依赖注入，获取数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()