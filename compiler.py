import subprocess
import os
import tempfile
import shutil
import resource
import signal
import time
from typing import Dict, Tuple, Optional
import json

class CompilerError(Exception):
    pass

class CompilationResult:
    def __init__(self, success: bool, output: str = "", error: str = "", 
                 time_ms: int = 0, memory_kb: int = 0, test_results: list = None):
        self.success = success
        self.output = output
        self.error = error
        self.time_ms = time_ms
        self.memory_kb = memory_kb
        self.test_results = test_results or []

def compile_and_run(code: str, testcases: list, time_limit_ms: int = 1000, 
                    memory_limit_mb: int = 256) -> CompilationResult:
    """
    编译并运行 C++ 代码，对每个测试用例进行评测
    """
    temp_dir = tempfile.mkdtemp()
    source_file = os.path.join(temp_dir, "main.cpp")
    executable_file = os.path.join(temp_dir, "main")
    
    try:
        # 写入源代码
        with open(source_file, "w", encoding="utf-8") as f:
            f.write(code)
        
        # 编译
        compile_cmd = ["g++", "-std=c++17", "-O2", "-Wall", source_file, "-o", executable_file]
        compile_process = subprocess.run(
            compile_cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if compile_process.returncode != 0:
            return CompilationResult(
                success=False,
                error=f"编译错误:\n{compile_process.stderr}"
            )
        
        # 运行测试用例
        test_results = []
        total_time = 0
        total_memory = 0
        
        for i, tc in enumerate(testcases):
            result = run_testcase(executable_file, tc["input"], tc["expected"], 
                                  time_limit_ms, memory_limit_mb)
            result["index"] = i
            test_results.append(result)
            total_time += result.get("time_ms", 0)
            total_memory = max(total_memory, result.get("memory_kb", 0))
        
        # 计算总分
        total_score = sum(r.get("score", 0) for r in test_results)
        
        return CompilationResult(
            success=True,
            output="所有测试用例执行完成",
            time_ms=total_time,
            memory_kb=total_memory,
            test_results=test_results
        )
        
    except subprocess.TimeoutExpired:
        return CompilationResult(success=False, error="编译超时 (超过30秒)")
    except Exception as e:
        return CompilationResult(success=False, error=f"运行错误: {str(e)}")
    finally:
        # 清理临时文件
        shutil.rmtree(temp_dir, ignore_errors=True)


def run_testcase(executable: str, input_data: str, expected: str, 
                 time_limit_ms: int, memory_limit_mb: int) -> Dict:
    """
    运行单个测试用例
    """
    result = {
        "input": input_data,
        "expected": expected,
        "actual": "",
        "passed": False,
        "score": 0,
        "time_ms": 0,
        "memory_kb": 0,
        "error": ""
    }
    
    try:
        start_time = time.time()
        
        # 使用 subprocess 运行，设置资源限制
        process = subprocess.Popen(
            [executable],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        try:
            stdout, stderr = process.communicate(input=input_data, timeout=time_limit_ms / 1000)
            
            # 设置资源限制（Linux 下使用 prlimit，这里用简单的内存检查）
            # 实际生产环境建议使用 docker 或 cgroups 做更严格的隔离
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            memory_kb = 0  # 简化实现，不追踪内存
            
            result["time_ms"] = elapsed_ms
            result["actual"] = stdout.strip()
            result["memory_kb"] = memory_kb
            
            # 检查输出是否匹配（简单字符串比较，可扩展为 SPJ）
            if stdout.strip() == expected.strip():
                result["passed"] = True
                result["score"] = 1.0  # 该用例满分
            else:
                result["passed"] = False
                result["score"] = 0.0
                
            if stderr:
                result["error"] = stderr
                
        except subprocess.TimeoutExpired:
            process.kill()
            result["error"] = f"运行超时 (>{time_limit_ms}ms)"
            result["passed"] = False
            result["score"] = 0.0
            
    except Exception as e:
        result["error"] = str(e)
        result["passed"] = False
        result["score"] = 0.0
    
    return result


def compile_with_wasm(code: str) -> Dict:
    """
    前端 WASM 编译接口（后端转发）
    这里只做代码检查，实际编译在前端完成
    """
    # 检查代码是否包含危险的系统调用
    dangerous_patterns = [
        "fork", "exec", "system", "popen", "unlink", "remove",
        "fopen", "fclose", "fread", "fwrite", "fscanf", "fprintf"
    ]
    
    warnings = []
    for pattern in dangerous_patterns:
        if pattern in code:
            warnings.append(f"检测到潜在不安全的函数调用: {pattern}")
    
    return {
        "success": True,
        "warnings": warnings,
        "message": "代码已准备就绪，将在浏览器中编译执行"
    }