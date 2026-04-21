"""
数据库配置文件 - MySQL连接配置
支持环境变量配置、默认配置和连接池
"""

import pymysql
import os
import threading
from pymysql.cursors import DictCursor
from smart_logger import smart_print, LogLevel

# ==================== 连接池实现 ====================
class ConnectionPool:
    """简易MySQL连接池，支持多线程安全复用连接"""
    
    def __init__(self, max_size=10, **db_config):
        self._max_size = max_size
        self._db_config = db_config
        self._pool = []  # 空闲连接
        self._lock = threading.Lock()
        self._current_size = 0  # 当前已创建的连接总数
    
    def _create_connection(self):
        """创建新的数据库连接"""
        conn = pymysql.connect(
            host=self._db_config.get('host', 'localhost'),
            port=self._db_config.get('port', 3306),
            user=self._db_config.get('user', 'root'),
            password=self._db_config.get('password', ''),
            database=self._db_config.get('database', 'pdf_md_system'),
            charset=self._db_config.get('charset', 'utf8mb4'),
            cursorclass=DictCursor,
            autocommit=self._db_config.get('autocommit', True),
            connect_timeout=self._db_config.get('connect_timeout', 10),
            read_timeout=self._db_config.get('read_timeout', 60),
            write_timeout=self._db_config.get('write_timeout', 60)
        )
        cursor = conn.cursor()
        cursor.execute("SET time_zone = '+8:00'")
        cursor.close()
        return conn
    
    def get_connection(self):
        """从池中获取一个可用连接"""
        with self._lock:
            # 尝试从池中取一个空闲连接
            while self._pool:
                conn = self._pool.pop()
                try:
                    conn.ping(reconnect=False)
                    return conn
                except Exception:
                    self._current_size -= 1  # 连接已失效，减少计数
            
            # 池中无空闲连接，创建新连接（不超过上限）
            if self._current_size < self._max_size:
                self._current_size += 1
            else:
                # 已达上限，等待释放（简单策略：直接创建，不严格限制）
                pass
        
        # 在锁外创建连接（避免长时间持锁）
        return self._create_connection()
    
    def release_connection(self, conn):
        """归还连接到池中"""
        if conn is None:
            return
        try:
            conn.ping(reconnect=False)
            with self._lock:
                if len(self._pool) < self._max_size:
                    self._pool.append(conn)
                    return
            # 池已满，关闭多余连接
            conn.close()
            with self._lock:
                self._current_size -= 1
        except Exception:
            # 连接已断开，直接丢弃
            try:
                conn.close()
            except Exception:
                pass
            with self._lock:
                self._current_size -= 1
    
    def close_all(self):
        """关闭池中所有连接"""
        with self._lock:
            for conn in self._pool:
                try:
                    conn.close()
                except Exception:
                    pass
            self._pool.clear()
            self._current_size = 0

# 全局连接池实例（延迟初始化）
_connection_pool = None
_pool_init_lock = threading.Lock()


class DatabaseConfig:
    """数据库配置类"""
    
    # 默认配置（可通过环境变量覆盖）
    DEFAULT_CONFIG = {
        'host': 'localhost',
        'port': 3306,
        'database': 'pdf_md_system',
        'user': 'root',
        'password': '',
        'charset': 'utf8mb4',
        'autocommit': True,
        'connect_timeout': 10,
        'read_timeout': 60,      # 增加读取超时时间
        'write_timeout': 60,     # 增加写入超时时间
        'max_allowed_packet': 1024 * 1024 * 16,  # 16MB
        'sql_mode': 'STRICT_TRANS_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO'
    }
    
    @classmethod
    def get_config(cls):
        """获取数据库配置，优先使用环境变量"""
        config = cls.DEFAULT_CONFIG.copy()
        
        # 从环境变量读取配置（如果存在）
        env_config = {
            'host': os.getenv('DB_HOST'),
            'port': int(os.getenv('DB_PORT', 3306)),
            'database': os.getenv('DB_NAME'),
            'user': os.getenv('DB_USER'),
            'password': os.getenv('DB_PASSWORD'),
            'charset': os.getenv('DB_CHARSET', 'utf8mb4')
        }
        
        # 更新非空的环境变量配置
        for key, value in env_config.items():
            if value is not None:
                config[key] = value
        
        return config
    
    @classmethod
    def _get_pool(cls):
        """获取或初始化全局连接池"""
        global _connection_pool
        if _connection_pool is None:
            with _pool_init_lock:
                if _connection_pool is None:
                    config = cls.get_config()
                    _connection_pool = ConnectionPool(max_size=10, **config)
        return _connection_pool
    
    @classmethod
    def get_db_connection(cls, retry_count=3):
        """获取数据库连接（优先从连接池获取），支持重试"""
        last_error = None
        
        pool = cls._get_pool()
        
        for attempt in range(retry_count):
            try:
                connection = pool.get_connection()
                return connection
                
            except pymysql.Error as e:
                last_error = e
                smart_print(f"数据库连接失败 (尝试 {attempt + 1}/{retry_count}): {e}", LogLevel.WARNING)
                if attempt < retry_count - 1:
                    import time
                    time.sleep(1)
                    
            except Exception as e:
                last_error = e
                smart_print(f"数据库连接异常 (尝试 {attempt + 1}/{retry_count}): {e}", LogLevel.ERROR)
                if attempt < retry_count - 1:
                    import time
                    time.sleep(1)
        
        smart_print(f"数据库连接最终失败，已重试 {retry_count} 次: {last_error}", LogLevel.ERROR)
        return None
    
    @classmethod
    def release_db_connection(cls, conn):
        """归还连接到连接池（替代 conn.close()）"""
        if conn is None:
            return
        pool = cls._get_pool()
        pool.release_connection(conn)
    
    @classmethod
    def test_connection(cls):
        """测试数据库连接"""
        smart_print("数据库连接测试开始", LogLevel.DEBUG)
        conn = cls.get_db_connection()
        
        if conn:
            try:
                cursor = conn.cursor()
                cursor.execute("SELECT VERSION() as version, DATABASE() as current_db")
                result = cursor.fetchone()
                
                if result:
                    # 只在明确测试时才打印成功信息
                    smart_print(f"数据库连接测试成功! MySQL版本: {result['version']}, 数据库: {result['current_db']}", LogLevel.INFO)
                else:
                    smart_print("无法获取数据库版本信息", LogLevel.WARNING)
                    conn.close()
                    return False
                
                # 检查必要的表是否存在
                cursor.execute("SHOW TABLES")
                tables = [row for row in cursor.fetchall()]
                
                expected_tables = ['users', 'user_api_keys', 'user_files', 'system_logs']
                # 移除已废弃的表：processing_tasks（纯内存管理），file_records（旧版本）
                legacy_tables = ['file_records', 'processing_tasks']
                existing_tables = [table[f'Tables_in_{cls.get_config()["database"]}'] for table in tables]
                
                smart_print(f"现有表: {existing_tables}", LogLevel.DEBUG)
                
                missing_tables = [table for table in expected_tables if table not in existing_tables]
                if missing_tables:
                    smart_print(f"缺失的表: {missing_tables}", LogLevel.WARNING)
                    smart_print("请运行database_setup.sql文件创建缺失的表", LogLevel.INFO)
                else:
                    smart_print("所有必要的表都已存在", LogLevel.DEBUG)
                
                # 检查是否存在旧版本的表
                legacy_found = [table for table in legacy_tables if table in existing_tables]
                if legacy_found:
                    smart_print(f"发现旧版本表: {legacy_found} (可选，用于兼容性)", LogLevel.DEBUG)
                
                conn.close()
                return True
                
            except Exception as e:
                smart_print(f"数据库查询测试失败: {e}", LogLevel.ERROR)
                conn.close()
                return False
        else:
            smart_print("数据库连接测试失败", LogLevel.ERROR)
            return False
    
    @classmethod
    def init_database(cls):
        """初始化数据库（检查连接和表结构）"""
        smart_print("=== 数据库初始化检查 ===", LogLevel.INFO)
        
        if cls.test_connection():
            smart_print("数据库初始化检查完成", LogLevel.INFO)
            return True
        else:
            smart_print("数据库初始化检查失败", LogLevel.ERROR)
            smart_print("请检查：1. MySQL服务是否已启动 2. 数据库连接配置是否正确 3. 数据库和表是否已创建", LogLevel.INFO)
            return False


if __name__ == "__main__":
    # 直接运行此文件时进行数据库连接测试
    DatabaseConfig.init_database()
