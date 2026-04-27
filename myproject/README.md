# 国自然申请书 & 毕业论文智能审查平台

基于 Flask 的企业级文档处理与智能审查系统，支持 **国家自然科学基金（NSFC）申请书 PDF** 与 **大学生毕业论文 Word** 两条独立处理链路，集成 MinerU API 完成 PDF→Markdown 转换，并通过正则初筛、LLM 质检、参考文献规范验证三级审查引擎输出结构化审查报告。

---

## ✨ 核心功能

### 📄 PDF 处理链路（NSFC 申请书）
- **MinerU API 转换**：将 NSFC 申请书 PDF 转换为结构化 Markdown，支持公式识别、表格 OCR
- **一键解析**：异步多线程处理，实时 SSE 进度推送（准备→上传→处理→下载→完成）
- **VLM 表格提取**：调用本地 Qwen2.5-VL-7B 或硅基流动 Qwen2.5-VL-72B 从 PDF 页面图像中精准提取表格
- **91 条审查规则**（见下文）

### 📝 Word 处理链路（毕业论文）
- **python-docx 跨平台解析**：无需安装 MS Office，跨平台运行
- **毕业论文参考文献审查**：60 条 GB/T 7714-2015 规则验证

### 🔍 三级审查引擎
| 级别 | 类型 | 说明 |
|------|------|------|
| 初筛层 | 正则 + 混合 | 22 条规则，毫秒级，覆盖格式、字段、数值一致性 |
| 质检层 | LLM | 调用本地 Qwen2.5-32B，评估立项依据/研究内容/研究基础质量 |
| 引用层 | 正则 + 可选 LLM | 60 条 GB/T 7714-2015 规则，含作者格式、文献类型标识、DOI 等 |

#### NSFC PDF 审查规则清单（91 条）
<details>
<summary>点击展开规则列表</summary>

**正则初筛规则（22 条）**
- `1` 申请代码格式（4 位数字）
- `2` 合作单位规范（不含附院）
- `3` 主要参与者人数与表格行数一致性
- `4.1~4.4` 报告正文：新模板章节、空白页、H18 专项、易漏章节
- `5.1~5.2` 年度计划时间一致性与相邻期衔接
- `6~8` 联系方式（手机/邮箱）、组织机构代码格式
- `A1` 预算总额与分项合计一致性
- `A2~A3` 执行期限合理性、身份证号校验
- `A4` 参与者工作月数 ≤ 12
- `A5` 关键词数量 3~5 个
- `A6~A7` 参考文献序号连续性与正文引用覆盖
- `A8~A9` 摘要字数、中英文项目名称一致性
- `A10~A14` 重复段落检测、必填字段、资助类别金额/年限、总人数统计
- `C1~C2` 参考文献时效性（混合正则+LLM）、自引率检查

**LLM 质检规则（3 条）**
- `LLM-1` 立项依据质量（研究动机与价值）
- `LLM-2` 研究内容质量（自主撰写 vs 套模板）
- `LLM-3` 研究基础质量（前期积累展示）

**参考文献 GB/T 7714 验证（60+ 条）**：覆盖专著[M]、期刊[J]、报纸[N]、学位论文[D]、专利[P]、报告[R]、标准[S]、电子资源[EB/OL] 等全文献类型
</details>

### 🤖 AI 推理后端
| 服务 | 模型 | 用途 |
|------|------|------|
| 本地 vLLM（VLM） | Qwen2.5-VL-7B | 表格 PDF 页图像提取（首选） |
| 硅基流动 API（VLM） | Qwen2.5-VL-72B-Instruct | VLM 备用 |
| 本地 vLLM（LLM） | Qwen2.5-32B | 文本质量审查 |

### 🔐 用户与权限管理
- 用户注册/登录，Werkzeug 密码哈希
- 角色体系：普通用户 / 管理员
- 文件隔离：用户只能访问自己的文档
- 记住我（30 天）/ 普通 session（24 小时）
- CSRF 保护（Flask-WTF）

### 👥 群组管理
- 创建群组，批量绑定 MinerU / 硅基流动 API Key
- 群组成员共享 API Key，减少个人 Token 管理成本
- 群组确认机制，管理员审批

### 🔔 通知系统
- 管理员向用户推送系统通知
- 用户反馈工单，支持管理员回复
- 未读消息计数角标

### 📊 管理后台
- 仪表盘：用户统计、文件处理量、服务状态
- 用户管理：新建/禁用/角色变更/删除
- 实时监控：任务队列、处理进度、系统性能（psutil）
- 日志管理：操作日志查询与定期清理

---

## 🏗️ 系统架构

### 双链路页面路由
```
/ (PDF 链路)                   /word/ (Word 链路)
├── /dashboard                 ├── /word/dashboard
├── /comprehensive-processor   ├── /word/comprehensive-processor
├── /rule-checker              ├── /word/rule-checker
├── /parsed-documents          ├── /word/parsed-documents
├── /reference-analysis        ├── /word/reference-analysis
├── /group-management          ├── /word/group-management
└── /admin                     └── /word/admin
```

### 数据库设计（MySQL 8.0+，utf8mb4_unicode_ci）

完整建库脚本见 [database_setup.sql](database_setup.sql)，共 7 张表：

| 表名 | 行数（约） | 说明 |
|------|-----------|------|
| `users` | 6 | 用户账号，含角色（user/admin/premium）与群组归属 |
| `user_files` | 71 | 上传文件及全部处理结果，含混合存储路由字段、NSFC JSON、参考文献验证 JSON |
| `system_logs` | 12,000+ | 用户操作审计日志，约 5.5 MB，支持定期清理 |
| `notifications` | — | 站内通知，支持 system/personal/group 三种投递范围 |
| `user_notification_reads` | — | 通知精确已读记录，UNIQUE(user_id, notification_id) 防重复 |
| `user_feedback` | — | 用户反馈工单，状态流转 open→in_progress→resolved/closed |
| `group_api_keys` | — | 群组共享 API Key，UNIQUE(group_id, api_provider) |

#### user_files 核心字段
```
file_id                   VARCHAR(255) UNIQUE  -- UUID 全局唯一标识
original_document_type    ENUM(pdf/word_doc/word_docx/unknown)
status                    ENUM(uploaded/processing/completed/error)
storage_type              ENUM(database/filesystem)  -- 混合存储路由
md_content                LONGTEXT     -- 数据库存储的 MD 正文
md_file_path              VARCHAR(500) -- 文件系统存储时的路径
extracted_json_data        LONGTEXT     -- MinerU 原始结构化数据
table_preliminary_check   LONGTEXT     -- 表格正则初筛结果 JSON
text_preliminary_check    LONGTEXT     -- 文本正则初筛结果 JSON
nsfc_json_data             LONGTEXT     -- NSFC 申请书结构化提取结果
reference_validation_json LONGTEXT     -- GB/T 7714 验证结果 JSON
pdf_data                  LONGBLOB     -- 原始 PDF 二进制（在线预览用）
```

### 混合存储策略
```
📁 存储路由
├── 数据库存储  (≤ 50 KB)   → 快速读取，适合小文件
└── 文件系统存储 (> 50 KB)  → md_storage/YYYYMM/uuid.md
```

### 并发控制
- 全局文件处理线程池：`ThreadPoolExecutor(max_workers=2)`
- VLM 并发信号量：`Semaphore(2)`（vLLM continuous batching）
- 本地 MinerU 并发信号量：`Semaphore(2)`
- `tasks_db_lock` / `one_click_tasks_lock` 保护任务字典并发读写

---

## 🚀 快速开始

### 环境要求
- Python 3.8+
- MySQL 8.0+
- MinerU API Token（PDF 转换必需）
- 可选：硅基流动 API Key（VLM 备用）

### 安装步骤

```bash
# 1. 进入项目目录
cd myproject

# 2. 安装依赖
pip install -r requirements.txt

# 3. 初始化数据库
#    database_setup.sql 会自动 CREATE DATABASE IF NOT EXISTS，可直接执行
mysql -u root -p < database_setup.sql

# 4. （可选）验证表结构
mysql -u root pdf_md_system -e "SHOW TABLES;"
```

### 环境变量（推荐生产环境设置）
```bash
set SECRET_KEY=your-strong-secret-key   # 必须设置，否则重启后 session 失效
set DB_HOST=localhost
set DB_PORT=3306
set DB_USER=zzt
set DB_PASSWORD=your_password
set DB_NAME=pdf_md_system
```

### 启动
```bash
# 开发模式
python app_pdf_md.py

# 生产模式（Gunicorn）
gunicorn -c gunicorn_config.py app_pdf_md:app
```

访问 `http://localhost:5000`，注册账号后开始使用。

---

## 📖 使用指南

### PDF 申请书处理
1. 登录后进入**仪表板**，上传 NSFC 申请书 PDF（≤ 50 MB）
2. 配置 MinerU API Token 和处理参数（公式/表格/OCR/语言）
3. 点击**一键解析**，实时查看 9 阶段进度
4. 解析完成后，在**综合处理器**页面运行三级审查，查看结构化报告

### Word 毕业论文处理
1. 访问 `/word/` 路由体系，注册/登录（独立会话）
2. 上传 `.docx` 论文文件
3. 在参考文献分析页查看 GB/T 7714-2015 验证报告

### 管理员操作
- 访问 `/admin` 进入管理后台
- 用户管理、通知推送、日志查看均在此完成

---

## 📁 项目结构

```
myproject/
├── app_pdf_md.py             # 主应用（12000+ 行，含全部路由）
├── database_config.py        # MySQL 连接池配置
├── database_manager.py       # 数据库连接错误处理封装
├── db_operations.py          # 数据库 CRUD 操作集合
├── md_storage_manager.py     # 混合存储管理器
├── md_content_processor.py   # MD 内容分离 + VLM/LLM 调用
├── reference_validator.py    # GB/T 7714-2015 参考文献验证器
├── regex_preliminary_check.py# 正则初筛规则引擎
├── title_enhancer.py         # NSFC 申请书标题优化处理器
├── notification_system.py    # 通知系统（路由注册 + 业务逻辑）
├── smart_logger.py           # 智能日志系统（分级 / 控制台优化）
├── timezone_adapter.py       # 时区适配（UTC+8）
├── generate_rules_excel.py   # 生成检查规则汇总 Excel（两 Sheet）
├── gunicorn_config.py        # Gunicorn 生产配置
├── env_loader.py             # 环境变量加载工具
├── database_setup.sql        # 完整建库脚本（7 张表，含注释与常用维护查询）
├── requirements.txt          # Python 依赖
├── 检查规则汇总.xlsx          # 导出的规则说明文档
├── templates/                # Jinja2 HTML 模板
│   ├── dashboard.html
│   ├── comprehensive_processor.html
│   ├── rule_checker.html
│   ├── parsed_documents.html
│   ├── reference_analysis.html
│   ├── group_management.html
│   ├── login.html / register.html / forgot_password.html
│   ├── admin/                # 管理后台模板
│   └── errors/               # 错误页
├── static/                   # 静态资源（CSS/JS/图片）
├── word_templates/           # Word 链路模板
├── uploads/                  # 上传文件临时目录
├── downloads/                # 处理结果下载
├── md_storage/               # MD 文件存储（按月分目录）
└── migrations/               # 数据库迁移脚本
```

---

## 🛠️ 关键配置

### 数据库（`database_config.py`）
```python
# 支持环境变量覆盖，默认值如下（user 为 root，password 为空）
DB_HOST = 'localhost'
DB_PORT = 3306
DB_NAME = 'pdf_md_system'
DB_USER = 'root'
# 生产环境请通过环境变量 DB_PASSWORD 设置
```

### 数据库维护
```sql
-- 查看各表数据量与磁盘占用
SELECT TABLE_NAME,
       TABLE_ROWS,
       ROUND((DATA_LENGTH + INDEX_LENGTH) / 1024 / 1024, 2) AS size_MB
FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'pdf_md_system'
ORDER BY TABLE_NAME;

-- 清理 90 天前的操作日志
DELETE FROM system_logs WHERE created_at < DATE_SUB(NOW(), INTERVAL 90 DAY);

-- 查看文件存储分布（数据库 vs 文件系统）
SELECT storage_type, COUNT(*) AS file_count,
       ROUND(SUM(file_size) / 1024 / 1024, 2) AS total_size_MB
FROM user_files GROUP BY storage_type;

-- 查看未回复的反馈工单
SELECT id, user_id, subject, feedback_type, created_at
FROM user_feedback
WHERE status IN ('open','in_progress') AND admin_reply IS NULL
ORDER BY created_at;
```
> 更多维护查询见 [database_setup.sql](database_setup.sql) 文末注释部分。

### 混合存储阈值（`md_storage_manager.py`）
```python
DATABASE_SIZE_LIMIT = 50 * 1024        # 50 KB 以下存数据库
FILESYSTEM_SIZE_LIMIT = 10 * 1024 * 1024  # 10 MB 上限
MD_STORAGE_DIR = "md_storage"
```

### AI 推理服务（`md_content_processor.py`）
```python
LOCAL_VLM_CONFIG = {
    "api_url": "http://<vllm-host>:60606/v1/chat/completions",
    "model": "Qwen2.5-VL-7B",
}
LOCAL_LLM_CONFIG = {
    "api_url": "http://<llm-host>:60687/v1/chat/completions",
    "model": "Qwen2.5-32B",
}
# 硅基流动备用 VLM 需在用户页面填写 API Key
```

---

## 🛡️ 安全特性

- **密码哈希**：Werkzeug `generate_password_hash` / `check_password_hash`
- **CSRF 防护**：Flask-WTF `CSRFProtect`
- **Session 安全**：`SESSION_COOKIE_HTTPONLY=True`，`SAMESITE=Lax`
- **SECRET_KEY**：生产环境必须通过环境变量注入；开发环境使用机器特征派生密钥并打印安全警告
- **SQL 注入防护**：全部使用参数化查询（PyMySQL）
- **文件隔离**：用户只能访问自己的文件记录
- **文件类型限制**：上传接口校验扩展名与 MIME 类型
- **上传大小限制**：50 MB（`MAX_CONTENT_LENGTH`）

---

## 🐛 故障排除

| 问题 | 排查方法 |
|------|---------|
| 数据库连接失败 | 检查 MySQL 服务、验证 DB_* 环境变量、确认 `pdf_md_system` 数据库已创建 |
| MinerU API 调用失败 | 验证 Token 有效期、检查网络、查看 `smart_logger` 控制台输出 |
| VLM/LLM 服务不可达 | 确认 vLLM 服务地址与端口，检查内网连通性 |
| 文件上传失败 | 确认文件为 PDF/DOCX、大小 ≤ 50 MB、`uploads/` 目录有写权限 |
| session 重启失效 | 生产环境设置 `SECRET_KEY` 环境变量 |
| 规则 Excel 未更新 | 修改 `generate_rules_excel.py` 中的规则列表后重新运行 `python generate_rules_excel.py` |

---

## 📝 更新日志

- **v2.0** (2026-04): Word 毕业论文链路（`/word/`）、群组管理、通知系统、管理后台全面升级
- **v1.5** (2025-09): 三级审查引擎上线（正则初筛 22 条 + LLM 质检 3 条 + GB/T 7714 60 条）
- **v1.4** (2025-08): VLM 表格提取（Qwen2.5-VL-7B）、硅基流动 API 备用支持
- **v1.3** (2025-08): 混合存储策略、连接池、性能优化
- **v1.2** (2025-07): 多 API 密钥管理、异步任务系统重构
- **v1.1** (2025-07): 用户管理、CSRF 防护、安全增强
- **v1.0** (2025-07): 基础 PDF→Markdown 转换功能

---

## 📞 支持联系

- **邮箱**: 15950525836@163.com
