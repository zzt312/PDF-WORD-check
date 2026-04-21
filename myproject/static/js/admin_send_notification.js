/**
 * 管理员发送通知页面JavaScript功能
 * 包含表单验证、AJAX提交、历史管理、统计图表等功能
 */

// 全局变量
let currentPage = 1;
let pageSize = 10;
let feedbackCurrentPage = 1;
let currentFeedbackId = null;
let richTextEditor = null;

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    initializePage();
    initializeRichTextEditor();
    setupFormValidation();
    setupEventListeners();
    loadUsers();
    loadNotificationHistory();
    loadFeedbackList();
});

/**
 * 初始化富文本编辑器
 */
function initializeRichTextEditor() {
    richTextEditor = document.getElementById('richTextEditor');
    if (!richTextEditor) return;
    
    // 设置编辑器样式
    richTextEditor.style.outline = 'none';
    richTextEditor.style.padding = '0.75rem';
    richTextEditor.style.minHeight = '120px';
    richTextEditor.style.border = 'none';
    
    // 占位符效果
    updatePlaceholder();
    richTextEditor.addEventListener('input', updatePlaceholder);
    richTextEditor.addEventListener('focus', updatePlaceholder);
    richTextEditor.addEventListener('blur', updatePlaceholder);
    
    // 工具栏按钮事件
    document.querySelectorAll('.editor-btn').forEach(btn => {
        btn.addEventListener('click', function(e) {
            e.preventDefault();
            const command = this.dataset.command;
            executeCommand(command);
        });
    });
    
    // 快捷键支持
    richTextEditor.addEventListener('keydown', function(e) {
        if (e.ctrlKey || e.metaKey) {
            switch(e.key) {
                case 'b':
                    e.preventDefault();
                    executeCommand('bold');
                    break;
                case 'i':
                    e.preventDefault();
                    executeCommand('italic');
                    break;
                case 'u':
                    e.preventDefault();
                    executeCommand('underline');
                    break;
            }
        }
    });
    
    // 内容同步到隐藏textarea
    richTextEditor.addEventListener('input', syncToHiddenTextarea);
    richTextEditor.addEventListener('blur', syncToHiddenTextarea);
    
    // 字符计数
    richTextEditor.addEventListener('input', updateCharacterCount);
}

/**
 * 更新占位符显示
 */
function updatePlaceholder() {
    const isEmpty = richTextEditor.textContent.trim() === '';
    if (isEmpty && !richTextEditor.contains(document.activeElement)) {
        if (!richTextEditor.querySelector('.placeholder')) {
            const placeholder = document.createElement('div');
            placeholder.className = 'placeholder';
            placeholder.style.color = '#6c757d';
            placeholder.style.pointerEvents = 'none';
            placeholder.textContent = richTextEditor.dataset.placeholder || '请输入通知内容...';
            richTextEditor.appendChild(placeholder);
        }
    } else {
        const placeholder = richTextEditor.querySelector('.placeholder');
        if (placeholder) {
            placeholder.remove();
        }
    }
}

/**
 * 执行富文本命令
 */
function executeCommand(command) {
    document.execCommand(command, false, null);
    richTextEditor.focus();
    updateToolbarState();
    syncToHiddenTextarea();
    updateCharacterCount();
}

/**
 * 更新工具栏状态
 */
function updateToolbarState() {
    document.querySelectorAll('.editor-btn').forEach(btn => {
        const command = btn.dataset.command;
        const isActive = document.queryCommandState(command);
        btn.classList.toggle('active', isActive);
    });
}

/**
 * 同步内容到隐藏textarea
 */
function syncToHiddenTextarea() {
    const hiddenTextarea = document.getElementById('notificationContent');
    if (hiddenTextarea && richTextEditor) {
        // 获取纯文本用于验证
        const textContent = richTextEditor.textContent || richTextEditor.innerText || '';
        
        // 获取HTML内容用于提交
        const htmlContent = richTextEditor.innerHTML;
        
        // 清理HTML，保留基本格式
        const cleanHtml = cleanHtmlContent(htmlContent);
        
        hiddenTextarea.value = cleanHtml;
        
        // 设置验证状态
        if (textContent.trim()) {
            hiddenTextarea.setCustomValidity('');
            hiddenTextarea.classList.remove('is-invalid');
        } else {
            hiddenTextarea.setCustomValidity('请输入通知内容');
            hiddenTextarea.classList.add('is-invalid');
        }
    }
}

/**
 * 清理HTML内容，只保留允许的标签
 */
function cleanHtmlContent(html) {
    // 移除占位符
    html = html.replace(/<div class="placeholder".*?<\/div>/g, '');
    
    // 允许的标签
    const allowedTags = ['b', 'strong', 'i', 'em', 'u', 'ul', 'ol', 'li', 'br', 'p', 'div'];
    
    // 简单的HTML清理（生产环境建议使用DOMPurify等库）
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = html;
    
    // 移除不允许的标签
    const allElements = tempDiv.querySelectorAll('*');
    allElements.forEach(el => {
        if (!allowedTags.includes(el.tagName.toLowerCase())) {
            // 保留文本内容，移除标签
            el.outerHTML = el.textContent || el.innerText || '';
        } else {
            // 移除所有属性，只保留标签
            while (el.attributes.length > 0) {
                el.removeAttribute(el.attributes[0].name);
            }
        }
    });
    
    return tempDiv.innerHTML;
}

/**
 * 更新字符计数
 */
function updateCharacterCount() {
    const counter = document.querySelector('.character-counter');
    if (!counter || !richTextEditor) return;
    
    const textContent = richTextEditor.textContent || richTextEditor.innerText || '';
    const length = textContent.length;
    const maxLength = 2000;
    
    counter.textContent = `${length}/${maxLength}`;
    
    // 更新样式
    counter.classList.remove('warning', 'danger');
    if (length > maxLength * 0.9) {
        counter.classList.add('danger');
    } else if (length > maxLength * 0.8) {
        counter.classList.add('warning');
    }
}

/**
 * 初始化页面
 */
function initializePage() {
    // 添加字符计数器
    addCharacterCounters();
    
    // 设置最小定时发送时间
    const scheduledTimeInput = document.getElementById('scheduledTime');
    if (scheduledTimeInput) {
        const now = new Date();
        now.setMinutes(now.getMinutes() + 1);
        scheduledTimeInput.min = now.toISOString().slice(0, 16);
    }
}

/**
 * 设置表单验证
 */
function setupFormValidation() {
    const form = document.getElementById('sendNotificationForm');
    if (!form) return;

    form.addEventListener('submit', handleFormSubmit);
    
    // 实时验证
    const inputs = form.querySelectorAll('input, select, textarea');
    inputs.forEach(input => {
        input.addEventListener('blur', validateField);
        input.addEventListener('input', clearFieldError);
    });
}

/**
 * 设置事件监听器
 */
function setupEventListeners() {
    // 接收用户选择改变
    const recipientRadios = document.querySelectorAll('input[name="recipients"]');
    recipientRadios.forEach(radio => {
        radio.addEventListener('change', handleRecipientChange);
    });
    
    // 发送时间选择改变
    const sendTimeRadios = document.querySelectorAll('input[name="sendTime"]');
    sendTimeRadios.forEach(radio => {
        radio.addEventListener('change', handleSendTimeChange);
    });
    
    // 标签页切换
    const tabButtons = document.querySelectorAll('[data-bs-toggle="tab"]');
    tabButtons.forEach(button => {
        button.addEventListener('shown.bs.tab', handleTabChange);
    });
    
    // 历史筛选
    const historyFilters = ['historyTypeFilter', 'historyPriorityFilter'];
    historyFilters.forEach(filterId => {
        const filter = document.getElementById(filterId);
        if (filter) {
            filter.addEventListener('change', loadNotificationHistory);
        }
    });
    
    // 反馈筛选
    const feedbackFilters = ['feedbackTypeFilter', 'feedbackStatusFilter'];
    feedbackFilters.forEach(filterId => {
        const filter = document.getElementById(filterId);
        if (filter) {
            filter.addEventListener('change', loadFeedbackList);
        }
    });
}

/**
 * 添加字符计数器
 */
function addCharacterCounters() {
    const fields = [
        { id: 'notificationTitle', maxLength: 100 },
        { id: 'notificationContent', maxLength: 2000 }
    ];
    
    fields.forEach(field => {
        const element = document.getElementById(field.id);
        if (element) {
            const counter = element.parentNode.querySelector('.character-counter');
            if (counter) {
                element.addEventListener('input', function() {
                    updateCharacterCounter(this, counter, field.maxLength);
                });
            }
        }
    });
}

/**
 * 更新字符计数器
 */
function updateCharacterCounter(input, counter, maxLength) {
    const currentLength = input.value.length;
    counter.textContent = `${currentLength}/${maxLength}`;
    
    // 更新样式
    counter.classList.remove('warning', 'danger');
    if (currentLength > maxLength * 0.9) {
        counter.classList.add('danger');
    } else if (currentLength > maxLength * 0.8) {
        counter.classList.add('warning');
    }
}

/**
 * 处理接收用户选择改变
 */
function handleRecipientChange(event) {
    const specificSection = document.getElementById('specificUsersSection');
    if (event.target.value === 'specific') {
        specificSection.style.display = 'block';
    } else {
        specificSection.style.display = 'none';
    }
}

/**
 * 处理发送时间选择改变
 */
function handleSendTimeChange(event) {
    const scheduledSection = document.getElementById('scheduledTimeSection');
    if (event.target.value === 'scheduled') {
        scheduledSection.style.display = 'block';
    } else {
        scheduledSection.style.display = 'none';
    }
}

/**
 * 处理标签页切换
 */
function handleTabChange(event) {
    const targetTab = event.target.getAttribute('data-bs-target');
    
    switch (targetTab) {
        case '#history-panel':
            if (!document.querySelector('#notificationHistory .notification-history-item')) {
                loadNotificationHistory();
            }
            break;
        case '#feedback-panel':
            if (!document.querySelector('#feedbackList .feedback-item')) {
                loadFeedbackList();
            }
            break;
    }
}

/**
 * 加载用户列表
 */
async function loadUsers() {
    try {
        const response = await fetch('/api/admin/users');
        const data = await response.json();
        
        if (data.success) {
            const userSelector = document.getElementById('userSelector');
            if (userSelector) {
                userSelector.innerHTML = '';
                data.users.forEach(user => {
                    const option = document.createElement('option');
                    option.value = user.id;
                    
                    // 构建丰富的用户信息显示
                    let displayText = `${user.username} (${user.email})`;
                    let additionalInfo = [];
                    
                    // 添加角色信息
                    if (user.role_display) {
                        additionalInfo.push(`${user.role_display}`);
                    }
                    
                    // 添加任务统计
                    if (user.total_tasks && user.total_tasks > 0) {
                        additionalInfo.push(`${user.total_tasks}个任务`);
                        if (user.completed_tasks > 0) {
                            additionalInfo.push(`${user.completed_tasks}已完成`);
                        }
                        if (user.active_tasks > 0) {
                            additionalInfo.push(`${user.active_tasks}进行中`);
                        }
                    }
                    
                    // 添加状态信息
                    if (user.status_display) {
                        additionalInfo.push(user.status_display);
                    }
                    
                    // 组合显示文本
                    if (additionalInfo.length > 0) {
                        displayText += ` - [${additionalInfo.join(', ')}]`;
                    }
                    
                    option.textContent = displayText;
                    
                    // 根据角色设置样式类
                    if (user.role === 'admin') {
                        option.style.fontWeight = 'bold';
                        option.style.color = '#dc3545'; // 红色表示管理员
                    } else if (user.role === 'premium') {
                        option.style.fontWeight = '600';
                        option.style.color = '#fd7e14'; // 橙色表示高级用户
                    }
                    
                    // 如果用户不活跃，使用灰色
                    if (user.is_active === 0) {
                        option.style.color = '#6c757d';
                        option.style.fontStyle = 'italic';
                    }
                    
                    userSelector.appendChild(option);
                });
            }
        }
    } catch (error) {
        console.error('加载用户列表失败:', error);
        
        // 显示错误信息
        const userSelector = document.getElementById('userSelector');
        if (userSelector) {
            userSelector.innerHTML = '<option value="">加载用户列表失败，请刷新页面重试</option>';
        }
    }
}

/**
 * 加载通知历史
 */
async function loadNotificationHistory(page = 1) {
    const historyContainer = document.getElementById('notificationHistory');
    if (!historyContainer) return;
    
    // 显示加载状态
    historyContainer.innerHTML = `
        <div class="text-center py-4">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">加载中...</span>
            </div>
            <p class="mt-2">正在加载通知历史...</p>
        </div>
    `;
    
    try {
        const typeFilter = document.getElementById('historyTypeFilter')?.value || '';
        const priorityFilter = document.getElementById('historyPriorityFilter')?.value || '';
        const searchText = document.getElementById('historySearch')?.value || '';
        
        const params = new URLSearchParams({
            page: page,
            page_size: pageSize,
            type: typeFilter,
            priority: priorityFilter,
            search: searchText
        });
        
        const response = await fetch(`/api/admin/notifications?${params}`);
        const data = await response.json();
        
        if (data.success) {
            renderNotificationHistory(data.notifications);
            renderPagination(data.pagination);
            currentPage = page;
        } else {
            throw new Error(data.message || '加载失败');
        }
    } catch (error) {
        console.error('加载通知历史失败:', error);
        historyContainer.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">
                    <i class="fe fe-alert-circle"></i>
                </div>
                <h5>加载失败</h5>
                <p>无法加载通知历史，请刷新页面重试</p>
            </div>
        `;
    }
}

/**
 * 渲染通知历史
 */
function renderNotificationHistory(notifications) {
    const container = document.getElementById('notificationHistory');
    if (!container) return;
    
    if (notifications.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">
                    <i class="fe fe-bell-off"></i>
                </div>
                <h5>暂无通知记录</h5>
                <p>还没有发送过通知，快去发送第一条通知吧！</p>
            </div>
        `;
        return;
    }
    
    const html = notifications.map(notification => `
        <div class="notification-history-item">
            <div class="notification-history-header">
                <div>
                    <h6 class="notification-title">${escapeHtml(notification.title)}</h6>
                    <div class="notification-meta">
                        <span class="type-badge">${getTypeText(notification.type)}</span>
                        <span class="priority-badge priority-${notification.priority}">${getPriorityText(notification.priority)}</span>
                        <span class="ms-2">发送时间: ${formatDateTime(notification.created_at)}</span>
                    </div>
                </div>
                <div class="notification-actions">
                    <button class="btn btn-sm btn-outline-info" onclick="viewNotificationDetails(${notification.id})">
                        <i class="fe fe-eye"></i> 查看
                    </button>
                    <button class="btn btn-sm btn-outline-danger" onclick="deleteNotification(${notification.id})">
                        <i class="fe fe-trash-2"></i> 删除
                    </button>
                </div>
            </div>
            <div class="notification-content">
                ${escapeHtml(notification.content).substring(0, 200)}${notification.content.length > 200 ? '...' : ''}
            </div>
            <div class="notification-stats">
                <span><i class="fe fe-users"></i> 发送给 ${notification.recipient_count} 用户</span>
                <span><i class="fe fe-check-circle"></i> 已读 ${notification.read_count} 次</span>
                <span><i class="fe fe-percent"></i> 阅读率 ${((notification.read_count / notification.recipient_count) * 100).toFixed(1)}%</span>
            </div>
        </div>
    `).join('');
    
    container.innerHTML = html;
}

/**
 * 渲染分页
 */
function renderPagination(pagination) {
    const container = document.getElementById('historyPagination');
    if (!container || !pagination) return;
    
    const { current_page, total_pages, total_records } = pagination;
    
    if (total_pages <= 1) {
        container.innerHTML = '';
        return;
    }
    
    let html = '';
    
    // 上一页
    if (current_page > 1) {
        html += `<li class="page-item">
            <a class="page-link" href="#" onclick="loadNotificationHistory(${current_page - 1})">上一页</a>
        </li>`;
    }
    
    // 页码
    const startPage = Math.max(1, current_page - 2);
    const endPage = Math.min(total_pages, current_page + 2);
    
    for (let i = startPage; i <= endPage; i++) {
        html += `<li class="page-item ${i === current_page ? 'active' : ''}">
            <a class="page-link" href="#" onclick="loadNotificationHistory(${i})">${i}</a>
        </li>`;
    }
    
    // 下一页
    if (current_page < total_pages) {
        html += `<li class="page-item">
            <a class="page-link" href="#" onclick="loadNotificationHistory(${current_page + 1})">下一页</a>
        </li>`;
    }
    
    container.innerHTML = html;
}

/**
 * 加载反馈列表
 */
async function loadFeedbackList(page = 1) {
    const feedbackContainer = document.getElementById('feedbackList');
    if (!feedbackContainer) return;
    
    // 显示加载状态
    feedbackContainer.innerHTML = `
        <div class="text-center py-4">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">加载中...</span>
            </div>
            <p class="mt-2">正在加载反馈列表...</p>
        </div>
    `;
    
    try {
        const typeFilter = document.getElementById('feedbackTypeFilter')?.value || '';
        const statusFilter = document.getElementById('feedbackStatusFilter')?.value || '';
        const searchText = document.getElementById('feedbackSearch')?.value || '';
        
        const params = new URLSearchParams({
            page: page,
            page_size: pageSize,
            type: typeFilter,
            status: statusFilter,
            search: searchText
        });
        
        const response = await fetch(`/api/admin/feedbacks?${params}`);
        const data = await response.json();
        
        if (data.success) {
            renderFeedbackList(data.feedbacks);
            renderFeedbackPagination(data.pagination);
            feedbackCurrentPage = page;
        } else {
            throw new Error(data.message || '加载失败');
        }
    } catch (error) {
        console.error('加载反馈列表失败:', error);
        feedbackContainer.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">
                    <i class="fe fe-alert-circle"></i>
                </div>
                <h5>加载失败</h5>
                <p>无法加载反馈列表，请刷新页面重试</p>
            </div>
        `;
    }
}

/**
 * 渲染反馈列表
 */
function renderFeedbackList(feedbacks) {
    const container = document.getElementById('feedbackList');
    if (!container) return;
    
    if (feedbacks.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-icon">
                    <i class="fe fe-message-circle"></i>
                </div>
                <h5>暂无反馈记录</h5>
                <p>还没有收到用户反馈</p>
            </div>
        `;
        return;
    }
    
    const html = feedbacks.map(feedback => `
        <div class="feedback-item">
            <div class="feedback-header">
                <div>
                    <h6 class="feedback-title">${escapeHtml(feedback.title)}</h6>
                    <div class="feedback-meta">
                        <span class="type-badge">${getFeedbackTypeText(feedback.feedback_type)}</span>
                        <span class="priority-badge priority-${feedback.priority}">${getPriorityText(feedback.priority)}</span>
                        <span class="status-badge status-${feedback.status}">${getFeedbackStatusText(feedback.status)}</span>
                        <span>用户: ${escapeHtml(feedback.username)}</span>
                        <span>时间: ${formatDateTime(feedback.created_at)}</span>
                    </div>
                </div>
                <div class="feedback-actions">
                    <button class="btn btn-sm btn-outline-primary" onclick="replyFeedback(${feedback.id})">
                        <i class="fe fe-message-square"></i> 回复
                    </button>
                    <button class="btn btn-sm btn-outline-success" onclick="updateFeedbackStatus(${feedback.id}, 'resolved')">
                        <i class="fe fe-check"></i> 已解决
                    </button>
                </div>
            </div>
            <div class="feedback-content">
                ${escapeHtml(feedback.content).substring(0, 200)}${feedback.content.length > 200 ? '...' : ''}
            </div>
        </div>
    `).join('');
    
    container.innerHTML = html;
}

/**
 * 渲染反馈分页
 */
function renderFeedbackPagination(pagination) {
    const container = document.getElementById('feedbackPagination');
    if (!container || !pagination) return;
    
    const { current_page, total_pages } = pagination;
    
    if (total_pages <= 1) {
        container.innerHTML = '';
        return;
    }
    
    let html = '';
    
    // 上一页
    if (current_page > 1) {
        html += `<li class="page-item">
            <a class="page-link" href="#" onclick="loadFeedbackList(${current_page - 1})">上一页</a>
        </li>`;
    }
    
    // 页码
    const startPage = Math.max(1, current_page - 2);
    const endPage = Math.min(total_pages, current_page + 2);
    
    for (let i = startPage; i <= endPage; i++) {
        html += `<li class="page-item ${i === current_page ? 'active' : ''}">
            <a class="page-link" href="#" onclick="loadFeedbackList(${i})">${i}</a>
        </li>`;
    }
    
    // 下一页
    if (current_page < total_pages) {
        html += `<li class="page-item">
            <a class="page-link" href="#" onclick="loadFeedbackList(${current_page + 1})">下一页</a>
        </li>`;
    }
    
    container.innerHTML = html;
}

/**
 * 回复反馈
 */
async function replyFeedback(feedbackId) {
    try {
        const response = await fetch(`/api/admin/feedbacks/${feedbackId}`);
        const data = await response.json();
        
        if (data.success) {
            const feedback = data.feedback;
            currentFeedbackId = feedbackId;
            
            // 填充反馈详情
            document.getElementById('feedbackDetails').innerHTML = `
                <div class="feedback-preview">
                    <div class="feedback-preview-header">
                        <h6 class="feedback-preview-title">${escapeHtml(feedback.title)}</h6>
                        <div>
                            <span class="type-badge">${getFeedbackTypeText(feedback.feedback_type)}</span>
                            <span class="priority-badge priority-${feedback.priority}">${getPriorityText(feedback.priority)}</span>
                        </div>
                    </div>
                    <div class="feedback-preview-content">${escapeHtml(feedback.content)}</div>
                    <div class="mt-2">
                        <strong>提交用户:</strong> ${escapeHtml(feedback.username)}<br>
                        <strong>提交时间:</strong> ${formatDateTime(feedback.created_at)}
                    </div>
                </div>
            `;
            
            // 设置当前状态
            document.getElementById('feedbackStatus').value = feedback.status;
            document.getElementById('replyContent').value = '';
            
            const modal = new bootstrap.Modal(document.getElementById('feedbackReplyModal'));
            modal.show();
        }
    } catch (error) {
        console.error('获取反馈详情失败:', error);
        showAlert('danger', '获取反馈详情失败');
    }
}

/**
 * 提交回复
 */
async function submitReply() {
    const replyContent = document.getElementById('replyContent').value.trim();
    const status = document.getElementById('feedbackStatus').value;
    
    if (!replyContent) {
        showAlert('danger', '请输入回复内容');
        return;
    }
    
    if (!currentFeedbackId) {
        showAlert('danger', '反馈ID错误');
        return;
    }
    
    try {
        const response = await fetch(`/api/admin/feedbacks/${currentFeedbackId}/reply`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                reply_content: replyContent,
                status: status
            })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showAlert('success', '回复发送成功！');
            
            const modal = bootstrap.Modal.getInstance(document.getElementById('feedbackReplyModal'));
            if (modal) modal.hide();
            
            loadFeedbackList(feedbackCurrentPage);
        } else {
            throw new Error(data.message || '回复失败');
        }
    } catch (error) {
        console.error('发送回复失败:', error);
        showAlert('danger', `回复失败: ${error.message}`);
    }
}

/**
 * 更新反馈状态
 */
async function updateFeedbackStatus(feedbackId, status) {
    try {
        const response = await fetch(`/api/admin/feedbacks/${feedbackId}/status`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ status: status })
        });
        
        const data = await response.json();
        
        if (data.success) {
            showAlert('success', '状态更新成功！');
            loadFeedbackList(feedbackCurrentPage);
        } else {
            throw new Error(data.message || '更新失败');
        }
    } catch (error) {
        console.error('更新状态失败:', error);
        showAlert('danger', `更新失败: ${error.message}`);
    }
}

/**
 * 搜索反馈
 */
function searchFeedback() {
    loadFeedbackList(1);
}

/**
 * 处理表单提交
 */
async function handleFormSubmit(event) {
    event.preventDefault();
    
    const form = event.target;
    if (!form.checkValidity()) {
        event.stopPropagation();
        form.classList.add('was-validated');
        return;
    }
    
    // 显示预览
    previewNotification();
}

/**
 * 预览通知
 */
function previewNotification() {
    const form = document.getElementById('sendNotificationForm');
    if (!form) return;
    
    const formData = new FormData(form);
    const data = Object.fromEntries(formData.entries());
    
    // 获取选中的用户
    let recipientText = '';
    switch (data.recipients) {
        case 'all':
            recipientText = '所有用户';
            break;
        case 'active':
            recipientText = '活跃用户 (近30天)';
            break;
        case 'specific':
            const selectedUsers = Array.from(document.getElementById('userSelector').selectedOptions);
            recipientText = `指定用户 (${selectedUsers.length}人)`;
            break;
    }
    
    // 发送时间
    let sendTimeText = '立即发送';
    if (data.sendTime === 'scheduled' && data.scheduled_time) {
        sendTimeText = `定时发送: ${formatDateTime(data.scheduled_time)}`;
    }
    
    const previewHtml = `
        <div class="notification-preview">
            <div class="notification-preview-header">
                <h6 class="notification-preview-title">${escapeHtml(data.title)}</h6>
                <div>
                    <span class="type-badge">${getTypeText(data.notification_type)}</span>
                    <span class="priority-badge priority-${data.priority}">${getPriorityText(data.priority)}</span>
                </div>
            </div>
            <div class="notification-preview-content">${escapeHtml(data.content)}</div>
            <div class="mt-3">
                <strong>接收用户:</strong> ${recipientText}<br>
                <strong>发送时间:</strong> ${sendTimeText}
            </div>
        </div>
    `;
    
    document.getElementById('notificationPreview').innerHTML = previewHtml;
    
    const modal = new bootstrap.Modal(document.getElementById('previewModal'));
    modal.show();
}

/**
 * 提交表单
 */
async function submitForm() {
    const form = document.getElementById('sendNotificationForm');
    if (!form) return;
    
    const submitBtn = form.querySelector('button[type="submit"]');
    const originalText = submitBtn.innerHTML;
    
    try {
        // 显示加载状态
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>发送中...';
        submitBtn.disabled = true;
        
        const formData = new FormData(form);
        
        // 处理特定用户选择
        if (formData.get('recipients') === 'specific') {
            const selectedUsers = Array.from(document.getElementById('userSelector').selectedOptions)
                .map(option => option.value);
            
            // 保持recipients='specific'，添加用户ID列表
            selectedUsers.forEach(userId => {
                formData.append('user_ids', userId);
            });
        }
        
        const response = await fetch('/api/admin/send-notification', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
            // 关闭预览模态框
            const previewModal = bootstrap.Modal.getInstance(document.getElementById('previewModal'));
            if (previewModal) previewModal.hide();
            
            // 显示成功消息
            document.getElementById('successMessage').textContent = data.message;
            const successModal = new bootstrap.Modal(document.getElementById('successModal'));
            successModal.show();
            
            // 重置表单
            form.reset();
            form.classList.remove('was-validated');
            
            // 隐藏条件区域
            document.getElementById('specificUsersSection').style.display = 'none';
            document.getElementById('scheduledTimeSection').style.display = 'none';
            
            // 重新加载历史
            loadNotificationHistory();
            loadFeedbackList();
        } else {
            throw new Error(data.message || '发送失败');
        }
    } catch (error) {
        console.error('发送通知失败:', error);
        showAlert('danger', `发送失败: ${error.message}`);
    } finally {
        // 恢复按钮状态
        submitBtn.innerHTML = originalText;
        submitBtn.disabled = false;
    }
}

/**
 * 重置表单
 */
function resetForm() {
    const form = document.getElementById('sendNotificationForm');
    if (!form) return;
    
    form.reset();
    form.classList.remove('was-validated');
    
    // 隐藏条件区域
    document.getElementById('specificUsersSection').style.display = 'none';
    document.getElementById('scheduledTimeSection').style.display = 'none';
    
    // 重置字符计数器
    const counters = form.querySelectorAll('.character-counter');
    counters.forEach(counter => {
        const input = counter.parentNode.querySelector('input, textarea');
        if (input) {
            const maxLength = input.getAttribute('maxlength');
            counter.textContent = `0/${maxLength}`;
            counter.classList.remove('warning', 'danger');
        }
    });
}

/**
 * 搜索历史
 */
function searchHistory() {
    loadNotificationHistory(1);
}

/**
 * 查看通知详情
 */
async function viewNotificationDetails(notificationId) {
    try {
        const response = await fetch(`/api/admin/notifications/${notificationId}`);
        const data = await response.json();
        
        if (data.success) {
            // 这里可以显示详情模态框
            console.log('通知详情:', data.notification);
            showAlert('info', '通知详情功能开发中...');
        }
    } catch (error) {
        console.error('获取通知详情失败:', error);
        showAlert('danger', '获取详情失败');
    }
}

/**
 * 删除通知
 */
async function deleteNotification(notificationId) {
    if (!confirm('确定要删除这条通知吗？此操作不可恢复。')) {
        return;
    }
    
    try {
        const response = await fetch(`/api/admin/notifications/${notificationId}`, {
            method: 'DELETE'
        });
        
        const data = await response.json();
        
        if (data.success) {
            showAlert('success', '删除成功');
            loadNotificationHistory(currentPage);
        } else {
            throw new Error(data.message || '删除失败');
        }
    } catch (error) {
        console.error('删除通知失败:', error);
        showAlert('danger', `删除失败: ${error.message}`);
    }
}

/**
 * 字段验证
 */
function validateField(event) {
    const field = event.target;
    const value = field.value.trim();
    
    field.classList.remove('is-invalid', 'is-valid');
    
    if (field.hasAttribute('required') && !value) {
        field.classList.add('is-invalid');
        return false;
    }
    
    // 特定字段验证
    switch (field.id) {
        case 'scheduledTime':
            if (field.closest('#scheduledTimeSection').style.display !== 'none' && value) {
                const scheduledTime = new Date(value);
                const now = new Date();
                if (scheduledTime <= now) {
                    field.classList.add('is-invalid');
                    return false;
                }
            }
            break;
    }
    
    field.classList.add('is-valid');
    return true;
}

/**
 * 清除字段错误
 */
function clearFieldError(event) {
    const field = event.target;
    field.classList.remove('is-invalid');
}

/**
 * 工具函数
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDateTime(datetime) {
    const date = new Date(datetime);
    return date.toLocaleString('zh-CN');
}

function getTypeText(type) {
    const types = {
        'system': '系统通知',
        'maintenance': '维护公告',
        'feature': '功能更新',
        'security': '安全提醒',
        'general': '一般消息'
    };
    return types[type] || type;
}

function getPriorityText(priority) {
    const priorities = {
        'urgent': '紧急',
        'high': '高',
        'normal': '普通',
        'low': '低'
    };
    return priorities[priority] || priority;
}

function getFeedbackTypeText(type) {
    const types = {
        'bug': '系统错误/Bug报告',
        'feature': '功能建议',
        'api': 'API配置问题',
        'performance': '性能问题',
        'ui': '界面/体验问题',
        'other': '其他问题'
    };
    return types[type] || type;
}

function getFeedbackStatusText(status) {
    const statuses = {
        'pending': '待处理',
        'in_progress': '处理中',
        'resolved': '已解决',
        'closed': '已关闭'
    };
    return statuses[status] || status;
}
