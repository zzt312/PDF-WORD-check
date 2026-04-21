#!/usr/bin/env python3
"""
混合MD存储管理器 - 智能选择数据库存储或文件系统存储
"""

import os
import json
import hashlib
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple, Dict, Any

from database_config import DatabaseConfig


class MDStorageManager:
    """MD内容混合存储管理器"""
    
    # 存储策略配置
    DATABASE_SIZE_LIMIT = 50 * 1024  # 50KB以下使用数据库存储
    FILESYSTEM_SIZE_LIMIT = 10 * 1024 * 1024  # 10MB以上拒绝存储
    MD_STORAGE_DIR = "md_storage"  # MD文件存储目录
    
    def __init__(self):
        """初始化存储管理器"""
        self.ensure_storage_directory()
    
    def ensure_storage_directory(self):
        """确保MD存储目录存在"""
        storage_path = Path(self.MD_STORAGE_DIR)
        storage_path.mkdir(exist_ok=True)
        
        # 按年月创建子目录
        current_month = datetime.now().strftime("%Y%m")
        monthly_path = storage_path / current_month
        monthly_path.mkdir(exist_ok=True)
        
        return monthly_path
    
    def get_storage_strategy(self, md_content: str) -> str:
        """根据内容大小决定存储策略"""
        content_size = len(md_content.encode('utf-8'))
        
        if content_size <= self.DATABASE_SIZE_LIMIT:
            return 'database'
        elif content_size <= self.FILESYSTEM_SIZE_LIMIT:
            return 'filesystem'
        else:
            raise ValueError(f"MD内容过大 ({content_size} bytes)，超过最大限制 ({self.FILESYSTEM_SIZE_LIMIT} bytes)")
    
    def generate_md_file_path(self, file_id: str, original_name: str) -> str:
        """生成MD文件的存储路径"""
        monthly_dir = self.ensure_storage_directory()
        
        # 使用文件ID和原始名称生成安全的文件名
        safe_name = "".join(c for c in original_name if c.isalnum() or c in ('-', '_', '.')).rstrip()
        if not safe_name:
            safe_name = "document"
        
        # 移除原扩展名，添加.md
        if '.' in safe_name:
            safe_name = safe_name.rsplit('.', 1)[0]
        
        md_filename = f"{file_id}_{safe_name}.md"
        return str(monthly_dir / md_filename)
    
    def save_md_content(self, file_id: str, user_id: int, md_content: str, 
                       original_name: str) -> Tuple[str, Optional[str]]:
        """保存MD内容，返回(storage_type, md_file_path)"""
        try:
            # 决定存储策略
            storage_type = self.get_storage_strategy(md_content)
            md_file_path = None
            
            if storage_type == 'database':
                # 数据库存储 - 直接返回，内容将存储在数据库中
                print(f"[MD存储] 使用数据库存储 (大小: {len(md_content)} chars)")
                
            elif storage_type == 'filesystem':
                # 文件系统存储
                md_file_path = self.generate_md_file_path(file_id, original_name)
                
                # 写入文件
                with open(md_file_path, 'w', encoding='utf-8') as f:
                    f.write(md_content)
                
                print(f"[MD存储] 使用文件系统存储: {md_file_path}")
                
                # 验证文件写入
                if not os.path.exists(md_file_path):
                    raise IOError(f"MD文件写入失败: {md_file_path}")
                
                file_size = os.path.getsize(md_file_path)
                print(f"[MD存储] 文件大小: {file_size} bytes")
            
            # 更新数据库记录
            self._update_database_record(file_id, md_content if storage_type == 'database' else None,
                                       storage_type, md_file_path)
            
            return storage_type, md_file_path
            
        except Exception as e:
            print(f"[MD存储] 保存失败: {e}")
            raise
    
    def load_md_content(self, file_id: str) -> Optional[str]:
        """加载MD内容"""
        try:
            # 从数据库获取存储信息
            storage_info = self._get_storage_info(file_id)
            if not storage_info:
                return None
            
            storage_type = storage_info['storage_type']
            
            if storage_type == 'database':
                # 从数据库读取
                content = storage_info['md_content']
                print(f"[MD存储] 从数据库加载内容 (大小: {len(content) if content else 0} chars)")
                return content
                
            elif storage_type == 'filesystem':
                # 从文件系统读取
                md_file_path = storage_info['md_file_path']
                if not md_file_path or not os.path.exists(md_file_path):
                    print(f"[MD存储] 文件不存在: {md_file_path}")
                    return None
                
                with open(md_file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                print(f"[MD存储] 从文件系统加载: {md_file_path} (大小: {len(content)} chars)")
                return content
            
            else:
                print(f"[MD存储] 未知存储类型: {storage_type}")
                return None
                
        except Exception as e:
            print(f"[MD存储] 加载失败: {e}")
            return None
    
    def delete_md_content(self, file_id: str) -> bool:
        """删除MD内容"""
        try:
            # 获取存储信息
            storage_info = self._get_storage_info(file_id)
            if not storage_info:
                return True  # 已经不存在
            
            storage_type = storage_info['storage_type']
            
            if storage_type == 'filesystem':
                # 删除文件系统中的文件
                md_file_path = storage_info['md_file_path']
                if md_file_path and os.path.exists(md_file_path):
                    os.remove(md_file_path)
                    print(f"[MD存储] 删除文件: {md_file_path}")
            
            # 清理数据库记录
            self._clear_database_record(file_id)
            print(f"[MD存储] 清理数据库记录: {file_id}")
            
            return True
            
        except Exception as e:
            print(f"[MD存储] 删除失败: {e}")
            return False
    
    def get_storage_stats(self) -> Dict[str, Any]:
        """获取存储统计信息"""
        try:
            conn = DatabaseConfig.get_db_connection()
            if not conn:
                return {}
            
            cursor = conn.cursor()
            
            # 统计不同存储类型的文件数量和大小
            cursor.execute("""
                SELECT 
                    storage_type,
                    COUNT(*) as count,
                    SUM(CASE WHEN storage_type = 'database' THEN CHAR_LENGTH(md_content) ELSE 0 END) as db_size,
                    COUNT(CASE WHEN storage_type = 'filesystem' THEN 1 END) as fs_count
                FROM user_files 
                WHERE md_content IS NOT NULL OR md_file_path IS NOT NULL
                GROUP BY storage_type
            """)
            
            results = cursor.fetchall()
            conn.close()
            
            stats = {
                'database_files': 0,
                'filesystem_files': 0,
                'database_size_chars': 0,
                'filesystem_size_bytes': 0,
                'total_files': 0
            }
            
            for row in results:
                if row['storage_type'] == 'database':
                    stats['database_files'] = row['count']
                    stats['database_size_chars'] = row['db_size'] or 0
                elif row['storage_type'] == 'filesystem':
                    stats['filesystem_files'] = row['count']
            
            stats['total_files'] = stats['database_files'] + stats['filesystem_files']
            
            # 计算文件系统实际占用大小
            if stats['filesystem_files'] > 0:
                fs_size = 0
                storage_path = Path(self.MD_STORAGE_DIR)
                if storage_path.exists():
                    for file_path in storage_path.rglob("*.md"):
                        fs_size += file_path.stat().st_size
                stats['filesystem_size_bytes'] = fs_size
            
            return stats
            
        except Exception as e:
            print(f"[MD存储] 获取统计信息失败: {e}")
            return {}
    
    def _get_storage_info(self, file_id: str) -> Optional[Dict]:
        """获取文件的存储信息"""
        try:
            conn = DatabaseConfig.get_db_connection()
            if not conn:
                return None
            
            cursor = conn.cursor()
            cursor.execute("""
                SELECT md_content, storage_type, md_file_path 
                FROM user_files 
                WHERE file_id = %s
            """, (file_id,))
            
            result = cursor.fetchone()
            conn.close()
            
            return result
            
        except Exception as e:
            print(f"[MD存储] 获取存储信息失败: {e}")
            return None
    
    def _update_database_record(self, file_id: str, md_content: Optional[str], 
                              storage_type: str, md_file_path: Optional[str]):
        """更新数据库记录，如果记录不存在则创建"""
        try:
            conn = DatabaseConfig.get_db_connection()
            if not conn:
                raise Exception("数据库连接失败")
            
            cursor = conn.cursor()
            
            # 检查记录是否存在
            cursor.execute("SELECT file_id FROM user_files WHERE file_id = %s", (file_id,))
            exists = cursor.fetchone() is not None
            
            if exists:
                # 更新现有记录
                cursor.execute("""
                    UPDATE user_files 
                    SET md_content = %s, storage_type = %s, md_file_path = %s, 
                        processed_time = CURRENT_TIMESTAMP, status = 'completed'
                    WHERE file_id = %s
                """, (md_content, storage_type, md_file_path, file_id))
            else:
                # 创建新记录（用于测试）
                cursor.execute("""
                    INSERT INTO user_files 
                    (file_id, user_id, original_name, safe_filename, file_path, size, 
                     status, md_content, storage_type, md_file_path, upload_time, processed_time)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """, (file_id, 1, "test.pdf", f"{file_id}.pdf", f"uploads/{file_id}.pdf", 
                      1024, "completed", md_content, storage_type, md_file_path))
            
            conn.commit()  # 提交MD存储数据库操作
            conn.close()
            
        except Exception as e:
            print(f"[MD存储] 更新数据库记录失败: {e}")
            raise
    
    def _clear_database_record(self, file_id: str):
        """清理数据库记录中的MD内容"""
        try:
            conn = DatabaseConfig.get_db_connection()
            if not conn:
                raise Exception("数据库连接失败")
            
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_files 
                SET md_content = NULL, storage_type = 'database', md_file_path = NULL
                WHERE file_id = %s
            """, (file_id,))
            
            conn.commit()  # 提交MD清理操作
            conn.close()
            
        except Exception as e:
            print(f"[MD存储] 清理数据库记录失败: {e}")
            raise


# 全局存储管理器实例
md_storage_manager = MDStorageManager()
