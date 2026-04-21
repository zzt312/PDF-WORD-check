/**
 * 用户反馈页面JavaScript功能
 * 包含表单验证、AJAX提交、富文本编辑器等功能
 */

// 全局变量
let richTextEditor;

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    initializeRichTextEditor();
    initializeFeedbackForm();
    setupFormValidation();
    addCharacterCounters();
});

/**
 * 初始化富文本编辑器
 */
function initializeRichTextEditor() {
    richTextEditor = document.getElementById('richTextEditor');
    if (!richTextEditor) return;
    
    // 工具栏按钮事件
    document.querySelectorAll('.editor-btn').forEach(btn => {
        btn.addEventListener('click', function() {
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
    const hiddenTextarea = document.getElementById('feedbackContent');
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
            hiddenTextarea.setCustomValidity('请输入反馈内容');
            hiddenTextarea.classList.add('is-invalid');
        }
    }
}

/**
 * 更新字符计数
 */
function updateCharacterCount() {
    const counter = document.querySelector('.character-counter');
    if (counter && richTextEditor) {
        const textContent = richTextEditor.textContent || richTextEditor.innerText || '';
        const length = textContent.length;
        const maxLength = 2000;
        
        counter.textContent = `${length}/${maxLength}`;
        
        // 颜色警告
        counter.className = 'character-counter text-muted';
        if (length > maxLength * 0.9) {
            counter.classList.add('text-danger');
        } else if (length > maxLength * 0.8) {
            counter.classList.add('text-warning');
        }
    }
}

/**
 * 清理HTML内容
 */
function cleanHtmlContent(html) {
    // 创建临时元素
    const temp = document.createElement('div');
    temp.innerHTML = html;
    
    // 移除不需要的元素和属性
    const unwantedElements = temp.querySelectorAll('script, style, meta, link');
    unwantedElements.forEach(el => el.remove());
    
    // 清理属性，只保留基本格式
    const allowedTags = ['strong', 'b', 'em', 'i', 'u', 'ul', 'ol', 'li', 'p', 'br'];
    const elements = temp.querySelectorAll('*');
    
    elements.forEach(el => {
        if (!allowedTags.includes(el.tagName.toLowerCase())) {
            // 不允许的标签，保留文本内容
            el.outerHTML = el.innerHTML;
        } else {
            // 清除所有属性，只保留标签
            Array.from(el.attributes).forEach(attr => el.removeAttribute(attr.name));
        }
    });
    
    return temp.innerHTML;
}

/**
 * 初始化反馈表单
 */
function initializeFeedbackForm() {
    const form = document.getElementById('feedbackForm');
    if (!form) return;

    // 表单提交事件
    form.addEventListener('submit', handleFormSubmit);
    
    // 实时验证
    const inputs = form.querySelectorAll('input, select, textarea');
    inputs.forEach(input => {
        input.addEventListener('blur', validateField);
        input.addEventListener('input', clearFieldError);
    });

    // 反馈类型改变时的提示
    const feedbackType = document.getElementById('feedbackType');
    if (feedbackType) {
        feedbackType.addEventListener('change', updateTypeGuidance);
    }
}

/**
 * 设置表单验证规则
 */
function setupFormValidation() {
    // 自定义验证消息
    const validationMessages = {
        'feedbackType': '请选择反馈类型',
        'priority': '请选择优先级',
        'feedbackTitle': '请输入反馈标题（最多100个字符）',
        'feedbackContent': '请详细描述您的反馈内容'
    };

    // 应用验证消息
    Object.keys(validationMessages).forEach(fieldId => {
        const field = document.getElementById(fieldId);
        if (field) {
            field.setAttribute('data-validation-message', validationMessages[fieldId]);
        }
    });
}

/**
 * 添加字符计数器
 */
function addCharacterCounters() {
    const title = document.getElementById('feedbackTitle');

    if (title) {
        addCounterToField(title, 100);
    }
    
    // 内容字段的字符计数由富文本编辑器的updateCharacterCount函数处理
}

/**
 * 为字段添加字符计数器
 */
function addCounterToField(field, maxLength) {
    field.setAttribute('maxlength', maxLength);
    
    const counter = document.querySelector('.character-counter');
    if (!counter) {
        const newCounter = document.createElement('div');
        newCounter.className = 'character-counter text-muted';
        newCounter.textContent = `0/${maxLength}`;
        field.parentNode.insertBefore(newCounter, field.nextSibling);
    }
    
    field.addEventListener('input', function() {
        const length = this.value.length;
        const fieldCounter = this.parentNode.querySelector('.character-counter');
        if (fieldCounter) {
            fieldCounter.textContent = `${length}/${maxLength}`;
            
            // 颜色警告
            fieldCounter.className = 'character-counter text-muted';
            if (length > maxLength * 0.9) {
                fieldCounter.classList.add('text-danger');
            } else if (length > maxLength * 0.8) {
                fieldCounter.classList.add('text-warning');
            }
        }
    });
}

/**
 * 处理表单提交
 */
async function handleFormSubmit(event) {
    event.preventDefault();
    
    const form = event.target;
    const submitBtn = form.querySelector('button[type="submit"]');
    
    // 同步富文本编辑器内容
    syncToHiddenTextarea();
    
    // 表单验证
    if (!validateForm(form)) {
        showValidationErrors(form);
        return;
    }
    
    // 显示加载状态
    const originalBtnText = submitBtn.innerHTML;
    submitBtn.innerHTML = '<span class="loading-spinner"></span> 提交中...';
    submitBtn.disabled = true;
    
    try {
        // 收集表单数据
        const formData = new FormData(form);
        const data = {
            feedback_type: formData.get('feedback_type'),
            priority: formData.get('priority'),
            title: formData.get('title'),
            content: formData.get('content')
        };
        
        // 发送请求
        const response = await fetch('/api/user/send-feedback', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: JSON.stringify(data)
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            // 提交成功
            showSuccessModal();
            resetForm();
        } else {
            // 提交失败
            showErrorMessage(result.message || '提交失败，请重试');
        }
    } catch (error) {
        console.error('提交反馈时出错:', error);
        showErrorMessage('网络错误，请检查连接后重试');
    } finally {
        // 恢复按钮状态
        submitBtn.innerHTML = originalBtnText;
        submitBtn.disabled = false;
    }
}

/**
 * 验证表单
 */
function validateForm(form) {
    const requiredFields = form.querySelectorAll('[required]');
    let isValid = true;
    
    requiredFields.forEach(field => {
        if (!validateField({ target: field })) {
            isValid = false;
        }
    });
    
    return isValid;
}

/**
 * 验证单个字段
 */
function validateField(event) {
    const field = event.target;
    const value = field.value.trim();
    let isValid = true;
    let message = '';
    
    // 清除之前的错误状态
    clearFieldError(event);
    
    // 必填字段验证
    if (field.hasAttribute('required') && !value) {
        isValid = false;
        message = field.getAttribute('data-validation-message') || '此字段为必填项';
    }
    
    // 特定字段验证
    switch (field.id) {
        case 'feedbackTitle':
            if (value && value.length > 100) {
                isValid = false;
                message = '标题不能超过100个字符';
            }
            break;
            
        case 'feedbackContent':
            if (value && value.length < 10) {
                isValid = false;
                message = '请提供更详细的描述（至少10个字符）';
            }
            break;
    }
    
    // 显示验证结果
    if (!isValid) {
        showFieldError(field, message);
    } else {
        showFieldSuccess(field);
    }
    
    return isValid;
}

/**
 * 清除字段错误状态
 */
function clearFieldError(event) {
    const field = event.target;
    field.classList.remove('is-invalid', 'is-valid');
    
    const feedback = field.parentNode.querySelector('.invalid-feedback');
    if (feedback) {
        feedback.style.display = 'none';
    }
}

/**
 * 显示字段错误
 */
function showFieldError(field, message) {
    field.classList.add('is-invalid');
    field.classList.remove('is-valid');
    
    let feedback = field.parentNode.querySelector('.invalid-feedback');
    if (!feedback) {
        feedback = document.createElement('div');
        feedback.className = 'invalid-feedback';
        field.parentNode.appendChild(feedback);
    }
    
    feedback.textContent = message;
    feedback.style.display = 'block';
}

/**
 * 显示字段成功状态
 */
function showFieldSuccess(field) {
    if (field.value.trim()) {
        field.classList.add('is-valid');
        field.classList.remove('is-invalid');
    }
}

/**
 * 显示验证错误
 */
function showValidationErrors(form) {
    const firstInvalidField = form.querySelector('.is-invalid');
    if (firstInvalidField) {
        firstInvalidField.focus();
        firstInvalidField.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    
    showErrorMessage('请检查并修正表单中的错误');
}

/**
 * 更新反馈类型指导
 */
function updateTypeGuidance(event) {
    const type = event.target.value;
    const contentField = document.getElementById('feedbackContent');
    
    const guidanceText = {
        'bug': '请详细描述错误现象、重现步骤、期望结果等',
        'feature': '请描述您希望的功能、使用场景、具体需求等',
        'api': '请说明API配置的具体问题、错误信息、期望行为等',
        'performance': '请描述性能问题的具体表现、操作环境等',
        'ui': '请描述界面问题、建议改进的地方等',
        'other': '请详细描述您的问题或建议'
    };
    
    if (type && guidanceText[type]) {
        contentField.placeholder = guidanceText[type];
    }
}

/**
 * 重置表单
 */
function resetForm() {
    const form = document.getElementById('feedbackForm');
    if (!form) return;
    
    form.reset();
    
    // 清除验证状态
    const fields = form.querySelectorAll('.is-invalid, .is-valid');
    fields.forEach(field => {
        field.classList.remove('is-invalid', 'is-valid');
    });
    
    // 重置富文本编辑器
    if (richTextEditor) {
        richTextEditor.innerHTML = '';
        const hiddenTextarea = document.getElementById('feedbackContent');
        if (hiddenTextarea) {
            hiddenTextarea.value = '';
            hiddenTextarea.setCustomValidity('');
        }
        updateCharacterCount();
    }
    
    // 重置字符计数器
    const counters = form.querySelectorAll('.character-counter');
    counters.forEach(counter => {
        const maxLength = counter.textContent.split('/')[1];
        counter.textContent = `0/${maxLength}`;
        counter.className = 'character-counter text-muted';
    });
}

/**
 * 显示反馈历史
 */
async function showFeedbackHistory() {
    const modal = new bootstrap.Modal(document.getElementById('feedbackHistoryModal'));
    const content = document.getElementById('feedbackHistoryContent');
    
    // 显示加载状态
    content.innerHTML = `
        <div class="text-center py-4">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">加载中...</span>
            </div>
            <p class="mt-2">正在加载反馈历史...</p>
        </div>
    `;
    
    modal.show();
    
    try {
        const response = await fetch('/api/user-feedback-history', {
            method: 'GET',
            headers: {
                'X-Requested-With': 'XMLHttpRequest'
            }
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            displayFeedbackHistory(result.data);
        } else {
            content.innerHTML = `
                <div class="empty-state">
                    <i class="fe fe-alert-circle"></i>
                    <h5>加载失败</h5>
                    <p>${result.message || '无法加载反馈历史'}</p>
                </div>
            `;
        }
    } catch (error) {
        console.error('加载反馈历史时出错:', error);
        content.innerHTML = `
            <div class="empty-state">
                <i class="fe fe-wifi-off"></i>
                <h5>网络错误</h5>
                <p>请检查网络连接后重试</p>
            </div>
        `;
    }
}

/**
 * 显示反馈历史内容
 */
function displayFeedbackHistory(feedbacks) {
    const content = document.getElementById('feedbackHistoryContent');
    
    if (!feedbacks || feedbacks.length === 0) {
        content.innerHTML = `
            <div class="empty-state">
                <i class="fe fe-message-circle"></i>
                <h5>暂无反馈记录</h5>
                <p>您还没有提交过任何反馈</p>
            </div>
        `;
        return;
    }
    
    const feedbacksHtml = feedbacks.map(feedback => `
        <div class="feedback-item fade-in">
            <div class="feedback-header">
                <h6 class="feedback-title">${escapeHtml(feedback.title)}</h6>
                <div class="d-flex gap-2">
                    <span class="status-badge status-${feedback.status}">
                        ${getStatusText(feedback.status)}
                    </span>
                    <span class="priority-badge priority-${feedback.priority}">
                        ${getPriorityText(feedback.priority)}
                    </span>
                    <span class="type-badge">
                        ${getTypeText(feedback.feedback_type)}
                    </span>
                </div>
            </div>
            <p class="feedback-content">${escapeHtml(feedback.content)}</p>
            <div class="feedback-meta">
                <small>
                    <i class="fe fe-calendar"></i> 提交时间：${formatDate(feedback.created_at)}
                    ${feedback.admin_response ? `<br><i class="fe fe-message-square"></i> 已回复` : ''}
                </small>
            </div>
        </div>
    `).join('');
    
    content.innerHTML = feedbacksHtml;
}

/**
 * 获取状态文本
 */
function getStatusText(status) {
    const statusMap = {
        'pending': '待处理',
        'processing': '处理中',
        'resolved': '已解决',
        'closed': '已关闭'
    };
    return statusMap[status] || status;
}

/**
 * 获取优先级文本
 */
function getPriorityText(priority) {
    const priorityMap = {
        'low': '低',
        'medium': '中',
        'high': '高',
        'urgent': '紧急'
    };
    return priorityMap[priority] || priority;
}

/**
 * 获取类型文本
 */
function getTypeText(type) {
    const typeMap = {
        'bug': 'Bug报告',
        'feature': '功能建议',
        'api': 'API问题',
        'performance': '性能问题',
        'ui': '界面问题',
        'other': '其他'
    };
    return typeMap[type] || type;
}

/**
 * 显示成功模态框
 */
function showSuccessModal() {
    const modal = new bootstrap.Modal(document.getElementById('successModal'));
    modal.show();
    
    // 添加成功动画
    const form = document.getElementById('feedbackForm');
    if (form) {
        form.classList.add('success-animation');
        setTimeout(() => {
            form.classList.remove('success-animation');
        }, 600);
    }
}

/**
 * 显示错误消息
 */
function showErrorMessage(message) {
    // 使用Toast显示错误消息
    if (typeof showToast === 'function') {
        showToast(message, 'error');
    } else {
        // 备用方案：使用alert
        showAlert('danger', '错误：' + message);
    }
}

/**
 * 显示成功消息
 */
function showSuccessMessage(message) {
    if (typeof showToast === 'function') {
        showToast(message, 'success');
    } else {
        // 备用方案：创建临时消息
        const alertDiv = document.createElement('div');
        alertDiv.className = 'alert alert-success alert-dismissible fade show';
        alertDiv.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        const container = document.querySelector('.container-fluid');
        container.insertBefore(alertDiv, container.firstChild);
        
        // 自动隐藏
        setTimeout(() => {
            alertDiv.remove();
        }, 5000);
    }
}

/**
 * 格式化日期
 */
function formatDate(dateString) {
    const date = new Date(dateString);
    return date.toLocaleString('zh-CN', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
    });
}

/**
 * HTML转义
 */
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

/**
 * 通用Toast消息显示函数（如果主应用中没有）
 */
function showToast(message, type = 'info') {
    // 检查是否已存在toast容器
    let container = document.getElementById('toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container position-fixed top-0 end-0 p-3';
        container.style.zIndex = '9999';
        document.body.appendChild(container);
    }
    
    // 创建toast元素
    const toastId = 'toast-' + Date.now();
    const toastHtml = `
        <div id="${toastId}" class="toast align-items-center text-white bg-${type === 'error' ? 'danger' : type === 'success' ? 'success' : 'info'} border-0" role="alert">
            <div class="d-flex">
                <div class="toast-body">
                    ${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        </div>
    `;
    
    container.insertAdjacentHTML('beforeend', toastHtml);
    
    // 显示toast
    const toastElement = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastElement, {
        autohide: true,
        delay: 5000
    });
    
    toast.show();
    
    // 清理：toast隐藏后移除元素
    toastElement.addEventListener('hidden.bs.toast', function() {
        this.remove();
    });
}
