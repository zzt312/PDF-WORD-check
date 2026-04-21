#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
管理员账号密码重置脚本
"""

from database_config import DatabaseConfig
from werkzeug.security import generate_password_hash

def reset_admin_password():
    """重置管理员密码"""
    conn = DatabaseConfig.get_db_connection()
    if not conn:
        print('数据库连接失败')
        return
    
    try:
        cursor = conn.cursor()
        
        # 查找管理员账号
        cursor.execute('SELECT id, username, email FROM users WHERE username = %s', ('admin',))
        admin_user = cursor.fetchone()
        
        if admin_user:
            print(f'找到管理员账号:')
            print(f'用户ID: {admin_user["id"]}')
            print(f'用户名: {admin_user["username"]}')
            print(f'邮箱: {admin_user["email"]}')
            
            # 设置新密码
            new_password = 'admin123'
            password_hash = generate_password_hash(new_password)
            
            # 更新密码并设置为管理员角色
            cursor.execute('''
                UPDATE users 
                SET password_hash = %s, role = 'admin'
                WHERE username = 'admin'
            ''', (password_hash,))
            
            conn.commit()
            
            print('\n✓ 管理员账号信息已更新:')
            print(f'用户名: admin')
            print(f'密码: {new_password}')
            print(f'角色: admin')
            print('\n请妥善保管这些登录信息！')
            
        else:
            print('未找到用户名为 admin 的账号')
            print('正在创建新的管理员账号...')
            
            # 创建新的管理员账号
            new_password = 'admin123'
            password_hash = generate_password_hash(new_password)
            
            cursor.execute('''
                INSERT INTO users (username, email, password_hash, role)
                VALUES (%s, %s, %s, %s)
            ''', ('admin', 'admin@example.com', password_hash, 'admin'))
            
            conn.commit()
            
            print('\n✓ 新管理员账号创建成功:')
            print(f'用户名: admin')
            print(f'密码: {new_password}')
            print(f'邮箱: admin@example.com')
            print(f'角色: admin')
            print('\n请妥善保管这些登录信息！')
        
        cursor.close()
        conn.close()
        
    except Exception as e:
        print(f'操作失败: {e}')
        if conn:
            conn.rollback()

if __name__ == "__main__":
    reset_admin_password()
