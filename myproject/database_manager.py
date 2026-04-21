"""
数据库连接管理模块
提供数据库连接的统一管理、错误处理和资源释放功能
"""

import logging
from typing import Tuple, Optional, Any, Union
from flask import jsonify, Response
from database_config import DatabaseConfig


class DatabaseManager:
    """数据库连接管理器"""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """
        初始化数据库管理器
        
        Args:
            logger: 日志记录器，如果为None则使用默认的logging
        """
        self.logger = logger or logging.getLogger(__name__)
    
    def get_db_connection_with_error_handling(self) -> Tuple[Optional[Any], Optional[Response], Optional[int]]:
        """
        获取数据库连接，并进行错误处理
        
        Returns:
            tuple: (connection, error_response, status_code)
                - connection: 数据库连接对象，失败时为None
                - error_response: 错误响应对象，成功时为None
                - status_code: HTTP状态码，成功时为None
        """
        try:
            conn = DatabaseConfig.get_db_connection()
            if not conn:
                self.logger.error("数据库连接失败")
                return None, jsonify({'error': '数据库连接失败，请稍后重试'}), 500
            return conn, None, None
        except Exception as e:
            self.logger.error(f"获取数据库连接时发生异常: {str(e)}")
            return None, jsonify({'error': '数据库连接异常，请稍后重试'}), 500
    
    def safe_db_close(self, conn: Any, cursor: Any = None) -> None:
        """
        安全关闭数据库连接和游标
        
        Args:
            conn: 数据库连接对象
            cursor: 数据库游标对象（可选）
        """
        try:
            if cursor:
                cursor.close()
            if conn:
                conn.close()
        except Exception as e:
            self.logger.error(f"关闭数据库连接时出错: {str(e)}")
    
    def execute_query(self, query: str, params: Optional[tuple] = None, fetch_one: bool = False, fetch_all: bool = True):
        """
        执行数据库查询的通用方法
        
        Args:
            query: SQL查询语句
            params: 查询参数
            fetch_one: 是否只获取一条记录
            fetch_all: 是否获取所有记录
            
        Returns:
            tuple: (success, data, error_message)
        """
        conn = None
        cursor = None
        try:
            conn, error_response, status_code = self.get_db_connection_with_error_handling()
            if not conn:
                return False, None, "数据库连接失败"
            
            cursor = conn.cursor()
            cursor.execute(query, params or ())
            
            if fetch_one:
                data = cursor.fetchone()
            elif fetch_all:
                data = cursor.fetchall()
            else:
                data = None
            
            conn.commit()
            return True, data, None
            
        except Exception as e:
            error_msg = f"执行数据库查询时出错: {str(e)}"
            self.logger.error(error_msg)
            if conn:
                conn.rollback()
            return False, None, error_msg
        finally:
            self.safe_db_close(conn, cursor)
    
    def execute_transaction(self, queries_and_params: list):
        """
        执行数据库事务
        
        Args:
            queries_and_params: 查询语句和参数的列表，格式：[(query1, params1), (query2, params2), ...]
            
        Returns:
            tuple: (success, error_message)
        """
        conn = None
        cursor = None
        try:
            conn, error_response, status_code = self.get_db_connection_with_error_handling()
            if not conn:
                return False, "数据库连接失败"
            
            cursor = conn.cursor()
            
            # 开始事务
            conn.begin()
            
            # 执行所有查询
            for query, params in queries_and_params:
                cursor.execute(query, params or ())
            
            # 提交事务
            conn.commit()
            return True, None
            
        except Exception as e:
            error_msg = f"执行数据库事务时出错: {str(e)}"
            self.logger.error(error_msg)
            if conn:
                conn.rollback()
            return False, error_msg
        finally:
            self.safe_db_close(conn, cursor)


# 创建全局数据库管理器实例
db_manager = DatabaseManager()

# 为了保持向后兼容，导出原来的函数
def get_db_connection_with_error_handling():
    """
    获取数据库连接，并进行错误处理（兼容性函数）
    返回三个值：连接对象、错误响应、状态码
    """
    return db_manager.get_db_connection_with_error_handling()

def safe_db_close(conn, cursor=None):
    """
    安全关闭数据库连接和游标（兼容性函数）
    """
    db_manager.safe_db_close(conn, cursor)
