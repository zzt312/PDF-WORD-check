# myproject/notification_system.py
# 通知系统独立模块

from flask import request, jsonify, render_template, session, redirect, url_for, flash, send_file
from functools import wraps
import json
import pymysql
from datetime import datetime

# 导入数据库操作函数
from db_operations import (
    get_all_notifications_for_admin,
    send_system_notification,
    bulk_update_notifications,
    save_user_feedback,
    get_user_feedback_history,
    get_all_feedbacks_for_admin,
    reply_to_feedback,
    update_feedback_status,
    # get_api_requests_for_admin,  # 已废弃
    # get_api_request_details,     # 已废弃
    get_unread_notification_count,
    get_user_notifications,
    mark_notifications_as_read,
    delete_user_notifications,
    clear_all_user_notifications
)

# 导入日志模块
import logging

logger = logging.getLogger(__name__)

# 全局app变量
app = None


def init_notification_routes(flask_app):
    """初始化通知系统路由"""
    global app
    app = flask_app
    
    # 注册所有路由
    app.add_url_rule('/notifications', 'user_notifications', user_notifications, methods=['GET'])
    app.add_url_rule('/user/send-feedback', 'user_send_feedback', user_send_feedback, methods=['GET'])
    app.add_url_rule('/admin/notifications', 'admin_notifications', admin_notifications, methods=['GET'])
    app.add_url_rule('/admin/send-notification', 'admin_send_notification', admin_send_notification, methods=['GET'])
    
    # API路由
    app.add_url_rule('/api/user/notification-count', 'api_user_notification_count', api_user_notification_count, methods=['GET'])
    app.add_url_rule('/api/user/notifications', 'api_user_notifications', api_get_user_notifications, methods=['GET'])
    app.add_url_rule('/api/user/notifications/mark-read', 'api_mark_notifications_read', api_mark_notifications_read, methods=['PUT'])
    app.add_url_rule('/api/user/notifications/delete', 'api_delete_user_notifications', api_delete_user_notifications, methods=['DELETE'])
    app.add_url_rule('/api/user/notifications/<int:notification_id>/read', 'api_mark_single_notification_read', api_mark_single_notification_read, methods=['POST'])
    app.add_url_rule('/api/user/notifications/<int:notification_id>', 'api_delete_single_notification', api_delete_single_notification, methods=['DELETE'])
    app.add_url_rule('/api/user/notifications/mark-all-read', 'api_user_mark_all_read', api_user_mark_all_read, methods=['POST'])
    app.add_url_rule('/api/user/notifications/clear', 'api_clear_all_user_notifications', api_clear_all_user_notifications, methods=['DELETE'])
    app.add_url_rule('/api/admin/notification-count', 'api_admin_notification_count', api_admin_notification_count, methods=['GET'])
    app.add_url_rule('/api/user/send-feedback', 'api_user_send_feedback', api_user_send_feedback, methods=['POST'])
    
    # 管理员通知管理API路由
    app.add_url_rule('/api/admin/notifications', 'api_admin_get_notifications', api_admin_get_notifications, methods=['GET'])
    app.add_url_rule('/api/admin/notifications/mark-all-read', 'api_admin_mark_all_read', api_admin_mark_all_read, methods=['POST'])
    app.add_url_rule('/api/admin/notifications/clear', 'api_admin_clear_notifications', api_admin_clear_notifications, methods=['POST'])
    app.add_url_rule('/api/admin/notifications/<int:notification_id>/read', 'api_admin_mark_notification_read', api_admin_mark_notification_read, methods=['POST'])
    app.add_url_rule('/api/admin/notifications/<int:notification_id>', 'api_admin_delete_notification', api_admin_delete_notification, methods=['DELETE'])
    
    # 管理员发送通知相关API
    app.add_url_rule('/api/admin/send-notification', 'api_admin_send_notification', api_admin_send_notification, methods=['POST'])
    app.add_url_rule('/api/admin/users', 'api_admin_get_users', api_admin_get_users, methods=['GET'])
    app.add_url_rule('/api/admin/feedbacks', 'api_admin_get_feedbacks', api_admin_get_feedbacks, methods=['GET'])
    app.add_url_rule('/api/admin/feedbacks/<int:feedback_id>', 'api_admin_get_feedback_detail', api_admin_get_feedback_detail, methods=['GET'])
    app.add_url_rule('/api/admin/feedbacks/<int:feedback_id>/reply', 'api_admin_reply_feedback', api_admin_reply_feedback, methods=['POST'])
    app.add_url_rule('/api/admin/feedbacks/<int:feedback_id>/status', 'api_admin_update_feedback_status', api_admin_update_feedback_status, methods=['PUT'])
    
    # API申请管理路由已废弃 - 管理员直接分配API密钥
    # app.add_url_rule('/api/admin/api-requests', 'api_admin_get_api_requests', api_admin_get_api_requests, methods=['GET'])
    # app.add_url_rule('/api/admin/api-requests/<int:request_id>/process', 'api_admin_process_api_request', api_admin_process_api_request, methods=['POST'])

# ==================== 权限装饰器 ====================

def admin_required(f):
    """管理员权限装饰器 - 仅允许admin用户"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        user_role = session.get('role', '')
        if user_role != 'admin':
            flash('需要管理员权限才能访问此页面', 'error')
            return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function

def view_admin_required(f):
    """查看管理信息权限装饰器 - 允许admin和premium用户"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        user_role = session.get('role', '')
        if user_role not in ['admin', 'premium']:
            flash('需要管理员权限才能访问此页面', 'error')
            return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function

def full_admin_required(f):
    """完全管理员权限装饰器 - 仅允许admin用户"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        
        user_role = session.get('role', '')
        if user_role != 'admin':
            flash('需要完全管理员权限才能访问此页面', 'error')
            return redirect(url_for('index'))
        
        return f(*args, **kwargs)
    return decorated_function

# ==================== 页面路由 ====================

def user_notifications():
    """用户通知中心页面"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    return render_template('user_notifications.html',
                         username=session.get('username'),
                         user_id=session.get('user_id'),
                         current_user_role=session.get('role', 'user'))

def user_send_feedback():
    """用户发送反馈页面"""
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('user_send_feedback.html')

@view_admin_required
def admin_notifications():
    """管理员通知管理页面"""
    return render_template('admin_notifications.html')

@full_admin_required
def admin_send_notification():
    """管理员发送通知页面"""
    return render_template('admin/admin_send_notification.html')

# ==================== API路由 ====================

def api_user_notification_count():
    """获取用户未读通知数量的API端点"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        user_id = session['user_id']
        count = get_unread_notification_count(user_id)
        
        return jsonify({
            'success': True,
            'count': count
        })
        
    except Exception as e:
        logger.error(f"获取用户通知数量失败: {e}")
        return jsonify({'success': False, 'message': '获取通知数量失败'}), 500

@admin_required
def api_admin_notification_count():
    """获取管理员未读通知数量的API端点"""
    try:
        user_id = session['user_id']
        count = get_unread_notification_count(user_id)
        
        return jsonify({
            'success': True,
            'count': count
        })
        
    except Exception as e:
        logger.error(f"获取管理员通知数量失败: {e}")
        return jsonify({'success': False, 'message': '获取通知数量失败'}), 500

def api_get_user_notifications():
    """获取用户通知列表的API端点"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        user_id = session['user_id']
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 10))
        filter_type = request.args.get('filter', 'all')
        
        result = get_user_notifications(user_id, page, page_size, filter_type)
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"获取用户通知列表失败: {e}")
        return jsonify({'success': False, 'message': '获取通知列表失败'}), 500

def api_mark_notifications_read():
    """标记通知为已读的API端点"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        user_id = session['user_id']
        data = request.get_json() or {}
        notification_ids = data.get('notification_ids')
        
        # 验证notification_ids
        if notification_ids:
            # 验证用户是否有权限操作这些通知
            from db_operations import get_db_connection_with_error_handling, safe_db_close
            conn, error_response, status_code = get_db_connection_with_error_handling()
            if not conn:
                return jsonify({'success': False, 'message': '数据库连接失败'}), 500
            
            cursor = conn.cursor()
            try:
                placeholders = ','.join(['%s'] * len(notification_ids))
                query = f"""
                    SELECT id FROM notifications 
                    WHERE id IN ({placeholders}) AND (recipient_id = %s OR recipient_id IS NULL)
                """
                cursor.execute(query, notification_ids + [user_id])
                valid_notifications = [row['id'] for row in cursor.fetchall()]
                
                # 只处理用户有权限的通知
                if len(valid_notifications) != len(notification_ids):
                    logger.warning(f"用户 {user_id} 尝试标记无权限的通知为已读")
                
                notification_ids = valid_notifications
                
            finally:
                safe_db_close(conn, cursor)
        
        success = mark_notifications_as_read(user_id, notification_ids)
        
        if success:
            return jsonify({'success': True, 'message': '标记成功'})
        else:
            return jsonify({'success': False, 'message': '标记失败'}), 500
            
    except Exception as e:
        logger.error(f"标记通知为已读失败: {e}")
        return jsonify({'success': False, 'message': '标记通知失败'}), 500

def api_delete_user_notifications():
    """删除用户通知的API端点"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        user_id = session['user_id']
        data = request.get_json() or {}
        notification_ids = data.get('notification_ids', [])
        
        if not notification_ids:
            return jsonify({'success': False, 'message': '请选择要删除的通知'}), 400
        
        # 验证用户是否有权限删除这些通知
        from db_operations import get_db_connection_with_error_handling, safe_db_close
        conn, error_response, status_code = get_db_connection_with_error_handling()
        if not conn:
            return jsonify({'success': False, 'message': '数据库连接失败'}), 500
        
        cursor = conn.cursor()
        try:
            placeholders = ','.join(['%s'] * len(notification_ids))
            query = f"""
                SELECT id FROM notifications 
                WHERE id IN ({placeholders}) AND (recipient_id = %s OR recipient_id IS NULL)
            """
            cursor.execute(query, notification_ids + [user_id])
            valid_notifications = [row['id'] for row in cursor.fetchall()]
            
            # 只删除用户有权限的通知
            if len(valid_notifications) != len(notification_ids):
                logger.warning(f"用户 {user_id} 尝试删除无权限的通知")
            
            notification_ids = valid_notifications
            
        finally:
            safe_db_close(conn, cursor)
        
        if not notification_ids:
            return jsonify({'success': False, 'message': '没有可删除的通知'}), 400
        
        success = delete_user_notifications(user_id, notification_ids)
        
        if success:
            return jsonify({'success': True, 'message': '删除成功'})
        else:
            return jsonify({'success': False, 'message': '删除失败'}), 500
            
    except Exception as e:
        logger.error(f"删除用户通知失败: {e}")
        return jsonify({'success': False, 'message': '删除通知失败'}), 500

def api_clear_all_user_notifications():
    """清除用户所有通知的API端点"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        user_id = session['user_id']
        success = clear_all_user_notifications(user_id)
        
        if success:
            return jsonify({'success': True, 'message': '清除成功'})
        else:
            return jsonify({'success': False, 'message': '清除失败'}), 500
            
    except Exception as e:
        logger.error(f"清除所有通知失败: {e}")
        return jsonify({'success': False, 'message': '清除通知失败'}), 500

def api_mark_single_notification_read(notification_id):
    """标记单条通知为已读的API端点"""
    print("DEBUG: api_mark_single_notification_read 函数被调用了!")
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        # notification_id已经通过Flask路由参数传递，无需从request.view_args获取
        if not notification_id or notification_id <= 0:
            return jsonify({'success': False, 'message': '无效的通知ID'}), 400
        
        user_id = session['user_id']
        logger.info(f"用户 {user_id} 尝试标记通知 {notification_id} 为已读")
        
        # 验证用户是否有权限标记这个通知
        from db_operations import get_db_connection_with_error_handling, safe_db_close
        conn, error_response, status_code = get_db_connection_with_error_handling()
        if not conn:
            return jsonify({'success': False, 'message': '数据库连接失败'}), 500
        
        cursor = conn.cursor()
        try:
            cursor.execute("""
                SELECT id FROM notifications 
                WHERE id = %s AND (recipient_id = %s OR recipient_id IS NULL)
            """, (notification_id, user_id))
            
            if not cursor.fetchone():
                return jsonify({'success': False, 'message': '无权限操作此通知'}), 403
                
        finally:
            safe_db_close(conn, cursor)
        
        success = mark_notifications_as_read(user_id, [notification_id])
        
        if success:
            return jsonify({'success': True, 'message': '标记成功'})
        else:
            return jsonify({'success': False, 'message': '标记失败'}), 500
            
    except Exception as e:
        logger.error(f"标记单条通知为已读失败: {e}")
        return jsonify({'success': False, 'message': '标记通知失败'}), 500

def api_delete_single_notification(notification_id):
    """删除单条通知的API端点"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        # notification_id已经通过Flask路由参数传递
        if not notification_id or notification_id <= 0:
            return jsonify({'success': False, 'message': '无效的通知ID'}), 400
        
        user_id = session['user_id']
        logger.info(f"用户 {user_id} 尝试删除通知 {notification_id}")
        
        success = delete_user_notifications(user_id, [notification_id])
        
        if success:
            return jsonify({'success': True, 'message': '删除成功'})
        else:
            return jsonify({'success': False, 'message': '删除失败'}), 500
            
    except Exception as e:
        logger.error(f"删除单条通知失败: {e}")
        return jsonify({'success': False, 'message': '删除通知失败'}), 500

def api_user_mark_all_read():
    """用户批量标记所有通知为已读"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        user_id = session['user_id']
        logger.info(f"用户 {user_id} 尝试批量标记所有通知为已读")
        
        # 获取用户所有未读通知ID
        unread_notifications = get_user_notifications(user_id, filter_type='unread')
        if not unread_notifications or not unread_notifications['notifications']:
            return jsonify({'success': True, 'message': '没有未读通知需要标记'})
        
        # 提取通知ID
        notification_ids = [notif['id'] for notif in unread_notifications['notifications']]
        
        # 批量标记为已读
        success = mark_notifications_as_read(user_id, notification_ids)
        
        if success:
            logger.info(f"用户 {user_id} 成功批量标记 {len(notification_ids)} 条通知为已读")
            return jsonify({'success': True, 'message': f'成功标记 {len(notification_ids)} 条通知为已读'})
        else:
            return jsonify({'success': False, 'message': '批量标记失败'}), 500
            
    except Exception as e:
        logger.error(f"用户批量标记已读失败: {e}")
        return jsonify({'success': False, 'message': '批量标记失败'}), 500

def api_user_send_feedback():
    """用户发送反馈API"""
    try:
        if 'user_id' not in session:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        data = request.get_json()
        if not data:
            return jsonify({'success': False, 'message': '无效的请求数据'}), 400
        
        user_id = session['user_id']
        username = session.get('username', '')
        feedback_type = data.get('type', 'suggestion')
        priority = data.get('priority', 'normal')
        title = data.get('title', '').strip()
        content = data.get('content', '').strip()
        
        if not title or not content:
            return jsonify({'success': False, 'message': '标题和内容不能为空'}), 400
        
        success = save_user_feedback(user_id, feedback_type, priority, title, content)
        
        if success:
            return jsonify({'success': True, 'message': '反馈提交成功'})
        else:
            return jsonify({'success': False, 'message': '反馈提交失败'}), 500
            
    except Exception as e:
        logger.error(f"发送反馈失败: {e}")
        return jsonify({'success': False, 'message': '反馈提交失败'}), 500

# ==================== 已废弃代码已清理 ====================

# ==================== 管理员通知管理功能 ====================

@admin_required
def api_admin_get_notifications():
    """获取管理员通知列表的API端点"""
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 10))
        filter_type = request.args.get('filter', 'all')
        
        # 管理员可以看到所有通知，不限制recipient_id
        result = get_all_notifications_for_admin(page, page_size, {'filter': filter_type})
        
        return jsonify({
            'success': True,
            'notifications': result.get('notifications', []),
            'pagination': {
                'current_page': page,
                'total_pages': result.get('pages', 0),
                'page_size': page_size
            },
            'total': result.get('total', 0)
        })
        
    except Exception as e:
        logger.error(f"获取管理员通知列表失败: {e}")
        return jsonify({'success': False, 'message': '获取通知列表失败'}), 500

@admin_required
def api_admin_mark_all_read():
    """批量标记所有通知为已读的API端点"""
    try:
        admin_id = session.get('user_id')
        if not admin_id:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        from db_operations import get_db_connection_with_error_handling
        
        conn, error_response, status_code = get_db_connection_with_error_handling()
        if error_response:
            return jsonify({'success': False, 'message': '数据库连接失败'}), 500
        
        try:
            cursor = conn.cursor()
            # 标记所有未读通知为已读
            cursor.execute("UPDATE notifications SET is_read = 1 WHERE is_read = 0")
            affected_rows = cursor.rowcount
            conn.commit()
            
            return jsonify({
                'success': True,
                'message': f'已标记 {affected_rows} 条通知为已读'
            })
            
        finally:
            cursor.close()
            conn.close()
            
    except Exception as e:
        logger.error(f"批量标记已读失败: {e}")
        return jsonify({'success': False, 'message': '批量标记失败'}), 500

@admin_required
def api_admin_clear_notifications():
    """清空所有通知的API端点"""
    try:
        admin_id = session.get('user_id')
        if not admin_id:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        from db_operations import get_db_connection_with_error_handling
        
        conn, error_response, status_code = get_db_connection_with_error_handling()
        if error_response:
            return jsonify({'success': False, 'message': '数据库连接失败'}), 500
        
        try:
            cursor = conn.cursor()
            # 删除所有通知（管理员权限）
            cursor.execute("DELETE FROM notifications")
            affected_rows = cursor.rowcount
            conn.commit()
            
            return jsonify({
                'success': True,
                'message': f'已清空 {affected_rows} 条通知'
            })
            
        finally:
            cursor.close()
            conn.close()
            
    except Exception as e:
        logger.error(f"清空通知失败: {e}")
        return jsonify({'success': False, 'message': '清空失败'}), 500

@admin_required
def api_admin_mark_notification_read(notification_id):
    """标记单条通知为已读的API端点"""
    try:
        admin_id = session.get('user_id')
        
        if not admin_id:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        from db_operations import get_db_connection_with_error_handling
        
        conn, error_response, status_code = get_db_connection_with_error_handling()
        if error_response:
            return jsonify({'success': False, 'message': '数据库连接失败'}), 500
        
        try:
            cursor = conn.cursor()
            # 标记指定通知为已读
            cursor.execute("UPDATE notifications SET is_read = 1 WHERE id = %s", (notification_id,))
            
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'message': '通知不存在'}), 404
            
            conn.commit()
            
            return jsonify({'success': True, 'message': '通知已标记为已读'})
            
        finally:
            cursor.close()
            conn.close()
            
    except Exception as e:
        logger.error(f"标记通知已读失败: {e}")
        return jsonify({'success': False, 'message': '标记失败'}), 500

@admin_required
def api_admin_delete_notification(notification_id):
    """删除单条通知的API端点"""
    try:
        admin_id = session.get('user_id')
        
        if not admin_id:
            return jsonify({'success': False, 'message': '未登录'}), 401
        
        from db_operations import get_db_connection_with_error_handling
        
        conn, error_response, status_code = get_db_connection_with_error_handling()
        if error_response:
            return jsonify({'success': False, 'message': '数据库连接失败'}), 500
        
        try:
            cursor = conn.cursor()
            # 删除指定通知
            cursor.execute("DELETE FROM notifications WHERE id = %s", (notification_id,))
            
            if cursor.rowcount == 0:
                return jsonify({'success': False, 'message': '通知不存在'}), 404
            
            conn.commit()
            
            return jsonify({'success': True, 'message': '通知已删除'})
            
        finally:
            cursor.close()
            conn.close()
            
    except Exception as e:
        logger.error(f"删除通知失败: {e}")
        return jsonify({'success': False, 'message': '删除失败'}), 500

# ==================== 管理员发送通知相关API ====================

@admin_required
def api_admin_send_notification():
    """管理员发送通知的API端点"""
    try:
        # 处理请求数据，支持JSON和FormData两种格式
        if request.is_json:
            # JSON格式请求
            data = request.get_json()
        else:
            # FormData格式请求
            data = {
                'notification_type': request.form.get('notification_type'),
                'priority': request.form.get('priority'),
                'title': request.form.get('title'),
                'content': request.form.get('content'),
                'recipients': request.form.get('recipients'),
                'user_ids': request.form.getlist('user_ids') if request.form.get('recipients') == 'specific' else None
            }
        
        # 验证必需字段
        required_fields = ['notification_type', 'priority', 'title', 'content', 'recipients']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'success': False, 'message': f'缺少必需字段: {field}'}), 400
        
        # 获取发送者信息
        sender_id = session.get('user_id')
        
        # 根据recipients类型确定接收者
        recipients_type = data['recipients']
        recipient_ids = []
        
        if recipients_type == 'all':
            # 发送给所有用户
            recipient_ids = None  # None表示发送给所有用户
        elif recipients_type == 'active':
            # 发送给活跃用户（近30天有活动的用户）
            from db_operations import get_active_users
            active_users = get_active_users(30)
            recipient_ids = [user['id'] for user in active_users]
        elif recipients_type == 'specific':
            # 发送给指定用户
            recipient_ids = data.get('user_ids', [])
            if not recipient_ids:
                return jsonify({'success': False, 'message': '请选择接收用户'}), 400
        
        # 发送通知
        if recipients_type == 'all':
            result = send_system_notification(
                sender_id=sender_id,
                title=data['title'],
                content=data['content'],
                target_type='all'
            )
        elif recipients_type == 'active':
            result = send_system_notification(
                sender_id=sender_id,
                title=data['title'],
                content=data['content'],
                target_type='users',
                target_users=recipient_ids
            )
        elif recipients_type == 'specific':
            result = send_system_notification(
                sender_id=sender_id,
                title=data['title'],
                content=data['content'],
                target_type='users',
                target_users=recipient_ids
            )
        
        if result:
            return jsonify({
                'success': True, 
                'message': '通知发送成功',
                'notification_id': result
            })
        else:
            return jsonify({'success': False, 'message': '通知发送失败'}), 500
            
    except Exception as e:
        logger.error(f"发送通知失败: {e}")
        return jsonify({'success': False, 'message': '发送通知失败'}), 500

@admin_required
def api_admin_get_users():
    """获取用户列表的API端点"""
    try:
        from db_operations import get_all_users
        users = get_all_users()
        
        # 格式化用户数据
        user_list = []
        for user in users:
            user_list.append({
                'id': user['id'],
                'username': user['username'],
                'email': user.get('email', ''),
                'role': user.get('role', 'user'),
                'last_active': user.get('last_active', '').strftime('%Y-%m-%d %H:%M:%S') if user.get('last_active') else '从未登录'
            })
        
        return jsonify({
            'success': True,
            'users': user_list,
            'total': len(user_list)
        })
        
    except Exception as e:
        logger.error(f"获取用户列表失败: {e}")
        return jsonify({'success': False, 'message': '获取用户列表失败'}), 500

@admin_required  
def api_admin_get_feedbacks():
    """获取反馈列表的API端点"""
    try:
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 10))
        feedback_type = request.args.get('type', '')
        status = request.args.get('status', '')
        search = request.args.get('search', '')
        
        from db_operations import get_all_feedbacks
        result = get_all_feedbacks(page, page_size, {
            'type': feedback_type,
            'status': status,
            'search': search
        })
        
        return jsonify({
            'success': True,
            'feedbacks': result.get('feedbacks', []),
            'pagination': {
                'current_page': page,
                'total_pages': result.get('pages', 0),
                'page_size': page_size
            },
            'total': result.get('total', 0)
        })
        
    except Exception as e:
        logger.error(f"获取反馈列表失败: {e}")
        return jsonify({'success': False, 'message': '获取反馈列表失败'}), 500

@admin_required
def api_admin_get_feedback_detail(feedback_id):
    """获取反馈详情的API端点"""
    try:
        from db_operations import get_feedback_by_id
        feedback = get_feedback_by_id(feedback_id)
        
        if not feedback:
            return jsonify({'success': False, 'message': '反馈不存在'}), 404
        
        return jsonify({
            'success': True,
            'feedback': feedback
        })
        
    except Exception as e:
        logger.error(f"获取反馈详情失败: {e}")
        return jsonify({'success': False, 'message': '获取反馈详情失败'}), 500

@admin_required
def api_admin_reply_feedback(feedback_id):
    """回复反馈的API端点"""
    try:
        data = request.get_json()
        reply_content = data.get('reply_content', '').strip()
        new_status = data.get('status', 'in_progress')
        
        if not reply_content:
            return jsonify({'success': False, 'message': '回复内容不能为空'}), 400
        
        admin_id = session.get('user_id')
        
        from db_operations import reply_to_feedback
        result = reply_to_feedback(feedback_id, admin_id, reply_content, new_status)
        
        if result:
            return jsonify({
                'success': True,
                'message': '回复成功'
            })
        else:
            return jsonify({'success': False, 'message': '回复失败'}), 500
            
    except Exception as e:
        logger.error(f"回复反馈失败: {e}")
        return jsonify({'success': False, 'message': '回复失败'}), 500

@admin_required
def api_admin_update_feedback_status(feedback_id):
    """更新反馈状态的API端点"""
    try:
        data = request.get_json()
        new_status = data.get('status', '')
        
        valid_statuses = ['open', 'in_progress', 'resolved', 'closed']
        if new_status not in valid_statuses:
            return jsonify({'success': False, 'message': '无效的状态值'}), 400
        
        from db_operations import update_feedback_status
        result = update_feedback_status(feedback_id, new_status)
        
        if result:
            return jsonify({
                'success': True,
                'message': '状态更新成功'
            })
        else:
            return jsonify({'success': False, 'message': '状态更新失败'}), 500
            
    except Exception as e:
        logger.error(f"更新反馈状态失败: {e}")
        return jsonify({'success': False, 'message': '更新状态失败'}), 500




    # 以下是重复的路由定义，需要清理
