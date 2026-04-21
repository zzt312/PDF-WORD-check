// 用户分组管理页面脚本

// 工具函数
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 检查是否是自动填充内容
function isAutofillContent(element) {
    if (!element || !element.value) return false;
    
    // 检查是否是浏览器自动填充的内容
    // 通常自动填充的内容会很快填充，我们可以通过检查元素状态来判断
    const value = element.value.trim();
    
    // 如果值为空或只包含默认的占位符文本，则认为不是有效内容
    if (!value || value === element.placeholder) {
        return false;
    }
    
    // 检查是否是常见的自动填充模式（如浏览器保存的密码等）
    // 这里我们采用简单的策略：如果有内容就认为是有效的
    return true;
}

// 获取角色颜色
function getRoleColor(role) {
    switch (role) {
        case 'admin':
            return 'bg-danger';
        case 'premium':
            return 'bg-warning';
        case 'user':
        default:
            return 'bg-primary';
    }
}

// 获取角色文本
function getRoleText(role) {
    switch (role) {
        case 'admin':
            return '管理员';
        case 'premium':
            return '高级用户';
        case 'user':
        default:
            return '普通用户';
    }
}

// 全局变量
let currentGroupId = null;
let allUsers = [];
let selectedUsers = new Set();
let selectedGroups = new Set(); // 新增: 选中的分组集合

// 新建分组时选择的用户ID列表
let selectedUsersForNewGroup = [];

// 页面初始化
document.addEventListener('DOMContentLoaded', async function() {
    console.log('[页面初始化] DOMContentLoaded事件触发');
    
    // 检查是否已经初始化过
    if (window.groupManagementInitialized) {
        console.warn('[页面初始化] 页面已经初始化过，跳过重复初始化');
        return;
    }
    window.groupManagementInitialized = true;
    
    initializePage();
    bindEvents();
    await loadData();
    
    console.log('[页面初始化] 初始化完成');
});

// 初始化页面
function initializePage() {
    // 显示Flash消息
    showFlashMessages();
    
    // 初始化工具提示
    initializeTooltips();
    
    // 设置权限控制
    setupPermissions();
    
    // 禁用所有输入框自动填充
    disableAllAutocomplete();
}

// 绑定事件监听器
function bindEvents() {
    // 搜索输入框事件
    const searchInput = document.getElementById('searchGroupInput');
    if (searchInput) {
        searchInput.addEventListener('input', debounce(handleGroupSearch, 300));
    }
    
    // 筛选下拉框事件
    const statusFilter = document.getElementById('statusFilter');
    if (statusFilter) {
        statusFilter.addEventListener('change', handleGroupFilter);
    }
    
    // 用户搜索输入框事件
    const userSearchInput = document.getElementById('userSearchInput');
    if (userSearchInput) {
        userSearchInput.addEventListener('input', debounce(handleUserSearch, 300));
    }
    
    // 角色筛选事件
    const roleFilter = document.getElementById('roleFilter');
    if (roleFilter) {
        roleFilter.addEventListener('change', handleUserFilter);
    }
    
    // 分组名称编辑事件
    document.addEventListener('click', function(e) {
        if (e.target.classList.contains('group-name-display')) {
            enableGroupNameEdit(e.target);
        }
    });
    
    // 分组名称保存事件（回车键）
    document.addEventListener('keypress', function(e) {
        if (e.target.classList.contains('group-name-edit') && e.key === 'Enter') {
            saveGroupNameEdit(e.target);
        }
    });
    
    // 分组名称保存事件（失去焦点）
    document.addEventListener('blur', function(e) {
        if (e.target.classList.contains('group-name-edit')) {
            saveGroupNameEdit(e.target);
        }
    });
    
    // 新建分组用户搜索和筛选事件
    const createGroupUserSearchInput = document.getElementById('createGroupUserSearchInput');
    if (createGroupUserSearchInput) {
        createGroupUserSearchInput.addEventListener('input', debounce(handleCreateGroupUserSearch, 300));
    }
    
    const createGroupRoleFilter = document.getElementById('createGroupRoleFilter');
    if (createGroupRoleFilter) {
        createGroupRoleFilter.addEventListener('change', handleCreateGroupUserFilter);
    }
    
    // 模态框打开时初始化用户列表
    const createGroupModal = document.getElementById('createGroupModal');
    if (createGroupModal) {
        createGroupModal.addEventListener('show.bs.modal', initializeCreateGroupUserList);
        createGroupModal.addEventListener('hidden.bs.modal', resetCreateGroupForm);
    }
}

// 加载数据
async function loadData() {
    loadGroupStats();
    loadGroupCards('初始化');
    await loadAllUsers(); // 加载真实用户数据
}

// 加载统计数据
function loadGroupStats() {
    // 统计数据现在通过updateStats()函数动态计算
    // 不再使用硬编码数据
    updateStats();
}

// 更新统计卡片
function updateStatCard(elementId, value) {
    const element = document.getElementById(elementId);
    if (element) {
        // 添加数字动画效果
        animateNumber(element, parseInt(element.textContent) || 0, value, 1000);
    }
}

// 数字动画效果
function animateNumber(element, start, end, duration) {
    const range = end - start;
    const startTime = performance.now();
    
    function updateNumber(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const current = Math.floor(start + range * progress);
        
        element.textContent = current;
        
        if (progress < 1) {
            requestAnimationFrame(updateNumber);
        }
    }
    
    requestAnimationFrame(updateNumber);
}

// 加载所有用户数据
async function loadAllUsers(excludeConfirmedGroups = false) {
    try {
        const url = excludeConfirmedGroups 
            ? '/api/users/list?exclude_confirmed_groups=true'
            : '/api/users/list';
            
        const response = await fetch(url);
        
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        
        const data = await response.json();
        
        if (data.success && data.users) {
            allUsers = data.users;
        } else {
            throw new Error(data.error || '获取用户列表失败');
        }
    } catch (error) {
        console.error('加载用户数据失败:', error);
        // 如果API失败，显示错误信息
        showAlert('danger', '无法加载用户数据，请刷新页面重试');
        allUsers = [];
    }
}

// 加载分组卡片
function loadGroupCards(caller = 'unknown') {
    console.log(`[loadGroupCards] 函数被调用，调用者: ${caller}`);
    const container = document.getElementById('dynamicGroupCards');
    if (!container) {
        console.error('找不到分组卡片容器');
        return;
    }
    
    console.log('[loadGroupCards] 清空容器前，现有子元素数量:', container.children.length);
    
    // 强制清空现有内容，防止重复渲染
    container.innerHTML = '';
    // 移除所有子元素（双重保护）
    while (container.firstChild) {
        container.removeChild(container.firstChild);
    }
    
    console.log('[loadGroupCards] 清空容器后，子元素数量:', container.children.length);
    console.log('[loadGroupCards] 开始加载分组卡片');
    
    // 从数据库加载分组数据
    fetch('/api/groups/list')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const groups = data.groups || [];
                
                console.log('[loadGroupCards] 接收到分组数据:', groups.length, '个分组');
                
                // 遍历数据生成卡片
                groups.forEach((group, index) => {
                    console.log(`[loadGroupCards] 创建分组卡片 ${index + 1}/${groups.length}, ID: ${group.id}, 名称: ${group.name}`);
                    const groupCard = createGroupCard(group);
                    container.appendChild(groupCard);
                    console.log('[loadGroupCards] 卡片已添加到容器，当前容器子元素数量:', container.children.length);
                });
                
                console.log('[loadGroupCards] 所有卡片创建完成，最终容器子元素数量:', container.children.length);
                
                // 加载每个分组的API密钥数据
                setTimeout(() => {
                    groups.forEach(group => {
                        loadGroupApiKeys(group.id);
                    });
                }, 100);
                
                // 更新统计数据和界面状态
                updateStats();
                updateGroupSelectionUI();
            } else {
                console.error('加载分组失败:', data.message);
                // 如果没有分组数据，显示空状态
                container.innerHTML = '<div class="text-center text-muted py-5"><i class="bi bi-people fs-3 d-block mb-2"></i><p>暂无分组数据</p></div>';
            }
        })
        .catch(error => {
            console.error('加载分组错误:', error);
            container.innerHTML = '<div class="text-center text-muted py-5"><i class="bi bi-exclamation-triangle fs-3 d-block mb-2"></i><p>加载分组失败</p></div>';
        });
}

// 创建分组卡片元素
function createGroupCard(group) {
    const cardDiv = document.createElement('div');
    cardDiv.className = 'card custom-card group-card mb-4';
    cardDiv.setAttribute('data-group-id', group.id);
    cardDiv.setAttribute('data-group-status', group.status || 'confirmed');
    
    const isAdmin = window.currentUserRole === 'admin';
    
    cardDiv.innerHTML = `
        <!-- 卡片头部 -->
        <div class="card-header d-flex justify-content-between align-items-center">
            <div class="group-header-info d-flex align-items-center">
                <!-- 分组选择复选框 - 位置调整到标题前 -->
                <input type="checkbox" class="group-card-checkbox me-3" data-group-id="${group.id}" 
                       onchange="toggleGroupSelection(${group.id}, this.checked)">
                
                <!-- 可编辑分组名称 - 增加左边距为复选框留空间 -->
                <div class="editable-group-name me-3" data-group-id="${group.id}">
                    <span class="group-name-display">${escapeHtml(group.name)}</span>
                    <input type="text" class="form-control group-name-edit d-none" value="${escapeHtml(group.name)}">
                </div>
                
                <!-- 分组状态标签 -->
                ${group.status === 'temporary' ? '<span class="badge bg-warning text-dark me-3">临时</span>' : '<span class="badge bg-success me-3">确定</span>'}
                
                <!-- 创建信息 -->
                <div class="group-meta-info">
                    <small class="text-muted">
                        <span class="me-2">
                            <i class="bi bi-calendar3 me-1"></i>创建时间: ${group.created_at}
                        </span>
                        <span class="me-2">|</span>
                        <span>
                            <i class="bi bi-person me-1"></i>创建者: ${escapeHtml(group.created_by)}
                        </span>
                    </small>
                </div>
            </div>
            
            <!-- 操作按钮 -->
            <div class="d-flex gap-2">
                ${group.status === 'temporary' && isAdmin ? `
                <button type="button" class="btn btn-sm btn-success" onclick="confirmGroup(${group.id})" title="确认分组">
                    <i class="bi bi-check-circle me-1"></i>确认分组
                </button>
                ` : ''}
                ${isAdmin ? `
                <button type="button" class="btn btn-sm btn-outline-danger" onclick="deleteGroup(${group.id})" title="删除分组">
                    <i class="bi bi-trash me-1"></i>清除
                </button>
                ` : ''}
            </div>
        </div>
        
        <!-- 卡片内容 -->
        <div class="card-body">
            <!-- API密钥配置区域 -->
            <div class="api-keys-section mb-4">
                <h6 class="mb-3">API密钥配置:</h6>
                
                <!-- MinerU提供商选择 -->
                <div class="api-input-group mb-3">
                    <label class="form-label fw-bold">MinerU提供商</label>
                    <div class="btn-group w-100" role="group" id="groupMineruProvider_${group.id}">
                        <input type="radio" class="btn-check" name="mineruProvider_${group.id}" 
                               id="mineruProviderOfficial_${group.id}" value="mineru" checked
                               onchange="switchMineruProvider(${group.id}, 'mineru')"
                               ${!isAdmin ? 'disabled' : ''}>
                        <label class="btn btn-outline-primary" for="mineruProviderOfficial_${group.id}">
                            <i class="bi bi-cloud me-1"></i>官方MinerU（云端）
                        </label>
                        
                        <input type="radio" class="btn-check" name="mineruProvider_${group.id}" 
                               id="mineruProviderLocal_${group.id}" value="local_mineru"
                               onchange="switchMineruProvider(${group.id}, 'local_mineru')"
                               ${!isAdmin ? 'disabled' : ''}>
                        <label class="btn btn-outline-success" for="mineruProviderLocal_${group.id}">
                            <i class="bi bi-pc-display me-1"></i>本地MinerU
                        </label>
                    </div>
                </div>
                
                <!-- 本地MinerU配置区域 -->
                <div class="api-input-group mb-4" id="groupLocalMineruConfig_${group.id}" style="display: none;">
                    <div class="alert alert-success py-2 mb-2">
                        <i class="bi bi-pc-display me-1"></i>
                        <strong>本地MinerU服务器</strong> — 无需API密钥
                    </div>
                    <div class="mb-2">
                        <small class="text-muted">
                            <i class="bi bi-info-circle me-1"></i>
                            地址: 172.16.135.211:60605 | 引擎: hybrid-auto-engine
                        </small>
                    </div>
                    <div class="api-key-info" id="groupLocalMineruSavedInfo_${group.id}">
                        <!-- 本地MinerU保存状态 -->
                    </div>
                </div>
                
                <!-- 官方MinerU API密钥 -->
                <div class="api-input-group mb-4" id="groupMineruConfig_${group.id}">
                    <label class="form-label">MinerU API密钥</label>
                    <div class="input-group">
                        <input type="password" class="form-control" id="groupMineruApiKey_${group.id}" 
                               placeholder="输入您的MinerU API密钥"
                               autocomplete="new-password"
                               autocorrect="off"
                               autocapitalize="off"
                               spellcheck="false"
                               data-lpignore="true"
                               data-form-type="other"
                               oninput="console.log('mineru input triggered'); autoSaveGroupApiKey(${group.id}, 'mineru', this.value)"
                               onblur="console.log('mineru blur triggered'); autoSaveGroupApiKey(${group.id}, 'mineru', this.value)"
                               ${!isAdmin ? 'disabled' : ''}>
                        <button type="button" class="btn btn-outline-secondary" 
                                onclick="toggleGroupApiKeyVisibility('groupMineruApiKey_${group.id}')"
                                ${!isAdmin ? 'disabled' : ''}>
                            <i class="bi bi-eye" id="groupMineruToggleIcon_${group.id}"></i>
                        </button>
                    </div>
                    <div class="api-key-info mt-2" id="groupMineruSavedInfo_${group.id}">
                        <!-- 保存状态信息将在这里显示 -->
                    </div>
                </div>
                
                <!-- LLM提供商选择 -->
                <div class="api-input-group mb-3">
                    <label class="form-label fw-bold">LLM提供商</label>
                    <div class="btn-group w-100" role="group" id="groupLlmProvider_${group.id}">
                        <input type="radio" class="btn-check" name="llmProvider_${group.id}" 
                               id="llmProviderSiliconflow_${group.id}" value="siliconflow" checked
                               onchange="switchLlmProvider(${group.id}, 'siliconflow')"
                               ${!isAdmin ? 'disabled' : ''}>
                        <label class="btn btn-outline-primary" for="llmProviderSiliconflow_${group.id}">
                            <i class="bi bi-cloud me-1"></i>硅基流动（云端）
                        </label>
                        
                        <input type="radio" class="btn-check" name="llmProvider_${group.id}" 
                               id="llmProviderLocal_${group.id}" value="local_llm"
                               onchange="switchLlmProvider(${group.id}, 'local_llm')"
                               ${!isAdmin ? 'disabled' : ''}>
                        <label class="btn btn-outline-success" for="llmProviderLocal_${group.id}">
                            <i class="bi bi-pc-display me-1"></i>本地LLM
                        </label>
                    </div>
                </div>
                
                <!-- 本地LLM配置区域 -->
                <div class="api-input-group mb-3" id="groupLocalLlmConfig_${group.id}" style="display: none;">
                    <div class="alert alert-success py-2 mb-2">
                        <i class="bi bi-pc-display me-1"></i>
                        <strong>本地LLM服务器</strong> — 无需API密钥
                    </div>
                    <div class="mb-2">
                        <small class="text-muted">
                            <i class="bi bi-info-circle me-1"></i>
                            模型: Qwen2.5-32B | 地址: 222.193.29.85:60687 | 上下文: 20024 tokens
                        </small>
                    </div>
                    <div class="api-key-info" id="groupLocalLlmSavedInfo_${group.id}">
                        <!-- 本地LLM保存状态 -->
                    </div>
                </div>
                
                <!-- SiliconFlow API密钥 -->
                <div class="api-input-group mb-0" id="groupSiliconflowConfig_${group.id}">
                    <label class="form-label">SiliconFlow API密钥</label>
                    <div class="input-group">
                        <input type="password" class="form-control" id="groupSiliconflowApiKey_${group.id}" 
                               placeholder="输入您的SiliconFlow API密钥"
                               autocomplete="new-password"
                               autocorrect="off"
                               autocapitalize="off"
                               spellcheck="false"
                               data-lpignore="true"
                               data-form-type="other"
                               oninput="console.log('siliconflow input triggered'); autoSaveGroupApiKey(${group.id}, 'siliconflow', this.value)"
                               onblur="console.log('siliconflow blur triggered'); autoSaveGroupApiKey(${group.id}, 'siliconflow', this.value)"
                               ${!isAdmin ? 'disabled' : ''}>
                        <button type="button" class="btn btn-outline-secondary" 
                                onclick="toggleGroupApiKeyVisibility('groupSiliconflowApiKey_${group.id}')"
                                ${!isAdmin ? 'disabled' : ''}>
                            <i class="bi bi-eye" id="groupSiliconflowToggleIcon_${group.id}"></i>
                        </button>
                    </div>
                    <div class="api-key-info mt-2" id="groupSiliconflowSavedInfo_${group.id}">
                        <!-- 保存状态信息将在这里显示 -->
                    </div>
                    
                    <!-- SiliconFlow 模型选择 -->
                    <div class="mt-3">
                        <label class="form-label">SiliconFlow 模型选择</label>
                        <select class="form-select" id="groupSiliconflowModel_${group.id}"
                                onchange="autoSaveGroupApiKey(${group.id}, 'siliconflow', document.getElementById('groupSiliconflowApiKey_${group.id}').value)"
                                ${!isAdmin ? 'disabled' : ''}>
                            <option value="">请选择模型（可选）</option>
                            <option value="deepseek-ai/DeepSeek-R1">deepseek-ai/DeepSeek-R1 - ¥16/M Tokens</option>
                            <option value="Qwen/Qwen2.5-72B-Instruct">Qwen/Qwen2.5-72B-Instruct - ¥4.13/M Tokens</option>
                            <option value="Qwen/Qwen2.5-72B-Instruct-128K">Qwen/Qwen2.5-72B-Instruct-128K - ¥4.13/M Tokens</option>
                            <option value="deepseek-ai/DeepSeek-V3.2">deepseek-ai/DeepSeek-V3.2 - ¥3/M Tokens</option>
                            <option value="Qwen/Qwen3-30B-A3B-Thinking-2507">Qwen/Qwen3-30B-A3B-Thinking-2507 - ¥2.8/M Tokens</option>
                            <option value="deepseek-ai/DeepSeek-R1-Distill-Qwen-14B">deepseek-ai/DeepSeek-R1-Distill-Qwen-14B - ¥0.7/M Tokens</option>
                            <option value="deepseek-ai/DeepSeek-R1-0528-Qwen3-8B">deepseek-ai/DeepSeek-R1-0528-Qwen3-8B - 免费</option>
                        </select>
                        <small class="text-muted d-block mt-1">
                            <i class="bi bi-info-circle me-1"></i>
                            选择后将应用于该组所有成员的SiliconFlow调用（参考文献验证、表格提取等）
                        </small>
                    </div>
                </div>
            </div>
            
            <!-- 组内用户列表 -->
            <div class="group-users-section">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <h6 class="mb-0">组内用户 (${group.users.length}/5):</h6>
                    ${isAdmin ? `
                    <button type="button" class="btn btn-sm btn-primary" 
                            onclick="addUserToGroup(${group.id})" 
                            title="添加用户"
                            ${group.users.length >= 5 ? 'disabled' : ''}>
                        <i class="bi bi-plus-circle me-1"></i>添加用户
                    </button>
                    ` : ''}
                </div>
                <div class="users-container">
                    ${renderGroupUsers(group.users, group.id, isAdmin)}
                </div>
            </div>
        </div>
    `;
    
    // 防止API密钥输入框被自动填充
    setTimeout(() => {
        const mineruInput = cardDiv.querySelector(`#groupMineruApiKey_${group.id}`);
        const siliconflowInput = cardDiv.querySelector(`#groupSiliconflowApiKey_${group.id}`);
        
        if (mineruInput && isAutofillContent(mineruInput)) {
            mineruInput.value = '';
            console.log(`清除了分组 ${group.id} MinerU输入框的自动填充内容`);
        }
        
        if (siliconflowInput && isAutofillContent(siliconflowInput)) {
            siliconflowInput.value = '';
            console.log(`清除了分组 ${group.id} SiliconFlow输入框的自动填充内容`);
        }
    }, 100);
    
    return cardDiv;
}

// 渲染分组用户列表
function renderGroupUsers(users, groupId, isAdmin) {
    if (!users || users.length === 0) {
        return '<div class="text-muted text-center py-3"><small>暂无用户</small></div>';
    }
    
    return users.map(user => `
        <div class="user-item d-flex justify-content-between align-items-center py-2 px-3 mb-2 border rounded">
            <div class="d-flex align-items-center">
                <span class="avatar avatar-sm avatar-rounded me-2 bg-primary-transparent">
                    <i class="bi bi-person"></i>
                </span>
                <div>
                    <span class="fw-semibold d-block">${escapeHtml(user.name)}</span>
                    <small class="text-muted">${escapeHtml(user.email)}</small>
                </div>
            </div>
            ${isAdmin ? `
            <button type="button" class="btn btn-sm btn-outline-danger" 
                    onclick="removeUserFromGroup(${groupId}, ${user.id})" title="移除用户">
                <i class="bi bi-trash me-1"></i>移除
            </button>
            ` : ''}
        </div>
    `).join('');
}

// 注意: loadGroupApiKeys 和 loadGroupApiKey 函数已被合并到 createGroupCard 中
// 保留这些函数以防需要单独调用

// 显示Flash消息
function showFlashMessages() {
    const flashMessages = document.querySelectorAll('.flash-message');
    flashMessages.forEach(msg => {
        const type = msg.getAttribute('data-type');
        const message = msg.getAttribute('data-message');
        if (message) {
            showAlert(type, message);
        }
    });
}

// 初始化工具提示
function initializeTooltips() {
    // 初始化Bootstrap工具提示
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(function (tooltipTriggerEl) {
        return new bootstrap.Tooltip(tooltipTriggerEl);
    });
}

// 设置权限控制
function setupPermissions() {
    // 使用全局变量获取用户角色
    const userRole = window.currentUserRole || 'user';
    
    console.log('setupPermissions - userRole:', userRole); // 调试信息
    
    // 如果不是管理员，禁用页面内的编辑功能（不影响侧边栏）
    if (userRole !== 'admin') {
        // 只操作页面内容区域的admin-only元素，不影响侧边栏
        document.querySelectorAll('.app-content .admin-only').forEach(el => {
            el.style.display = 'none';
        });
        
        // 禁用API密钥输入框
        document.querySelectorAll('input[type="password"]').forEach(input => {
            input.disabled = true;
        });
    }
}

// 防抖函数
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}

// 分组搜索处理
function handleGroupSearch() {
    const searchInput = document.getElementById('searchGroupInput');
    let searchTerm = searchInput.value.toLowerCase();
    
    // 检测并清除可能的自动填充内容
    if (isAutofillContent(searchInput)) {
        searchInput.value = '';
        searchTerm = '';
    }
    
    // 硬编码搜索逻辑 - 实际应该调用API
    filterGroupCards(searchTerm);
}

// 分组筛选处理
function handleGroupFilter() {
    const statusFilter = document.getElementById('statusFilter').value;

    // 立即应用筛选
    filterGroupCards();
}

// 筛选分组卡片
function filterGroupCards(searchTerm = '') {
    const groupCards = document.querySelectorAll('.group-card');
    const statusFilter = document.getElementById('statusFilter').value;

    let visibleCount = 0;

    groupCards.forEach((card, index) => {
        const groupName = card.querySelector('.group-name-display').textContent.toLowerCase();
        const groupId = parseInt(card.getAttribute('data-group-id'));
        const groupStatus = card.getAttribute('data-group-status') || 'confirmed';

        let shouldShow = true;

        // 搜索词筛选
        if (searchTerm && !groupName.includes(searchTerm)) {
            shouldShow = false;
        }

        // 状态筛选
        if (statusFilter && groupStatus !== statusFilter) {
            shouldShow = false;
        }

        if (shouldShow) {
            card.style.display = 'block';
            visibleCount++;
        } else {
            card.style.display = 'none';
            // 如果隐藏的卡片被选中，取消选择
            if (selectedGroups.has(groupId)) {
                selectedGroups.delete(groupId);
                const checkbox = card.querySelector('.group-card-checkbox');
                if (checkbox) checkbox.checked = false;
            }
        }
    });

    // 更新界面状态
    updateGroupSelectionUI();

    // 更新总计显示（仅显示可见的分组）
    const groupCountElement = document.getElementById('groupCount');
    if (groupCountElement) {
        groupCountElement.textContent = visibleCount;
    }
}

// 用户搜索处理
function handleUserSearch() {
    const userSearchInput = document.getElementById('userSearchInput');
    let searchTerm = userSearchInput.value.toLowerCase();
    
    // 检测并清除可能的自动填充内容
    if (isAutofillContent(userSearchInput)) {
        userSearchInput.value = '';
        searchTerm = '';
    }
    
    console.log('搜索用户:', searchTerm);
    
    renderUserList();
}

// 用户筛选处理
function handleUserFilter() {
    const roleFilter = document.getElementById('roleFilter').value;
    
    renderUserList();
}

// 创建新分组
function createNewGroup() {
    // 重置表单
    document.getElementById('createGroupForm').reset();
    
    // 显示模态框
    const modal = new bootstrap.Modal(document.getElementById('createGroupModal'));
    modal.show();
}

// 保存新分组
function saveNewGroup() {
    const groupName = document.getElementById('groupName').value.trim();
    
    if (!groupName) {
        showAlert('danger', '请输入分组名称');
        return;
    }
    
    // 检查选中用户数量限制
    if (selectedUsersForNewGroup.length > 5) {
        showAlert('warning', '每个分组最多只能包含5个用户');
        return;
    }

    if (selectedUsersForNewGroup.length === 0) {
        showAlert('warning', '请选择至少一个用户');
        return;
    }
    
    console.log('保存新分组:', { 
        name: groupName, 
        selectedUsers: selectedUsersForNewGroup 
    });
    
    // 调用API创建分组
    fetch('/api/groups/create', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            name: groupName,
            users: selectedUsersForNewGroup
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showAlert('success', data.message);
            
            // 清空表单
            document.getElementById('groupName').value = '';
            selectedUsersForNewGroup = [];
            
            // 重新加载用户数据
            loadAllUsers();
            
            // 重新加载分组列表
            loadGroupCards('创建分组后');
            
            // 关闭模态框
            bootstrap.Modal.getInstance(document.getElementById('createGroupModal')).hide();
        } else {
            showAlert('danger', data.message || '创建分组失败');
        }
    })
    .catch(error => {
        console.error('创建分组错误:', error);
        showAlert('danger', '创建分组时发生错误');
    });
}

// 删除分组
function deleteGroup(groupId) {
    console.log('删除分组:', groupId);
    
    // 获取分组信息用于确认对话框
    const groupCard = document.querySelector(`[data-group-id="${groupId}"]`);
    const groupName = groupCard ? groupCard.querySelector('.card-title')?.textContent?.trim() || '未知分组' : '未知分组';
    const userItems = groupCard ? groupCard.querySelectorAll('.user-item') : [];
    const userCount = userItems.length;
    
    let confirmMessage = `确定要删除分组 "${groupName}" 吗？`;
    if (userCount > 0) {
        confirmMessage += `\n\n此分组包含 ${userCount} 个用户，删除后这些用户将被移出分组。`;
    }
    confirmMessage += '\n\n此操作不可恢复。';
    
    if (!confirm(confirmMessage)) {
        return;
    }
    
    // 调用API删除分组
    fetch(`/api/groups/${groupId}`, {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showAlert('success', data.message || '分组删除成功');
            
            // 重新加载用户数据
            loadAllUsers().then(() => {
                // 如果用户列表模态框是打开的，重新渲染
                const addUserModal = document.getElementById('addUserModal');
                if (addUserModal && addUserModal.classList.contains('show')) {
                    loadAllUsers(true).then(() => renderUserList());
                }
                // 如果创建分组模态框是打开的，重新渲染
                const createGroupModal = document.getElementById('createGroupModal');
                if (createGroupModal && createGroupModal.classList.contains('show')) {
                    loadAllUsers(true).then(() => renderCreateGroupUserList(allUsers));
                }
            });
            
            // 重新加载分组数据
            setTimeout(() => {
                loadGroupCards();
            }, 1000);
        } else {
            showAlert('error', data.message || '删除分组失败');
        }
    })
    .catch(error => {
        console.error('删除分组请求失败:', error);
        showAlert('error', '网络错误，请稍后重试');
    });
}

// 确认分组（临时分组转为确定分组）
function confirmGroup(groupId) {
    if (!confirm('确定要将此临时分组转为确定分组吗？确认后将无法自动调整分组成员。')) {
        return;
    }
    
    fetch(`/api/groups/${groupId}/confirm`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showAlert('success', data.message);
            // 重新加载分组列表
            loadGroupCards();
            
            // 如果有创建分组模态框打开，重新加载用户数据
            const createGroupModal = document.getElementById('createGroupModal');
            if (createGroupModal && createGroupModal.classList.contains('show')) {
                loadAllUsers(true).then(() => {
                    renderCreateGroupUserList(allUsers);
                });
            }
            
            // 如果有添加用户模态框打开，重新加载用户数据
            const addUserModal = document.getElementById('addUserModal');
            if (addUserModal && addUserModal.classList.contains('show')) {
                loadAllUsers(true).then(() => {
                    renderUserList();
                });
            }
        } else {
            showAlert('danger', data.message || '确认分组失败');
        }
    })
    .catch(error => {
        console.error('确认分组错误:', error);
        showAlert('danger', '确认分组时发生错误');
    });
}

// 启用分组名称编辑
function enableGroupNameEdit(displayElement) {
    const container = displayElement.parentElement;
    const editInput = container.querySelector('.group-name-edit');
    
    if (editInput) {
        displayElement.classList.add('d-none');
        editInput.classList.remove('d-none');
        editInput.focus();
        editInput.select();
    }
}

// 保存分组名称编辑
function saveGroupNameEdit(editInput) {
    const container = editInput.parentElement;
    const displayElement = container.querySelector('.group-name-display');
    const groupId = container.getAttribute('data-group-id');
    const newName = editInput.value.trim();
    
    if (!newName) {
        // 恢复原值
        editInput.value = displayElement.textContent;
        cancelGroupNameEdit(editInput);
        return;
    }
    
    if (newName === displayElement.textContent) {
        // 没有更改
        cancelGroupNameEdit(editInput);
        return;
    }
    
    console.log('保存分组名称:', { groupId, newName });
    
    // 硬编码保存逻辑 - 实际应该调用 PUT /api/groups/{groupId}
    displayElement.textContent = newName;
    cancelGroupNameEdit(editInput);
    
    showAlert('success', '分组名称更新成功');
}

// 取消分组名称编辑
function cancelGroupNameEdit(editInput) {
    const container = editInput.parentElement;
    const displayElement = container.querySelector('.group-name-display');
    
    editInput.classList.add('d-none');
    displayElement.classList.remove('d-none');
}

// 切换LLM提供商（本地LLM vs 硅基流动）
function switchLlmProvider(groupId, provider) {
    const localConfig = document.getElementById(`groupLocalLlmConfig_${groupId}`);
    const siliconflowConfig = document.getElementById(`groupSiliconflowConfig_${groupId}`);
    
    if (provider === 'local_llm') {
        if (localConfig) localConfig.style.display = 'block';
        if (siliconflowConfig) siliconflowConfig.style.display = 'none';
        // 自动保存本地LLM配置
        performGroupApiKeySave(groupId, 'local_llm', 'local-not-needed');
    } else {
        if (localConfig) localConfig.style.display = 'none';
        if (siliconflowConfig) siliconflowConfig.style.display = 'block';
    }
}

// 切换MinerU提供商（本地MinerU vs 官方MinerU）
function switchMineruProvider(groupId, provider) {
    const localConfig = document.getElementById(`groupLocalMineruConfig_${groupId}`);
    const officialConfig = document.getElementById(`groupMineruConfig_${groupId}`);
    
    if (provider === 'local_mineru') {
        if (localConfig) localConfig.style.display = 'block';
        if (officialConfig) officialConfig.style.display = 'none';
        // 自动保存本地MinerU配置
        performGroupApiKeySave(groupId, 'local_mineru', 'local-not-needed');
    } else {
        if (localConfig) localConfig.style.display = 'none';
        if (officialConfig) officialConfig.style.display = 'block';
    }
}

// 加载分组API密钥 - 完全复制个人信息页面的实现
async function loadGroupApiKeys(groupId) {
    try {
        const response = await fetch(`/api/groups/${groupId}/api-keys`);
        
        if (!response.ok) {
            console.error(`加载分组 ${groupId} API密钥失败: HTTP ${response.status}`);
            return;
        }
        
        const data = await response.json();
        
        if (data.success && data.keys) {
            // 加载MinerU API密钥
            const mineruKey = data.keys.find(key => key.is_active && key.api_provider === 'mineru');
            if (mineruKey) {
                const mineruInput = document.getElementById(`groupMineruApiKey_${groupId}`);
                if (mineruInput) {
                    mineruInput.value = mineruKey.api_token;
                    mineruInput.setAttribute('data-using-saved', 'true');
                    
                    const mineruSavedInfo = document.getElementById(`groupMineruSavedInfo_${groupId}`);
                    if (mineruSavedInfo) {
                        // 安全处理日期显示
                        let dateStr = mineruKey.created_at;
                        if (dateStr && dateStr !== '历史数据') {
                            try {
                                dateStr = new Date(mineruKey.created_at).toLocaleString('zh-CN');
                            } catch (e) {
                                dateStr = mineruKey.created_at;
                            }
                        }
                        
                        mineruSavedInfo.innerHTML = `
                            <small class="text-success">
                                <i class="bi bi-check-circle me-1"></i>
                                已保存 (${dateStr})
                            </small>
                        `;
                    }
                }
            }
            
            // 加载SiliconFlow API密钥和模型名称
            const siliconflowKey = data.keys.find(key => key.is_active && key.api_provider === 'siliconflow');
            if (siliconflowKey) {
                const siliconflowInput = document.getElementById(`groupSiliconflowApiKey_${groupId}`);
                if (siliconflowInput) {
                    siliconflowInput.value = siliconflowKey.api_token;
                    siliconflowInput.setAttribute('data-using-saved', 'true');
                    
                    // 加载模型选择
                    const modelSelect = document.getElementById(`groupSiliconflowModel_${groupId}`);
                    if (modelSelect && siliconflowKey.model_name) {
                        modelSelect.value = siliconflowKey.model_name;
                    }
                    
                    const siliconflowSavedInfo = document.getElementById(`groupSiliconflowSavedInfo_${groupId}`);
                    if (siliconflowSavedInfo) {
                        // 安全处理日期显示
                        let dateStr = siliconflowKey.created_at;
                        if (dateStr && dateStr !== '历史数据') {
                            try {
                                dateStr = new Date(siliconflowKey.created_at).toLocaleString('zh-CN');
                            } catch (e) {
                                dateStr = siliconflowKey.created_at;
                            }
                        }
                        
                        siliconflowSavedInfo.innerHTML = `
                            <small class="text-success">
                                <i class="bi bi-check-circle me-1"></i>
                                已保存 (${dateStr})
                            </small>
                        `;
                    }
                }
            }
            
            // 加载本地LLM配置
            const localLlmKey = data.keys.find(key => key.is_active && key.api_provider === 'local_llm');
            if (localLlmKey) {
                // 切换到本地LLM视图
                const localRadio = document.getElementById(`llmProviderLocal_${groupId}`);
                if (localRadio) localRadio.checked = true;
                switchLlmProvider(groupId, 'local_llm');
                
                const localSavedInfo = document.getElementById(`groupLocalLlmSavedInfo_${groupId}`);
                if (localSavedInfo) {
                    let dateStr = localLlmKey.created_at;
                    if (dateStr && dateStr !== '历史数据') {
                        try {
                            dateStr = new Date(localLlmKey.created_at).toLocaleString('zh-CN');
                        } catch (e) {
                            dateStr = localLlmKey.created_at;
                        }
                    }
                    localSavedInfo.innerHTML = `
                        <small class="text-success">
                            <i class="bi bi-check-circle me-1"></i>
                            已配置 (${dateStr})
                        </small>
                    `;
                }
            }
            
            // 加载本地MinerU配置
            const localMineruKey = data.keys.find(key => key.is_active && key.api_provider === 'local_mineru');
            if (localMineruKey) {
                // 切换到本地MinerU视图
                const localMineruRadio = document.getElementById(`mineruProviderLocal_${groupId}`);
                if (localMineruRadio) localMineruRadio.checked = true;
                switchMineruProvider(groupId, 'local_mineru');
                
                const localMineruSavedInfo = document.getElementById(`groupLocalMineruSavedInfo_${groupId}`);
                if (localMineruSavedInfo) {
                    let dateStr = localMineruKey.created_at;
                    if (dateStr && dateStr !== '历史数据') {
                        try {
                            dateStr = new Date(localMineruKey.created_at).toLocaleString('zh-CN');
                        } catch (e) {
                            dateStr = localMineruKey.created_at;
                        }
                    }
                    localMineruSavedInfo.innerHTML = `
                        <small class="text-success">
                            <i class="bi bi-check-circle me-1"></i>
                            已配置 (${dateStr})
                        </small>
                    `;
                }
            }
        }
    } catch (error) {
        console.error('加载分组API密钥失败:', error);
    }
}

// 防抖计时器存储
let groupApiKeySaveTimers = {};

// 自动保存分组API密钥 - 采用个人信息页面的单独保存模式，每个provider单独调用
async function autoSaveGroupApiKey(groupId, provider, value) {
    console.log(`autoSaveGroupApiKey called: groupId=${groupId}, provider=${provider}, value.length=${value ? value.length : 0}`);
    
    const timerId = `${groupId}_${provider}`;
    value = value.trim();
    
    // 清除之前的计时器
    if (groupApiKeySaveTimers[timerId]) {
        clearTimeout(groupApiKeySaveTimers[timerId]);
    }
    
    // 如果值为空，清除保存状态并返回
    if (!value) {
        console.log(`autoSaveGroupApiKey: value is empty, returning`);
        const infoElementIdMap = {
            'mineru': `groupMineruSavedInfo_${groupId}`,
            'local_mineru': `groupLocalMineruSavedInfo_${groupId}`,
            'local_llm': `groupLocalLlmSavedInfo_${groupId}`,
            'siliconflow': `groupSiliconflowSavedInfo_${groupId}`
        };
        const infoElementId = infoElementIdMap[provider] || `groupSiliconflowSavedInfo_${groupId}`;
        const infoElement = document.getElementById(infoElementId);
        if (infoElement) {
            infoElement.innerHTML = '';
        }
        return;
    }
    
    console.log(`autoSaveGroupApiKey: setting timer for ${provider}`);
    // 设置新的计时器，1秒后执行保存
    groupApiKeySaveTimers[timerId] = setTimeout(async () => {
        console.log(`autoSaveGroupApiKey: timer triggered for ${provider}`);
        await performGroupApiKeySave(groupId, provider, value);
    }, 1000);
}

// 执行实际的分组API密钥保存 - 采用个人信息页面的单独保存模式（支持模型选择）
async function performGroupApiKeySave(groupId, provider, value) {
    console.log(`performGroupApiKeySave called: groupId=${groupId}, provider=${provider}, value.length=${value ? value.length : 0}`);
    
    const infoElementIdMap = {
        'mineru': `groupMineruSavedInfo_${groupId}`,
        'local_mineru': `groupLocalMineruSavedInfo_${groupId}`,
        'local_llm': `groupLocalLlmSavedInfo_${groupId}`,
        'siliconflow': `groupSiliconflowSavedInfo_${groupId}`
    };
    const infoElementId = infoElementIdMap[provider] || `groupSiliconflowSavedInfo_${groupId}`;
    const infoElement = document.getElementById(infoElementId);
    
    console.log(`performGroupApiKeySave: infoElementId=${infoElementId}, element found=${!!infoElement}`);
    
    if (!infoElement) return;
    
    // 显示保存中状态
    infoElement.innerHTML = '<small class="text-muted"><i class="bi bi-clock me-1"></i>保存中...</small>';
    
    try {
        // 构建请求体
        const requestBody = {
            group_id: groupId,
            provider: provider,
            api_key: value
        };
        
        // 如果是SiliconFlow，包含模型选择
        if (provider === 'siliconflow') {
            const modelSelect = document.getElementById(`groupSiliconflowModel_${groupId}`);
            if (modelSelect && modelSelect.value) {
                requestBody.model_name = modelSelect.value;
            }
        } else if (provider === 'local_llm') {
            requestBody.model_name = 'Qwen2.5-32B';
        } else if (provider === 'local_mineru') {
            requestBody.model_name = 'local-mineru';
        }
        
        const response = await fetch('/api/groups/api-keys/save', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(requestBody)
        });
        
        const data = await response.json();
        
        if (response.ok && data.success) {
            // 显示保存成功状态
            infoElement.innerHTML = '<small class="text-success"><i class="bi bi-check-circle me-1"></i>已自动保存</small>';
            
            // 3秒后清除提示
            setTimeout(() => {
                infoElement.innerHTML = '';
            }, 3000);
        } else {
            infoElement.innerHTML = '<small class="text-danger"><i class="bi bi-exclamation-circle me-1"></i>保存失败: ' + (data.error || data.message || '未知错误') + '</small>';
        }
    } catch (error) {
        console.error('保存分组API密钥出错:', error);
        infoElement.innerHTML = '<small class="text-danger"><i class="bi bi-exclamation-circle me-1"></i>保存失败</small>';
    }
}

// 切换分组API密钥可见性 - 参考个人信息页面实现
function toggleGroupApiKeyVisibility(inputId) {
    const input = document.getElementById(inputId);
    const icon = document.getElementById(inputId.replace('ApiKey', 'ToggleIcon'));
    
    if (!input || !icon) return;
    
    if (input.type === 'password') {
        input.type = 'text';
        icon.className = 'bi bi-eye-slash';
    } else {
        input.type = 'password';
        icon.className = 'bi bi-eye';
    }
}

// 添加用户到分组
async function addUserToGroup(groupId) {
    console.log('添加用户到分组:', groupId);
    
    // 从DOM中获取当前分组的用户数量
    const groupCard = document.querySelector(`[data-group-id="${groupId}"]`);
    const userItems = groupCard ? groupCard.querySelectorAll('.user-item') : [];
    
    if (userItems.length >= 5) {
        showAlert('warning', '每个分组最多只能添加5个用户');
        return;
    }
    
    currentGroupId = groupId;
    selectedUsers = new Set();
    
    // 加载可用用户（过滤掉已在确定分组的用户）
    await loadAllUsers(true);
    
    // 初始化选择计数显示
    const selectedCountElement = document.getElementById('selectedUserCount');
    if (selectedCountElement) {
        selectedCountElement.textContent = '0';
    }
    
    // 获取当前分组已有的用户ID
    userItems.forEach(item => {
        const removeBtn = item.querySelector('[onclick*="removeUserFromGroup"]');
        if (removeBtn) {
            const onclickAttr = removeBtn.getAttribute('onclick');
            const userIdMatch = onclickAttr.match(/removeUserFromGroup\((\d+),\s*(\d+)\)/);
            if (userIdMatch && userIdMatch[2]) {
                selectedUsers.add(parseInt(userIdMatch[2]));
            }
        }
    });
    
    // 确保用户列表是最新的并渲染
    renderUserList();
    
    // 显示模态框
    const modal = new bootstrap.Modal(document.getElementById('addUserModal'));
    modal.show();
}

// 渲染用户列表
function renderUserList() {
    const searchTerm = document.getElementById('userSearchInput').value.toLowerCase();
    const roleFilter = document.getElementById('roleFilter').value;
    
    const filteredUsers = allUsers.filter(user => {
        // 只显示没有分组或在临时分组中的用户
        if (user.group_status === 'confirmed') {
            return false;
        }
        
        // 安全处理可能为undefined的属性，支持两种字段名
        const username = user.username || user.name || '';
        const email = user.email || '';
        
        const matchesSearch = username.toLowerCase().includes(searchTerm) || 
                             email.toLowerCase().includes(searchTerm);
        const matchesRole = !roleFilter || user.role === roleFilter;
        return matchesSearch && matchesRole;
    });
    
    const userListGroup = document.getElementById('userListGroup');
    userListGroup.innerHTML = '';
    
    filteredUsers.forEach(user => {
        const isSelected = selectedUsers.has(user.id);
        const userItem = document.createElement('div');
        userItem.className = `list-group-item d-flex justify-content-between align-items-center ${isSelected ? 'active' : ''}`;
        
        const roleMap = {
            'admin': { text: '管理员', class: 'bg-danger' },
            'premium': { text: '高级用户', class: 'bg-warning' },
            'user': { text: '普通用户', class: 'bg-primary' }
        };
        
        const roleInfo = roleMap[user.role] || { text: '未知', class: 'bg-dark' };
        
        userItem.innerHTML = `
            <div class="form-check">
                <input class="form-check-input" type="checkbox" 
                       ${isSelected ? 'checked' : ''} 
                       onchange="toggleUserSelection(${user.id}, this.checked)"
                       id="user_${user.id}">
                <label class="form-check-label" for="user_${user.id}">
                    <div>
                        <strong>${user.username || user.name || '未知用户'}</strong>
                        <br>
                        <small class="text-muted">${user.email || '无邮箱'}</small>
                    </div>
                </label>
            </div>
            <span class="badge ${roleInfo.class} fs-11 fw-semibold text-uppercase px-2 py-1" style="min-width: 50px; text-align: center;">
                ${roleInfo.text}
            </span>
        `;
        
        userListGroup.appendChild(userItem);
    });
}

// 切换用户选择状态
function toggleUserSelection(userId, isSelected) {
    if (isSelected) {
        selectedUsers.add(userId);
    } else {
        selectedUsers.delete(userId);
    }
    
    // 更新选择计数显示
    const selectedCountElement = document.getElementById('selectedUserCount');
    if (selectedCountElement) {
        selectedCountElement.textContent = selectedUsers.size;
    }
    
    console.log('选中的用户:', Array.from(selectedUsers));
}

// 保存选中的用户
function saveSelectedUsers() {
    const selectedUserIds = Array.from(selectedUsers);
    console.log('保存选中的用户到分组:', { groupId: currentGroupId, userIds: selectedUserIds });
    
    if (selectedUserIds.length === 0) {
        showAlert('warning', '请至少选择一个用户');
        return;
    }
    
    // 获取当前分组的API密钥
    const groupCard = document.querySelector(`[data-group-id="${currentGroupId}"]`);
    const mineruApiKey = groupCard ? groupCard.querySelector(`#groupMineruApiKey_${currentGroupId}`)?.value || '' : '';
    const siliconflowApiKey = groupCard ? groupCard.querySelector(`#groupSiliconflowApiKey_${currentGroupId}`)?.value || '' : '';
    
    // 调用API添加用户到分组，并为新成员分配API密钥
    fetch('/api/groups/members/add', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            group_id: currentGroupId,
            user_ids: selectedUserIds,
            api_keys: {
                mineru: mineruApiKey,
                siliconflow: siliconflowApiKey
            }
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            const addedCount = data.added_count || selectedUserIds.length;
            showAlert('success', `成功添加 ${addedCount} 个用户到分组，API密钥已自动分配`);
            
            // 关闭模态框
            bootstrap.Modal.getInstance(document.getElementById('addUserModal')).hide();
            
            // 清空选中的用户
            selectedUsers.clear();
            
            // 重新加载用户数据
            loadAllUsers().then(() => {
            });
            
            // 重新加载分组数据
            setTimeout(() => {
                loadGroupCards();
            }, 1000);
        } else {
            showAlert('error', data.message || '添加用户失败');
        }
    })
    .catch(error => {
        console.error('添加用户请求失败:', error);
        showAlert('error', '网络错误，请稍后重试');
    });
}

// 从分组移除用户
function removeUserFromGroup(groupId, userId) {
    console.log('从分组移除用户:', { groupId, userId });
    
    // 调用API移除用户
    fetch(`/api/groups/${groupId}/members/${userId}`, {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showAlert('success', '用户移除成功');
            
            // 移除用户项
            const userItems = document.querySelectorAll('.user-item');
            userItems.forEach(item => {
                const button = item.querySelector(`[onclick*="${userId}"]`);
                if (button) {
                    item.style.opacity = '0';
                    setTimeout(() => {
                        item.remove();
                    }, 300);
                }
            });
            
            // 重新加载用户数据和分组数据
            loadAllUsers().then(() => {
                // 如果用户列表模态框是打开的，重新渲染
                const addUserModal = document.getElementById('addUserModal');
                if (addUserModal && addUserModal.classList.contains('show')) {
                    renderUserList();
                }
                // 如果创建分组模态框是打开的，重新渲染
                const createGroupModal = document.getElementById('createGroupModal');
                if (createGroupModal && createGroupModal.classList.contains('show')) {
                    renderCreateGroupUserList(allUsers);
                }
            });
            
            // 重新加载分组数据
            setTimeout(() => {
                loadGroupCards();
            }, 1000);
        } else {
            showAlert('error', data.message || '移除用户失败');
        }
    })
    .catch(error => {
        console.error('移除用户请求失败:', error);
        showAlert('error', '网络错误，请稍后重试');
    });
}

// showAlert 函数已在 base_ynex.html 中全局定义，无需在此重复定义

// 导出主要函数供HTML调用
window.GroupManagement = {
    createNewGroup,
    saveNewGroup,
    deleteGroup,
    autoSaveGroupApiKey,
    toggleGroupApiKeyVisibility,
    addUserToGroup,
    removeUserFromGroup,
    toggleUserSelection,
    saveSelectedUsers
};

// 为了与HTML内联事件处理器兼容，将函数绑定到全局作用域
window.createNewGroup = createNewGroup;
window.saveNewGroup = saveNewGroup;
window.deleteGroup = deleteGroup;
window.autoSaveGroupApiKey = autoSaveGroupApiKey;
window.toggleGroupApiKeyVisibility = toggleGroupApiKeyVisibility;
window.addUserToGroup = addUserToGroup;
window.removeUserFromGroup = removeUserFromGroup;
window.toggleUserSelection = toggleUserSelection;
window.saveSelectedUsers = saveSelectedUsers;
window.toggleCreateGroupUserSelection = toggleCreateGroupUserSelection;

// 新建分组相关函数

// 初始化创建分组的用户列表
async function initializeCreateGroupUserList() {
    console.log('初始化创建分组用户列表');
    selectedUsersForNewGroup = [];
    
    // 先加载可用用户（过滤掉已在确定分组的用户）
    await loadAllUsers(true);
    
    // 渲染用户列表
    renderCreateGroupUserList(allUsers);
    updateSelectedUsersPreview();
    
    // 获取下一个分组ID并设置默认分组名称
    fetch('/api/groups/next-id')
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // 设置默认分组名称
                const groupNameInput = document.getElementById('groupName');
                if (groupNameInput && !groupNameInput.value) { // 只在输入框为空时设置默认值
                    groupNameInput.value = data.default_name;
                }
                console.log(`设置默认分组名称: ${data.default_name}`);
            } else {
                console.error('获取下一个分组ID失败:', data.message);
            }
        })
        .catch(error => {
            console.error('获取分组ID错误:', error);
        });
}

// 渲染创建分组的用户列表
function renderCreateGroupUserList(users) {
    const listGroup = document.getElementById('createGroupUserListGroup');
    if (!listGroup) return;
    
    listGroup.innerHTML = '';
    
    // 只显示没有分组或在临时分组中的用户
    const availableUsers = users.filter(user => user.group_status !== 'confirmed');
    
    if (availableUsers.length === 0) {
        listGroup.innerHTML = '<div class="text-center text-muted py-3"><small>没有可用的用户</small></div>';
        return;
    }
    
    availableUsers.forEach(user => {
        const isSelected = selectedUsersForNewGroup.includes(user.id);
        const roleColor = getRoleColor(user.role || 'user'); // 使用真实角色
        const roleText = getRoleText(user.role || 'user'); // 使用真实角色
        
        const userItem = document.createElement('div');
        userItem.className = 'list-group-item border-0 py-2';
        userItem.innerHTML = `
            <div class="form-check">
                <input class="form-check-input" type="checkbox" value="${user.id}" 
                       id="create_user_${user.id}" ${isSelected ? 'checked' : ''}
                       onchange="toggleCreateGroupUserSelection(${user.id}, this.checked)">
                <label class="form-check-label w-100" for="create_user_${user.id}">
                    <div class="d-flex justify-content-between align-items-center">
                        <div class="d-flex align-items-center">
                            <span class="avatar avatar-sm avatar-rounded me-2 bg-primary-transparent">
                                <i class="bi bi-person"></i>
                            </span>
                            <div>
                                <span class="fw-semibold d-block">${escapeHtml(user.username || user.name || '未知用户')}</span>
                                <small class="text-muted">${escapeHtml(user.email || '无邮箱')}</small>
                            </div>
                        </div>
                        <span class="badge ${roleColor} fs-11 fw-semibold text-uppercase px-2 py-1" style="min-width: 50px; text-align: center;">${roleText}</span>
                    </div>
                </label>
            </div>
        `;
        
        listGroup.appendChild(userItem);
    });
}

// 切换创建分组时的用户选择状态
function toggleCreateGroupUserSelection(userId, isChecked) {
    if (isChecked) {
        if (!selectedUsersForNewGroup.includes(userId)) {
            selectedUsersForNewGroup.push(userId);
        }
    } else {
        selectedUsersForNewGroup = selectedUsersForNewGroup.filter(id => id !== userId);
    }
    
    updateSelectedUsersPreview();
}

// 更新已选择用户预览
function updateSelectedUsersPreview() {
    const countElement = document.getElementById('selectedUserCount');
    const listElement = document.getElementById('selectedUsersList');
    
    if (!countElement || !listElement) return;
    
    countElement.textContent = selectedUsersForNewGroup.length;
    
    if (selectedUsersForNewGroup.length === 0) {
        listElement.innerHTML = '';
        return;
    }
    
    const selectedUsers = allUsers.filter(user => 
        selectedUsersForNewGroup.includes(user.id)
    );
    
    listElement.innerHTML = selectedUsers.map(user => 
        `<span class="badge bg-primary me-1">${escapeHtml(user.name)}</span>`
    ).join('');
}

// 处理创建分组用户搜索
function handleCreateGroupUserSearch() {
    const createGroupUserSearchInput = document.getElementById('createGroupUserSearchInput');
    let searchValue = createGroupUserSearchInput.value.toLowerCase().trim();
    
    // 检测并清除可能的自动填充内容
    if (isAutofillContent(createGroupUserSearchInput)) {
        createGroupUserSearchInput.value = '';
        searchValue = '';
    }
    
    const roleFilter = document.getElementById('createGroupRoleFilter').value;
    
    let filteredUsers = allUsers;
    
    // 搜索过滤
    if (searchValue) {
        filteredUsers = filteredUsers.filter(user => {
            const username = user.username || user.name || '';
            const email = user.email || '';
            return username.toLowerCase().includes(searchValue) ||
                   email.toLowerCase().includes(searchValue);
        });
    }
    
    // 角色过滤
    if (roleFilter) {
        filteredUsers = filteredUsers.filter(user => user.role === roleFilter);
    }
    
    renderCreateGroupUserList(filteredUsers);
}

// 处理创建分组用户角色筛选
function handleCreateGroupUserFilter() {
    handleCreateGroupUserSearch();
}

// 重置创建分组表单
function resetCreateGroupForm() {
    document.getElementById('createGroupForm').reset();
    selectedUsersForNewGroup = [];
    updateSelectedUsersPreview();
    
    // 清空分组名称输入框，确保下次打开时重新获取默认名称
    const groupNameInput = document.getElementById('groupName');
    if (groupNameInput) {
        groupNameInput.value = '';
    }
}

// ================================
// 批量选择和操作功能
// ================================

// 切换分组选择状态
function toggleGroupSelection(groupId, isSelected) {
    if (isSelected) {
        selectedGroups.add(groupId);
    } else {
        selectedGroups.delete(groupId);
    }
    updateGroupSelectionUI();
}

// 全选/取消全选分组
function toggleSelectAllGroups() {
    const selectAllCheckbox = document.getElementById('selectAllGroupsCheckbox');
    const isSelectAll = selectAllCheckbox.checked;
    
    // 清空当前选择
    selectedGroups.clear();
    
    if (isSelectAll) {
        // 选择所有分组
        document.querySelectorAll('.group-card-checkbox').forEach(checkbox => {
            const groupId = parseInt(checkbox.getAttribute('data-group-id'));
            if (groupId) {
                selectedGroups.add(groupId);
            }
        });
    }
    
    // 更新所有分组卡片的复选框状态
    document.querySelectorAll('.group-card-checkbox').forEach(checkbox => {
        checkbox.checked = isSelectAll;
    });
    
    updateGroupSelectionUI();
}

// 更新分组选择界面
function updateGroupSelectionUI() {
    // 更新选择数量显示
    const selectedCountElement = document.getElementById('selectedGroupCount');
    if (selectedCountElement) {
        selectedCountElement.textContent = selectedGroups.size;
    }
    
    // 更新全选复选框状态
    const selectAllCheckbox = document.getElementById('selectAllGroupsCheckbox');
    if (selectAllCheckbox) {
        const totalGroups = document.querySelectorAll('.group-card').length;
        const selectedCount = selectedGroups.size;
        
        if (selectedCount === 0) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
        } else if (selectedCount === totalGroups) {
            selectAllCheckbox.checked = true;
            selectAllCheckbox.indeterminate = false;
        } else {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = true;
        }
    }
    
    // 更新批量删除按钮状态
    const batchDeleteBtn = document.getElementById('batchDeleteBtn');
    if (batchDeleteBtn) {
        batchDeleteBtn.disabled = selectedGroups.size === 0;
        batchDeleteBtn.innerHTML = selectedGroups.size > 0 
            ? `<i class="bi bi-trash me-1"></i>批量删除 (${selectedGroups.size})`
            : '<i class="bi bi-trash me-1"></i>批量删除';
    }
}

// 批量删除分组
function batchDeleteGroups() {
    if (selectedGroups.size === 0) {
        showAlert('warning', '请先选择要删除的分组');
        return;
    }
    
    // 获取选中分组的名称和用户数量
    const selectedGroupCards = Array.from(selectedGroups).map(groupId => {
        const groupCard = document.querySelector(`[data-group-id="${groupId}"]`);
        if (groupCard) {
            const groupName = groupCard.querySelector('.card-title')?.textContent?.trim() || '未知分组';
            const userCount = groupCard.querySelectorAll('.user-item').length;
            return { id: groupId, name: groupName, userCount: userCount };
        }
        return null;
    }).filter(Boolean);
    
    const totalUsers = selectedGroupCards.reduce((sum, group) => sum + group.userCount, 0);
    const groupNames = selectedGroupCards.map(group => `• ${group.name} (${group.userCount}个用户)`);
    
    let confirmMessage = `确定要删除以下 ${selectedGroups.size} 个分组吗？\n\n${groupNames.join('\n')}`;
    if (totalUsers > 0) {
        confirmMessage += `\n\n总计 ${totalUsers} 个用户将被移出分组。`;
    }
    confirmMessage += '\n\n此操作不可恢复！';
    
    if (!confirm(confirmMessage)) {
        return;
    }
    
    // 调用API批量删除分组
    fetch('/api/groups/batch-delete', {
        method: 'DELETE',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            group_ids: Array.from(selectedGroups)
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            showAlert('success', data.message || '批量删除分组成功');
            
            // 清空选择状态
            selectedGroups.clear();
            updateGroupSelectionUI();
            
            // 重新加载用户数据
            loadAllUsers().then(() => {
                // 如果用户列表模态框是打开的，重新渲染
                const addUserModal = document.getElementById('addUserModal');
                if (addUserModal && addUserModal.classList.contains('show')) {
                    renderUserList();
                }
                // 如果创建分组模态框是打开的，重新渲染
                const createGroupModal = document.getElementById('createGroupModal');
                if (createGroupModal && createGroupModal.classList.contains('show')) {
                    renderCreateGroupUserList(allUsers);
                }
            });
            
            // 重新加载分组数据
            setTimeout(() => {
                loadGroupCards();
            }, 1000);
        } else {
            showAlert('error', data.message || '批量删除分组失败');
        }
    })
    .catch(error => {
        console.error('批量删除分组请求失败:', error);
        showAlert('error', '网络错误，请稍后重试');
    });
}

// 搜索分组功能
// 搜索分组（调用统一的筛选函数）
function searchGroups() {
    const searchInput = document.getElementById('searchGroupInput');
    const searchTerm = searchInput.value.toLowerCase().trim();
    
    // 调用统一的筛选函数
    filterGroupCards(searchTerm);
}

// 显示创建分组模态框
function showCreateGroupModal() {
    // 重置表单
    resetCreateGroupForm();
    
    // 显示模态框（会触发show.bs.modal事件，自动加载用户数据）
    const modal = new bootstrap.Modal(document.getElementById('createGroupModal'));
    modal.show();
}

// 更新统计数据
function updateStats() {
    // 从DOM中动态计算统计数据
    const groupCards = document.querySelectorAll('.group-card');
    const groupCount = groupCards.length;
    
    let totalUsers = 0;
    groupCards.forEach(card => {
        const userItems = card.querySelectorAll('.user-item');
        totalUsers += userItems.length;
    });
    
    // 更新分组总数
    const groupCountElement = document.getElementById('groupCount');
    if (groupCountElement) {
        groupCountElement.textContent = groupCount;
    }
    
    // 更新统计卡片
    const totalGroupsElement = document.getElementById('totalGroups');
    if (totalGroupsElement) {
        totalGroupsElement.textContent = groupCount;
    }
    
    const activeGroupsElement = document.getElementById('activeGroups');
    if (activeGroupsElement) {
        activeGroupsElement.textContent = groupCount;
    }
    
    const totalUsersElement = document.getElementById('totalUsers');
    if (totalUsersElement) {
        totalUsersElement.textContent = totalUsers;
    }
}

// 禁用搜索框自动填充
// 禁用所有输入框的自动填充功能
function disableAllAutocomplete() {
    console.log('开始禁用指定输入框的自动填充功能');
    
    // 禁用搜索框自动填充
    disableSearchAutocomplete();
    
    // 注意：分组名称输入框保留正常的自动填充功能
    
    console.log('指定输入框自动填充禁用功能已启用');
}

// 禁用搜索框自动填充
function disableSearchAutocomplete() {
    // 获取所有搜索框
    const searchInputs = [
        'searchGroupInput',
        'createGroupUserSearchInput', 
        'userSearchInput'
    ];
    
    searchInputs.forEach(inputId => {
        const input = document.getElementById(inputId);
        if (input) {
            // 设置多重防护属性
            input.setAttribute('autocomplete', 'new-password');
            input.setAttribute('data-form-type', 'search');
            input.setAttribute('spellcheck', 'false');
            input.setAttribute('autocorrect', 'off');
            input.setAttribute('autocapitalize', 'off');
            input.setAttribute('data-lpignore', 'true'); // LastPass忽略
            input.setAttribute('data-form-type', 'other'); // 额外标记
            
            // 特殊处理：使用readonly技巧防止自动填充
            input.setAttribute('readonly', '');
            input.addEventListener('focus', function() {
                this.removeAttribute('readonly');
                setTimeout(() => {
                    if (isAutofillContent(this)) {
                        this.value = '';
                    }
                }, 50);
            });
            
            // 页面加载时清除任何自动填充的值
            setTimeout(() => {
                if (isAutofillContent(input)) {
                    input.value = '';
                }
                // 移除readonly属性以允许正常输入
                input.removeAttribute('readonly');
            }, 200);
            
            // 监听输入事件，如果检测到自动填充，清除它
            input.addEventListener('input', function() {
                if (isAutofillContent(this)) {
                    this.value = '';
                }
            });
            
            // 防止浏览器记住搜索历史
            input.addEventListener('blur', function() {
                setTimeout(() => {
                    if (isAutofillContent(this)) {
                        this.value = '';
                    }
                }, 100);
            });
            
            console.log(`搜索框 ${inputId} 自动填充已禁用（增强版）`);
        }
    });
    
    console.log('搜索框自动填充禁用功能已启用（增强版）');
}


