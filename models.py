from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, Enum, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

Base = declarative_base()

class UserRole(str, enum.Enum):
    ADMIN = "admin"
    JUDGE = "judge"
    PLAYER = "player"

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    role = Column(Enum(UserRole), default=UserRole.PLAYER)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    submissions = relationship("Submission", back_populates="user")

class Problem(Base):
    __tablename__ = "problems"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)
    input_format = Column(Text)
    output_format = Column(Text)
    sample_input = Column(Text)
    sample_output = Column(Text)
    time_limit = Column(Integer, default=1000)  # 毫秒
    memory_limit = Column(Integer, default=256)  # MB
    total_score = Column(Float, default=100.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    testcases = relationship("TestCase", back_populates="problem")
    submissions = relationship("Submission", back_populates="problem")

class TestCase(Base):
    __tablename__ = "testcases"
    
    id = Column(Integer, primary_key=True, index=True)
    problem_id = Column(Integer, ForeignKey("problems.id"), nullable=False)
    input_data = Column(Text, nullable=False)
    expected_output = Column(Text, nullable=False)
    score = Column(Float, default=1.0)  # 单个测试用例分值
    is_sample = Column(Boolean, default=False)  # 是否为样例用例
    order = Column(Integer, default=0)
    
    problem = relationship("Problem", back_populates="testcases")

class Submission(Base):
    __tablename__ = "submissions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    problem_id = Column(Integer, ForeignKey("problems.id"), nullable=False)
    code = Column(Text, nullable=False)
    language = Column(String(20), default="cpp")
    status = Column(String(20), default="pending")  # pending, compiling, running, finished, error
    score = Column(Float, default=0.0)
    compile_output = Column(Text)
    test_results = Column(Text)  # JSON 存储每个用例结果
    submitted_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("User", back_populates="submissions")
    problem = relationship("Problem", back_populates="submissions")