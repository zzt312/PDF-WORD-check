"""
Gunicorn 生产环境配置
用法: gunicorn -c gunicorn_config.py app_pdf_md:app

注意事项:
- tasks_db 是进程内存变量，workers=1 保证数据一致性
- 如需多 worker，需将 tasks_db 迁移到 Redis
- threads 参数提供线程级并发，适合 I/O 密集型任务
"""

import os
import multiprocessing

# ==================== 基本配置 ====================
# 绑定地址和端口
bind = os.getenv('GUNICORN_BIND', '0.0.0.0:5001')

# Worker 数量: 因为 tasks_db 在进程内存中，只能用 1 个 worker
# 如果迁移到 Redis 后，可以改为: workers = multiprocessing.cpu_count() * 2 + 1
workers = 1

# 每个 worker 的线程数: 提供并发处理能力
threads = 8

# Worker 类型: gthread 支持多线程
worker_class = 'gthread'

# ==================== 超时配置 ====================
# Worker 超时时间（秒），文档处理可能较慢
timeout = 600

# 优雅关闭超时
graceful_timeout = 30

# Keep-alive 连接超时
keepalive = 5

# ==================== 日志配置 ====================
# 日志级别
loglevel = os.getenv('GUNICORN_LOG_LEVEL', 'info')

# 错误日志
errorlog = 'logs/gunicorn_error.log'

# 访问日志
accesslog = 'logs/gunicorn_access.log'

# 访问日志格式
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# ==================== 进程管理 ====================
# 预加载应用（加快 worker 启动，共享内存）
preload_app = True

# PID 文件
pidfile = 'logs/gunicorn.pid'

# 后台运行（生产环境建议用 systemd 管理，此处保持前台）
daemon = False

# ==================== 安全配置 ====================
# 限制请求体大小 (100MB，支持大文件上传)
limit_request_body = 100 * 1024 * 1024

# 限制请求行长度
limit_request_line = 8190

# 限制请求头数量
limit_request_fields = 100

# ==================== 钩子函数 ====================
def on_starting(server):
    """服务器启动前"""
    os.makedirs('logs', exist_ok=True)
    print("🚀 Gunicorn 服务器正在启动...")

def on_reload(server):
    """服务器重载时"""
    print("🔄 Gunicorn 服务器正在重载...")

def worker_exit(server, worker):
    """Worker 退出时"""
    print(f"👋 Worker {worker.pid} 已退出")
