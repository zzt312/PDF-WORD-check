#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能日志管理系统
实现高优先级日志优化：静默化、去重、过滤
"""

import time
import hashlib
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from collections import defaultdict
import threading
import os
import glob

class LogLevel:
    """日志级别定义"""
    CRITICAL = "CRITICAL"
    ERROR = "ERROR" 
    WARNING = "WARNING"
    INFO = "INFO"
    DEBUG = "DEBUG"
    NOISE = "NOISE"  # 噪音级别，需要过滤

class SmartLogger:
    """智能日志管理器"""
    
    def __init__(self):
        # 重复日志检测
        self._log_cache = defaultdict(list)  # {log_hash: [timestamps]}
        self._cache_lock = threading.Lock()
        
        # 日志配置
        self.config = {
            'duplicate_threshold': 3,  # 相同日志3次后忽略
            'duplicate_window': 3600,  # 1小时窗口
            'noise_filters': [
                '数据库连接成功',
                '队列总数: 0',
                '24小时活跃用户: 1',
                'CPU使用率:', 
                '内存使用率:'
            ],
            'silent_patterns': [
                'localhost:3306',
                'connection.cursor()',
                'SELECT 1',
                'cursor.close()'
            ],
            # 自动清理配置
            'auto_cleanup_enabled': True,
            'cleanup_interval': 3600,  # 1小时清理一次
            'log_retention_days': 30,   # 保留30天的日志
            'max_cache_size': 1000,    # 最大缓存条目数
            'cleanup_on_startup': True  # 启动时自动清理
        }
        
        # 自动清理
        self._cleanup_timer = None
        self._last_cleanup = 0
        if self.config['cleanup_on_startup']:
            self._schedule_cleanup()
        
        # 环境模式
        self.mode = 'production'  # production / development
        
    def _hash_log(self, message: str, level: str) -> str:
        """生成日志哈希用于去重"""
        # 移除时间戳和动态内容进行去重
        clean_message = message
        # 移除常见的动态内容
        import re
        clean_message = re.sub(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', '', clean_message)
        clean_message = re.sub(r'\d+秒', 'X秒', clean_message)
        clean_message = re.sub(r'\d+\.?\d*%', 'X%', clean_message)
        clean_message = re.sub(r'用户: \d+', '用户: X', clean_message)
        
        return hashlib.md5(f"{level}:{clean_message}".encode()).hexdigest()
    
    def _is_duplicate(self, log_hash: str) -> bool:
        """检查是否为重复日志"""
        with self._cache_lock:
            now = time.time()
            timestamps = self._log_cache[log_hash]
            
            # 清理过期的时间戳
            timestamps[:] = [t for t in timestamps if now - t < self.config['duplicate_window']]
            
            # 检查是否超过阈值
            if len(timestamps) >= self.config['duplicate_threshold']:
                return True
            
            # 记录新的时间戳
            timestamps.append(now)
            return False
    
    def _is_noise(self, message: str) -> bool:
        """检查是否为噪音日志"""
        for pattern in self.config['noise_filters']:
            if pattern in message:
                return True
        return False
    
    def _should_silence(self, message: str) -> bool:
        """检查是否应该静默"""
        for pattern in self.config['silent_patterns']:
            if pattern in message:
                return True
        return False
    
    def log(self, level: str, message: str, context: Dict[str, Any] = None) -> bool:
        """智能日志记录
        
        Returns:
            bool: True if logged, False if filtered
        """
        # 1. 检查静默模式
        if self._should_silence(message):
            return False
            
        # 2. 检查噪音过滤
        if level == LogLevel.NOISE or self._is_noise(message):
            return False
            
        # 3. 检查重复日志
        log_hash = self._hash_log(message, level)
        if self._is_duplicate(log_hash):
            # 重复日志，只记录摘要
            if level in [LogLevel.CRITICAL, LogLevel.ERROR]:
                # 关键错误即使重复也要记录
                message = f"[重复] {message}"
            else:
                return False
        
        # 4. 环境过滤
        if self.mode == 'production' and level == LogLevel.DEBUG:
            return False
            
        # 5. 执行实际日志记录
        self._write_log(level, message, context)
        return True
    
    def _write_log(self, level: str, message: str, context: Dict[str, Any] = None):
        """实际写入日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level}] {message}"
        
        if context:
            log_entry += f" | Context: {context}"
            
        # 根据级别决定输出方式
        if level in [LogLevel.CRITICAL, LogLevel.ERROR]:
            print(f"🔴 {log_entry}")
        elif level == LogLevel.WARNING:
            print(f"🟡 {log_entry}")
        elif level == LogLevel.INFO:
            print(f"🔵 {log_entry}")
        else:
            print(f"⚪ {log_entry}")
    
    def get_stats(self) -> Dict[str, Any]:
        """获取日志统计信息"""
        with self._cache_lock:
            total_hashes = len(self._log_cache)
            total_logs = sum(len(timestamps) for timestamps in self._log_cache.values())
            
            return {
                'unique_log_types': total_hashes,
                'total_log_attempts': total_logs,
                'duplicate_prevention': f"{total_logs - total_hashes} duplicates filtered",
                'cache_size': total_hashes,
                'auto_cleanup_enabled': self.config['auto_cleanup_enabled'],
                'last_cleanup': datetime.fromtimestamp(self._last_cleanup).strftime('%Y-%m-%d %H:%M:%S') if self._last_cleanup else 'Never',
                'next_cleanup': 'In ' + str(int((self._last_cleanup + self.config['cleanup_interval'] - time.time()) / 60)) + ' minutes' if self.config['auto_cleanup_enabled'] and self._last_cleanup else 'Disabled'
            }
    
    def clear_cache(self):
        """清理缓存"""
        with self._cache_lock:
            self._log_cache.clear()
    
    def _schedule_cleanup(self):
        """调度自动清理任务"""
        if not self.config['auto_cleanup_enabled']:
            return
            
        def cleanup_task():
            try:
                self.auto_cleanup()
                # 调度下一次清理
                if self.config['auto_cleanup_enabled']:
                    self._cleanup_timer = threading.Timer(
                        self.config['cleanup_interval'], 
                        cleanup_task
                    )
                    self._cleanup_timer.daemon = True
                    self._cleanup_timer.start()
            except Exception as e:
                self._write_log(LogLevel.ERROR, f"自动清理任务失败: {e}")
        
        # 启动定时器
        if self._cleanup_timer:
            self._cleanup_timer.cancel()
        
        self._cleanup_timer = threading.Timer(
            self.config['cleanup_interval'], 
            cleanup_task
        )
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()
    
    def auto_cleanup(self):
        """执行自动清理"""
        now = time.time()
        
        # 检查是否需要清理
        if now - self._last_cleanup < self.config['cleanup_interval'] / 2:
            return
        
        cleanup_stats = {
            'cache_cleaned': 0,
            'old_logs_removed': 0,
            'memory_freed': 0
        }
        
        try:
            # 1. 清理过期的缓存条目
            with self._cache_lock:
                original_size = len(self._log_cache)
                
                # 清理过期时间戳
                for log_hash in list(self._log_cache.keys()):
                    timestamps = self._log_cache[log_hash]
                    timestamps[:] = [t for t in timestamps if now - t < self.config['duplicate_window']]
                    
                    # 如果没有有效时间戳，删除条目
                    if not timestamps:
                        del self._log_cache[log_hash]
                
                # 如果缓存过大，删除最旧的条目
                if len(self._log_cache) > self.config['max_cache_size']:
                    sorted_entries = sorted(
                        self._log_cache.items(),
                        key=lambda x: max(x[1]) if x[1] else 0
                    )
                    
                    # 保留最新的条目
                    keep_count = int(self.config['max_cache_size'] * 0.8)
                    to_keep = dict(sorted_entries[-keep_count:])
                    
                    self._log_cache.clear()
                    self._log_cache.update(to_keep)
                
                cleanup_stats['cache_cleaned'] = original_size - len(self._log_cache)
            
            # 2. 清理旧的日志文件（如果存在）
            cleanup_stats['old_logs_removed'] = self._cleanup_old_log_files()
            
            # 3. 计算内存释放估算
            cleanup_stats['memory_freed'] = cleanup_stats['cache_cleaned'] * 100  # 估算字节数
            
            self._last_cleanup = now
            
            # 记录清理结果
            if any(cleanup_stats.values()):
                self._write_log(
                    LogLevel.INFO,
                    f"日志自动清理完成: 缓存清理 {cleanup_stats['cache_cleaned']} 条, "
                    f"文件清理 {cleanup_stats['old_logs_removed']} 个, "
                    f"释放内存约 {cleanup_stats['memory_freed']} 字节"
                )
            
        except Exception as e:
            self._write_log(LogLevel.ERROR, f"自动清理过程中出错: {e}")
        
        return cleanup_stats
    
    def _cleanup_old_log_files(self):
        """清理旧的日志文件"""
        cleaned_count = 0
        
        try:
            # 获取当前工作目录
            current_dir = os.getcwd()
            
            # 查找日志文件模式
            log_patterns = [
                'logs/*.log',
                'logs/*.txt', 
                '*.log',
                'log_*.txt',
                '*_log_*.txt'
            ]
            
            retention_seconds = self.config['log_retention_days'] * 24 * 3600
            now = time.time()
            
            for pattern in log_patterns:
                for log_file in glob.glob(os.path.join(current_dir, pattern)):
                    try:
                        # 检查文件修改时间
                        file_mtime = os.path.getmtime(log_file)
                        if now - file_mtime > retention_seconds:
                            # 检查文件大小，如果很大则压缩而不是删除
                            file_size = os.path.getsize(log_file)
                            if file_size > 10 * 1024 * 1024:  # 大于10MB
                                # 尝试压缩而不是删除
                                self._compress_log_file(log_file)
                            else:
                                # 删除小文件
                                os.remove(log_file)
                                cleaned_count += 1
                    except Exception as e:
                        # 单个文件处理失败不影响整体清理
                        continue
                        
        except Exception as e:
            self._write_log(LogLevel.DEBUG, f"日志文件清理过程中的错误: {e}")
        
        return cleaned_count
    
    def _compress_log_file(self, log_file):
        """压缩日志文件"""
        try:
            import gzip
            import shutil
            
            compressed_file = log_file + '.gz'
            with open(log_file, 'rb') as f_in:
                with gzip.open(compressed_file, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # 删除原文件
            os.remove(log_file)
            self._write_log(LogLevel.DEBUG, f"日志文件已压缩: {log_file} -> {compressed_file}")
            
        except Exception as e:
            self._write_log(LogLevel.DEBUG, f"压缩日志文件失败 {log_file}: {e}")
    
    def manual_cleanup(self):
        """手动触发清理"""
        self._last_cleanup = 0  # 重置时间，强制执行清理
        return self.auto_cleanup()
    
    def stop_auto_cleanup(self):
        """停止自动清理"""
        self.config['auto_cleanup_enabled'] = False
        if self._cleanup_timer:
            self._cleanup_timer.cancel()
            self._cleanup_timer = None
    
    def start_auto_cleanup(self):
        """启动自动清理"""
        self.config['auto_cleanup_enabled'] = True
        self._schedule_cleanup()

# 全局智能日志实例
smart_logger = SmartLogger()

def smart_print(message: str, level: str = LogLevel.INFO, context: Dict[str, Any] = None):
    """智能打印函数，替换普通print"""
    return smart_logger.log(level, message, context)

def configure_logging(mode: str = 'production', config: Dict[str, Any] = None):
    """配置日志系统"""
    smart_logger.mode = mode
    if config:
        smart_logger.config.update(config)

# 使用示例和测试函数
def test_smart_logging():
    """测试智能日志系统"""
    print("=" * 60)
    print("智能日志系统测试")
    print("=" * 60)
    
    # 配置为开发模式
    configure_logging('development')
    
    print("\n1. 测试正常日志")
    smart_print("用户登录成功", LogLevel.INFO, {"user_id": 123})
    smart_print("处理文件开始", LogLevel.INFO, {"file": "test.pdf"})
    
    print("\n2. 测试重复日志过滤")
    for i in range(5):
        result = smart_print("队列总数: 0, 处理中: 0", LogLevel.INFO)
        print(f"  尝试 {i+1}: {'记录' if result else '过滤'}")
    
    print("\n3. 测试噪音过滤")
    smart_print("数据库连接成功: localhost:3306/test", LogLevel.INFO)
    smart_print("CPU使用率: 15.2%", LogLevel.INFO)
    
    print("\n4. 测试错误日志（重复也记录）")
    for i in range(3):
        result = smart_print("文件处理失败", LogLevel.ERROR)
        print(f"  错误 {i+1}: {'记录' if result else '过滤'}")
    
    print("\n5. 统计信息")
    stats = smart_logger.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print("\n" + "=" * 60)
    print("智能日志系统测试完成")
    print("=" * 60)

if __name__ == "__main__":
    test_smart_logging()
