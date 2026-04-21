#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库操作模块
提供所有数据库相关的CRUD操作函数
基于现有数据库表结构：users, user_files, group_api_keys, system_logs, migrations
注意：个人密钥功能已移除，所有API密钥通过分组统一管理
"""

import logging
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Union
from database_manager import get_db_connection_with_error_handling, safe_db_close
import json
import traceback
import os
import base64
import hashlib

# 配置日志
logger = logging.getLogger(__name__)

# ================================
# #22 API密钥加密（Fernet对称加密）
# ================================

def _get_fernet_key():
    """获取Fernet加密密钥（从环境变量或自动派生）"""
    from cryptography.fernet import Fernet
    
    # 优先使用专用环境变量
    env_key = os.environ.get('API_KEY_ENCRYPTION_KEY')
    if env_key:
        # 如果是有效的Fernet key（44字节base64），直接使用
        try:
            Fernet(env_key.encode() if isinstance(env_key, str) else env_key)
            return env_key.encode() if isinstance(env_key, str) else env_key
        except Exception:
            pass
    
    # 从Flask SECRET_KEY派生（确保32字节 → base64编码后44字节）
    secret = os.environ.get('SECRET_KEY', 'default-fallback-key-for-encryption')
    derived = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(derived)

def encrypt_api_token(plaintext: str) -> str:
    """加密API密钥令牌。如果加密失败，返回原文（不阻断使用）"""
    if not plaintext:
        return plaintext
    try:
        from cryptography.fernet import Fernet
        f = Fernet(_get_fernet_key())
        encrypted = f.encrypt(plaintext.encode())
        return encrypted.decode()  # gAAAAA... 格式的base64字符串
    except Exception as e:
        logger.warning(f"API密钥加密失败（将存储明文）: {e}")
        return plaintext

def decrypt_api_token(token: str) -> str:
    """解密API密钥令牌。兼容明文令牌（如未迁移的旧数据）"""
    if not token:
        return token
    # Fernet加密的token固定以 'gAAAAA' 开头
    if not token.startswith('gAAAAA'):
        return token  # 明文，直接返回
    try:
        from cryptography.fernet import Fernet
        f = Fernet(_get_fernet_key())
        decrypted = f.decrypt(token.encode())
        return decrypted.decode()
    except Exception as e:
        logger.warning(f"API密钥解密失败（可能是明文或密钥变更）: {e}")
        return token  # 解密失败时返回原文，避免阻断

# ================================
# 错误类型和错误处理系统
# ================================

class ErrorType:
    """错误类型常量"""
    # 数据库相关错误
    DB_CONNECTION_FAILED = "DB_CONNECTION_FAILED"
    DB_QUERY_FAILED = "DB_QUERY_FAILED" 
    DB_COMMIT_FAILED = "DB_COMMIT_FAILED"
    DB_CONSTRAINT_VIOLATION = "DB_CONSTRAINT_VIOLATION"
    DB_DUPLICATE_ENTRY = "DB_DUPLICATE_ENTRY"
    DB_FOREIGN_KEY_VIOLATION = "DB_FOREIGN_KEY_VIOLATION"
    DB_TABLE_NOT_EXISTS = "DB_TABLE_NOT_EXISTS"
    DB_COLUMN_NOT_EXISTS = "DB_COLUMN_NOT_EXISTS"
    
    # 用户相关错误
    USER_NOT_FOUND = "USER_NOT_FOUND"
    USER_ALREADY_EXISTS = "USER_ALREADY_EXISTS"
    USER_EMAIL_EXISTS = "USER_EMAIL_EXISTS"
    USER_INVALID_CREDENTIALS = "USER_INVALID_CREDENTIALS"
    USER_ACCOUNT_LOCKED = "USER_ACCOUNT_LOCKED"
    USER_INACTIVE = "USER_INACTIVE"
    USER_PERMISSION_DENIED = "USER_PERMISSION_DENIED"
    USER_SESSION_EXPIRED = "USER_SESSION_EXPIRED"
    USER_INVALID_TOKEN = "USER_INVALID_TOKEN"
    
    # 文件相关错误
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_ACCESS_DENIED = "FILE_ACCESS_DENIED"
    FILE_SIZE_EXCEEDED = "FILE_SIZE_EXCEEDED"
    FILE_TYPE_INVALID = "FILE_TYPE_INVALID"
    FILE_UPLOAD_FAILED = "FILE_UPLOAD_FAILED"
    FILE_PROCESSING_FAILED = "FILE_PROCESSING_FAILED"
    FILE_CORRUPTED = "FILE_CORRUPTED"
    FILE_STORAGE_FULL = "FILE_STORAGE_FULL"
    
    # API相关错误
    API_KEY_INVALID = "API_KEY_INVALID"
    API_KEY_EXPIRED = "API_KEY_EXPIRED"
    API_RATE_LIMITED = "API_RATE_LIMITED"
    API_QUOTA_EXCEEDED = "API_QUOTA_EXCEEDED"
    API_SERVICE_UNAVAILABLE = "API_SERVICE_UNAVAILABLE"
    API_REQUEST_FAILED = "API_REQUEST_FAILED"
    
    # 任务相关错误
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    TASK_ALREADY_COMPLETED = "TASK_ALREADY_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_TIMEOUT = "TASK_TIMEOUT"
    
    # 业务逻辑错误
    VALIDATION_FAILED = "VALIDATION_FAILED"
    OPERATION_NOT_ALLOWED = "OPERATION_NOT_ALLOWED"
    RESOURCE_LOCKED = "RESOURCE_LOCKED"
    INSUFFICIENT_RESOURCES = "INSUFFICIENT_RESOURCES"
    INPUT_INVALID = "INPUT_INVALID"
    PASSWORD_WEAK = "PASSWORD_WEAK"
    EMAIL_INVALID = "EMAIL_INVALID"
    
    # 系统错误
    SYSTEM_ERROR = "SYSTEM_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    TIMEOUT_ERROR = "TIMEOUT_ERROR"
    CONFIGURATION_ERROR = "CONFIGURATION_ERROR"
    STORAGE_ERROR = "STORAGE_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"

class ErrorSeverity:
    """错误严重程度"""
    LOW = "LOW"        # 低级别，用户输入错误等
    MEDIUM = "MEDIUM"  # 中级别，业务逻辑错误等
    HIGH = "HIGH"      # 高级别，系统错误等
    CRITICAL = "CRITICAL"  # 严重级别，数据库连接失败等

class ErrorHandler:
    """错误处理类"""
    
    # 错误消息映射表
    ERROR_MESSAGES = {
        # 数据库错误 - 用户看到的简化消息
        ErrorType.DB_CONNECTION_FAILED: "系统暂时无法连接数据库，请稍后重试",
        ErrorType.DB_QUERY_FAILED: "数据查询失败，请检查输入参数",
        ErrorType.DB_COMMIT_FAILED: "数据保存失败，请重试",
        ErrorType.DB_CONSTRAINT_VIOLATION: "数据完整性错误，请检查输入数据",
        ErrorType.DB_DUPLICATE_ENTRY: "数据已存在，请勿重复操作",
        ErrorType.DB_FOREIGN_KEY_VIOLATION: "相关数据不存在，无法完成操作",
        ErrorType.DB_TABLE_NOT_EXISTS: "数据表不存在，请联系管理员",
        ErrorType.DB_COLUMN_NOT_EXISTS: "数据字段不存在，请联系管理员",
        
        # 用户错误
        ErrorType.USER_NOT_FOUND: "用户不存在",
        ErrorType.USER_ALREADY_EXISTS: "用户名已被使用",
        ErrorType.USER_EMAIL_EXISTS: "邮箱已被注册",
        ErrorType.USER_INVALID_CREDENTIALS: "用户名或密码错误",
        ErrorType.USER_ACCOUNT_LOCKED: "账户已被锁定，请联系管理员",
        ErrorType.USER_INACTIVE: "账户已被禁用，请联系管理员",
        ErrorType.USER_PERMISSION_DENIED: "权限不足，无法执行此操作",
        ErrorType.USER_SESSION_EXPIRED: "登录已过期，请重新登录",
        ErrorType.USER_INVALID_TOKEN: "验证令牌无效",
        
        # 文件错误  
        ErrorType.FILE_NOT_FOUND: "文件不存在",
        ErrorType.FILE_ACCESS_DENIED: "文件访问被拒绝",
        ErrorType.FILE_SIZE_EXCEEDED: "文件大小超出限制",
        ErrorType.FILE_TYPE_INVALID: "文件类型不支持",
        ErrorType.FILE_UPLOAD_FAILED: "文件上传失败",
        ErrorType.FILE_PROCESSING_FAILED: "文件处理失败",
        ErrorType.FILE_CORRUPTED: "文件已损坏",
        ErrorType.FILE_STORAGE_FULL: "存储空间不足",
        
        # API错误
        ErrorType.API_KEY_INVALID: "API密钥无效",
        ErrorType.API_KEY_EXPIRED: "API密钥已过期",
        ErrorType.API_RATE_LIMITED: "API调用频率受限，请稍后重试",
        ErrorType.API_QUOTA_EXCEEDED: "API配额已用完",
        ErrorType.API_SERVICE_UNAVAILABLE: "API服务暂不可用",
        
        # 业务错误
        ErrorType.VALIDATION_FAILED: "输入验证失败",
        ErrorType.OPERATION_NOT_ALLOWED: "操作不被允许",
        ErrorType.RESOURCE_LOCKED: "资源正在被使用中",
        ErrorType.INSUFFICIENT_RESOURCES: "系统资源不足",
        
        # 系统错误
        ErrorType.SYSTEM_ERROR: "系统内部错误",
        ErrorType.NETWORK_ERROR: "网络连接异常",
        ErrorType.TIMEOUT_ERROR: "操作超时",
        ErrorType.CONFIGURATION_ERROR: "系统配置错误",
    }
    
    # 错误严重程度映射
    ERROR_SEVERITY = {
        # 严重级别
        ErrorType.DB_CONNECTION_FAILED: ErrorSeverity.CRITICAL,
        ErrorType.SYSTEM_ERROR: ErrorSeverity.CRITICAL,
        ErrorType.CONFIGURATION_ERROR: ErrorSeverity.CRITICAL,
        
        # 高级别
        ErrorType.DB_COMMIT_FAILED: ErrorSeverity.HIGH,
        ErrorType.DB_CONSTRAINT_VIOLATION: ErrorSeverity.HIGH,
        ErrorType.DB_TABLE_NOT_EXISTS: ErrorSeverity.HIGH,
        ErrorType.DB_COLUMN_NOT_EXISTS: ErrorSeverity.HIGH,
        ErrorType.FILE_STORAGE_FULL: ErrorSeverity.HIGH,
        ErrorType.API_SERVICE_UNAVAILABLE: ErrorSeverity.HIGH,
        
        # 中级别
        ErrorType.DB_QUERY_FAILED: ErrorSeverity.MEDIUM,
        ErrorType.DB_DUPLICATE_ENTRY: ErrorSeverity.MEDIUM,
        ErrorType.DB_FOREIGN_KEY_VIOLATION: ErrorSeverity.MEDIUM,
        ErrorType.FILE_PROCESSING_FAILED: ErrorSeverity.MEDIUM,
        ErrorType.FILE_UPLOAD_FAILED: ErrorSeverity.MEDIUM,
        ErrorType.FILE_CORRUPTED: ErrorSeverity.MEDIUM,
        ErrorType.USER_PERMISSION_DENIED: ErrorSeverity.MEDIUM,
        ErrorType.USER_ACCOUNT_LOCKED: ErrorSeverity.MEDIUM,
        ErrorType.USER_INACTIVE: ErrorSeverity.MEDIUM,
        ErrorType.API_KEY_INVALID: ErrorSeverity.MEDIUM,
        ErrorType.API_KEY_EXPIRED: ErrorSeverity.MEDIUM,
        ErrorType.NETWORK_ERROR: ErrorSeverity.MEDIUM,
        ErrorType.TIMEOUT_ERROR: ErrorSeverity.MEDIUM,
        ErrorType.OPERATION_NOT_ALLOWED: ErrorSeverity.MEDIUM,
        ErrorType.RESOURCE_LOCKED: ErrorSeverity.MEDIUM,
        ErrorType.INSUFFICIENT_RESOURCES: ErrorSeverity.MEDIUM,
        
        # 低级别（用户输入错误等）
        ErrorType.USER_NOT_FOUND: ErrorSeverity.LOW,
        ErrorType.USER_ALREADY_EXISTS: ErrorSeverity.LOW,
        ErrorType.USER_EMAIL_EXISTS: ErrorSeverity.LOW,
        ErrorType.USER_INVALID_CREDENTIALS: ErrorSeverity.LOW,
        ErrorType.USER_SESSION_EXPIRED: ErrorSeverity.LOW,
        ErrorType.USER_INVALID_TOKEN: ErrorSeverity.LOW,
        ErrorType.FILE_NOT_FOUND: ErrorSeverity.LOW,
        ErrorType.FILE_ACCESS_DENIED: ErrorSeverity.LOW,
        ErrorType.FILE_SIZE_EXCEEDED: ErrorSeverity.LOW,
        ErrorType.FILE_TYPE_INVALID: ErrorSeverity.LOW,
        ErrorType.API_RATE_LIMITED: ErrorSeverity.LOW,
        ErrorType.API_QUOTA_EXCEEDED: ErrorSeverity.LOW,
        ErrorType.VALIDATION_FAILED: ErrorSeverity.LOW,
    }
    
    @staticmethod
    def log_error(error_type: str, user_id: Optional[int] = None, details: str = None, 
                  exception: Optional[Exception] = None, context: Dict[str, Any] = None) -> str:
        """
        记录错误日志并返回错误ID用于追踪
        
        Args:
            error_type: 错误类型
            user_id: 用户ID
            details: 详细错误信息
            exception: 异常对象
            context: 上下文信息
            
        Returns:
            str: 错误追踪ID
        """
        import uuid
        import time
        
        # 生成错误追踪ID
        error_id = f"ERR_{int(time.time())}_{str(uuid.uuid4())[:8]}"
        
        # 获取错误严重程度
        severity = ErrorHandler.ERROR_SEVERITY.get(error_type, ErrorSeverity.MEDIUM)
        
        # 构建详细日志信息
        log_details = {
            'error_id': error_id,
            'error_type': error_type,
            'severity': severity,
            'user_id': user_id,
            'details': details,
            'context': context or {},
            'timestamp': datetime.now().isoformat()
        }
        
        # 添加异常信息
        if exception:
            log_details.update({
                'exception_type': type(exception).__name__,
                'exception_message': str(exception),
                'traceback': traceback.format_exc()
            })
        
        # 记录到系统日志
        try:
            log_user_action(
                user_id=user_id,
                action=f"ERROR_{error_type}",
                details=json.dumps(log_details, ensure_ascii=False),
                ip_address=context.get('ip_address') if context else None,
                user_agent=context.get('user_agent') if context else None
            )
        except:
            # 如果日志记录失败，至少要输出到控制台
            logger.error(f"Failed to log error to database: {log_details}")
        
        # 根据严重程度决定日志级别
        if severity == ErrorSeverity.CRITICAL:
            logger.critical(f"[{error_id}] {error_type}: {details}")
        elif severity == ErrorSeverity.HIGH:
            logger.error(f"[{error_id}] {error_type}: {details}")
        elif severity == ErrorSeverity.MEDIUM:
            logger.warning(f"[{error_id}] {error_type}: {details}")
        else:
            logger.info(f"[{error_id}] {error_type}: {details}")
        
        return error_id
    
    @staticmethod
    def get_user_message(error_type: str, **kwargs) -> str:
        """
        获取面向用户的错误消息
        
        Args:
            error_type: 错误类型
            **kwargs: 消息模板参数
            
        Returns:
            str: 用户友好的错误消息
        """
        base_message = ErrorHandler.ERROR_MESSAGES.get(error_type, "操作失败，请稍后重试")
        
        # 支持消息模板参数替换
        try:
            return base_message.format(**kwargs)
        except:
            return base_message
    
    @staticmethod
    def handle_db_error(exception: Exception, operation: str = "数据库操作", 
                       user_id: Optional[int] = None, context: Dict[str, Any] = None) -> Tuple[str, str]:
        """
        处理数据库错误，返回错误类型和用户消息
        
        Args:
            exception: 数据库异常
            operation: 操作描述
            user_id: 用户ID
            context: 上下文信息
            
        Returns:
            Tuple[str, str]: (错误类型, 用户消息)
        """
        error_str = str(exception).lower()
        
        # 判断具体的数据库错误类型
        if "duplicate entry" in error_str:
            error_type = ErrorType.DB_DUPLICATE_ENTRY
        elif "foreign key constraint" in error_str:
            error_type = ErrorType.DB_FOREIGN_KEY_VIOLATION
        elif "table" in error_str and "doesn't exist" in error_str:
            error_type = ErrorType.DB_TABLE_NOT_EXISTS
        elif "column" in error_str and ("unknown" in error_str or "doesn't exist" in error_str):
            error_type = ErrorType.DB_COLUMN_NOT_EXISTS
        elif "connection" in error_str or "can't connect" in error_str:
            error_type = ErrorType.DB_CONNECTION_FAILED
        else:
            error_type = ErrorType.DB_QUERY_FAILED
        
        # 记录错误
        error_id = ErrorHandler.log_error(
            error_type=error_type,
            user_id=user_id,
            details=f"{operation}失败: {str(exception)}",
            exception=exception,
            context=context
        )
        
        # 返回用户友好的消息
        user_message = ErrorHandler.get_user_message(error_type)
        
        return error_type, f"{user_message} (错误ID: {error_id[-8:]})"

def create_error_result(error_type: str, user_message: str = None, 
                       details: str = None, error_id: str = None) -> Dict[str, Any]:
    """
    创建标准化的错误结果
    
    Args:
        error_type: 错误类型
        user_message: 用户消息
        details: 详细信息
        error_id: 错误ID
        
    Returns:
        Dict[str, Any]: 标准化错误结果
    """
    return {
        'success': False,
        'error_type': error_type,
        'message': user_message or ErrorHandler.get_user_message(error_type),
        'details': details,
        'error_id': error_id,
        'timestamp': datetime.now().isoformat()
    }

def create_success_result(data: Any = None, message: str = "操作成功") -> Dict[str, Any]:
    """
    创建标准化的成功结果
    
    Args:
        data: 返回数据
        message: 成功消息
        
    Returns:
        Dict[str, Any]: 标准化成功结果
    """
    return {
        'success': True,
        'data': data,
        'message': message,
        'timestamp': datetime.now().isoformat()
    }
    
    # 用户相关错误
    USER_NOT_FOUND = "USER_NOT_FOUND"
    USER_ALREADY_EXISTS = "USER_ALREADY_EXISTS"
    USER_INACTIVE = "USER_INACTIVE"
    USER_PERMISSION_DENIED = "USER_PERMISSION_DENIED"
    
    # 文件相关错误
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_UPLOAD_FAILED = "FILE_UPLOAD_FAILED"
    FILE_PROCESSING_FAILED = "FILE_PROCESSING_FAILED"
    FILE_SIZE_EXCEEDED = "FILE_SIZE_EXCEEDED"
    # FILE_TYPE_NOT_SUPPORTED = "FILE_TYPE_NOT_SUPPORTED"  # 使用FILE_TYPE_INVALID代替
    
    # API相关错误
    API_KEY_INVALID = "API_KEY_INVALID"
    API_KEY_EXPIRED = "API_KEY_EXPIRED"
    API_QUOTA_EXCEEDED = "API_QUOTA_EXCEEDED"
    API_REQUEST_FAILED = "API_REQUEST_FAILED"
    
    # 任务相关错误
    TASK_NOT_FOUND = "TASK_NOT_FOUND"
    TASK_ALREADY_COMPLETED = "TASK_ALREADY_COMPLETED"
    TASK_FAILED = "TASK_FAILED"
    TASK_TIMEOUT = "TASK_TIMEOUT"
    
    # 验证相关错误
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INPUT_INVALID = "INPUT_INVALID"
    PASSWORD_WEAK = "PASSWORD_WEAK"
    EMAIL_INVALID = "EMAIL_INVALID"
    
    # 系统相关错误
    SYSTEM_ERROR = "SYSTEM_ERROR"
    NETWORK_ERROR = "NETWORK_ERROR"
    STORAGE_ERROR = "STORAGE_ERROR"
    CONFIG_ERROR = "CONFIG_ERROR"

class UserErrorMessage:
    """用户友好的错误消息"""
    
    @staticmethod
    def get_message(error_type: str, context: Dict[str, Any] = None) -> str:
        """根据错误类型获取用户友好的错误消息"""
        context = context or {}
        
        messages = {
            # 数据库相关错误
            ErrorType.DB_CONNECTION_FAILED: "系统暂时无法连接到数据库，请稍后重试",
            ErrorType.DB_QUERY_FAILED: "数据查询失败，请检查输入参数或联系管理员",
            ErrorType.DB_COMMIT_FAILED: "数据保存失败，请重试或联系管理员",
            ErrorType.DB_CONSTRAINT_VIOLATION: "数据完整性约束冲突，请检查输入数据",
            
            # 用户相关错误
            ErrorType.USER_NOT_FOUND: "用户不存在或已被删除",
            ErrorType.USER_ALREADY_EXISTS: f"用户名或邮箱已存在，请使用其他信息注册",
            ErrorType.USER_INACTIVE: "账户已被禁用，请联系管理员",
            ErrorType.USER_PERMISSION_DENIED: "您没有权限执行此操作",
            
            # 文件相关错误
            ErrorType.FILE_NOT_FOUND: "文件未找到或已被删除",
            ErrorType.FILE_UPLOAD_FAILED: "文件上传失败，请检查网络连接后重试",
            ErrorType.FILE_PROCESSING_FAILED: f"文件处理失败：{context.get('reason', '未知原因')}",
            ErrorType.FILE_SIZE_EXCEEDED: f"文件大小超过限制（{context.get('max_size', '未知')}MB）",
            ErrorType.FILE_TYPE_INVALID: f"不支持的文件类型：{context.get('file_type', '未知类型')}",
            
            # API相关错误
            ErrorType.API_KEY_INVALID: "API密钥无效或已过期",
            ErrorType.API_KEY_EXPIRED: "API密钥已过期，请更新密钥",
            ErrorType.API_QUOTA_EXCEEDED: "API调用次数已达上限，请稍后重试",
            ErrorType.API_REQUEST_FAILED: f"API请求失败：{context.get('api_error', '未知错误')}",
            
            # 任务相关错误
            ErrorType.TASK_NOT_FOUND: "任务不存在或已被删除",
            ErrorType.TASK_ALREADY_COMPLETED: "任务已完成，无法重复执行",
            ErrorType.TASK_FAILED: f"任务执行失败：{context.get('task_error', '未知原因')}",
            ErrorType.TASK_TIMEOUT: "任务执行超时，请稍后重试",
            
            # 验证相关错误
            ErrorType.VALIDATION_FAILED: f"数据验证失败：{context.get('validation_error', '格式不正确')}",
            ErrorType.INPUT_INVALID: f"输入参数无效：{context.get('invalid_field', '未知字段')}",
            ErrorType.PASSWORD_WEAK: "密码强度不足，请使用至少8位包含字母和数字的密码",
            ErrorType.EMAIL_INVALID: "邮箱格式不正确，请检查输入",
            
            # 系统相关错误
            ErrorType.SYSTEM_ERROR: "系统内部错误，请稍后重试或联系管理员",
            ErrorType.NETWORK_ERROR: "网络连接异常，请检查网络后重试",
            ErrorType.STORAGE_ERROR: "存储空间不足或存储服务异常",
            ErrorType.CONFIG_ERROR: "系统配置错误，请联系管理员"
        }
        
        return messages.get(error_type, f"未知错误类型：{error_type}")

def log_error_with_user_message(user_id: Optional[int], error_type: str, 
                               technical_details: str, context: Dict[str, Any] = None,
                               ip_address: Optional[str] = None, 
                               user_agent: Optional[str] = None) -> Tuple[bool, str]:
    """
    记录错误日志并返回用户友好的错误消息
    
    Args:
        user_id: 用户ID（可为None，系统级错误）
        error_type: 错误类型（使用ErrorType中的常量）
        technical_details: 技术详细信息（记录到日志）
        context: 错误上下文信息
        ip_address: 用户IP地址
        user_agent: 用户代理
        
    Returns:
        Tuple[bool, str]: (记录是否成功, 用户友好的错误消息)
    """
    context = context or {}
    
    # 获取调用栈信息
    stack_trace = traceback.format_exc() if traceback.format_exc() != 'NoneType: None\n' else ""
    
    # 构建详细的技术日志
    log_details = {
        "error_type": error_type,
        "technical_details": technical_details,
        "context": context,
        "stack_trace": stack_trace,
        "timestamp": datetime.now().isoformat()
    }
    
    # 记录到系统日志
    success = log_user_action(
        user_id=user_id,
        action=f"ERROR_{error_type}",
        details=json.dumps(log_details, ensure_ascii=False),
        ip_address=ip_address,
        user_agent=user_agent
    )
    
    # 生成用户友好的错误消息
    user_message = UserErrorMessage.get_message(error_type, context)
    
    # 同时记录到Python日志系统
    logger.error(f"Error for user {user_id}: {error_type} - {technical_details}", 
                extra={"context": context})
    
    return success, user_message

def get_user_errors(user_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """
    获取指定用户的错误记录（仅显示给对应用户）
    
    Args:
        user_id: 用户ID
        limit: 返回记录数量限制
        
    Returns:
        List[Dict]: 错误记录列表
    """
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, action, details, created_at, ip_address
            FROM system_logs 
            WHERE user_id = %s 
            AND action LIKE 'ERROR_%'
            ORDER BY created_at DESC 
            LIMIT %s
        """, (user_id, limit))
        
        results = cursor.fetchall()
        errors = []
        
        for row in results:
            try:
                details = json.loads(row['details']) if row['details'] else {}
                error_type = details.get('error_type', 'UNKNOWN')
                
                # 生成用户友好的错误消息
                user_message = UserErrorMessage.get_message(
                    error_type, 
                    details.get('context', {})
                )
                
                errors.append({
                    'id': row['id'],
                    'error_type': error_type,
                    'user_message': user_message,
                    'created_at': row['created_at'],
                    'ip_address': row['ip_address']
                })
            except json.JSONDecodeError:
                # 如果JSON解析失败，跳过此记录
                continue
                
        return errors
    except Exception as e:
        logger.error(f"获取用户错误记录失败: {e}")
        return []
    finally:
        safe_db_close(conn, cursor)

# ================================
# 用户相关操作
# ================================

def get_user_by_username(username: str, request_user_id: Optional[int] = None,
                        ip_address: Optional[str] = None, 
                        user_agent: Optional[str] = None) -> Dict[str, Any]:
    """
    根据用户名获取用户信息
    
    Returns:
        Dict[str, Any]: 标准化结果 {'success': bool, 'data': dict, 'message': str, 'error_type': str}
    """
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        error_id = ErrorHandler.log_error(
            error_type=ErrorType.DB_CONNECTION_FAILED,
            user_id=request_user_id,
            details="Failed to connect to database in get_user_by_username",
            context={"username": username, "ip_address": ip_address, "user_agent": user_agent}
        )
        return create_error_result(
            ErrorType.DB_CONNECTION_FAILED,
            error_id=error_id
        )
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, email, password_hash, 
                   created_at, updated_at, is_active, role, group_id, group_name, group_status
            FROM users 
            WHERE username = %s AND is_active = 1
        """, (username,))
        result = cursor.fetchone()
        
        if result is None:
            error_id = ErrorHandler.log_error(
                error_type=ErrorType.USER_NOT_FOUND,
                user_id=request_user_id,
                details=f"User not found: {username}",
                context={"username": username, "ip_address": ip_address, "user_agent": user_agent}
            )
            return create_error_result(
                ErrorType.USER_NOT_FOUND,
                user_message=f"用户'{username}'不存在",
                error_id=error_id
            )
        
        # 记录成功查询日志（仅记录查询行为，不记录敏感信息）
        log_user_action(
            user_id=request_user_id,
            action="user_query_by_username",
            details=f"Successfully queried user: {username}",
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        return create_success_result(
            data=result,
            message="用户信息获取成功"
        )
        
    except Exception as e:
        error_type, user_message = ErrorHandler.handle_db_error(
            exception=e,
            operation="查询用户信息",
            user_id=request_user_id,
            context={"username": username, "ip_address": ip_address, "user_agent": user_agent}
        )
        return create_error_result(error_type, user_message)
    finally:
        safe_db_close(conn, cursor)

def get_user_by_username_or_email(identifier: str, request_user_id: Optional[int] = None,
                                  ip_address: Optional[str] = None, 
                                  user_agent: Optional[str] = None) -> Dict[str, Any]:
    """
    根据用户名或邮箱获取用户信息
    
    Returns:
        Dict[str, Any]: 标准化结果
    """
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        error_id = ErrorHandler.log_error(
            error_type=ErrorType.DB_CONNECTION_FAILED,
            user_id=request_user_id,
            details="Failed to connect to database in get_user_by_username_or_email",
            context={"identifier": identifier, "ip_address": ip_address, "user_agent": user_agent}
        )
        return create_error_result(ErrorType.DB_CONNECTION_FAILED, error_id=error_id)
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, email, password_hash, 
                   created_at, updated_at, is_active, role, group_id, group_name, group_status
            FROM users 
            WHERE (username = %s OR email = %s) AND is_active = 1
        """, (identifier, identifier))
        result = cursor.fetchone()
        
        if result is None:
            error_id = ErrorHandler.log_error(
                error_type=ErrorType.USER_NOT_FOUND,
                user_id=request_user_id,
                details=f"User not found by identifier: {identifier}",
                context={"identifier": identifier, "ip_address": ip_address, "user_agent": user_agent}
            )
            return create_error_result(
                ErrorType.USER_NOT_FOUND,
                user_message=f"用户或邮箱'{identifier}'不存在",
                error_id=error_id
            )
        
        # 检查用户是否被禁用
        if not result.get('is_active', True):
            error_id = ErrorHandler.log_error(
                error_type=ErrorType.USER_ACCOUNT_LOCKED,
                user_id=result.get('id'),
                details=f"Inactive user attempted access: {identifier}",
                context={"identifier": identifier, "user_id": result.get('id'), "ip_address": ip_address, "user_agent": user_agent}
            )
            return create_error_result(
                ErrorType.USER_ACCOUNT_LOCKED,
                error_id=error_id
            )
        
        # 记录成功查询日志
        log_user_action(
            user_id=request_user_id,
            action="user_query_by_identifier",
            details=f"Successfully queried user by identifier: {identifier}",
            ip_address=ip_address,
            user_agent=user_agent
        )
            
        return create_success_result(
            data=result,
            message="用户信息获取成功"
        )
        
    except Exception as e:
        error_type, user_message = ErrorHandler.handle_db_error(
            exception=e,
            operation="查询用户信息",
            user_id=request_user_id,
            context={"identifier": identifier, "ip_address": ip_address, "user_agent": user_agent}
        )
        return create_error_result(error_type, user_message)
    finally:
        safe_db_close(conn, cursor)

def check_user_exists(username: str, request_user_id: Optional[int] = None,
                     ip_address: Optional[str] = None, 
                     user_agent: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    检查用户名是否存在
    
    Returns:
        Tuple[bool, Optional[str]]: (是否存在, 错误消息)
    """
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        _, error_msg = log_error_with_user_message(
            user_id=request_user_id,
            error_type=ErrorType.DB_CONNECTION_FAILED,
            technical_details="Failed to connect to database in check_user_exists",
            context={"username": username},
            ip_address=ip_address,
            user_agent=user_agent
        )
        return False, error_msg
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE username = %s", (username,))
        result = cursor.fetchone()
        exists = result['count'] > 0
        
        if exists:
            # 用户已存在，记录为警告而非错误
            log_user_action(
                user_id=request_user_id,
                action="user_exists_check",
                details=f"Username already exists: {username}",
                ip_address=ip_address,
                user_agent=user_agent
            )
        
        return exists, None
    except Exception as e:
        _, error_msg = log_error_with_user_message(
            user_id=request_user_id,
            error_type=ErrorType.DB_QUERY_FAILED,
            technical_details=f"Database query failed in check_user_exists: {str(e)}",
            context={"username": username},
            ip_address=ip_address,
            user_agent=user_agent
        )
        return False, error_msg
    finally:
        safe_db_close(conn, cursor)

def check_email_exists(email: str, request_user_id: Optional[int] = None,
                      ip_address: Optional[str] = None, 
                      user_agent: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    检查邮箱是否存在
    
    Returns:
        Tuple[bool, Optional[str]]: (是否存在, 错误消息)
    """
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        _, error_msg = log_error_with_user_message(
            user_id=request_user_id,
            error_type=ErrorType.DB_CONNECTION_FAILED,
            technical_details="Failed to connect to database in check_email_exists",
            context={"email": email},
            ip_address=ip_address,
            user_agent=user_agent
        )
        return False, error_msg
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM users WHERE email = %s", (email,))
        result = cursor.fetchone()
        exists = result['count'] > 0
        
        if exists:
            # 邮箱已存在，记录为警告而非错误
            log_user_action(
                user_id=request_user_id,
                action="email_exists_check",
                details=f"Email already exists: {email}",
                ip_address=ip_address,
                user_agent=user_agent
            )
        
        return exists, None
    except Exception as e:
        _, error_msg = log_error_with_user_message(
            user_id=request_user_id,
            error_type=ErrorType.DB_QUERY_FAILED,
            technical_details=f"Database query failed in check_email_exists: {str(e)}",
            context={"email": email},
            ip_address=ip_address,
            user_agent=user_agent
        )
        return False, error_msg
    finally:
        safe_db_close(conn, cursor)

def get_or_create_temp_group(cursor):
    """获取或创建一个临时分组
    
    Returns:
        tuple: (group_id, group_name)
    """
    # 查找第一个未满5人的临时分组
    cursor.execute("""
        SELECT group_id, group_name
        FROM users 
        WHERE group_status = 'temporary' AND group_id IS NOT NULL
        GROUP BY group_id, group_name
        HAVING COUNT(*) < 5 
        ORDER BY group_id ASC 
        LIMIT 1
    """)
    
    result = cursor.fetchone()
    if result:
        return result['group_id'], result['group_name']
    
    # 如果没有找到未满的临时分组，创建新的分组
    cursor.execute("SELECT COALESCE(MAX(group_id), 0) + 1 as next_group_id FROM users")
    result = cursor.fetchone()
    if not result:
        raise Exception("Failed to get next group ID")
    next_group_id = result['next_group_id']
    group_name = f"临时分组{next_group_id}"
    
    return next_group_id, group_name


def create_user(username: str, email: str, password_hash: str, role: str = 'user') -> Optional[int]:
    """创建新用户并自动分配到临时分组"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        
        # 获取或创建临时分组
        group_id, group_name = get_or_create_temp_group(cursor)
        
        # 创建用户并分配到临时分组
        cursor.execute("""
            INSERT INTO users (username, email, password_hash, role, is_active, 
                             group_id, group_name, group_status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 1, %s, %s, 'temporary', NOW(), NOW())
        """, (username, email, password_hash, role, group_id, group_name))
        
        user_id = cursor.lastrowid
        conn.commit()
        logger.info(f"用户创建成功: {username}, ID: {user_id}, 自动分配到临时分组: {group_name}")
        return user_id
    except Exception as e:
        conn.rollback()
        logger.error(f"创建用户失败: {e}")
        return None
    finally:
        safe_db_close(conn, cursor)

# ================================
# 文件相关操作
# ================================

def count_pending_files_for_user(user_id: int) -> int:
    """快速查询用户未完成的文件数量（用于上传前检查）"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return 0
    
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) as count FROM user_files WHERE user_id = %s AND status != 'completed'",
            (user_id,)
        )
        result = cursor.fetchone()
        return result['count'] if result else 0
    except Exception as e:
        logger.error(f"查询待处理文件数失败: {e}")
        return 0
    finally:
        safe_db_close(conn, cursor)

def get_user_files_from_db(user_id: int, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
    """获取用户的文件列表 - 优化版本，排除大字段"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        # 优化：排除大字段 md_content, nsfc_json_data, extracted_json_data, pdf_data
        # 直接在SQL中计算处理时间，将processing_start_time转换为本地时间（+8小时）后再计算
        cursor.execute("""
            SELECT id, file_id, user_id, original_name, original_document_type, safe_filename, file_path,
                   upload_time, file_size, status, storage_type, md_file_path, 
                   processed_time, task_id, nsfc_json_created_at, nsfc_json_updated_at,
                   remarks, 
                   processing_start_time,
                   TIMESTAMPDIFF(SECOND, processing_start_time, processed_time) as processing_time_seconds,
                   CASE WHEN pdf_data IS NOT NULL AND pdf_data != '' THEN 1 ELSE 0 END as has_pdf_data,
                   CASE WHEN md_content IS NOT NULL AND md_content != '' THEN 1 ELSE 0 END as has_md_content,
                   CASE WHEN nsfc_json_data IS NOT NULL AND nsfc_json_data != '' THEN 1 ELSE 0 END as has_nsfc_json,
                   CASE WHEN extracted_json_data IS NOT NULL AND extracted_json_data != '' THEN 1 ELSE 0 END as has_extracted_json
            FROM user_files 
            WHERE user_id = %s 
            ORDER BY upload_time DESC 
            LIMIT %s OFFSET %s
        """, (user_id, limit, offset))
        results = cursor.fetchall()
        return results or []
    except Exception as e:
        logger.error(f"获取用户文件列表失败: {e}")
        return []
    finally:
        safe_db_close(conn, cursor)

def get_file_content_by_id(file_id: str, user_id: int = None) -> Dict[str, Any]:
    """获取文件的详细内容数据（包含大字段）"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return {}
    
    try:
        cursor = conn.cursor()
        if user_id:
            cursor.execute("""
                SELECT md_content, nsfc_json_data, extracted_json_data, pdf_data
                FROM user_files 
                WHERE file_id = %s AND user_id = %s
            """, (file_id, user_id))
        else:
            cursor.execute("""
                SELECT md_content, nsfc_json_data, extracted_json_data, pdf_data
                FROM user_files 
                WHERE file_id = %s
            """, (file_id,))
        
        result = cursor.fetchone()
        if result:
            return {
                'md_content': result['md_content'],
                'nsfc_json_data': result['nsfc_json_data'], 
                'extracted_json_data': result['extracted_json_data'],
                'pdf_data': result['pdf_data']
            }
        return {}
    except Exception as e:
        logger.error(f"获取文件内容失败: {e}")
        return {}
    finally:
        safe_db_close(conn, cursor)

def get_file_reference_data(file_id: str, user_id: int) -> Dict[str, Any]:
    """获取文件的参考文献数据"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return {}
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT file_id, original_name, reference_md_content, reference_validation_json
            FROM user_files 
            WHERE file_id = %s AND user_id = %s
        """, (file_id, user_id))
        
        result = cursor.fetchone()
        if result:
            return {
                'file_id': result['file_id'],
                'original_name': result['original_name'],
                'reference_md_content': result['reference_md_content'],
                'reference_validation_json': result['reference_validation_json']
            }
        return {}
    except Exception as e:
        logger.error(f"获取文件参考文献数据失败: {e}")
        return {}
    finally:
        safe_db_close(conn, cursor)

def detect_document_type(filename: str) -> str:
    """
    根据文件名检测原始文档类型
    
    Args:
        filename: 原始文件名
        
    Returns:
        str: 文档类型 ('pdf', 'word_doc', 'word_docx', 'unknown')
    """
    if not filename:
        return 'unknown'
    
    filename_lower = filename.lower()
    
    if filename_lower.endswith('.pdf'):
        return 'pdf'
    elif filename_lower.endswith('.doc'):
        return 'word_doc'
    elif filename_lower.endswith('.docx'):
        return 'word_docx'
    else:
        return 'unknown'

def save_file_to_db(user_id: int, file_id: str, original_name: str, safe_filename: str, 
                   file_path: str, file_size: int, pdf_data: Optional[bytes] = None, 
                   storage_type: str = 'database', ip_address: Optional[str] = None,
                   user_agent: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    """
    保存文件到数据库
    
    Returns:
        Tuple[bool, Optional[str]]: (是否成功, 错误消息)
    """
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        _, error_msg = log_error_with_user_message(
            user_id=user_id,
            error_type=ErrorType.DB_CONNECTION_FAILED,
            technical_details="Failed to connect to database in save_file_to_db",
            context={"file_id": file_id, "original_name": original_name},
            ip_address=ip_address,
            user_agent=user_agent
        )
        return False, error_msg
    
    try:
        cursor = conn.cursor()
        # 使用中国时区的当前时间
        from app_pdf_md import get_current_time
        current_time = get_current_time().strftime('%Y-%m-%d %H:%M:%S')
        
        # 检测原始文档类型
        original_document_type = detect_document_type(original_name)
        
        cursor.execute("""
            INSERT INTO user_files 
            (file_id, user_id, original_name, original_document_type, safe_filename, file_path, file_size, 
             status, storage_type, pdf_data, upload_time)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'uploaded', %s, %s, %s)
        """, (file_id, user_id, original_name, original_document_type, safe_filename, file_path, 
              file_size, storage_type, pdf_data, current_time))
        
        conn.commit()
        logger.info(f"文件保存成功: {original_name}")
        
        # 记录成功操作
        log_user_action(
            user_id=user_id,
            action="file_upload_success",
            details=f"File uploaded successfully: {original_name} (size: {file_size} bytes)",
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        return True, None
    except Exception as e:
        conn.rollback()
        
        # 判断是否为文件大小超限等特定错误
        error_msg = str(e).lower()
        if "data too long" in error_msg or "packet too large" in error_msg:
            _, user_error_msg = log_error_with_user_message(
                user_id=user_id,
                error_type=ErrorType.FILE_SIZE_EXCEEDED,
                technical_details=f"File size exceeded database limit: {str(e)}",
                context={"file_id": file_id, "original_name": original_name, "file_size": file_size},
                ip_address=ip_address,
                user_agent=user_agent
            )
        elif "duplicate" in error_msg:
            _, user_error_msg = log_error_with_user_message(
                user_id=user_id,
                error_type=ErrorType.DB_CONSTRAINT_VIOLATION,
                technical_details=f"Duplicate file entry: {str(e)}",
                context={"file_id": file_id, "original_name": original_name},
                ip_address=ip_address,
                user_agent=user_agent
            )
        else:
            _, user_error_msg = log_error_with_user_message(
                user_id=user_id,
                error_type=ErrorType.FILE_UPLOAD_FAILED,
                technical_details=f"Database error in save_file_to_db: {str(e)}",
                context={"file_id": file_id, "original_name": original_name},
                ip_address=ip_address,
                user_agent=user_agent
            )
        
        return False, user_error_msg
    finally:
        safe_db_close(conn, cursor)

def get_file_content_from_db(file_id: str, user_id: Optional[int] = None, 
                            request_user_id: Optional[int] = None,
                            ip_address: Optional[str] = None, 
                            user_agent: Optional[str] = None) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    从数据库获取文件内容
    
    Returns:
        Tuple[Optional[Dict], Optional[str]]: (文件内容, 错误消息)
    """
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        _, error_msg = log_error_with_user_message(
            user_id=request_user_id or user_id,
            error_type=ErrorType.DB_CONNECTION_FAILED,
            technical_details="Failed to connect to database in get_file_content_from_db",
            context={"file_id": file_id},
            ip_address=ip_address,
            user_agent=user_agent
        )
        return None, error_msg
    
    try:
        cursor = conn.cursor()
        if user_id is not None:
            # 验证用户权限
            cursor.execute("""
                SELECT file_id, original_name, original_document_type, md_content, pdf_data, 
                       storage_type, md_file_path, status
                FROM user_files 
                WHERE file_id = %s AND user_id = %s
            """, (file_id, user_id))
        else:
            # 不验证权限（向后兼容）
            cursor.execute("""
                SELECT file_id, original_name, original_document_type, md_content, pdf_data, 
                       storage_type, md_file_path, status
                FROM user_files 
                WHERE file_id = %s
            """, (file_id,))
        
        result = cursor.fetchone()
        
        if result is None:
            if user_id is not None:
                # 权限验证失败或文件不存在
                _, error_msg = log_error_with_user_message(
                    user_id=request_user_id or user_id,
                    error_type=ErrorType.FILE_NOT_FOUND,
                    technical_details=f"File not found or permission denied: {file_id}",
                    context={"file_id": file_id, "user_id": user_id},
                    ip_address=ip_address,
                    user_agent=user_agent
                )
            else:
                # 文件不存在
                _, error_msg = log_error_with_user_message(
                    user_id=request_user_id,
                    error_type=ErrorType.FILE_NOT_FOUND,
                    technical_details=f"File not found: {file_id}",
                    context={"file_id": file_id},
                    ip_address=ip_address,
                    user_agent=user_agent
                )
            return None, error_msg
        
        return result, None
    except Exception as e:
        _, error_msg = log_error_with_user_message(
            user_id=request_user_id or user_id,
            error_type=ErrorType.DB_QUERY_FAILED,
            technical_details=f"Database query failed in get_file_content_from_db: {str(e)}",
            context={"file_id": file_id},
            ip_address=ip_address,
            user_agent=user_agent
        )
        return None, error_msg
    finally:
        safe_db_close(conn, cursor)

def get_pdf_data_from_db(file_id: str, user_id: Optional[int] = None) -> Optional[bytes]:
    """从数据库获取PDF数据"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        if user_id is not None:
            # 验证用户权限
            cursor.execute("SELECT pdf_data FROM user_files WHERE file_id = %s AND user_id = %s", (file_id, user_id))
        else:
            # 不验证权限（向后兼容）
            cursor.execute("SELECT pdf_data FROM user_files WHERE file_id = %s", (file_id,))
        result = cursor.fetchone()
        return result['pdf_data'] if result else None
    except Exception as e:
        logger.error(f"获取PDF数据失败: {e}")
        return None
    finally:
        safe_db_close(conn, cursor)

def get_file_info_from_db(file_id: str, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """从数据库获取完整文件信息"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        if user_id is not None:
            # 验证用户权限 - 增加查询md_content字段
            cursor.execute("""
                SELECT pdf_data, original_name, file_size, md_content, status, 
                       upload_time, processed_time, file_id, user_id
                FROM user_files 
                WHERE file_id = %s AND user_id = %s
            """, (file_id, user_id))
        else:
            # 不验证权限（向后兼容）- 增加查询md_content字段
            cursor.execute("""
                SELECT pdf_data, original_name, file_size, md_content, status, 
                       upload_time, processed_time, file_id, user_id
                FROM user_files 
                WHERE file_id = %s
            """, (file_id,))
        result = cursor.fetchone()
        return result if result else None
    except Exception as e:
        logger.error(f"获取文件信息失败: {e}")
        return None
    finally:
        safe_db_close(conn, cursor)

def update_file_status_in_db(file_id: str, status: Optional[str] = None, md_content: Optional[str] = None, 
                            task_id: Optional[str] = None,
                            processed_time: Optional[Union[str, datetime]] = None,
                            remarks: Optional[str] = None,
                            processing_start_time: Optional[Union[str, datetime]] = None) -> bool:
    """更新文件状态"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return False

    try:
        cursor = conn.cursor()
        
        # 构建动态更新SQL
        update_fields = []
        params = []
        
        # 只有当status不为None时才更新状态
        if status is not None:
            update_fields.append("status = %s")
            params.append(status)
            
            # 根据是否提供processed_time参数决定如何更新时间
            if processed_time is not None:
                if isinstance(processed_time, datetime):
                    processed_time = processed_time.isoformat()
                update_fields.append("processed_time = %s")
                params.append(processed_time)
            else:
                update_fields.append("processed_time = NOW()")

        if md_content is not None:
            update_fields.append("md_content = %s")
            params.append(md_content)
            
        if task_id is not None:
            update_fields.append("task_id = %s")
            params.append(task_id)
        
        if remarks is not None:
            update_fields.append("remarks = %s")
            params.append(remarks)
            
        if processing_start_time is not None:
            update_fields.append("processing_start_time = %s")
            if isinstance(processing_start_time, datetime):
                params.append(processing_start_time)
            elif isinstance(processing_start_time, (int, float)):
                # 如果是时间戳，转换为datetime对象，使用UTC时间避免时区问题
                from datetime import timezone  # 只导入timezone，datetime已在模块顶部导入
                try:
                    # 验证时间戳范围（Unix时间戳应该在合理范围内）
                    if processing_start_time < 0 or processing_start_time > 4102444800:  # 2100年1月1日
                        print(f"[时间戳警告] 时间戳超出范围: {processing_start_time}，使用当前时间")
                        params.append(datetime.now())
                    else:
                        # 使用UTC时间转换，避免时区问题
                        dt = datetime.fromtimestamp(processing_start_time, tz=timezone.utc)
                        # 转换为本地时间（无时区信息），并移除微秒避免MySQL兼容性问题
                        dt_local = dt.replace(tzinfo=None, microsecond=0)
                        params.append(dt_local)
                except (ValueError, OSError, OverflowError) as e:
                    print(f"[时间戳转换错误] {processing_start_time}: {e}，使用当前时间")
                    params.append(datetime.now())
            else:
                # 如果是字符串，尝试解析
                try:
                    if isinstance(processing_start_time, str):
                        # 尝试解析ISO格式或其他格式
                        from datetime import timezone  # 只导入timezone，datetime已在模块顶部导入
                        if 'T' in processing_start_time:
                            dt = datetime.fromisoformat(processing_start_time.replace('Z', '+00:00'))
                            # 如果有时区信息，转换为本地时间
                            if dt.tzinfo is not None:
                                dt = dt.astimezone().replace(tzinfo=None)
                        else:
                            # 可能是时间戳字符串
                            timestamp = float(processing_start_time)
                            if timestamp < 0 or timestamp > 4102444800:
                                print(f"[时间戳字符串警告] 时间戳超出范围: {timestamp}，使用当前时间")
                                dt = datetime.now()
                            else:
                                dt = datetime.fromtimestamp(timestamp, tz=timezone.utc).replace(tzinfo=None, microsecond=0)
                        params.append(dt)
                    else:
                        params.append(processing_start_time)
                except (ValueError, TypeError, OSError, OverflowError) as e:
                    # 解析失败，使用当前时间
                    print(f"[时间解析错误] {processing_start_time}: {e}，使用当前时间")
                    params.append(datetime.now())
        
        if not update_fields:
            # 没有任何字段需要更新
            return True
            
        params.append(file_id)
        
        sql = f"UPDATE user_files SET {', '.join(update_fields)} WHERE file_id = %s"
        cursor.execute(sql, params)
        
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        conn.rollback()
        logger.error(f"更新文件状态失败: {e}")
        return False
    finally:
        safe_db_close(conn, cursor)

def update_file_extracted_json(file_id: str, json_data: str) -> bool:
    """更新文件的提取JSON数据"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE user_files 
            SET extracted_json_data = %s, processed_time = NOW()
            WHERE file_id = %s
        """, (json_data, file_id))
        
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        conn.rollback()
        logger.error(f"更新文件JSON数据失败: {e}")
        return False
    finally:
        safe_db_close(conn, cursor)

# ================================
# API密钥相关操作 - 仅支持分组密钥
# ================================

def get_active_api_key(user_id: int, provider: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """获取用户的API密钥 - 仅从分组密钥获取"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        
        # 首先获取用户的分组ID
        cursor.execute("SELECT group_id FROM users WHERE id = %s", (user_id,))
        user_result = cursor.fetchone()
        
        if not user_result or not user_result['group_id']:
            logger.warning(f"用户 {user_id} 没有分组，无法获取API密钥")
            return None
        
        group_id = user_result['group_id']
        
        # 从分组密钥表获取API密钥
        if provider:
            cursor.execute("""
                SELECT id, group_id as user_id, api_provider, api_token, 
                       is_active, is_valid, created_at
                FROM group_api_keys 
                WHERE group_id = %s AND api_provider = %s AND is_active = 1 AND is_valid = 1
                LIMIT 1
            """, (group_id, provider))
        else:
            cursor.execute("""
                SELECT id, group_id as user_id, api_provider, api_token, 
                       is_active, is_valid, created_at
                FROM group_api_keys 
                WHERE group_id = %s AND is_active = 1 AND is_valid = 1
                ORDER BY created_at DESC
                LIMIT 1
            """, (group_id,))
        
        result = cursor.fetchone()
        if result:
            # #22 解密API密钥
            if 'api_token' in result and result['api_token']:
                result['api_token'] = decrypt_api_token(result['api_token'])
            logger.info(f"为用户 {user_id} (分组 {group_id}) 获取到 {result['api_provider']} API密钥")
        else:
            logger.warning(f"用户 {user_id} (分组 {group_id}) 没有找到有效的API密钥 (provider: {provider})")
        
        return result
    except Exception as e:
        logger.error(f"获取分组API密钥失败: {e}")
        return None
    finally:
        safe_db_close(conn, cursor)

def add_group_api_key(group_id: int, api_provider: str, api_token: str, created_by: int, model_name: Optional[str] = None) -> Tuple[bool, Optional[int]]:
    """添加或更新分组API密钥，采用覆盖模式：每个分组每个提供商只有一个密钥"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return False, None
    
    try:
        cursor = conn.cursor()
        
        # 覆盖模式：先删除该分组该提供商的现有密钥
        cursor.execute("""
            DELETE FROM group_api_keys 
            WHERE group_id = %s AND api_provider = %s
        """, (group_id, api_provider))
        
        deleted_count = cursor.rowcount
        logger.info(f"分组覆盖模式删除旧密钥: group_id={group_id}, api_provider={api_provider}, 删除数量={deleted_count}")
        
        # #22 加密API密钥后存储
        encrypted_token = encrypt_api_token(api_token)
        
        # 插入新的分组密钥（包含model_name）
        cursor.execute("""
            INSERT INTO group_api_keys 
            (group_id, api_provider, api_token, model_name, is_active, is_valid, created_by, created_at, updated_at)
            VALUES (%s, %s, %s, %s, 1, 1, %s, NOW(), NOW())
        """, (group_id, api_provider, encrypted_token, model_name, created_by))
        
        key_id = cursor.lastrowid
        logger.info(f"分组覆盖模式添加新密钥成功: group_id={group_id}, api_provider={api_provider}, model_name={model_name}, new_id={key_id}")
        
        conn.commit()
        return True, key_id
    except Exception as e:
        conn.rollback()
        logger.error(f"添加分组API密钥失败: {e}")
        return False, str(e)
    finally:
        safe_db_close(conn, cursor)

def get_group_api_keys(group_id: int) -> List[Dict[str, Any]]:
    """获取分组的所有API密钥（包含model_name），自动解密"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, group_id, api_provider, api_token, model_name, is_active, is_valid, created_at, updated_at
            FROM group_api_keys 
            WHERE group_id = %s AND is_active = 1 AND is_valid = 1
            ORDER BY api_provider
        """, (group_id,))
        
        results = cursor.fetchall()
        if results:
            # #22 解密API密钥
            for row in results:
                if 'api_token' in row and row['api_token']:
                    row['api_token'] = decrypt_api_token(row['api_token'])
        return results if results else []
    except Exception as e:
        logger.error(f"获取分组API密钥失败: {e}")
        return []
    finally:
        safe_db_close(conn, cursor)

def get_user_llm_provider(user_id: int) -> Optional[str]:
    """获取用户分组配置的LLM提供商（local_llm 或 siliconflow）
    
    优先级: local_llm > siliconflow
    """
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        
        # 获取用户分组ID
        cursor.execute("SELECT group_id FROM users WHERE id = %s", (user_id,))
        user_result = cursor.fetchone()
        
        if not user_result or not user_result['group_id']:
            return None
        
        group_id = user_result['group_id']
        
        # 查询该分组所有活跃的LLM提供商
        cursor.execute("""
            SELECT api_provider
            FROM group_api_keys 
            WHERE group_id = %s AND api_provider IN ('local_llm', 'siliconflow') 
                  AND is_active = 1 AND is_valid = 1
            ORDER BY FIELD(api_provider, 'local_llm', 'siliconflow')
            LIMIT 1
        """, (group_id,))
        
        result = cursor.fetchone()
        if result:
            logger.info(f"用户 {user_id} (分组 {group_id}) 的LLM提供商: {result['api_provider']}")
            return result['api_provider']
        
        return None
        
    except Exception as e:
        logger.error(f"获取用户LLM提供商失败: {e}")
        return None
    finally:
        safe_db_close(conn, cursor)


def get_user_mineru_provider(user_id: int) -> Optional[str]:
    """获取用户分组配置的MinerU提供商（local_mineru 或 mineru）
    
    优先级: local_mineru > mineru
    """
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        
        cursor.execute("SELECT group_id FROM users WHERE id = %s", (user_id,))
        user_result = cursor.fetchone()
        
        if not user_result or not user_result['group_id']:
            return None
        
        group_id = user_result['group_id']
        
        # 查询该分组活跃的MinerU提供商
        cursor.execute("""
            SELECT api_provider
            FROM group_api_keys 
            WHERE group_id = %s AND api_provider IN ('local_mineru', 'mineru') 
                  AND is_active = 1 AND is_valid = 1
            ORDER BY FIELD(api_provider, 'local_mineru', 'mineru')
            LIMIT 1
        """, (group_id,))
        
        result = cursor.fetchone()
        if result:
            logger.info(f"用户 {user_id} (分组 {group_id}) 的MinerU提供商: {result['api_provider']}")
            return result['api_provider']
        
        return None
        
    except Exception as e:
        logger.error(f"获取用户MinerU提供商失败: {e}")
        return None
    finally:
        safe_db_close(conn, cursor)


def get_user_siliconflow_model(user_id: int) -> Optional[str]:
    """获取用户分组配置的SiliconFlow模型名称"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        
        # 首先获取用户的分组ID
        cursor.execute("SELECT group_id FROM users WHERE id = %s", (user_id,))
        user_result = cursor.fetchone()
        
        if not user_result or not user_result['group_id']:
            logger.warning(f"用户 {user_id} 没有分组，无法获取模型配置")
            return None
        
        group_id = user_result['group_id']
        
        # 从分组密钥表获取SiliconFlow配置的模型名称
        cursor.execute("""
            SELECT model_name
            FROM group_api_keys 
            WHERE group_id = %s AND api_provider = 'siliconflow' AND is_active = 1 AND is_valid = 1
            LIMIT 1
        """, (group_id,))
        
        result = cursor.fetchone()
        if result and result.get('model_name'):
            logger.info(f"为用户 {user_id} (分组 {group_id}) 获取到SiliconFlow模型: {result['model_name']}")
            return result['model_name']
        else:
            logger.info(f"用户 {user_id} (分组 {group_id}) 未配置SiliconFlow模型，将使用默认模型")
            return None
        
    except Exception as e:
        logger.error(f"获取用户SiliconFlow模型失败: {e}")
        return None
    finally:
        safe_db_close(conn, cursor)

# ================================
# 任务相关操作
# ================================

def update_task_status_in_db(task_id: str, status: str, progress: Optional[int] = None, 
                            message: Optional[str] = None, batch_id: Optional[str] = None,
                            error_details: Optional[str] = None,
                            download_url: Optional[str] = None, download_path: Optional[str] = None) -> bool:
    """更新任务状态 - 仅内存管理，无需数据库操作"""
    # 由于使用纯内存任务管理，此函数不再需要数据库操作
    # 保留函数签名以保持兼容性，但直接返回 True
    return True

# ================================
# 系统日志操作
# ================================

def log_user_action(user_id: Optional[int], action: str, details: Optional[str] = None, 
                   ip_address: Optional[str] = None, user_agent: Optional[str] = None) -> bool:
    """记录用户操作日志"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        
        # 严格验证user_id类型和值
        if user_id is not None:
            # 确保user_id是整数类型
            if not isinstance(user_id, int):
                logger.error(f"记录用户操作日志失败: 用户ID {user_id} 类型错误，期望int，实际{type(user_id)}")
                return False
            
            # 验证user_id是否存在于users表中
            cursor.execute("SELECT id FROM users WHERE id = %s", (user_id,))
            if not cursor.fetchone():
                logger.error(f"记录用户操作日志失败: 用户ID {user_id} 在users表中不存在")
                return False
        
        cursor.execute("""
            INSERT INTO system_logs 
            (user_id, action, details, ip_address, user_agent, created_at)
            VALUES (%s, %s, %s, %s, %s, NOW())
        """, (user_id, action, details, ip_address, user_agent))
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"记录用户操作日志失败: {e}")
        # 记录更详细的错误信息
        if "foreign key constraint fails" in str(e):
            logger.error(f"外键约束失败 - user_id: {user_id} (type: {type(user_id)}), action: {action}")
        return False
    finally:
        safe_db_close(conn, cursor)

# ================================
# 辅助函数
# ================================

def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """根据用户ID获取用户信息"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, username, email, password_hash, 
                   created_at, updated_at, is_active, role, group_id, group_name, group_status
            FROM users 
            WHERE id = %s AND is_active = 1
        """, (user_id,))
        result = cursor.fetchone()
        return result
    except Exception as e:
        logger.error(f"获取用户信息失败: {e}")
        return None
    finally:
        safe_db_close(conn, cursor)

def get_file_by_id(file_id: str) -> Optional[Dict[str, Any]]:
    """根据文件ID获取文件信息"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, file_id, user_id, original_name, safe_filename, file_path,
                   upload_time, size, status, storage_type, md_file_path, 
                   processed_time, task_id
            FROM user_files 
            WHERE file_id = %s
        """, (file_id,))
        result = cursor.fetchone()
        return result
    except Exception as e:
        logger.error(f"获取文件信息失败: {e}")
        return None
    finally:
        safe_db_close(conn, cursor)

def get_task_by_id(task_id: str) -> Optional[Dict[str, Any]]:
    """根据任务ID获取任务信息 - 已废弃，使用内存任务管理"""
    # 由于使用纯内存任务管理，此函数已废弃
    # 保留函数签名以保持兼容性，但返回 None
    logger.warning(f"get_task_by_id({task_id}) 已废弃，请使用内存中的 tasks_db")
    return None

def update_file_complete_status(user_id: int, file_id: str) -> bool:
    """检查并更新文档完成状态"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        # 获取文件信息，包括文档类型和参考文献相关字段
        cursor.execute("""
            SELECT original_name, original_document_type, md_content, nsfc_json_data, extracted_json_data, 
                   storage_type, md_file_path, reference_md_content, reference_validation_json
            FROM user_files 
            WHERE file_id = %s AND user_id = %s
        """, (file_id, user_id))
        
        result = cursor.fetchone()
        if not result:
            return False
        
        # 从数据库获取文档类型
        original_name = result['original_name'] or ''
        document_type = result['original_document_type'] or 'unknown'
        is_word_document = document_type in ['word_doc', 'word_docx']
        
        # 检查MD内容
        has_md = False
        if result['md_content']:
            has_md = True
        elif result['storage_type'] == 'filesystem' and result['md_file_path']:
            try:
                # 这里需要导入md_storage_manager，但为了避免循环导入，我们简化处理
                has_md = True  # 假设文件存在
            except:
                has_md = False
        
        # 检查参考文献相关字段
        has_reference_md = bool(result['reference_md_content'] and result['reference_md_content'].strip())
        has_reference_validation = bool(result['reference_validation_json'] and result['reference_validation_json'].strip())
        
        has_nsfc = bool(result['nsfc_json_data'] and result['nsfc_json_data'].strip())
        has_extracted = bool(result['extracted_json_data'] and result['extracted_json_data'].strip())
        
        # 调试信息
        logger.info(f"文件状态检查 {file_id}:")
        logger.info(f"  - 文件名: {original_name}")
        logger.info(f"  - 文档类型: {document_type}")
        logger.info(f"  - 是否Word文档: {is_word_document}")
        logger.info(f"  - 参考文献内容: {has_reference_md}")
        logger.info(f"  - 验证JSON: {has_reference_validation}")
        if result['reference_md_content']:
            logger.info(f"  - 参考文献长度: {len(result['reference_md_content'])} 字符")
        if result['reference_validation_json']:
            logger.info(f"  - 验证JSON长度: {len(result['reference_validation_json'])} 字符")
        
        # 根据文档类型使用不同的完成判断标准
        if is_word_document:
            # Word文档：只需要有完整的参考文献内容和验证JSON即可
            is_complete = has_reference_md and has_reference_validation
            logger.info(f"  - Word文档完成状态: {is_complete}")
        else:
            # PDF文档：需要MD、正文JSON、表格JSON都存在
            is_complete = has_md and has_nsfc and has_extracted
            logger.info(f"  - PDF文档完成状态: {is_complete}")
        
        if is_complete:
            # 完整时设为completed，并记录processed_time
            cursor.execute("""
                UPDATE user_files 
                SET status = 'completed', error_message = NULL, processed_time = NOW()
                WHERE file_id = %s AND user_id = %s AND status != 'completed'
            """, (file_id, user_id))
            
            # 检查是否真的更新了状态（避免重复记录日志）
            if cursor.rowcount > 0:
                logger.info(f"文件 {file_id} 标记为完成")
                
                # 获取文件名用于日志记录
                cursor.execute("SELECT original_name FROM user_files WHERE file_id = %s", (file_id,))
                file_result = cursor.fetchone()
                file_name = file_result['original_name'] if file_result else file_id
                
                # 记录处理成功到系统日志
                log_user_action(
                    user_id, 
                    'file_processed', 
                    f"文件 {file_name} 处理成功完成",
                    None,  # ip_address  
                    None   # user_agent
                )
            else:
                logger.info(f"文件 {file_id} 已经是完成状态，跳过重复日志记录")
        else:
            # 不完整时设为error状态
            missing_parts = []
            
            if is_word_document:
                # Word文档只检查参考文献相关字段
                if not has_reference_md:
                    missing_parts.append("参考文献内容")
                if not has_reference_validation:
                    missing_parts.append("参考文献验证JSON")
            else:
                # PDF文档检查所有必需字段
                if not has_md:
                    missing_parts.append("MD文档")
                if not has_nsfc:
                    missing_parts.append("正文JSON")
                if not has_extracted:
                    missing_parts.append("表格JSON")
            
            error_message = f"缺失文件：{', '.join(missing_parts)}"
            cursor.execute("""
                UPDATE user_files 
                SET status = 'error', error_message = %s
                WHERE file_id = %s AND user_id = %s
            """, (error_message, file_id, user_id))
            logger.info(f"文件 {file_id} 标记为错误（缺失文件）：{error_message}")
        
        conn.commit()
        return True
        
    except Exception as e:
        logger.error(f"更新文档完成状态失败: {e}")
        return False
    finally:
        safe_db_close(conn, cursor)


# ================================
# 通知系统数据库操作
# ================================

def get_all_notifications_for_admin(page: int = 1, per_page: int = 20, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """管理员获取所有通知（分页、筛选）"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return {'notifications': [], 'total': 0, 'pages': 0}
    
    try:
        cursor = conn.cursor()
        
        # 构建查询条件
        where_conditions = []
        params = []
        
        # 管理员只看发送给管理员的通知，不看管理员发送的通知
        # 包括：1. recipient_id为空的系统通知 2. recipient_id是管理员的通知
        where_conditions.append("(n.recipient_id IS NULL OR u_recipient.role = 'admin')")
        
        if filters:
            # 支持管理员页面的filter参数（all/read/unread）
            if filters.get('filter'):
                filter_type = filters['filter']
                if filter_type == 'read':
                    where_conditions.append("n.is_read = 1")
                elif filter_type == 'unread':
                    where_conditions.append("n.is_read = 0")
                # 'all' 不需要额外条件
            
            if filters.get('type'):
                where_conditions.append("n.type = %s")
                params.append(filters['type'])
            
            if filters.get('is_read') is not None:
                where_conditions.append("n.is_read = %s")
                params.append(int(filters['is_read']))
            
            if filters.get('date_from'):
                where_conditions.append("DATE(n.created_at) >= %s")
                params.append(filters['date_from'])
            
            if filters.get('date_to'):
                where_conditions.append("DATE(n.created_at) <= %s")
                params.append(filters['date_to'])
        
        where_clause = " AND " + " AND ".join(where_conditions) if where_conditions else ""
        
        # 获取总数
        count_sql = f"""
            SELECT COUNT(*) as total
            FROM notifications n
            LEFT JOIN users u_sender ON n.sender_id = u_sender.id
            LEFT JOIN users u_recipient ON n.recipient_id = u_recipient.id
            WHERE 1=1 {where_clause}
        """
        cursor.execute(count_sql, params)
        result = cursor.fetchone()
        if not result:
            raise Exception("Failed to get notifications count")
        total = result['total']
        
        # 计算分页
        offset = (page - 1) * per_page
        pages = (total + per_page - 1) // per_page
        
        # 获取分页数据
        data_sql = f"""
            SELECT n.id, n.title, n.content, n.type, n.is_read, n.created_at,
                   u_sender.username as sender_name, u_sender.role as sender_role,
                   u_recipient.username as recipient_name, u_recipient.role as recipient_role
            FROM notifications n
            LEFT JOIN users u_sender ON n.sender_id = u_sender.id
            LEFT JOIN users u_recipient ON n.recipient_id = u_recipient.id
            WHERE 1=1 {where_clause}
            ORDER BY n.created_at DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(data_sql, params + [per_page, offset])
        notifications = cursor.fetchall()
        
        # 格式化数据
        formatted_notifications = []
        for notification in notifications:
            formatted_notifications.append({
                'id': notification['id'],
                'title': notification['title'],
                'content': notification['content'],
                'type': notification['type'],
                'is_read': bool(notification['is_read']),
                'created_at': notification['created_at'].strftime('%Y-%m-%d %H:%M:%S'),
                'sender_name': notification['sender_name'],
                'sender_role': notification['sender_role'],
                'recipient_name': notification['recipient_name'] or '全体用户',
                'recipient_role': notification['recipient_role']
            })
        
        return {
            'notifications': formatted_notifications,
            'total': total,
            'pages': pages,
            'current_page': page,
            'per_page': per_page
        }
        
    except Exception as e:
        logger.error(f"获取通知列表失败: {e}")
        return {'notifications': [], 'total': 0, 'pages': 0}
    finally:
        safe_db_close(conn, cursor)


def send_system_notification(sender_id: int, title: str, content: str, 
                           target_type: str = 'all', target_users: Optional[List[int]] = None) -> Optional[int]:
    """发送系统通知"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        
        if target_type == 'all':
            # 发送给所有用户（recipient_id为NULL表示全体通知）
            cursor.execute("""
                INSERT INTO notifications (sender_id, recipient_id, title, content, type)
                VALUES (%s, NULL, %s, %s, 'system')
            """, (sender_id, title, content))
            
            notification_id = cursor.lastrowid
            
        elif target_type == 'role':
            # 按角色发送
            notification_id = None
            if target_users:  # target_users此时包含角色名称
                for role in target_users:
                    # 获取该角色的所有用户
                    cursor.execute("SELECT id FROM users WHERE role = %s", (role,))
                    users = cursor.fetchall()
                    
                    for user in users:
                        cursor.execute("""
                            INSERT INTO notifications (sender_id, recipient_id, title, content, type)
                            VALUES (%s, %s, %s, %s, 'system')
                        """, (sender_id, user['id'], title, content))
                        if notification_id is None:
                            notification_id = cursor.lastrowid
            
        elif target_type == 'users':
            # 发送给指定用户
            notification_id = None
            if target_users:
                for user_id in target_users:
                    cursor.execute("""
                        INSERT INTO notifications (sender_id, recipient_id, title, content, type)
                        VALUES (%s, %s, %s, %s, 'personal')
                    """, (sender_id, user_id, title, content))
                    if notification_id is None:
                        notification_id = cursor.lastrowid
        
        conn.commit()
        return notification_id
        
    except Exception as e:
        logger.error(f"发送通知失败: {e}")
        return None
    finally:
        safe_db_close(conn, cursor)


def bulk_update_notifications(notification_ids: List[int], action: str, admin_id: int) -> bool:
    """批量更新通知状态"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        
        if action == 'mark_read':
            # 批量标记为已读
            placeholders = ','.join(['%s'] * len(notification_ids))
            cursor.execute(f"""
                UPDATE notifications 
                SET is_read = 1, updated_at = NOW()
                WHERE id IN ({placeholders})
            """, notification_ids)
            
        elif action == 'delete':
            # 批量删除
            placeholders = ','.join(['%s'] * len(notification_ids))
            cursor.execute(f"""
                DELETE FROM notifications 
                WHERE id IN ({placeholders})
            """, notification_ids)
        
        conn.commit()
        return True
        
    except Exception as e:
        logger.error(f"批量更新通知失败: {e}")
        return False
    finally:
        safe_db_close(conn, cursor)


def save_user_feedback(user_id: int, feedback_type: str, priority: str, title: str, content: str) -> bool:
    """保存用户反馈"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        
        # 映射前端priority到数据库feedback_type
        db_feedback_type = 'suggestion'  # 默认值
        if priority in ['high', 'urgent']:
            db_feedback_type = 'bug_report'
        elif 'feature' in title.lower() or 'function' in title.lower():
            db_feedback_type = 'feature_request'
        
        cursor.execute("""
            INSERT INTO user_feedback (user_id, subject, content, feedback_type, status)
            VALUES (%s, %s, %s, %s, 'open')
        """, (user_id, title, content, db_feedback_type))
        
        feedback_id = cursor.lastrowid
        conn.commit()
        
        # 向管理员发送通知
        cursor.execute("SELECT id FROM users WHERE role = 'admin'")
        admin_users = cursor.fetchall()
        
        notification_title = f'新的用户反馈 - {title}'
        notification_content = f'用户反馈类型：{feedback_type}\n优先级：{priority}\n\n内容：{content}\n\n请及时查看和处理。'
        
        for admin_user in admin_users:
            cursor.execute("""
                INSERT INTO notifications (sender_id, recipient_id, title, content, type)
                VALUES (%s, %s, %s, %s, 'system')
            """, (user_id, admin_user['id'], notification_title, notification_content))
        
        conn.commit()
        return True
        
    except Exception as e:
        logger.error(f"保存用户反馈失败: {e}")
        return False
    finally:
        safe_db_close(conn, cursor)


def get_user_feedback_history(user_id: int, page: int = 1, per_page: int = 10) -> List[Dict[str, Any]]:
    """获取用户反馈历史"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        
        offset = (page - 1) * per_page
        
        cursor.execute("""
            SELECT f.id, f.subject, f.content, f.feedback_type, f.status, 
                   f.admin_reply, f.created_at, f.replied_at,
                   u.username as replied_by_name
            FROM user_feedback f
            LEFT JOIN users u ON f.replied_by = u.id
            WHERE f.user_id = %s
            ORDER BY f.created_at DESC
            LIMIT %s OFFSET %s
        """, (user_id, per_page, offset))
        
        feedbacks = cursor.fetchall()
        
        formatted_feedbacks = []
        for feedback in feedbacks:
            formatted_feedbacks.append({
                'id': feedback['id'],
                'subject': feedback['subject'],
                'content': feedback['content'],
                'feedback_type': feedback['feedback_type'],
                'status': feedback['status'],
                'admin_reply': feedback['admin_reply'],
                'created_at': feedback['created_at'].strftime('%Y-%m-%d %H:%M:%S'),
                'replied_at': feedback['replied_at'].strftime('%Y-%m-%d %H:%M:%S') if feedback['replied_at'] else None,
                'replied_by_name': feedback['replied_by_name']
            })
        
        return formatted_feedbacks
        
    except Exception as e:
        logger.error(f"获取用户反馈历史失败: {e}")
        return []
    finally:
        safe_db_close(conn, cursor)


def get_all_feedbacks_for_admin(page: int = 1, per_page: int = 20, status_filter: Optional[str] = None) -> Dict[str, Any]:
    """管理员获取所有反馈"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return {'feedbacks': [], 'total': 0, 'pages': 0}
    
    try:
        cursor = conn.cursor()
        
        # 构建查询条件
        where_clause = ""
        params = []
        
        if status_filter:
            where_clause = " AND f.status = %s"
            params.append(status_filter)
        
        # 获取总数
        count_sql = f"""
            SELECT COUNT(*) as total
            FROM user_feedback f
            JOIN users u ON f.user_id = u.id
            WHERE 1=1 {where_clause}
        """
        cursor.execute(count_sql, params)
        result = cursor.fetchone()
        if not result:
            raise Exception("Failed to get user feedback count")
        total = result['total']
        
        # 计算分页
        offset = (page - 1) * per_page
        pages = (total + per_page - 1) // per_page
        
        # 获取分页数据
        data_sql = f"""
            SELECT f.id, f.subject, f.content, f.feedback_type, f.status, 
                   f.admin_reply, f.created_at, f.replied_at,
                   u.username, u.role as user_role,
                   admin_user.username as replied_by_name
            FROM user_feedback f
            JOIN users u ON f.user_id = u.id
            LEFT JOIN users admin_user ON f.replied_by = admin_user.id
            WHERE 1=1 {where_clause}
            ORDER BY f.created_at DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(data_sql, params + [per_page, offset])
        feedbacks = cursor.fetchall()
        
        # 格式化数据
        formatted_feedbacks = []
        for feedback in feedbacks:
            formatted_feedbacks.append({
                'id': feedback['id'],
                'subject': feedback['subject'],
                'content': feedback['content'],
                'feedback_type': feedback['feedback_type'],
                'status': feedback['status'],
                'admin_reply': feedback['admin_reply'],
                'created_at': feedback['created_at'].strftime('%Y-%m-%d %H:%M:%S'),
                'replied_at': feedback['replied_at'].strftime('%Y-%m-%d %H:%M:%S') if feedback['replied_at'] else None,
                'username': feedback['username'],
                'user_role': feedback['user_role'],
                'replied_by_name': feedback['replied_by_name']
            })
        
        return {
            'feedbacks': formatted_feedbacks,
            'total': total,
            'pages': pages,
            'current_page': page,
            'per_page': per_page
        }
        
    except Exception as e:
        logger.error(f"获取反馈列表失败: {e}")
        return {'feedbacks': [], 'total': 0, 'pages': 0}
    finally:
        safe_db_close(conn, cursor)


def reply_to_feedback(feedback_id: int, admin_id: int, reply_content: str) -> bool:
    """管理员回复反馈"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        
        # 更新反馈记录
        cursor.execute("""
            UPDATE user_feedback 
            SET admin_reply = %s, replied_by = %s, replied_at = NOW(), 
                status = 'in_progress', updated_at = NOW()
            WHERE id = %s
        """, (reply_content, admin_id, feedback_id))
        
        # 获取反馈信息，向用户发送通知
        cursor.execute("""
            SELECT f.user_id, f.subject, u.username as admin_name
            FROM user_feedback f
            JOIN users u ON u.id = %s
            WHERE f.id = %s
        """, (admin_id, feedback_id))
        
        feedback_info = cursor.fetchone()
        if feedback_info:
            notification_title = f'您的反馈已收到回复 - {feedback_info["subject"]}'
            notification_content = f'管理员 {feedback_info["admin_name"]} 已回复您的反馈：\n\n{reply_content}\n\n请查看详情。'
            
            cursor.execute("""
                INSERT INTO notifications (sender_id, recipient_id, title, content, type)
                VALUES (%s, %s, %s, %s, 'personal')
            """, (admin_id, feedback_info['user_id'], notification_title, notification_content))
        
        conn.commit()
        return True
        
    except Exception as e:
        logger.error(f"回复反馈失败: {e}")
        return False
    finally:
        safe_db_close(conn, cursor)


def update_feedback_status_with_admin(feedback_id: int, status: str, admin_id: int) -> bool:
    """更新反馈状态"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        
        cursor.execute("""
            UPDATE user_feedback 
            SET status = %s, updated_at = NOW()
            WHERE id = %s
        """, (status, feedback_id))
        
        conn.commit()
        return True
        
    except Exception as e:
        logger.error(f"更新反馈状态失败: {e}")
        return False
    finally:
        safe_db_close(conn, cursor)


def get_api_requests_for_admin(page: int = 1, per_page: int = 20, status_filter: Optional[str] = None) -> Dict[str, Any]:
    """获取API申请记录 - 已废弃，管理员直接分配API密钥"""
    # API申请功能已废弃，管理员直接为用户分配API密钥
    logger.warning("get_api_requests_for_admin 已废弃，请使用管理员直接分配API密钥功能")
    return {'api_requests': [], 'total': 0, 'pages': 0}


def get_api_request_details(request_id: int) -> Optional[Dict[str, Any]]:
    """获取API申请详情 - 已废弃，管理员直接分配API密钥"""
    # API申请功能已废弃，管理员直接为用户分配API密钥
    logger.warning("get_api_request_details 已废弃，请使用管理员直接分配API密钥功能")
    return None

def get_unread_notification_count(user_id: int) -> int:
    """
    获取用户未读通知数量 - 支持个人通知和全局通知的个人读取状态
    
    Args:
        user_id: 用户ID
        
    Returns:
        int: 未读通知数量
    """
    conn, cursor = None, None
    try:
        conn, error_response, status_code = get_db_connection_with_error_handling()
        if not conn:
            return 0
        
        cursor = conn.cursor()
        
        # 查询用户未读通知数量 - 使用与get_user_notifications相同的逻辑
        cursor.execute("""
            SELECT COUNT(*) as count 
            FROM notifications n
            LEFT JOIN user_notification_reads unr ON (n.id = unr.notification_id AND unr.user_id = %s AND n.recipient_id IS NULL)
            WHERE (n.recipient_id = %s OR 
                   (n.recipient_id IS NULL AND (unr.read_at IS NOT NULL OR unr.id IS NULL)))
                  AND (
                      (n.recipient_id = %s AND n.is_read = 0) OR 
                      (n.recipient_id IS NULL AND unr.id IS NULL)
                  )
        """, (user_id, user_id, user_id))
        
        result = cursor.fetchone()
        return result['count'] if result else 0
        
    except Exception as e:
        logger.error(f"获取用户未读通知数量失败: {e}")
        return 0
    finally:
        safe_db_close(conn, cursor)

def get_user_notifications(user_id: int, page: int = 1, page_size: int = 10, filter_type: str = 'all') -> Dict[str, Any]:
    """
    获取用户通知列表（分页）
    
    Args:
        user_id: 用户ID
        page: 页码
        page_size: 每页大小
        filter_type: 筛选类型 ('all', 'unread', 'read')
        
    Returns:
        Dict: 包含通知列表和分页信息的字典
    """
    conn, cursor = None, None
    try:
        conn, error_response, status_code = get_db_connection_with_error_handling()
        if not conn:
            return {'success': False, 'message': '数据库连接失败'}
        
        cursor = conn.cursor()
        
        # 获取分页数据 - 使用新的用户读取记录表优化查询
        offset = (page - 1) * page_size
        
        # 构建主查询 - 联合用户特定通知和全局通知，排除用户删除的全局通知
        base_query = """
            SELECT n.id, n.title, n.content, n.type, n.created_at, n.sender_id, n.recipient_id,
                   CASE 
                       WHEN n.recipient_id = %s THEN n.is_read
                       WHEN n.recipient_id IS NULL THEN COALESCE(unr.read_at IS NOT NULL, 0)
                       ELSE 0
                   END as is_read
            FROM notifications n
            LEFT JOIN user_notification_reads unr ON (n.id = unr.notification_id AND unr.user_id = %s AND n.recipient_id IS NULL)
            WHERE (n.recipient_id = %s OR 
                   (n.recipient_id IS NULL AND (unr.read_at IS NOT NULL OR unr.id IS NULL)))
        """
        
        # 添加筛选条件
        if filter_type == 'unread':
            base_query += """
                AND (
                    (n.recipient_id = %s AND n.is_read = 0) OR 
                    (n.recipient_id IS NULL AND unr.read_at IS NULL AND unr.id IS NOT NULL)
                )
            """
            params = [user_id, user_id, user_id, user_id]
        elif filter_type == 'read':
            base_query += """
                AND (
                    (n.recipient_id = %s AND n.is_read = 1) OR 
                    (n.recipient_id IS NULL AND unr.read_at IS NOT NULL)
                )
            """
            params = [user_id, user_id, user_id, user_id]
        else:
            params = [user_id, user_id, user_id]
        
        # 添加排序和分页
        base_query += " ORDER BY n.created_at DESC LIMIT %s OFFSET %s"
        params.extend([page_size, offset])
        
        cursor.execute(base_query, params)
        notifications = cursor.fetchall()
        
        # 重新计算总数
        count_query = """
            SELECT COUNT(*) as total
            FROM notifications n
            LEFT JOIN user_notification_reads unr ON (n.id = unr.notification_id AND unr.user_id = %s AND n.recipient_id IS NULL)
            WHERE (n.recipient_id = %s OR 
                   (n.recipient_id IS NULL AND (unr.read_at IS NOT NULL OR unr.id IS NULL)))
        """
        
        count_params = [user_id, user_id]
        if filter_type == 'unread':
            count_query += """
                AND (
                    (n.recipient_id = %s AND n.is_read = 0) OR 
                    (n.recipient_id IS NULL AND unr.read_at IS NULL AND unr.id IS NOT NULL)
                )
            """
            count_params.append(user_id)
        elif filter_type == 'read':
            count_query += """
                AND (
                    (n.recipient_id = %s AND n.is_read = 1) OR 
                    (n.recipient_id IS NULL AND unr.read_at IS NOT NULL)
                )
            """
            count_params.append(user_id)
        
        cursor.execute(count_query, count_params)
        result = cursor.fetchone()
        if not result:
            raise Exception("Failed to get notifications count for user")
        total = result['total']
        formatted_notifications = []
        for notification in notifications:
            formatted_notifications.append({
                'id': notification['id'],
                'title': notification['title'],
                'content': notification['content'],
                'type': notification['type'],
                'is_read': bool(notification['is_read']),
                'created_at': notification['created_at'].strftime('%Y-%m-%d %H:%M:%S') if notification['created_at'] else '',
                'sender_id': notification['sender_id'],
                'is_global': notification['recipient_id'] is None  # 标记是否为全局通知
            })
        
        return {
            'success': True,
            'notifications': formatted_notifications,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total': total,
                'total_pages': (total + page_size - 1) // page_size
            }
        }
        
    except Exception as e:
        logger.error(f"获取用户通知列表失败: {e}")
        return {'success': False, 'message': '获取通知列表失败'}
    finally:
        safe_db_close(conn, cursor)

def mark_notifications_as_read(user_id: int, notification_ids: List[int] = None) -> bool:
    """
    标记通知为已读 - 支持用户特定通知和全局通知
    
    Args:
        user_id: 用户ID
        notification_ids: 通知ID列表，如果为None则标记所有未读通知
        
    Returns:
        bool: 操作是否成功
    """
    conn, cursor = None, None
    try:
        conn, error_response, status_code = get_db_connection_with_error_handling()
        if not conn:
            return False
        
        cursor = conn.cursor()
        
        if notification_ids:
            # 标记指定通知为已读
            for notification_id in notification_ids:
                # 先检查这是用户特定通知还是全局通知
                cursor.execute("SELECT recipient_id FROM notifications WHERE id = %s", (notification_id,))
                result = cursor.fetchone()
                
                if result:
                    if result['recipient_id'] == user_id:
                        # 用户特定通知：更新is_read字段
                        cursor.execute(
                            "UPDATE notifications SET is_read = 1, updated_at = NOW() WHERE id = %s", 
                            (notification_id,)
                        )
                    elif result['recipient_id'] is None:
                        # 全局通知：插入读取记录
                        cursor.execute(
                            """INSERT IGNORE INTO user_notification_reads 
                               (user_id, notification_id, read_at) VALUES (%s, %s, NOW())""", 
                            (user_id, notification_id)
                        )
        else:
            # 标记所有未读通知为已读
            # 1. 标记用户特定的未读通知
            cursor.execute(
                "UPDATE notifications SET is_read = 1, updated_at = NOW() WHERE recipient_id = %s AND is_read = 0", 
                (user_id,)
            )
            
            # 2. 为所有未读的全局通知插入读取记录
            cursor.execute("""
                INSERT IGNORE INTO user_notification_reads (user_id, notification_id, read_at)
                SELECT %s, n.id, NOW()
                FROM notifications n
                LEFT JOIN user_notification_reads unr ON (n.id = unr.notification_id AND unr.user_id = %s)
                WHERE n.recipient_id IS NULL AND unr.id IS NULL
            """, (user_id, user_id))
        
        conn.commit()
        return True
        
    except Exception as e:
        logger.error(f"标记通知为已读失败: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        safe_db_close(conn, cursor)

def mark_single_notification_read(user_id: int, notification_id: int) -> bool:
    """
    标记单个通知为已读 - 便捷函数
    
    Args:
        user_id: 用户ID
        notification_id: 通知ID
        
    Returns:
        bool: 操作是否成功
    """
    return mark_notifications_as_read(user_id, [notification_id])

def delete_user_notifications(user_id: int, notification_ids: List[int]) -> bool:
    """
    删除用户通知 - 支持个人通知删除和全局通知的个人隐藏
    
    Args:
        user_id: 用户ID
        notification_ids: 要删除的通知ID列表
        
    Returns:
        bool: 操作是否成功
    """
    conn, cursor = None, None
    try:
        conn, error_response, status_code = get_db_connection_with_error_handling()
        if not conn:
            return False
        
        cursor = conn.cursor()
        
        for notification_id in notification_ids:
            # 检查通知类型
            cursor.execute("SELECT recipient_id FROM notifications WHERE id = %s", (notification_id,))
            result = cursor.fetchone()
            
            if result:
                if result['recipient_id'] == user_id:
                    # 个人通知：直接删除
                    cursor.execute("DELETE FROM notifications WHERE id = %s AND recipient_id = %s", 
                                 (notification_id, user_id))
                elif result['recipient_id'] is None:
                    # 全局通知：创建一个特殊的"已删除"记录，使用特殊的时间戳NULL来标记为删除
                    cursor.execute("""
                        INSERT INTO user_notification_reads (user_id, notification_id, read_at) 
                        VALUES (%s, %s, NULL)
                        ON DUPLICATE KEY UPDATE read_at = NULL
                    """, (user_id, notification_id))
        
        conn.commit()
        return True
        
    except Exception as e:
        logger.error(f"删除用户通知失败: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        safe_db_close(conn, cursor)

def clear_all_user_notifications(user_id: int) -> bool:
    """
    清除用户所有通知 - 删除个人通知并标记所有全局通知为已删除
    
    Args:
        user_id: 用户ID
        
    Returns:
        bool: 操作是否成功
    """
    conn, cursor = None, None
    try:
        conn, error_response, status_code = get_db_connection_with_error_handling()
        if not conn:
            return False
        
        cursor = conn.cursor()
        
        # 1. 删除所有个人通知
        cursor.execute("DELETE FROM notifications WHERE recipient_id = %s", (user_id,))
        
        # 2. 为所有全局通知创建"已删除"标记
        cursor.execute("""
            INSERT INTO user_notification_reads (user_id, notification_id, read_at)
            SELECT %s, n.id, NULL
            FROM notifications n
            WHERE n.recipient_id IS NULL
            ON DUPLICATE KEY UPDATE read_at = NULL
        """, (user_id,))
        
        conn.commit()
        return True
        
    except Exception as e:
        logger.error(f"清除所有用户通知失败: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        safe_db_close(conn, cursor)

# ==================== 管理员发送通知相关数据库操作 ====================

def get_all_users() -> List[Dict[str, Any]]:
    """获取所有用户列表，包含丰富的用户信息"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        
        sql = """
            SELECT 
                u.id, 
                u.username, 
                u.email, 
                u.role, 
                u.is_active,
                u.created_at, 
                (SELECT MAX(sl.created_at) FROM system_logs sl 
                 WHERE sl.user_id = u.id AND sl.action = 'login') as last_login,
                COALESCE((SELECT MAX(sl.created_at) FROM system_logs sl 
                         WHERE sl.user_id = u.id AND sl.action = 'login'), u.created_at) as last_active,
                COUNT(pt.id) as total_tasks,
                COUNT(CASE WHEN pt.status = 'completed' THEN 1 END) as completed_tasks,
                COUNT(CASE WHEN pt.status = 'failed' THEN 1 END) as failed_tasks,
                COUNT(CASE WHEN pt.status IN ('pending', 'processing') THEN 1 END) as active_tasks,
                CASE 
                    WHEN u.role = 'admin' THEN '管理员'
                    WHEN u.role = 'premium' THEN '高级用户'
                    WHEN u.role = 'user' THEN '普通用户'
                    ELSE '未知角色'
                END as role_display,
                CASE 
                    WHEN u.is_active = 1 THEN '活跃'
                    ELSE '停用'
                END as status_display
            FROM users u
            GROUP BY u.id, u.username, u.email, u.role, u.is_active, u.created_at
            ORDER BY u.created_at DESC
        """
        cursor.execute(sql)
        users = cursor.fetchall()
        
        return users
        
    except Exception as e:
        logger.error(f"获取用户列表失败: {e}")
        return []
    finally:
        safe_db_close(conn, cursor)

def get_active_users(days: int = 30) -> List[Dict[str, Any]]:
    """获取活跃用户列表（指定天数内有活动的用户），包含丰富的用户信息"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        
        sql = """
            SELECT 
                u.id, 
                u.username, 
                u.email, 
                u.role, 
                u.is_active,
                u.created_at,
                (SELECT MAX(sl.created_at) FROM system_logs sl 
                 WHERE sl.user_id = u.id AND sl.action = 'login') as last_login,
                COALESCE((SELECT MAX(sl.created_at) FROM system_logs sl 
                         WHERE sl.user_id = u.id AND sl.action = 'login'), u.created_at) as last_activity,
                COUNT(pt.id) as total_tasks,
                COUNT(CASE WHEN pt.status = 'completed' THEN 1 END) as completed_tasks,
                COUNT(CASE WHEN pt.status = 'failed' THEN 1 END) as failed_tasks,
                COUNT(CASE WHEN pt.status IN ('pending', 'processing') THEN 1 END) as active_tasks,
                CASE 
                    WHEN u.role = 'admin' THEN '管理员'
                    WHEN u.role = 'premium' THEN '高级用户'
                    WHEN u.role = 'user' THEN '普通用户'
                    ELSE '未知角色'
                END as role_display,
                CASE 
                    WHEN u.is_active = 1 THEN '活跃'
                    ELSE '停用'
                END as status_display
            FROM users u
            WHERE ((SELECT MAX(sl.created_at) FROM system_logs sl 
                    WHERE sl.user_id = u.id AND sl.action = 'login') >= DATE_SUB(NOW(), INTERVAL %s DAY)
                   OR ((SELECT MAX(sl.created_at) FROM system_logs sl 
                       WHERE sl.user_id = u.id AND sl.action = 'login') IS NULL 
                       AND u.created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)))
            GROUP BY u.id, u.username, u.email, u.role, u.is_active, u.created_at
            ORDER BY COALESCE((SELECT MAX(sl.created_at) FROM system_logs sl 
                              WHERE sl.user_id = u.id AND sl.action = 'login'), u.created_at) DESC
        """
        cursor.execute(sql, (days, days))
        users = cursor.fetchall()
        
        return users
        
    except Exception as e:
        logger.error(f"获取活跃用户列表失败: {e}")
        return []
    finally:
        safe_db_close(conn, cursor)

def get_all_feedbacks(page: int = 1, per_page: int = 20, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """获取所有反馈列表（分页、筛选）- 使用user_feedback表"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return {'feedbacks': [], 'total': 0, 'pages': 0}
    
    try:
        cursor = conn.cursor()
        
        # 构建查询条件
        where_conditions = []
        params = []
        
        if filters:
            if filters.get('type'):
                where_conditions.append("f.feedback_type = %s")
                params.append(filters['type'])
            
            if filters.get('status'):
                where_conditions.append("f.status = %s")
                params.append(filters['status'])
            
            if filters.get('search'):
                where_conditions.append("(f.subject LIKE %s OR f.content LIKE %s)")
                search_term = f"%{filters['search']}%"
                params.extend([search_term, search_term])
        
        where_clause = " AND " + " AND ".join(where_conditions) if where_conditions else ""
        
        # 获取总数
        count_sql = f"""
            SELECT COUNT(*) as total
            FROM user_feedback f
            LEFT JOIN users u ON f.user_id = u.id
            WHERE 1=1 {where_clause}
        """
        cursor.execute(count_sql, params)
        result = cursor.fetchone()
        if not result:
            raise Exception("Failed to get feedback count")
        total = result['total']
        
        # 计算分页
        offset = (page - 1) * per_page
        pages = (total + per_page - 1) // per_page
        
        # 获取分页数据
        data_sql = f"""
            SELECT f.id, f.subject as title, f.content, f.feedback_type, f.status, f.created_at,
                   u.username, u.email, f.admin_reply, f.replied_at
            FROM user_feedback f
            LEFT JOIN users u ON f.user_id = u.id
            WHERE 1=1 {where_clause}
            ORDER BY f.created_at DESC
            LIMIT %s OFFSET %s
        """
        cursor.execute(data_sql, params + [per_page, offset])
        feedbacks = cursor.fetchall()
        
        # 格式化数据
        formatted_feedbacks = []
        for feedback in feedbacks:
            formatted_feedbacks.append({
                'id': feedback['id'],
                'title': feedback['title'],
                'content': feedback['content'],
                'feedback_type': feedback['feedback_type'],
                'status': feedback['status'],
                'created_at': feedback['created_at'].strftime('%Y-%m-%d %H:%M:%S'),
                'username': feedback['username'],
                'email': feedback['email'],
                'admin_reply': feedback['admin_reply'],
                'replied_at': feedback['replied_at'].strftime('%Y-%m-%d %H:%M:%S') if feedback['replied_at'] else None
            })
        
        return {
            'feedbacks': formatted_feedbacks,
            'total': total,
            'pages': pages,
            'current_page': page,
            'per_page': per_page
        }
        
    except Exception as e:
        logger.error(f"获取反馈列表失败: {e}")
        return {'feedbacks': [], 'total': 0, 'pages': 0}
    finally:
        safe_db_close(conn, cursor)

def get_feedback_by_id(feedback_id: int) -> Optional[Dict[str, Any]]:
    """根据ID获取反馈详情 - 使用user_feedback表"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor()
        
        sql = """
            SELECT f.id, f.subject as title, f.content, f.feedback_type, f.status, f.created_at, f.updated_at,
                   u.username, u.email, u.id as user_id, f.admin_reply, f.replied_at, f.replied_by
            FROM user_feedback f
            LEFT JOIN users u ON f.user_id = u.id
            WHERE f.id = %s
        """
        cursor.execute(sql, (feedback_id,))
        feedback = cursor.fetchone()
        
        if feedback:
            return {
                'id': feedback['id'],
                'title': feedback['title'],
                'content': feedback['content'],
                'feedback_type': feedback['feedback_type'],
                'status': feedback['status'],
                'created_at': feedback['created_at'].strftime('%Y-%m-%d %H:%M:%S'),
                'updated_at': feedback['updated_at'].strftime('%Y-%m-%d %H:%M:%S') if feedback['updated_at'] else None,
                'username': feedback['username'],
                'email': feedback['email'],
                'user_id': feedback['user_id'],
                'admin_reply': feedback['admin_reply'],
                'replied_at': feedback['replied_at'].strftime('%Y-%m-%d %H:%M:%S') if feedback['replied_at'] else None,
                'replied_by': feedback['replied_by']
            }
        
        return None
        
    except Exception as e:
        logger.error(f"获取反馈详情失败: {e}")
        return None
    finally:
        safe_db_close(conn, cursor)

def reply_to_feedback(feedback_id: int, admin_id: int, reply_content: str, new_status: str = 'in_progress') -> bool:
    """回复反馈并发送通知 - 使用user_feedback表"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        
        # 获取反馈信息
        cursor.execute("SELECT subject, user_id FROM user_feedback WHERE id = %s", (feedback_id,))
        feedback = cursor.fetchone()
        
        if not feedback:
            return False
        
        # 更新反馈状态和回复内容
        update_sql = """
            UPDATE user_feedback 
            SET status = %s, admin_reply = %s, replied_by = %s, replied_at = NOW(), updated_at = NOW() 
            WHERE id = %s
        """
        cursor.execute(update_sql, (new_status, reply_content, admin_id, feedback_id))
        
        # 创建回复通知发送给用户
        notification_sql = """
            INSERT INTO notifications (sender_id, recipient_id, title, content, type, is_read, created_at)
            VALUES (%s, %s, %s, %s, %s, 0, NOW())
        """
        
        notification_title = f"反馈回复：{feedback['subject']}"
        cursor.execute(notification_sql, (
            admin_id, 
            feedback['user_id'], 
            notification_title, 
            reply_content, 
            'system'
        ))
        
        conn.commit()
        return True
        
    except Exception as e:
        logger.error(f"回复反馈失败: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        safe_db_close(conn, cursor)

def update_feedback_status(feedback_id: int, new_status: str) -> bool:
    """更新反馈状态 - 使用user_feedback表"""
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        
        sql = """
            UPDATE user_feedback 
            SET status = %s, updated_at = NOW() 
            WHERE id = %s
        """
        cursor.execute(sql, (new_status, feedback_id))
        conn.commit()
        
        return cursor.rowcount > 0
        
    except Exception as e:
        logger.error(f"更新反馈状态失败: {e}")
        if conn:
            conn.rollback()
        return False
    finally:
        safe_db_close(conn, cursor)

# ================================
# 便捷的错误处理和用户消息函数
# ================================

def get_user_errors_for_alerts(user_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """
    获取用户相关的错误信息，用于前端alert显示
    
    Args:
        user_id: 用户ID
        limit: 返回记录数限制
        
    Returns:
        List[Dict]: 错误信息列表，包含用户友好的消息
    """
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT action, details, created_at
            FROM system_logs 
            WHERE user_id = %s 
              AND action LIKE 'ERROR_%'
              AND created_at >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
            ORDER BY created_at DESC 
            LIMIT %s
        """, (user_id, limit))
        
        results = cursor.fetchall()
        alerts = []
        
        for record in results:
            try:
                # 解析错误详情
                details = json.loads(record['details']) if record['details'] else {}
                error_type = record['action'].replace('ERROR_', '')
                
                # 获取用户友好的消息
                user_message = ErrorHandler.get_user_message(error_type)
                
                # 确定alert类型
                severity = ErrorHandler.ERROR_SEVERITY.get(error_type, ErrorSeverity.MEDIUM)
                if severity == ErrorSeverity.CRITICAL:
                    alert_type = 'danger'
                elif severity == ErrorSeverity.HIGH:
                    alert_type = 'danger'  
                elif severity == ErrorSeverity.MEDIUM:
                    alert_type = 'warning'
                else:
                    alert_type = 'info'
                
                alerts.append({
                    'type': alert_type,
                    'message': user_message,
                    'error_type': error_type,
                    'error_id': details.get('error_id', ''),
                    'timestamp': record['created_at'].isoformat() if record['created_at'] else None
                })
                
            except (json.JSONDecodeError, KeyError):
                # 如果解析失败，跳过这条记录
                continue
                
        return alerts
        
    except Exception as e:
        logger.error(f"获取用户错误信息失败: {e}")
        return []
    finally:
        safe_db_close(conn, cursor)

def create_user_alert(user_id: int, alert_type: str, message: str, 
                     error_type: str = None, details: str = None) -> bool:
    """
    创建一个用户alert记录，用于后续显示
    
    Args:
        user_id: 用户ID
        alert_type: alert类型 (success, warning, danger, info)
        message: 用户消息
        error_type: 错误类型（可选）
        details: 详细信息（可选）
        
    Returns:
        bool: 是否成功创建
    """
    action = f"USER_ALERT_{alert_type.upper()}"
    
    alert_details = {
        'alert_type': alert_type,
        'message': message,
        'error_type': error_type,
        'details': details,
        'created_for_display': True
    }
    
    return log_user_action(
        user_id=user_id,
        action=action,
        details=json.dumps(alert_details, ensure_ascii=False)
    )

def get_system_health_alerts() -> List[Dict[str, Any]]:
    """
    获取系统健康状态相关的alert信息，供管理员查看
    
    Returns:
        List[Dict]: 系统alert信息列表
    """
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return []
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT action, details, created_at, COUNT(*) as count
            FROM system_logs 
            WHERE action LIKE 'ERROR_%'
              AND created_at >= DATE_SUB(NOW(), INTERVAL 1 HOUR)
            GROUP BY action, DATE_FORMAT(created_at, '%Y-%m-%d %H:%i')
            HAVING count > 1
            ORDER BY created_at DESC, count DESC
            LIMIT 20
        """)
        
        results = cursor.fetchall()
        alerts = []
        
        for record in results:
            try:
                error_type = record['action'].replace('ERROR_', '')
                severity = ErrorHandler.ERROR_SEVERITY.get(error_type, ErrorSeverity.MEDIUM)
                
                if severity in [ErrorSeverity.CRITICAL, ErrorSeverity.HIGH]:
                    alert_type = 'danger'
                elif severity == ErrorSeverity.MEDIUM:
                    alert_type = 'warning'
                else:
                    alert_type = 'info'
                
                alerts.append({
                    'type': alert_type,
                    'message': f"系统出现{record['count']}次{ErrorHandler.get_user_message(error_type)}",
                    'error_type': error_type,
                    'count': record['count'],
                    'severity': severity,
                    'timestamp': record['created_at'].isoformat() if record['created_at'] else None
                })
                
            except (json.JSONDecodeError, KeyError):
                continue
                
        return alerts
        
    except Exception as e:
        logger.error(f"获取系统健康状态失败: {e}")
        return []
    finally:
        safe_db_close(conn, cursor)

def log_user_success_action(user_id: int, action: str, message: str, 
                           details: str = None, ip_address: str = None, 
                           user_agent: str = None) -> bool:
    """
    记录用户成功操作，并创建成功alert
    
    Args:
        user_id: 用户ID
        action: 操作类型
        message: 成功消息
        details: 详细信息
        ip_address: IP地址
        user_agent: 用户代理
        
    Returns:
        bool: 是否记录成功
    """
    # 记录操作日志
    log_success = log_user_action(
        user_id=user_id,
        action=f"SUCCESS_{action}",
        details=details,
        ip_address=ip_address,
        user_agent=user_agent
    )
    
    # 创建成功alert
    alert_success = create_user_alert(
        user_id=user_id,
        alert_type='success',
        message=message,
        details=details
    )
    
    return log_success and alert_success

def validate_and_log_error(condition: bool, error_type: str, user_id: int = None, 
                          error_message: str = None, context: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
    """
    验证条件，如果失败则记录错误并返回错误结果
    
    Args:
        condition: 验证条件
        error_type: 错误类型
        user_id: 用户ID
        error_message: 自定义错误消息
        context: 上下文信息
        
    Returns:
        Optional[Dict]: 如果验证失败返回错误结果，否则返回None
    """
    if not condition:
        error_id = ErrorHandler.log_error(
            error_type=error_type,
            user_id=user_id,
            details=error_message or f"Validation failed for {error_type}",
            context=context or {}
        )
        
        user_message = error_message or ErrorHandler.get_user_message(error_type)
        
        return create_error_result(
            error_type=error_type,
            user_message=user_message,
            error_id=error_id
        )
    
    return None

# ================================
# 错误统计和分析函数
# ================================

def get_error_statistics(hours: int = 24) -> Dict[str, Any]:
    """
    获取错误统计信息
    
    Args:
        hours: 统计时间范围（小时）
        
    Returns:
        Dict: 错误统计信息
    """
    conn, error_response, status_code = get_db_connection_with_error_handling()
    if not conn:
        return {}
    
    try:
        cursor = conn.cursor()
        
        # 总错误数
        cursor.execute("""
            SELECT COUNT(*) as total_errors
            FROM system_logs 
            WHERE action LIKE 'ERROR_%'
              AND created_at >= DATE_SUB(NOW(), INTERVAL %s HOUR)
        """, (hours,))
        result = cursor.fetchone()
        if not result:
            raise Exception("Failed to get error analysis count")
        total_errors = result['total_errors']
        
        # 按错误类型统计
        cursor.execute("""
            SELECT 
                REPLACE(action, 'ERROR_', '') as error_type,
                COUNT(*) as count,
                COUNT(DISTINCT user_id) as affected_users
            FROM system_logs 
            WHERE action LIKE 'ERROR_%'
              AND created_at >= DATE_SUB(NOW(), INTERVAL %s HOUR)
            GROUP BY action
            ORDER BY count DESC
            LIMIT 10
        """, (hours,))
        error_types = cursor.fetchall()
        
        # 按严重程度统计
        severity_stats = {}
        for error in error_types:
            error_type = error['error_type']
            severity = ErrorHandler.ERROR_SEVERITY.get(error_type, ErrorSeverity.MEDIUM)
            if severity not in severity_stats:
                severity_stats[severity] = 0
            severity_stats[severity] += error['count']
        
        return {
            'total_errors': total_errors,
            'error_types': error_types,
            'severity_stats': severity_stats,
            'time_range_hours': hours
        }
        
    except Exception as e:
        logger.error(f"获取错误统计失败: {e}")
        return {}
    finally:
        safe_db_close(conn, cursor)


# ================================
# 向后兼容性包装函数
# ================================

def get_user_by_username_legacy(username: str) -> Optional[Dict[str, Any]]:
    """
    向后兼容的获取用户函数，返回原来的格式
    保持与现有代码的兼容性
    """
    result = get_user_by_username_original(username)
    if result['success']:
        return result['data']
    else:
        # 如果需要，可以在这里记录错误或显示flash消息
        return None

def get_user_by_username_or_email_legacy(identifier: str) -> Optional[Dict[str, Any]]:
    """
    向后兼容的获取用户函数，返回原来的格式
    """
    result = get_user_by_username_or_email_original(identifier)
    if result['success']:
        return result['data']
    else:
        return None

# 保存原始函数的引用并替换为向后兼容版本
get_user_by_username_original = get_user_by_username
get_user_by_username = get_user_by_username_legacy

get_user_by_username_or_email_original = get_user_by_username_or_email
get_user_by_username_or_email = get_user_by_username_or_email_legacy


# ================================
# 新的带错误处理的便捷函数
# ================================

def get_user_with_error_handling(username: str, user_id: Optional[int] = None, 
                                ip_address: Optional[str] = None, 
                                user_agent: Optional[str] = None) -> Dict[str, Any]:
    """
    获取用户信息，包含完整的错误处理
    推荐在新代码中使用此函数
    """
    return get_user_by_username_original(
        username=username, 
        request_user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent
    )

def validate_and_flash_errors(result: Dict[str, Any], success_message: str = None) -> bool:
    """
    验证操作结果并显示相应的flash消息
    
    Args:
        result: 标准化结果字典
        success_message: 成功时显示的消息（可选）
    
    Returns:
        bool: 操作是否成功
    """
    try:
        # 动态导入flask以避免循环依赖
        from flask import flash
        
        if result['success']:
            if success_message:
                flash(success_message, 'success')
            return True
        else:
            # 显示用户友好的错误消息
            error_message = result.get('message', '操作失败')
            error_type = result.get('error_type', '')
            
            # 根据错误类型选择flash消息类型
            if error_type.startswith('USER_'):
                flash(error_message, 'warning')
            elif error_type.startswith('FILE_'):
                flash(error_message, 'error')
            elif error_type.startswith('DB_'):
                flash(error_message, 'error')
            elif error_type.startswith('API_'):
                flash(error_message, 'warning')
            else:
                flash(error_message, 'error')
                
            return False
            
    except ImportError:
        # 如果flask不可用，仅记录到日志
        logger.warning(f"Flask不可用，无法显示flash消息: {result.get('message')}")
        return result['success']

def get_error_summary() -> Dict[str, Any]:
    """
    获取系统错误统计摘要
    返回各种错误类型的统计信息
    """
    try:
        conn, error_response, status_code = get_db_connection_with_error_handling()
        if not conn:
            return {'success': False, 'message': '无法连接数据库'}
        
        cursor = conn.cursor()
        
        # 获取最近24小时的错误统计
        cursor.execute("""
            SELECT 
                action,
                COUNT(*) as error_count,
                MAX(created_at) as last_occurred
            FROM system_logs 
            WHERE action LIKE 'ERROR_%' 
            AND created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
            GROUP BY action 
            ORDER BY error_count DESC
            LIMIT 10
        """)
        
        error_stats = cursor.fetchall()
        
        # 获取错误总数
        cursor.execute("""
            SELECT COUNT(*) as total_errors
            FROM system_logs 
            WHERE action LIKE 'ERROR_%' 
            AND created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
        """)
        
        total_result = cursor.fetchone()
        total_errors = total_result['total_errors'] if total_result else 0
        
        return {
            'success': True,
            'data': {
                'total_errors_24h': total_errors,
                'error_breakdown': error_stats,
                'timestamp': datetime.now().isoformat()
            }
        }
        
    except Exception as e:
        error_id = ErrorHandler.log_error(
            error_type=ErrorType.DB_QUERY_FAILED,
            details=f"Failed to get error summary: {str(e)}",
            exception=e
        )
        return create_error_result(
            ErrorType.DB_QUERY_FAILED,
            error_id=error_id
        )
    finally:
        safe_db_close(conn, cursor)
