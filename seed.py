"""
独立初始化脚本 - 可手动运行添加题目
python seed.py
"""
from database import SessionLocal, init_db
from models import User, UserRole, Problem, TestCase
from auth import get_password_hash

def seed_database():
    db = SessionLocal()
    try:
        # 创建管理员
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin = User(
                username="admin",
                password_hash=get_password_hash("admin123"),
                role=UserRole.ADMIN
            )
            db.add(admin)
        
        # 创建裁判
        judge = db.query(User).filter(User.username == "judge").first()
        if not judge:
            judge = User(
                username="judge",
                password_hash=get_password_hash("judge123"),
                role=UserRole.JUDGE
            )
            db.add(judge)
        
        db.commit()
        print("✅ 用户初始化完成")
        print("   admin / admin123 (管理员)")
        print("   judge / judge123 (裁判)")
        
    except Exception as e:
        print(f"错误: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    init_db()
    seed_database()