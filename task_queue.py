import asyncio
import threading
import queue as q
from typing import Dict, Any
import json
from datetime import datetime
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Submission, TestCase, Problem, User
from compiler import compile_and_run, CompilationResult

# 全局任务队列
task_queue = q.Queue()
task_results = {}  # 存储任务结果，用于轮询

class CompileTask:
    def __init__(self, submission_id: int, code: str, problem_id: int, user_id: int):
        self.submission_id = submission_id
        self.code = code
        self.problem_id = problem_id
        self.user_id = user_id
        self.status = "pending"  # pending, running, finished, error
        self.result = None
        self.created_at = datetime.utcnow()

def process_queue_worker():
    """后台线程：处理编译任务队列"""
    while True:
        try:
            task = task_queue.get(timeout=5)
            if task is None:
                continue
            
            process_task(task)
            task_queue.task_done()
            
        except q.Empty:
            continue
        except Exception as e:
            print(f"队列处理错误: {e}")

def process_task(task: CompileTask):
    """处理单个编译任务"""
    db = SessionLocal()
    try:
        # 更新状态为运行中
        submission = db.query(Submission).filter(Submission.id == task.submission_id).first()
        if submission:
            submission.status = "compiling"
            db.commit()
        
        # 获取测试用例
        testcases = db.query(TestCase).filter(TestCase.problem_id == task.problem_id).order_by(TestCase.order).all()
        problem = db.query(Problem).filter(Problem.id == task.problem_id).first()
        
        if not testcases:
            submission.status = "error"
            submission.compile_output = "该题目没有测试用例"
            db.commit()
            return
        
        # 准备测试用例数据
        tc_data = [
            {"input": tc.input_data, "expected": tc.expected_output}
            for tc in testcases
        ]
        
        time_limit = problem.time_limit if problem else 1000
        memory_limit = problem.memory_limit if problem else 256
        
        # 编译并运行
        result = compile_and_run(task.code, tc_data, time_limit, memory_limit)
        
        # 更新提交记录
        if submission:
            if result.success:
                # 计算总分（按测试用例得分）
                total_score = 0
                if result.test_results:
                    # 计算加权得分
                    for i, tc_result in enumerate(result.test_results):
                        if i < len(testcases):
                            tc = testcases[i]
                            if tc_result.get("passed", False):
                                total_score += tc.score
                            # 保存每个用例的详细结果
                    
                    # 归一化到题目总分
                    max_score = sum(tc.score for tc in testcases)
                    if max_score > 0:
                        final_score = (total_score / max_score) * problem.total_score
                    else:
                        final_score = 0
                else:
                    final_score = 0
                
                submission.score = final_score
                submission.status = "finished"
                submission.compile_output = result.output
                submission.test_results = json.dumps({
                    "details": result.test_results,
                    "time_ms": result.time_ms,
                    "memory_kb": result.memory_kb
                })
            else:
                submission.status = "error"
                submission.compile_output = result.error
            
            db.commit()
            
    except Exception as e:
        print(f"处理任务失败: {e}")
        if task:
            submission = db.query(Submission).filter(Submission.id == task.submission_id).first()
            if submission:
                submission.status = "error"
                submission.compile_output = f"系统错误: {str(e)}"
                db.commit()
    finally:
        db.close()

def submit_compile_task(submission_id: int, code: str, problem_id: int, user_id: int):
    """提交编译任务到队列"""
    task = CompileTask(submission_id, code, problem_id, user_id)
    task_queue.put(task)
    return task

# 启动后台线程
worker_thread = threading.Thread(target=process_queue_worker, daemon=True)
worker_thread.start()