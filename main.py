from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import json
from sqlalchemy.orm import Session

from database import init_db, get_db, SessionLocal  # ← 确保 SessionLocal 已导入
from models import User, UserRole, Problem, TestCase, Submission
from auth import (
    get_password_hash, create_access_token, get_current_user,
    require_any_user, require_judge_or_admin, require_admin
)
from compiler import compile_with_wasm
from task_queue import submit_compile_task
import pydantic
app = FastAPI(title="CCSU 编程竞赛平台", version="1.5.1 Pre1")

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化数据库
init_db()

# ============ Pydantic 模型 ============

class UserRegister(BaseModel):
    username: str
    password: str

class UserLogin(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    username: str
    role: str
    user_id: int

class ProblemCreate(BaseModel):
    title: str
    description: str
    input_format: Optional[str] = ""
    output_format: Optional[str] = ""
    sample_input: Optional[str] = ""
    sample_output: Optional[str] = ""
    time_limit: int = 1000
    memory_limit: int = 256
    total_score: float = 100.0
    testcases: List[dict] = []

class ProblemUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    input_format: Optional[str] = None
    output_format: Optional[str] = None
    sample_input: Optional[str] = None
    sample_output: Optional[str] = None
    time_limit: Optional[int] = None
    memory_limit: Optional[int] = None
    total_score: Optional[float] = None
    testcases: Optional[List[dict]] = None

class CodeSubmit(BaseModel):
    code: str
    problem_id: int
    compiler: str = "g++"

class SubmissionResponse(BaseModel):
    id: int
    problem_id: int
    problem_title: str
    username: str
    code: str
    status: str
    score: float
    compile_output: Optional[str]
    submitted_at: str

# ============ 用户 API ============

@app.post("/api/register", response_model=TokenResponse)
def register(user: UserRegister, db: Session = Depends(get_db)):
    """用户注册"""
    existing = db.query(User).filter(User.username == user.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")
    
    hashed_password = get_password_hash(user.password)
    new_user = User(
        username=user.username,
        password_hash=hashed_password,
        role=UserRole.PLAYER
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    
    token = create_access_token({"sub": str(new_user.id), "role": new_user.role.value})
    
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        username=new_user.username,
        role=new_user.role.value,
        user_id=new_user.id
    )

@app.post("/api/login", response_model=TokenResponse)
def login(user: UserLogin, db: Session = Depends(get_db)):
    """用户登录"""
    db_user = db.query(User).filter(User.username == user.username).first()
    if not db_user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    from auth import verify_password
    if not verify_password(user.password, db_user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    token = create_access_token({"sub": str(db_user.id), "role": db_user.role.value})
    
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        username=db_user.username,
        role=db_user.role.value,
        user_id=db_user.id
    )

@app.get("/api/user/me")
def get_me(current_user: User = Depends(require_any_user)):
    """获取当前用户信息"""
    return {
        "id": current_user.id,
        "username": current_user.username,
        "role": current_user.role.value
    }

# ============ 题目 API ============

@app.get("/api/problems")
def get_problems(db: Session = Depends(get_db)):
    """获取所有题目（公开）"""
    problems = db.query(Problem).all()
    return [
        {
            "id": p.id,
            "title": p.title,
            "total_score": p.total_score,
            "time_limit": p.time_limit,
            "memory_limit": p.memory_limit,
            "created_at": p.created_at.isoformat()
        }
        for p in problems
    ]

@app.get("/api/problems/{problem_id}")
def get_problem(problem_id: int, db: Session = Depends(get_db)):
    """获取单道题目详情"""
    problem = db.query(Problem).filter(Problem.id == problem_id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="题目不存在")
    
    testcases = db.query(TestCase).filter(TestCase.problem_id == problem_id).order_by(TestCase.order).all()
    
    return {
        "id": problem.id,
        "title": problem.title,
        "description": problem.description,
        "input_format": problem.input_format,
        "output_format": problem.output_format,
        "sample_input": problem.sample_input,
        "sample_output": problem.sample_output,
        "time_limit": problem.time_limit,
        "memory_limit": problem.memory_limit,
        "total_score": problem.total_score,
        "testcases": [
            {
                "id": tc.id,
                "input": tc.input_data,
                "expected": tc.expected_output,
                "score": tc.score,
                "is_sample": tc.is_sample
            }
            for tc in testcases
        ]
    }

@app.post("/api/problems")
def create_problem(
    problem: ProblemCreate,
    current_user: User = Depends(require_judge_or_admin),
    db: Session = Depends(get_db)
):
    """创建题目（管理员/裁判）"""
    new_problem = Problem(
        title=problem.title,
        description=problem.description,
        input_format=problem.input_format,
        output_format=problem.output_format,
        sample_input=problem.sample_input,
        sample_output=problem.sample_output,
        time_limit=problem.time_limit,
        memory_limit=problem.memory_limit,
        total_score=problem.total_score
    )
    db.add(new_problem)
    db.flush()
    
    for i, tc in enumerate(problem.testcases):
        testcase = TestCase(
            problem_id=new_problem.id,
            input_data=tc.get("input", ""),
            expected_output=tc.get("output", ""),
            score=tc.get("score", 0),
            is_sample=tc.get("is_sample", False),
            order=i
        )
        db.add(testcase)
    
    db.commit()
    db.refresh(new_problem)
    
    return {"id": new_problem.id, "message": "题目创建成功"}

@app.put("/api/problems/{problem_id}")
def update_problem(
    problem_id: int,
    problem: ProblemUpdate,
    current_user: User = Depends(require_judge_or_admin),
    db: Session = Depends(get_db)
):
    """更新题目（管理员/裁判）"""
    db_problem = db.query(Problem).filter(Problem.id == problem_id).first()
    if not db_problem:
        raise HTTPException(status_code=404, detail="题目不存在")
    
    for field, value in problem.dict(exclude_unset=True).items():
        if field != "testcases" and value is not None:
            setattr(db_problem, field, value)
    
    if problem.testcases is not None:
        db.query(TestCase).filter(TestCase.problem_id == problem_id).delete()
        for i, tc in enumerate(problem.testcases):
            testcase = TestCase(
                problem_id=problem_id,
                input_data=tc.get("input", ""),
                expected_output=tc.get("output", ""),
                score=tc.get("score", 0),
                is_sample=tc.get("is_sample", False),
                order=i
            )
            db.add(testcase)
    
    db_problem.updated_at = datetime.utcnow()
    db.commit()
    
    return {"message": "题目更新成功（已全局同步）"}

@app.delete("/api/problems/{problem_id}")
def delete_problem(
    problem_id: int,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """删除题目（仅管理员）"""
    problem = db.query(Problem).filter(Problem.id == problem_id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="题目不存在")
    
    db.query(TestCase).filter(TestCase.problem_id == problem_id).delete()
    db.delete(problem)
    db.commit()
    
    return {"message": "题目删除成功"}

# ============ 提交 API ============

@app.post("/api/submit")
def submit_code(
    submission: CodeSubmit,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """提交代码 - 入队编译"""
    problem = db.query(Problem).filter(Problem.id == submission.problem_id).first()
    if not problem:
        raise HTTPException(status_code=404, detail="题目不存在")
    
    new_submission = Submission(
        user_id=current_user.id,
        problem_id=submission.problem_id,
        code=submission.code,
        status="pending",
        score=0
    )
    db.add(new_submission)
    db.commit()
    db.refresh(new_submission)
    
    if submission.compiler == "wasm":
        new_submission.status = "pending_wasm"
        db.commit()
        return {
            "submission_id": new_submission.id,
            "status": "pending_wasm",
            "message": "代码已提交，请在前端使用 WASM 编译"
        }
    else:
        submit_compile_task(new_submission.id, submission.code, submission.problem_id, current_user.id)
        return {
            "submission_id": new_submission.id,
            "status": "queued",
            "message": "代码已提交，正在排队编译..."
        }

@app.get("/api/submissions/{submission_id}")
def get_submission(
    submission_id: int,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """获取提交详情"""
    submission = db.query(Submission).filter(Submission.id == submission_id).first()
    if not submission:
        raise HTTPException(status_code=404, detail="提交不存在")
    
    if submission.user_id != current_user.id and current_user.role not in [UserRole.ADMIN, UserRole.JUDGE]:
        raise HTTPException(status_code=403, detail="无权查看此提交")
    
    problem = db.query(Problem).filter(Problem.id == submission.problem_id).first()
    
    return {
        "id": submission.id,
        "problem_id": submission.problem_id,
        "problem_title": problem.title if problem else "未知题目",
        "username": current_user.username,
        "code": submission.code,
        "status": submission.status,
        "score": submission.score,
        "compile_output": submission.compile_output,
        "test_results": json.loads(submission.test_results) if submission.test_results else None,
        "submitted_at": submission.submitted_at.isoformat()
    }

@app.get("/api/submissions")
def get_submissions(
    problem_id: Optional[int] = None,
    user_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 20,
    current_user: User = Depends(require_any_user),
    db: Session = Depends(get_db)
):
    """获取提交列表（分页）"""
    query = db.query(Submission)
    
    if current_user.role not in [UserRole.ADMIN, UserRole.JUDGE]:
        query = query.filter(Submission.user_id == current_user.id)
    
    if problem_id:
        query = query.filter(Submission.problem_id == problem_id)
    if user_id:
        query = query.filter(Submission.user_id == user_id)
    
    total = query.count()
    submissions = query.order_by(Submission.submitted_at.desc()).offset((page-1)*page_size).limit(page_size).all()
    
    result = []
    for sub in submissions:
        user = db.query(User).filter(User.id == sub.user_id).first()
        problem = db.query(Problem).filter(Problem.id == sub.problem_id).first()
        result.append({
            "id": sub.id,
            "problem_id": sub.problem_id,
            "problem_title": problem.title if problem else "未知",
            "username": user.username if user else "未知",
            "status": sub.status,
            "score": sub.score,
            "submitted_at": sub.submitted_at.isoformat()
        })
    
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": result
    }

# ============ 排名 API ============

@app.get("/api/rankings")
def get_rankings(
    problem_id: Optional[int] = None,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    """获取排名列表 - 按得分排序，同分按提交时间早优先"""
    query = db.query(
        Submission.user_id,
        User.username,
        User.role,
        db.func.sum(Submission.score).label("total_score"),
        db.func.max(Submission.submitted_at).label("last_submit")
    ).join(User, User.id == Submission.user_id)
    
    if problem_id:
        query = query.filter(Submission.problem_id == problem_id)
    
    query = query.filter(Submission.status == "finished")
    
    results = query.group_by(Submission.user_id, User.username, User.role).all()
    
    sorted_results = sorted(
        results,
        key=lambda x: (-x.total_score, x.last_submit)
    )[:limit]
    
    rankings = []
    rank = 1
    for r in sorted_results:
        rankings.append({
            "rank": rank,
            "user_id": r.user_id,
            "username": r.username,
            "role": r.role.value,
            "total_score": float(r.total_score),
            "last_submit": r.last_submit.isoformat() if r.last_submit else None
        })
        rank += 1
    
    return rankings

# ============ 编译器切换 API ============

@app.post("/api/compile/wasm")
def wasm_compile_check(data: dict, current_user: User = Depends(require_any_user)):
    """WASM 编译模式：代码安全检查"""
    code = data.get("code", "")
    result = compile_with_wasm(code)
    return result

# ============ 管理员初始化 ============

@app.on_event("startup")
def startup_event():
    """启动时初始化管理员账号"""
    from auth import get_password_hash
    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.username == "admin").first()
        if not admin:
            admin_user = User(
                username="admin",
                password_hash=get_password_hash("admin123"),
                role=UserRole.ADMIN
            )
            db.add(admin_user)
            db.commit()
            print("✅ 管理员账号已创建: admin / admin123")
        
        problem_count = db.query(Problem).count()
        if problem_count == 0:
            default_problem = Problem(
                title="A + B 问题",
                description="计算两个整数的和。\n\n## 输入格式\n两个整数 a 和 b，用空格分隔。\n\n## 输出格式\n输出 a + b 的结果。",
                input_format="两个整数 a 和 b",
                output_format="一个整数，a + b 的值",
                sample_input="1 2",
                sample_output="3",
                time_limit=1000,
                memory_limit=256,
                total_score=100.0
            )
            db.add(default_problem)
            db.flush()
            
            testcases = [
                {"input": "1 2", "output": "3", "score": 25, "is_sample": True},
                {"input": "0 0", "output": "0", "score": 25, "is_sample": False},
                {"input": "100 200", "output": "300", "score": 25, "is_sample": False},
                {"input": "-5 10", "output": "5", "score": 25, "is_sample": False},
            ]
            
            for i, tc in enumerate(testcases):
                testcase = TestCase(
                    problem_id=default_problem.id,
                    input_data=tc["input"],
                    expected_output=tc["output"],
                    score=tc["score"],
                    is_sample=tc["is_sample"],
                    order=i
                )
                db.add(testcase)
            
            db.commit()
            print("✅ 示例题目已创建: A + B 问题")
            
    except Exception as e:
        print(f"初始化错误: {e}")
    finally:
        db.close()

# ============ 启动 ============
if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)