# PDF转Markdown文档处理系统 📄➡️📝

一个基于Flask的企业级PDF文档智能转换系统，集成MinerU API，提供高质量的PDF到Markdown转换服务。

## ✨ 核心特性

### 🔐 完整的用户管理
- **用户注册登录**: 安全的密码哈希存储
- **多API密钥管理**: 每用户最多管理3个API密钥
- **权限控制**: 文件隔离，用户只能访问自己的文件
- **操作审计**: 完整的用户行为日志记录

### 📁 智能文件管理
- **批量上传**: 支持多文件同时上传
- **混合存储策略**: 
  - 小文件(≤50KB): 数据库存储，快速访问
  - 大文件(>50KB): 文件系统存储，节省数据库空间
- **文件状态跟踪**: 上传中→处理中→已完成→错误处理
- **安全文件命名**: UUID防冲突，原名保留显示

### ⚡ 异步处理引擎
- **后台任务**: 多线程异步处理，不阻塞界面
- **实时进度**: 9个处理阶段的详细进度反馈
- **错误恢复**: 智能重试机制和详细错误信息
- **批量处理**: 支持MinerU批量API调用

### 🎯 高质量转换
- **MinerU API集成**: 使用最新的V4 API
- **智能配置**: 
  - 公式识别开关
  - 表格处理优化
  - OCR模式选择
  - 多语言支持
- **结果验证**: 自动验证转换结果完整性

## 🏗️ 系统架构

### 数据库设计
```
📊 MySQL 8.0+ (utf8mb4_unicode_ci)
├── users              # 用户基础信息
├── user_api_keys      # API密钥管理
├── user_files         # 文件存储(混合策略)
├── processing_tasks   # 异步任务跟踪
└── system_logs        # 系统操作日志
```

### 混合存储策略
```
📁 存储架构
├── 数据库存储 (≤50KB)
│   └── 快速访问，适合小文件
├── 文件系统存储 (>50KB)
│   ├── md_storage/
│   │   ├── 202508/        # 按月组织
│   │   └── 202509/
│   └── 大文件优化存储
└── 智能路由选择
```

### 处理流程
```
🔄 转换流程 (9个阶段)
准备阶段 → 验证阶段 → 上传阶段 → 处理阶段 → 下载阶段 → 解压阶段 → 完成
   2%        7%        15%       35%        85%        95%       100%
```

## 🚀 快速开始

### 环境要求
- Python 3.8+
- MySQL 8.0+
- MinerU API Token

### 安装步骤

1. **克隆项目**
```bash
git clone <repository-url>
cd myproject
```

2. **安装依赖**
```bash
pip install -r requirements.txt
```

3. **数据库配置**
```bash
# 启动MySQL服务
start_mysql.bat

# 在MySQL Workbench中执行
database_setup.sql
```

4. **环境变量配置**（可选）
```bash
set DB_HOST=localhost
set DB_USER=zzt
set DB_PASSWORD=your_password
set DB_NAME=pdf_md_system
```

5. **启动应用**
```bash
# 开发模式
python app_pdf_md.py

# 生产模式
start_production.bat
```

## 📖 使用指南

### 首次使用
1. 访问 `http://localhost:5000`
2. 注册新用户账号
3. 登录并进入仪表板

### API密钥配置
1. 点击"配置API"或在上传时配置
2. 输入MinerU API Token
3. 设置处理参数：
   - 启用公式识别
   - 启用表格处理
   - OCR模式选择
   - 语言设置

### 文件处理
1. 在仪表板选择PDF文件上传
2. 系统自动分配处理任务
3. 实时查看处理进度
4. 完成后查看MD结果或下载ZIP

### 高级功能
- **批量处理**: 同时上传多个文件
- **密钥管理**: 在Token管理页面切换API密钥
- **历史记录**: 查看所有处理过的文件
- **错误诊断**: 详细的错误信息和解决建议

## 🛠️ 配置选项

### 数据库配置 (`database_config.py`)
```python
DEFAULT_CONFIG = {
    'host': 'localhost',
    'port': 3306,
    'database': 'pdf_md_system',
    'user': 'zzt',
    'password': '@2938730291$Zzt',
    'charset': 'utf8mb4'
}
```

### 存储配置 (`md_storage_manager.py`)
```python
DATABASE_SIZE_LIMIT = 50 * 1024      # 50KB
FILESYSTEM_SIZE_LIMIT = 10 * 1024 * 1024  # 10MB
MD_STORAGE_DIR = "md_storage"         # 文件存储目录
```

### API配置
```python
MINERU_CONFIG = {
    'enable_formula': True,    # 启用公式识别
    'enable_table': True,      # 启用表格处理
    'is_ocr': False,          # OCR模式
    'language': 'auto',       # 语言自动检测
    'model_version': 'v2'     # 模型版本
}
```

## 📁 项目结构

```
myproject/
├── app_pdf_md.py           # 主应用程序
├── database_config.py      # 数据库配置
├── md_storage_manager.py   # 存储管理器
├── database_setup.sql      # 数据库初始化脚本
├── requirements.txt        # Python依赖包
├── start_production.bat    # 生产环境启动脚本
├── start_mysql.bat        # MySQL启动脚本
├── templates/             # HTML模板
│   ├── dashboard.html     # 主控制台
│   ├── login.html         # 登录页面
│   ├── register.html      # 注册页面
│   ├── token_manager.html # API密钥管理
│   └── errors/            # 错误页面
├── uploads/               # 文件上传目录
├── downloads/             # 处理结果下载
├── md_storage/            # MD文件存储
│   └── 202508/           # 按月组织
├── logs/                  # 应用日志
└── migrations/            # 数据库迁移脚本
```

## 🔧 维护管理

### 数据库迁移
```bash
# 查看当前表结构
DESCRIBE user_files;

# 应用新迁移
mysql -u zzt -p pdf_md_system < migrations/latest_migration.sql
```

### 日志管理
```bash
# 查看应用日志
tail -f logs/app.log

# 查看系统日志（数据库中）
SELECT * FROM system_logs ORDER BY created_at DESC LIMIT 100;
```

### 存储空间管理
```bash
# 清理旧文件（文件系统）
python -c "from md_storage_manager import md_storage_manager; md_storage_manager.cleanup_old_files()"

# 检查存储使用情况
SELECT storage_type, COUNT(*) as count, 
       SUM(CASE WHEN md_content IS NOT NULL THEN LENGTH(md_content) ELSE 0 END) as db_size
FROM user_files GROUP BY storage_type;
```

## 🛡️ 安全特性

- **密码安全**: Werkzeug密码哈希
- **文件隔离**: 用户级别的权限控制
- **API安全**: Token验证和使用跟踪
- **输入验证**: 文件类型和大小限制
- **SQL注入防护**: 参数化查询
- **会话管理**: Flask安全会话

## 📊 性能优化

- **数据库索引**: 优化查询性能
- **混合存储**: 平衡速度和空间
- **异步处理**: 避免界面阻塞
- **连接池**: 数据库连接复用
- **文件缓存**: 智能缓存策略

## 🐛 故障排除

### 常见问题

1. **数据库连接失败**
   - 检查MySQL服务状态
   - 验证连接配置
   - 确认数据库和表是否创建

2. **API调用失败**
   - 验证MinerU Token有效性
   - 检查网络连接
   - 查看详细错误日志

3. **文件上传失败**
   - 检查文件大小限制（50MB）
   - 确认uploads目录权限
   - 验证文件格式（仅支持PDF）

### 调试工具
```bash
# 测试数据库连接
python database_config.py

# 验证API Token
python -c "from app_pdf_md import validate_mineru_token; print(validate_mineru_token('your_token'))"
```

## 📝 更新日志

- **v1.3** (2025-08-07): 混合存储策略，性能优化
- **v1.2** (2025-07-21): 多API密钥管理，任务系统重构
- **v1.1** (2025-07-17): 用户管理系统，安全增强
- **v1.0** (2025-07-01): 基础PDF转换功能

## 🤝 贡献指南

1. Fork 项目
2. 创建功能分支
3. 提交更改
4. 推送到分支
5. 创建 Pull Request

## 📄 许可证

本项目基于 MIT 许可证开源 - 查看 [LICENSE](LICENSE) 文件了解详情。

## 📞 支持联系

- **开发者**: zzt
- **邮箱**: 15950525836@163.com
- **项目地址**: [GitHub Repository]

---

🌟 **感谢使用 PDF转Markdown文档处理系统！** 如果这个项目对您有帮助，请给我们一个Star ⭐
