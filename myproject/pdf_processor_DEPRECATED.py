"""
PDF处理器 - 完整的PDF文档处理流程
包含MinerU API调用、内容提取、LLM处理等功能

功能模块：
1. MinerU API交互：上传、轮询、下载
2. 内容提取：表格提取、NSFC内容提取
3. LLM处理：使用SiliconFlow API进行智能内容分析
4. 完整流程：一键解析、并行处理
5. 辅助工具：文件解压、编码处理、任务管理
"""

import os
import sys
import json
import time
import threading
import tempfile
import shutil
import re
import zipfile
from typing import Dict, List, Optional, Tuple, Any, Callable
from concurrent.futures import ThreadPoolExecutor

# HTTP请求相关
import requests
from requests.exceptions import Timeout, ConnectionError, RequestException

# 数据库相关
import pymysql

# 导入数据库配置和管理模块
from database_config import DatabaseConfig
from database_manager import get_db_connection_with_error_handling, safe_db_close, db_manager

# 导入数据库操作模块
from db_operations import (
    get_file_info_from_db, 
    get_file_content_from_db,
    update_file_status_in_db,
    update_file_extracted_json,
    get_user_siliconflow_model
)

# 导入MD存储管理器
from md_storage_manager import md_storage_manager

# 导入标题优化处理器
from title_enhancer import TitleEnhancer

# 导入智能日志系统
from smart_logger import smart_print, LogLevel, smart_logger


# ==================== 全局配置 ====================

# 全局并发控制
GLOBAL_MAX_PARALLEL_TASKS = 2  # 最大并行任务数
global_task_semaphore = threading.Semaphore(GLOBAL_MAX_PARALLEL_TASKS)
global_active_tasks_lock = threading.Lock()
global_active_tasks = 0

# MinerU API配置
MINERU_API_BASE_URL = "https://mineru.net/api/v4"
MINERU_UPLOAD_URL = f"{MINERU_API_BASE_URL}/file-urls/batch"
MINERU_POLL_URL_TEMPLATE = f"{MINERU_API_BASE_URL}/extract-results/batch/{{batch_id}}"

# SiliconFlow API配置
SILICONFLOW_API_URL = "https://api.siliconflow.cn/v1/chat/completions"
DEFAULT_SILICONFLOW_MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"

# 处理超时配置
DEFAULT_TIMEOUT = 600  # 10分钟
LONG_CONTENT_TIMEOUT = 600  # 长内容处理超时

# 任务数据库（内存）
tasks_db = {}  # 任务状态管理


# ==================== 模块1: 辅助工具函数 ====================

def is_task_cancelled(task_id: str) -> bool:
    """检查任务是否已被取消/删除
    
    Args:
        task_id: 任务ID
        
    Returns:
        bool: True表示任务已取消，False表示任务仍在进行
    """
    if not task_id:
        return False
    
    # 只检查内存中的任务（纯内存管理）
    if task_id not in tasks_db:
        return True
    
    # 任务存在于内存中，说明还在处理
    return False


def extract_md_from_zip(zip_path: str, original_filename: str) -> Optional[str]:
    """从ZIP文件中提取Markdown内容并进行处理（重要内容提取+标题优化）
    
    Args:
        zip_path: ZIP文件路径
        original_filename: 原始文件名（用于查找对应的.md文件）
        
    Returns:
        str: 提取并处理后的Markdown内容，失败返回None
    """
    try:
        print(f"[MD提取] 开始提取ZIP文件: {zip_path}")
        
        # 检查文件是否存在
        if not os.path.exists(zip_path):
            print(f"[MD提取] 错误: ZIP文件不存在: {zip_path}")
            return None
        
        file_size = os.path.getsize(zip_path)
        print(f"[MD提取] ZIP文件大小: {file_size} bytes")
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # 列出所有文件
            all_files = zip_ref.namelist()
            print(f"[MD提取] ZIP文件包含 {len(all_files)} 个文件:")
            for file_name in all_files[:10]:  # 只显示前10个文件名
                print(f"[MD提取]   - {file_name}")
            if len(all_files) > 10:
                print(f"[MD提取]   ...还有 {len(all_files) - 10} 个文件")
            
            # 查找full.md文件
            md_files = [name for name in all_files if name.endswith('full.md')]
            print(f"[MD提取] 找到 {len(md_files)} 个.md文件: {md_files}")
            
            if not md_files:
                # 尝试查找其他可能的MD文件
                all_md_files = [name for name in all_files if name.endswith('.md')]
                print(f"[MD提取] 尝试查找其他MD文件: {all_md_files}")
                
                if all_md_files:
                    md_file = all_md_files[0]
                    print(f"[MD提取] 使用第一个MD文件: {md_file}")
                else:
                    print(f"[MD提取] ZIP文件中未找到任何MD文件: {zip_path}")
                    return None
            else:
                # 提取第一个找到的full.md文件
                md_file = md_files[0]
                print(f"[MD提取] 使用full.md文件: {md_file}")
            
            # 提取文件内容
            try:
                with zip_ref.open(md_file) as file:
                    raw_content = file.read()
                    print(f"[MD提取] 读取原始内容，字节长度: {len(raw_content)}")
                    
                    # 尝试多种编码
                    for encoding in ['utf-8', 'utf-8-sig', 'gbk', 'gb2312', 'latin-1']:
                        try:
                            content = raw_content.decode(encoding)
                            print(f"[MD提取] 成功使用 {encoding} 编码解析，字符长度: {len(content)}")
                            
                            # 简单验证内容是否有效
                            if len(content.strip()) > 0:
                                print(f"[MD提取] 内容预览（前200字符）: {content[:200]}")
                                
                                # 对提取的MD内容进行处理：重要内容提取和标题优化
                                print(f"[MD处理] 开始处理MD内容，原始长度: {len(content)}")
                                
                                # 1. 重要内容提取（去除承诺书等无关内容）
                                important_content = TitleEnhancer.extract_important_content(content)
                                print(f"[MD处理] 重要内容提取完成，长度: {len(important_content)}")
                                
                                # 2. 标题优化处理
                                optimized_content = TitleEnhancer.optimize_headers_with_extractor(important_content)
                                print(f"[MD处理] 标题优化完成，最终长度: {len(optimized_content)}")
                                
                                return optimized_content
                            else:
                                print(f"[MD提取] 警告: {encoding} 解析的内容为空")
                        except UnicodeDecodeError:
                            print(f"[MD提取] {encoding} 编码解析失败，尝试下一个")
                            continue
                    
                    print(f"[MD提取] 所有编码尝试失败，返回原始字节内容")
                    return raw_content.decode('utf-8', errors='ignore')
                    
            except KeyError as e:
                print(f"[MD提取] 文件不存在于ZIP中: {e}")
                return None
            except Exception as e:
                print(f"[MD提取] 读取文件内容失败: {e}")
                return None
                
    except zipfile.BadZipFile as e:
        print(f"[MD提取] 无效的ZIP文件: {e}")
        return None
    except Exception as e:
        print(f"[MD提取] 提取MD内容失败: {e}")
        import traceback
        print(f"[MD提取] 异常详情: {traceback.format_exc()}")
        return None


def download_and_extract_markdown_from_zip(zip_url: str) -> Optional[str]:
    """下载ZIP文件并提取Markdown内容（临时文件自动清理）
    
    Args:
        zip_url: ZIP文件下载URL
        
    Returns:
        str: 提取的Markdown内容，失败返回None
    """
    temp_zip_path = None
    try:
        print(f"[结果下载] 开始下载: {zip_url}")
        
        # 创建临时文件
        with tempfile.NamedTemporaryFile(delete=False, suffix='.zip') as temp_file:
            temp_zip_path = temp_file.name
        
        # 下载ZIP文件
        with requests.get(zip_url, stream=True, timeout=DEFAULT_TIMEOUT) as response:
            if response.status_code != 200:
                print(f"[结果下载] 下载失败: {response.status_code}")
                return None
            
            with open(temp_zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
        
        print(f"[结果下载] 下载完成，大小: {os.path.getsize(temp_zip_path)} bytes")
        
        # 解压并提取Markdown
        return extract_md_from_zip(temp_zip_path, "result.md")
        
    except Exception as e:
        print(f"[结果下载] 下载和解压失败: {e}")
        return None
    finally:
        # 清理临时文件
        if temp_zip_path and os.path.exists(temp_zip_path):
            try:
                os.unlink(temp_zip_path)
                print(f"[结果下载] 临时文件已清理")
            except:
                pass


def test_siliconflow_api(api_key: str) -> bool:
    """测试SiliconFlow API密钥是否有效"""
    try:
        api_url = "https://api.siliconflow.cn/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        test_data = {
            "model": "Qwen/Qwen3-30B-A3B-Instruct-2507",  # 改为Qwen模型
            "messages": [{"role": "user", "content": "测试"}],
            "max_tokens": 10
        }
        
        response = requests.post(api_url, json=test_data, headers=headers, timeout=600)  # 10分钟超时
        return response.status_code == 200
    except:
        return False


print("[PDF处理器] 模块已加载 - 辅助工具函数")


# ==================== 模块2: MinerU API交互 ====================

def upload_file_to_mineru(file_id: str, user_id: int, api_token: str, options: Dict[str, Any], 
                          task_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """从数据库读取PDF数据并上传到MinerU - 使用官方批量上传API
    
    Args:
        file_id: 文件ID
        user_id: 用户ID
        api_token: MinerU API令牌
        options: 处理选项（enable_formula, language, enable_table等）
        task_id: 任务ID（可选，用于取消检查）
        
    Returns:
        dict: 包含batch_id等信息的字典，失败返回None
    """
    import tempfile
    import os
    try:
        smart_print(f"[MinerU-API] 从数据库获取文件: {file_id}", LogLevel.DEBUG)
        
        # 检查任务是否已被删除
        if task_id and is_task_cancelled(task_id):
            smart_print(f"[MinerU-API] 任务已被删除，取消上传: {task_id}", LogLevel.WARNING)
            return None
        
        # 从数据库获取PDF数据
        pdf_info = get_file_info_from_db(file_id, user_id)
        if not pdf_info:
            smart_print(f"[MinerU-API] 错误: 无法从数据库获取PDF数据", LogLevel.ERROR)
            return None
        
        smart_print(f"[MinerU-API] PDF数据大小: {pdf_info['size']} bytes", LogLevel.DEBUG)
        smart_print(f"[MinerU-API] 文件名: {pdf_info['original_name']}", LogLevel.DEBUG)
        smart_print(f"[MinerU-API] API Token长度: {len(api_token) if api_token else 0}", LogLevel.DEBUG)
        
        # 再次检查任务是否已被删除
        if task_id and is_task_cancelled(task_id):
            smart_print(f"[MinerU-API] 任务已被删除，取消上传: {task_id}", LogLevel.WARNING)
            return None
        
        # 第一步：申请上传链接
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_token}'
        }
        
        # 构建请求参数 - 按照官方API文档
        data = {
            "enable_formula": options.get("enable_formula", True),
            "language": options.get("language", "ch"),  # 默认中文
            "enable_table": options.get("enable_table", True),
            "files": [{
                "name": pdf_info['original_name'],
                "is_ocr": options.get("is_ocr", True),
                "data_id": file_id  # 使用file_id作为data_id
            }]
        }
        
        # 如果有额外格式要求
        if options.get("extra_formats"):
            data["extra_formats"] = options["extra_formats"]
        
        # 如果有页码范围要求
        if options.get("page_ranges"):
            data["files"][0]["page_ranges"] = options["page_ranges"]
            
        url = 'https://mineru.net/api/v4/file-urls/batch'
        smart_print(f"[MinerU-API] 申请上传链接URL: {url}", LogLevel.DEBUG)
        smart_print(f"[MinerU-API] 请求参数: {data}", LogLevel.DEBUG)
        
        response = requests.post(url, headers=headers, json=data, timeout=600)  # 10分钟超时
        smart_print(f"[MinerU-API] 响应状态码: {response.status_code}", LogLevel.DEBUG)
        
        if response.status_code != 200:
            smart_print(f"[MinerU-API] 申请上传链接失败: {response.status_code} {response.text}", LogLevel.ERROR)
            return None
            
        result = response.json()
        smart_print(f"[MinerU-API] 响应内容: {result}", LogLevel.DEBUG)
        
        if result.get("code") != 0:
            smart_print(f"[MinerU-API] API返回错误: {result.get('msg', 'Unknown error')}", LogLevel.ERROR)
            return None
            
        # 获取批次ID和上传链接
        batch_id = result["data"]["batch_id"]
        file_urls = result["data"]["file_urls"]
        
        if not file_urls:
            smart_print(f"[MinerU-API] 未获取到上传链接", LogLevel.ERROR)
            return None
            
        upload_url = file_urls[0]  # 第一个文件的上传链接
        smart_print(f"[MinerU-API] 获取到批次ID: {batch_id}", LogLevel.INFO)
        smart_print(f"[MinerU-API] 获取到上传链接: {upload_url}", LogLevel.DEBUG)
        
        # 检查任务是否已被删除（在上传文件前）
        if task_id and task_id not in tasks_db:
            smart_print(f"[MinerU-API] 任务已被删除，取消文件上传: {task_id}", LogLevel.WARNING)
            return None
        
        # 第二步：上传文件到获取的链接
        smart_print(f"[MinerU-API] 开始上传文件到: {upload_url}", LogLevel.INFO)
        
        upload_response = requests.put(upload_url, data=pdf_info['pdf_data'], timeout=600)  # 10分钟超时
        smart_print(f"[MinerU-API] 文件上传响应状态码: {upload_response.status_code}", LogLevel.DEBUG)
        
        if upload_response.status_code == 200:
            smart_print(f"[MinerU-API] 文件上传成功！", LogLevel.INFO)
            smart_print(f"[MinerU-API] 系统将自动开始解析，批次ID: {batch_id}", LogLevel.INFO)
            
            # 返回批次ID，用于后续查询结果
            return {
                "batch_id": batch_id,
                "data_id": file_id,
                "status": "uploaded",
                "upload_url": upload_url
            }
        else:
            print(f"[MinerU-API] 文件上传失败: {upload_response.status_code}")
            if upload_response.text:
                print(f"[MinerU-API] 上传失败详情: {upload_response.text}")
            return None
        
    except requests.exceptions.Timeout as e:
        print(f"[MinerU-API] 请求超时: {e}")
        return None
    except requests.exceptions.ConnectionError as e:
        print(f"[MinerU-API] 连接错误: {e}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"[MinerU-API] 请求异常: {e}")
        return None
    except Exception as e:
        print(f"[MinerU-API] 上传文件异常: {e}")
        import traceback
        print(f"[MinerU-API] 异常详情: {traceback.format_exc()}")
        return None


def poll_batch_status(batch_id: str, api_token: str) -> Tuple[str, List[Dict[str, Any]]]:
    """轮询MinerU批量任务状态 - 完全按照mineru_api.py的方法
    
    Args:
        batch_id: 批次ID
        api_token: MinerU API令牌
        
    Returns:
        tuple: (状态, 文件列表)
            状态: "completed"(全部完成), "processing"(处理中), "failed"(失败)
            文件列表: 包含文件信息的字典列表
    """
    try:
        poll_url = f"https://mineru.net/api/v4/extract-results/batch/{batch_id}"
        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json"
        }
        
        print(f"[MinerU-API] 批量轮询: {poll_url}")
        response = requests.get(poll_url, headers=headers, timeout=600)  # 10分钟超时
        print(f"[MinerU-API] 批量轮询响应: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            print(f"[MinerU-API] 批量轮询结果: {result}")
            if result.get("code") == 0 and result.get("data") and "extract_result" in result["data"]:
                extract_results = result["data"]["extract_result"]
                
                all_done = True
                completed_files = []
                failed_files = []
                
                for item in extract_results:
                    file_name = item.get("file_name", "")
                    state = item.get("state", "")
                    zip_url = item.get("full_zip_url", "")
                    error_msg = item.get("err_msg", "")
                    print(f"[MinerU-API] 文件: {file_name}, 状态: {state}, 错误: {error_msg}")
                    
                    if state == "done" and zip_url:
                        completed_files.append({
                            "file_name": file_name,
                            "zip_url": zip_url,
                            "state": state
                        })
                    elif state == "failed":
                        failed_files.append({
                            "file_name": file_name,
                            "error": error_msg or "未知错误",
                            "state": state
                        })
                    elif state not in ("done", "failed"):
                        all_done = False
                        print(f"[MinerU-API] 文件 {file_name} 仍在处理中，状态: {state}")
                
                if all_done:
                    if failed_files:
                        print(f"[MinerU-API] 处理完成，但有 {len(failed_files)} 个文件失败")
                        return "failed", failed_files
                    else:
                        print(f"[MinerU-API] 所有文件处理完成，成功 {len(completed_files)} 个")
                        return "completed", completed_files
                else:
                    print(f"[MinerU-API] 仍在处理中，已完成 {len(completed_files)} 个")
                    return "processing", completed_files + failed_files
            elif result.get("code") != 0:
                error_msg = result.get("message", "未知错误")
                print(f"[MinerU-API] API返回错误: {error_msg}")
                return "failed", [{"error": error_msg}]
            else:
                print(f"[MinerU-API] 数据格式异常: {result}")
                return "failed", []
        elif response.status_code == 401:
            print(f"[MinerU-API] 认证失败，请检查API Token")
            return "failed", [{"error": "API Token认证失败"}]
        elif response.status_code == 404:
            print(f"[MinerU-API] 批次任务不存在: {batch_id}")
            return "failed", [{"error": "批次任务不存在"}]
        else:
            print(f"[MinerU-API] 轮询失败: {response.status_code} - {response.text}")
            return "failed", [{"error": f"轮询失败: {response.status_code}"}]
    except requests.exceptions.Timeout as e:
        print(f"[MinerU-API] 轮询超时: {e}")
        return "failed", [{"error": "轮询超时"}]
    except requests.exceptions.ConnectionError as e:
        print(f"[MinerU-API] 连接错误: {e}")
        return "failed", [{"error": "网络连接错误"}]
    except requests.exceptions.RequestException as e:
        print(f"[MinerU-API] 请求异常: {e}")
        return "failed", [{"error": f"请求异常: {str(e)}"}]
    except Exception as e:
        print(f"[MinerU-API] 查询批量任务异常: {e}")
        import traceback
        print(f"[MinerU-API] 异常详情: {traceback.format_exc()}")
        return "failed", [{"error": f"查询异常: {str(e)}"}]


def download_result_file(zip_url: str, output_path: str) -> bool:
    """下载处理结果 - 完全按照mineru_api.py的方法
    
    Args:
        zip_url: ZIP文件下载URL
        output_path: 输出文件路径
        
    Returns:
        bool: 下载成功返回True，失败返回False
    """
    try:
        print(f"[MinerU-API] 开始下载结果: {zip_url}")
        print(f"[MinerU-API] 输出路径: {output_path}")
        
        with requests.get(zip_url, stream=True, timeout=600) as response:  # 10分钟超时
            print(f"[MinerU-API] 下载响应: {response.status_code}")
            
            if response.status_code == 200:
                # 检查Content-Type
                content_type = response.headers.get('Content-Type', '')
                content_length = response.headers.get('Content-Length', '0')
                print(f"[MinerU-API] 内容类型: {content_type}, 大小: {content_length} bytes")
                
                # 确保目录存在
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                
                downloaded_size = 0
                with open(output_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded_size += len(chunk)
                
                final_size = os.path.getsize(output_path)
                print(f"[MinerU-API] 下载完成: {output_path}, 最终大小: {final_size} bytes")
                
                # 验证文件是否为有效的ZIP文件
                try:
                    import zipfile
                    with zipfile.ZipFile(output_path, 'r') as zip_ref:
                        file_list = zip_ref.namelist()
                        print(f"[MinerU-API] ZIP文件验证成功，包含 {len(file_list)} 个文件")
                        for file_name in file_list[:5]:  # 只显示前5个文件名
                            print(f"[MinerU-API] ZIP内文件: {file_name}")
                        if len(file_list) > 5:
                            print(f"[MinerU-API] ...还有 {len(file_list) - 5} 个文件")
                except zipfile.BadZipFile as e:
                    print(f"[MinerU-API] 警告: 下载的文件不是有效的ZIP文件: {e}")
                    return False
                
                return True
            else:
                print(f"[MinerU-API] 下载失败: {response.status_code} - {response.text[:200]}")
                return False
    except requests.exceptions.Timeout as e:
        print(f"[MinerU-API] 下载超时: {e}")
        return False
    except requests.exceptions.ConnectionError as e:
        print(f"[MinerU-API] 下载连接错误: {e}")
        return False
    except requests.exceptions.RequestException as e:
        print(f"[MinerU-API] 下载请求异常: {e}")
        return False
    except IOError as e:
        print(f"[MinerU-API] 文件写入错误: {e}")
        return False
    except Exception as e:
        print(f"[MinerU-API] 下载异常: {e}")
        import traceback
        print(f"[MinerU-API] 异常详情: {traceback.format_exc()}")
        return False


print("[PDF处理器] 模块已加载 - MinerU API交互")


# ==================== 模块3: 内容提取 ====================

def extract_basic_info_table(content: str) -> str:
    """提取基本信息表格内容（从"# 基本信息"到"# 报告正文"之间的内容）
    
    Args:
        content: Markdown文档内容
        
    Returns:
        str: 提取的基本信息表格内容
    """
    try:
        lines = content.split('\n')
        start_idx = -1
        end_idx = len(lines)
        
        # 寻找"# 基本信息"标题
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if re.match(r'^#+\s*基本信息\s*$', line_stripped, re.IGNORECASE):
                start_idx = i
                break
            elif '基本信息' in line_stripped and line_stripped.startswith('#'):
                start_idx = i
                break
        
        if start_idx == -1:
            print("[表格提取] 未找到基本信息标题")
            return ""
        
        # 寻找"# 报告正文"标题作为结束位置
        for i, line in enumerate(lines[start_idx + 1:], start_idx + 1):
            line_stripped = line.strip()
            if re.match(r'^#+\s*报告正文\s*$', line_stripped, re.IGNORECASE):
                end_idx = i
                break
            elif '报告正文' in line_stripped and line_stripped.startswith('#'):
                end_idx = i
                break
        
        # 提取基本信息内容
        table_lines = lines[start_idx:end_idx]
        table_content = '\n'.join(table_lines).strip()
        
        print(f"[表格提取] 提取到基本信息内容，从第{start_idx + 1}行到第{end_idx}行，共{len(table_lines)}行")
        
        return table_content
        
    except Exception as e:
        print(f"[表格提取] 提取基本信息失败: {e}")
        return ""


def extract_report_content_for_nsfc(content: str) -> str:
    """提取报告正文内容：从'# 报告正文'开始到'附件信息'前的部分
    
    Args:
        content: Markdown文档内容
        
    Returns:
        str: 提取的报告正文内容
    """
    try:
        lines = content.split('\n')
        start_idx = -1
        end_idx = len(lines)
        
        # 寻找"# 报告正文"标题
        for i, line in enumerate(lines):
            line_stripped = line.strip()
            if re.match(r'^#+\s*报告正文\s*$', line_stripped, re.IGNORECASE):
                start_idx = i + 1  # 跳过标题行本身
                break
            elif '报告正文' in line_stripped and line_stripped.startswith('#'):
                start_idx = i + 1
                break
        
        if start_idx == -1:
            print("[NSFC内容提取] 未找到'报告正文'标题，使用整个文档")
            # 如果没找到报告正文，寻找第一个实质性章节
            for i, line in enumerate(lines):
                if re.match(r'^#+\s*[1-9一二三四五六七八九十]', line) or \
                   re.match(r'^#+\s*(项目|研究|背景|目标|内容|方案|创新)', line):
                    start_idx = i
                    break
            if start_idx == -1:
                start_idx = 0
        
        # 寻找结束标记：附件信息（可能有或没有#标记）
        for i, line in enumerate(lines[start_idx:], start_idx):
            line_stripped = line.strip()
            # 匹配以#开头的附件信息标题
            if re.match(r'^#+\s*附件信息', line_stripped, re.IGNORECASE):
                end_idx = i
                break
            # 匹配独立行的附件信息（没有#标记）
            elif re.match(r'^附件信息\s*$', line_stripped, re.IGNORECASE):
                end_idx = i
                break
            # 匹配包含附件信息的行（更宽泛的匹配）
            elif '附件信息' in line_stripped and len(line_stripped) <= 20:
                end_idx = i
                break
        
        # 提取报告正文内容
        report_lines = lines[start_idx:end_idx]
        report_content = '\n'.join(report_lines).strip()
        
        print(f"[NSFC内容提取] 提取到报告正文内容，从第{start_idx + 1}行到第{end_idx}行，共{len(report_lines)}行")
        print(f"[NSFC内容提取] 内容长度: {len(report_content)} 字符")
        
        return report_content
        
    except Exception as e:
        print(f"[NSFC内容提取] 提取报告正文失败: {e}")
        return content  # 失败时返回原内容


def extract_key_content(md_content: str) -> Optional[str]:
    """提取重要内容 - 使用TitleEnhancer
    
    Args:
        md_content: Markdown内容
        
    Returns:
        str: 提取的重要内容，失败返回None
    """
    try:
        important_content = TitleEnhancer.extract_important_content(md_content)
        
        if important_content and len(important_content.strip()) > 0:
            smart_print(f"[重要内容提取] 成功，长度: {len(important_content)}", LogLevel.INFO)
            return important_content
        else:
            smart_print(f"[重要内容提取] 未找到重要内容", LogLevel.WARNING)
            return None
        
    except Exception as e:
        smart_print(f"[重要内容提取] 错误: {e}", LogLevel.ERROR)
        return None


def enhance_title(md_content: str) -> Optional[str]:
    """优化标题 - 使用TitleEnhancer
    
    Args:
        md_content: Markdown内容
        
    Returns:
        str: 优化后的内容，失败返回None
    """
    try:
        optimized_content = TitleEnhancer.optimize_headers_with_extractor(md_content)
        
        if optimized_content and len(optimized_content.strip()) > 0:
            smart_print(f"[标题优化] 成功", LogLevel.INFO)
            return optimized_content
        else:
            smart_print(f"[标题优化] 失败", LogLevel.WARNING)
            return None
        
    except Exception as e:
        smart_print(f"[标题优化] 错误: {e}", LogLevel.ERROR)
        return None


print("[PDF处理器] 模块已加载 - 内容提取")


# ==================== 模块4: LLM处理 ====================

def process_nsfc_content_with_llm(content: str, api_key: str, task_check_func=None, user_id: int = None) -> dict:
    """使用SiliconFlow LLM处理国自然申请书内容提取结构化信息
    
    Args:
        content: 要处理的内容
        api_key: SiliconFlow API密钥
        task_check_func: 可选的任务检查函数，如果返回True则中断处理
        user_id: 用户ID（用于获取分组模型配置）
    """
    try:
        # 首先测试API密钥
        print(f"[NSFC LLM处理] 测试API密钥...")
        if not test_siliconflow_api(api_key):
            print(f"[NSFC LLM处理] API密钥测试失败")
            return {'success': False, 'error': 'API密钥无效或网络连接失败'}
        
        print(f"[NSFC LLM处理] API密钥测试成功")
        
        # SiliconFlow API配置 - 动态获取模型名称（从用户分组配置）
        api_url = "https://api.siliconflow.cn/v1/chat/completions"
        default_model = "Qwen/Qwen3-30B-A3B-Instruct-2507"
        
        # 尝试从用户分组获取配置的模型
        model_name = default_model
        if user_id:
            try:
                user_model = get_user_siliconflow_model(user_id)
                if user_model:
                    model_name = user_model
                    print(f"[NSFC正文LLM处理] 使用用户分组配置的模型: {model_name}")
                else:
                    print(f"[NSFC正文LLM处理] 用户未配置模型，使用默认模型: {model_name}")
            except Exception as e:
                print(f"[NSFC正文LLM处理] 获取用户模型配置失败，使用默认模型: {e}")
        else:
            print(f"[NSFC正文LLM处理] 未提供用户ID，使用默认模型: {model_name}")
        
        # 构建系统提示（平衡保持原文 + 语义理解）
        system_prompt = """请将国家自然科学基金申请书内容转换为嵌套JSON格式。

要求：
1. 对于已有的Markdown标题（以#开头的行），严格保持原文的标题和编号，完全不要修改，除非遇到类似于"# 无"的情况，将其视为正文内容
2. 对于正文中的编号内容（如"1.1 研究内容"等），通过语义判断其性质：
   - 如果是章节标题（独立成行，内容简短），保持其编号格式作为JSON键名
   - 如果是列举项目（在段落中，后面跟详细描述），保持原始文本格式
   - 严格保留编号
3. 按照文档的层级结构构建嵌套JSON，严格保留编号
4. 标题和编号作为JSON的键名，对应的正文内容作为值
5. 通过上下文判断真正的章节分界，避免将段落中的编号误认为标题
6. 保持原有的编号体系和文档结构不变，但隐藏"#"

只返回JSON格式结果。"""

        # 构建用户提示
        user_prompt = f"请分析以下国家自然科学基金申请书内容，提取关键信息并转换为结构化JSON：\n\n{content}"
        
        # API请求数据
        request_data = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user", 
                    "content": user_prompt
                }
            ],
            "temperature": 0.1,  # 低温度确保输出稳定
            "max_tokens": 4096,  
            "stream": False
        }
        
        # 设置请求头
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        print(f"[NSFC LLM处理] 开始调用SiliconFlow API，模型: {model_name}")
        print(f"[NSFC LLM处理] 输入内容长度: {len(content)} 字符")
        
        # 检查内容长度，根据长度动态调整处理策略
        max_content_length = 25000  # 增加到25000字符，支持更长的文档
        processing_mode = "standard"  # 标准模式
        
        if len(content) > max_content_length:
            # 超长内容智能截断：保留完整段落
            truncated_content = content[:max_content_length]
            last_newline = truncated_content.rfind('\n')
            if last_newline > max_content_length * 0.8:  # 如果最后一个换行位置合理
                content = truncated_content[:last_newline]
            else:
                content = truncated_content
            user_prompt = f"请分析以下国家自然科学基金申请书内容，提取关键信息并转换为结构化JSON（内容已截断到前{len(content)}字符，请根据可用信息进行分析）：\n\n{content}"
            print(f"[NSFC LLM处理] 内容过长，已智能截断到 {len(content)} 字符")
            processing_mode = "truncated"
        elif len(content) > 15000:
            # 中长内容：使用标准处理
            user_prompt = f"请分析以下国家自然科学基金申请书内容，提取关键信息并转换为结构化JSON：\n\n{content}"
            processing_mode = "long"
        else:
            # 短内容：快速处理
            user_prompt = f"请分析以下国家自然科学基金申请书内容，提取关键信息并转换为结构化JSON：\n\n{content}"
            processing_mode = "short"
        
        print(f"[NSFC LLM处理] 处理模式: {processing_mode}，内容长度: {len(content)} 字符")
        
        # 根据内容长度动态调整重试策略
        if processing_mode == "truncated":
            max_retries = 3  # 超长内容增加重试次数
            retry_delay = 15  # 增加重试间隔
            timeout_duration = 600  # 10分钟超时
        elif processing_mode == "long":
            max_retries = 3  # 长内容适当重试
            retry_delay = 12
            timeout_duration = 600  # 10分钟超时
        else:
            max_retries = 2  # 短内容快速重试
            retry_delay = 8
            timeout_duration = 600  # 10分钟超时
        
        for attempt in range(max_retries):
            # 在每次重试前检查任务是否被取消
            if task_check_func and task_check_func():
                print(f"[NSFC LLM处理] 任务已被取消，中断API调用")
                return {'success': False, 'error': '任务已被取消', 'cancelled': True}
            
            try:
                if attempt > 0:
                    print(f"[NSFC LLM处理] 第{attempt + 1}次重试（{processing_mode}模式）...")
                    time.sleep(retry_delay)
                
                print(f"[NSFC LLM处理] 发送API请求（超时设置: {timeout_duration}秒）...")
                response = requests.post(
                    api_url,
                    json=request_data,
                    headers=headers,
                    timeout=timeout_duration  # 动态超时时间
                )
                
                print(f"[NSFC LLM处理] API请求完成，状态码: {response.status_code}")
                # 如果请求成功，跳出重试循环
                break
                
            except requests.exceptions.Timeout:
                print(f"[NSFC LLM处理] 第{attempt + 1}次请求超时（{timeout_duration}秒）")
                if attempt == max_retries - 1:
                    print(f"[NSFC LLM处理] 经过{max_retries}次尝试后仍然超时")
                    error_msg = f'API请求超时（{processing_mode}模式，{timeout_duration}秒），请尝试处理较短的内容'
                    return {'success': False, 'error': error_msg}
                else:
                    print(f"[NSFC LLM处理] 准备{retry_delay}秒后重试...")
                    continue
            except requests.exceptions.ConnectionError:
                print(f"[NSFC LLM处理] 第{attempt + 1}次连接错误")
                if attempt == max_retries - 1:
                    return {'success': False, 'error': '网络连接失败，请检查网络连接'}
                else:
                    print(f"[NSFC LLM处理] 连接错误，准备{retry_delay}秒后重试...")
                    time.sleep(retry_delay)
                    continue
            except requests.exceptions.RequestException as e:
                print(f"[NSFC LLM处理] 第{attempt + 1}次网络错误: {e}")
                if attempt == max_retries - 1:
                    print(f"[NSFC LLM处理] 网络请求错误: {e}")
                    return {'success': False, 'error': f'网络请求失败: {str(e)}'}
                else:
                    print(f"[NSFC LLM处理] 准备{retry_delay}秒后重试...")
                    time.sleep(retry_delay)
                    continue
        
        # 检查响应状态
        if response.status_code != 200:
            error_msg = f"API请求失败，状态码: {response.status_code}"
            print(f"[NSFC LLM处理] {error_msg}")
            try:
                error_detail = response.json()
                print(f"[NSFC LLM处理] 错误详情: {error_detail}")
                error_msg += f", 详情: {error_detail}"
            except:
                print(f"[NSFC LLM处理] 响应内容: {response.text[:500]}...")
                error_msg += f", 响应: {response.text[:200]}"
            return {'success': False, 'error': error_msg, 'processing_mode': processing_mode}
        
        # 解析响应
        try:
            response_data = response.json()
            print(f"[NSFC LLM处理] API响应成功（{processing_mode}模式）")
        except json.JSONDecodeError as e:
            print(f"[NSFC LLM处理] API响应JSON解析失败: {e}")
            return {'success': False, 'error': f'API响应格式错误: {str(e)}', 'processing_mode': processing_mode}
        
        # 提取LLM生成的内容
        if 'choices' in response_data and len(response_data['choices']) > 0:
            llm_output = response_data['choices'][0]['message']['content'].strip()
            print(f"[NSFC LLM处理] LLM输出长度: {len(llm_output)}")
            
            # 尝试解析JSON
            try:
                # 清理可能的markdown代码块标记
                if llm_output.startswith('```json'):
                    llm_output = llm_output[7:]
                if llm_output.startswith('```'):
                    llm_output = llm_output[3:]
                if llm_output.endswith('```'):
                    llm_output = llm_output[:-3]
                
                llm_output = llm_output.strip()
                
                # 解析JSON
                json_data = json.loads(llm_output)
                print(f"[NSFC LLM处理] JSON解析成功，包含 {len(json_data)} 个顶级字段")
                
                return {
                    'success': True,
                    'json_data': json_data,
                    'raw_output': llm_output,
                    'processing_mode': processing_mode
                }
                
            except json.JSONDecodeError as e:
                print(f"[NSFC LLM处理] JSON解析失败: {e}")
                print(f"[NSFC LLM处理] 原始输出: {llm_output[:500]}...")
                
                # 尝试修复JSON - 查找最后一个完整的JSON对象
                try:
                    # 寻找最后一个完整的 } 来修复截断的JSON
                    last_brace = llm_output.rfind('}')
                    if last_brace > 0:
                        # 从开始到最后一个}的内容
                        fixed_json = llm_output[:last_brace + 1]
                        json_data = json.loads(fixed_json)
                        print(f"[NSFC LLM处理] JSON修复成功")
                        return {
                            'success': True,
                            'json_data': json_data,
                            'raw_output': llm_output,
                            'fixed': True,
                            'processing_mode': processing_mode
                        }
                except json.JSONDecodeError:
                    print(f"[NSFC LLM处理] JSON修复失败")
                
                return {
                    'success': False,
                    'error': f'JSON解析失败: {str(e)}',
                    'raw_output': llm_output[:1000] + ('...' if len(llm_output) > 1000 else ''),
                    'processing_mode': processing_mode
                }
        else:
            print(f"[NSFC LLM处理] API响应格式异常: {response_data}")
            return {'success': False, 'error': 'API响应格式异常', 'processing_mode': processing_mode}
    
    except Exception as e:
        print(f"[NSFC LLM处理] 处理异常: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': f'处理异常: {str(e)}', 'processing_mode': 'unknown'}


def process_table_with_llm(table_content: str, api_key: str, task_check_func=None, user_id: int = None) -> dict:
    """使用SiliconFlow LLM处理表格内容转JSON
    
    Args:
        table_content: 要处理的表格内容
        api_key: SiliconFlow API密钥
        task_check_func: 可选的任务检查函数，如果返回True则中断处理
        user_id: 用户ID（用于获取分组模型配置）
    """
    try:
        # 动态获取模型名称（从用户分组配置）
        # SiliconFlow API配置 - 恢复使用Qwen3-30B模型，优化指令和参数
        api_url = "https://api.siliconflow.cn/v1/chat/completions"
        default_model = "Qwen/Qwen3-30B-A3B-Instruct-2507"
        
        # 尝试从用户分组获取配置的模型
        model_name = default_model
        if user_id:
            try:
                user_model = get_user_siliconflow_model(user_id)
                if user_model:
                    model_name = user_model
                    print(f"[表格LLM处理] 使用用户分组配置的模型: {model_name}")
                else:
                    print(f"[表格LLM处理] 用户未配置模型，使用默认模型: {model_name}")
            except Exception as e:
                print(f"[表格LLM处理] 获取用户模型配置失败，使用默认模型: {e}")
        else:
            print(f"[表格LLM处理] 未提供用户ID，使用默认模型: {model_name}")
        
        # 构建优化的系统提示（针对表格理解特别优化）
        system_prompt = """你是一个专业的表格数据分析专家，专门负责将国家自然科学基金申请书的基本信息表格转换为结构化JSON格式。

## 核心任务：
精确提取表格中的所有字段和值，转换为清晰的JSON结构。

## 处理原则：
1. **完整性**：提取表格中所有有意义的信息，不遗漏
2. **准确性**：字段名称和值必须与原表格完全对应
3. **结构化**：按照逻辑关系将字段分组归类
4. **标准化**：使用规范的中文键名，确保JSON格式正确

## 分组规则：
- "项目基本信息"：项目名称、申请代码、研究期限、申请金额等
- "申请人信息"：姓名、性别、出生日期、学位、职称等  
- "工作单位信息"：单位名称、通讯地址、邮政编码等
- "依托单位信息"：依托单位名称、组织机构代码等

## 输出格式：
严格的JSON格式，不包含任何解释文字或markdown标记。

## 示例结构：
{
  "项目基本信息": {
    "项目名称": "具体项目名称",
    "申请代码": "具体申请代码",
    "研究期限": "起止时间"
  },
  "申请人信息": {
    "姓名": "申请人姓名",
    "性别": "男/女",
    "出生日期": "具体日期"
  }
}"""

        # 构建精确的用户提示
        user_prompt = f"""请将以下国家自然科学基金申请书基本信息表格转换为JSON格式：

表格内容：
{table_content}

要求：
1. 提取所有字段和对应的值
2. 按逻辑关系分组
3. 使用中文键名
4. 输出标准JSON格式
5. 不要包含任何解释、说明文字或标签

请直接输出JSON结果："""
        
        # API请求数据（优化参数配置）
        request_data = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user", 
                    "content": user_prompt
                }
            ],
            "temperature": 0.1,  # 降低温度提高准确性和一致性
            "max_tokens": 2500,  # 充足的输出长度
            "top_p": 0.9,       # 添加top_p参数提高输出质量
            "stream": False
        }
        
        # 设置请求头
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        print(f"[LLM处理] 开始调用SiliconFlow API，模型: {model_name}")
        
        # 发送API请求（优化重试策略）
        max_retries = 2  # 合理的重试次数
        retry_delay = 5   # 重试间隔
        
        for attempt in range(max_retries):
            # 在每次重试前检查任务是否被取消
            if task_check_func and task_check_func():
                print(f"[LLM处理] 任务已被取消，中断API调用")
                return {'success': False, 'error': '任务已被取消', 'cancelled': True}
            
            try:
                if attempt > 0:
                    print(f"[LLM处理] 第{attempt + 1}次重试...")
                    time.sleep(retry_delay)
                
                response = requests.post(
                    api_url,
                    json=request_data,
                    headers=headers,
                    timeout=600  # 10分钟超时
                )
                
                # 如果请求成功，跳出重试循环
                break
                
            except requests.exceptions.Timeout:
                if attempt == max_retries - 1:
                    print(f"[LLM处理] 经过{max_retries}次尝试后仍然超时（推理模型需要更多分析时间）")
                    print("[LLM处理] 建议：1.简化表格内容 2.分段处理 3.稍后重试")
                    return {'error': 'API请求超时，推理模型分析时间较长，建议简化内容'}
                else:
                    print(f"[LLM处理] 第{attempt + 1}次请求超时，推理模型分析中，准备重试...")
                    continue
            except requests.exceptions.RequestException as e:
                if attempt == max_retries - 1:
                    print(f"[LLM处理] 网络请求错误: {e}")
                    return {'error': f'网络请求失败: {str(e)}'}
                else:
                    print(f"[LLM处理] 第{attempt + 1}次请求失败，准备重试: {e}")
                    continue
        
        if response.status_code != 200:
            error_msg = f"API请求失败，状态码: {response.status_code}"
            if response.text:
                error_msg += f"，错误信息: {response.text}"
            print(f"[LLM处理] {error_msg}")
            return {'error': error_msg}
        
        # 解析API响应
        response_data = response.json()
        
        if 'choices' not in response_data or not response_data['choices']:
            return {'error': 'API响应格式错误：缺少choices字段'}
        
        # 提取AI生成的内容
        ai_content = response_data['choices'][0]['message']['content'].strip()
        
        print(f"[LLM处理] API调用成功，Qwen3-30B模型返回内容长度: {len(ai_content)}")
        
        # 尝试解析AI返回的JSON（优化解析逻辑）
        try:
            # 清理可能的格式问题
            import re
            
            # 寻找JSON内容（推理模型可能包含思考过程）
            json_match = re.search(r'\{.*\}', ai_content, re.DOTALL)
            if json_match:
                ai_content = json_match.group()
            
            # 清理可能的markdown代码块标记
            if ai_content.startswith('```json'):
                ai_content = ai_content[7:]
            if ai_content.startswith('```'):
                ai_content = ai_content[3:]
            if ai_content.endswith('```'):
                ai_content = ai_content[:-3]
            
            ai_content = ai_content.strip()
            
            # 解析JSON
            json_data = json.loads(ai_content)
            
            print(f"[LLM处理] Qwen3-30B JSON解析成功，包含{len(json_data)}个顶级字段")
            
            return {
                'success': True,
                'json_data': json_data,
                'metadata': {
                    'model_used': model_name,
                    'api_provider': 'SiliconFlow',
                    'model_type': 'Large-Language-Model',
                    'content_length': len(table_content),
                    'json_fields': len(json_data),
                    'temperature': 0.1,
                    'max_tokens': 2500,
                    'top_p': 0.9
                },
                'raw_response': ai_content
            }
            
        except json.JSONDecodeError as e:
            print(f"[LLM处理] Qwen3-30B JSON解析失败: {e}")
            print(f"[LLM处理] 模型返回内容: {ai_content[:500]}...")
            return {'error': f'模型返回的内容不是有效的JSON格式: {str(e)}'}
            
    except Exception as e:
        print(f"[LLM处理] Qwen3-30B处理过程中发生错误: {e}")
        return {'error': f'推理模型处理失败: {str(e)}'}


print("[PDF处理器] 模块已加载 - LLM处理")


# ==================== 模块5: 完整PDF处理流程 ====================

def process_single_pdf_file(file_id: str, user_id: int, mineru_api_key: str, siliconflow_api_key: str,
                            task_id: Optional[str] = None, progress_callback: Optional[Callable] = None) -> bool:
    """处理单个PDF文件的完整流程
    
    Args:
        file_id: 文件ID
        user_id: 用户ID
        mineru_api_key: MinerU API密钥
        siliconflow_api_key: SiliconFlow API密钥
        task_id: 任务ID（可选）
        progress_callback: 进度回调函数（可选）
        
    Returns:
        bool: 处理成功返回True，失败返回False
    """
    try:
        smart_print(f"[PDF处理] 开始处理文件: {file_id}", LogLevel.INFO)
        
        # 定义任务检查函数
        def check_cancelled():
            return is_task_cancelled(task_id) if task_id else False
        
        # 步骤1: 上传到MinerU
        if progress_callback:
            progress_callback(10, "上传文件到MinerU...")
        
        options = {
            "enable_formula": True,
            "language": "ch",
            "enable_table": True,
            "is_ocr": True
        }
        
        upload_result = upload_file_to_mineru(file_id, user_id, mineru_api_key, options, task_id)
        if not upload_result:
            smart_print(f"[PDF处理] 上传失败: {file_id}", LogLevel.ERROR)
            return False
        
        batch_id = upload_result['batch_id']
        smart_print(f"[PDF处理] 上传成功，批次ID: {batch_id}", LogLevel.INFO)
        
        # 步骤2: 轮询处理状态
        if progress_callback:
            progress_callback(30, "等待MinerU处理...")
        
        max_poll_attempts = 60  # 最多轮询60次
        poll_interval = 10  # 每10秒轮询一次
        
        for attempt in range(max_poll_attempts):
            if check_cancelled():
                smart_print(f"[PDF处理] 任务已取消", LogLevel.WARNING)
                return False
            
            time.sleep(poll_interval)
            
            status, results = poll_batch_status(batch_id, mineru_api_key)
            
            if status == "completed":
                smart_print(f"[PDF处理] MinerU处理完成", LogLevel.INFO)
                
                # 获取下载URL
                if not results or not results[0].get('zip_url'):
                    smart_print(f"[PDF处理] 未获取到下载URL", LogLevel.ERROR)
                    return False
                
                zip_url = results[0]['zip_url']
                break
            elif status == "failed":
                smart_print(f"[PDF处理] MinerU处理失败: {results}", LogLevel.ERROR)
                return False
            else:
                if progress_callback:
                    progress = min(30 + (attempt * 40 // max_poll_attempts), 70)
                    progress_callback(progress, f"MinerU处理中... ({attempt}/{max_poll_attempts})")
        else:
            smart_print(f"[PDF处理] 轮询超时", LogLevel.ERROR)
            return False
        
        # 步骤3: 下载并提取Markdown
        if progress_callback:
            progress_callback(75, "下载并提取Markdown...")
        
        md_content = download_and_extract_markdown_from_zip(zip_url)
        if not md_content:
            smart_print(f"[PDF处理] Markdown提取失败", LogLevel.ERROR)
            return False
        
        smart_print(f"[PDF处理] Markdown提取成功，长度: {len(md_content)}", LogLevel.INFO)
        
        # 步骤4: 保存Markdown到数据库（使用md_storage_manager）
        try:
            success = md_storage_manager.save_md_content(file_id, md_content)
            if success:
                # 更新文件状态为已完成
                update_file_status_in_db(file_id, 'completed', user_id)
                smart_print(f"[PDF处理] Markdown已保存到数据库", LogLevel.INFO)
            else:
                smart_print(f"[PDF处理] Markdown保存失败", LogLevel.ERROR)
                return False
        except Exception as e:
            smart_print(f"[PDF处理] 保存Markdown失败: {e}", LogLevel.ERROR)
            return False
        
        # 步骤5: 表格数据提取
        if progress_callback:
            progress_callback(80, "表格数据提取...")
        
        table_content = extract_basic_info_table(md_content)
        if table_content:
            table_result = process_table_with_llm(table_content, siliconflow_api_key, check_cancelled, user_id)
            if table_result.get('success'):
                json_data = table_result['json_data']
                
                # 使用update_file_extracted_json保存表格JSON
                try:
                    success = update_file_extracted_json(file_id, json_data)
                    if success:
                        smart_print(f"[PDF处理] 表格JSON已保存", LogLevel.INFO)
                    else:
                        smart_print(f"[PDF处理] 表格JSON保存失败", LogLevel.WARNING)
                except Exception as e:
                    smart_print(f"[PDF处理] 保存表格JSON失败: {e}", LogLevel.WARNING)
        
        # 步骤6: NSFC内容提取
        if progress_callback:
            progress_callback(90, "NSFC内容提取...")
        
        nsfc_content = extract_report_content_for_nsfc(md_content)
        if nsfc_content:
            nsfc_result = process_nsfc_content_with_llm(nsfc_content, siliconflow_api_key, check_cancelled, user_id)
            if nsfc_result.get('success'):
                json_data = nsfc_result['json_data']
                
                try:
                    conn = DatabaseConfig.get_db_connection()
                    if conn:
                        cursor = conn.cursor()
                        json_str = json.dumps(json_data, ensure_ascii=False, indent=2)
                        
                        # 检查JSON数据大小
                        if len(json_str) > 16 * 1024 * 1024:  # 16MB限制
                            smart_print(f"[PDF处理] NSFC JSON数据过大，将被截断", LogLevel.WARNING)
                            json_str = json_str[:16 * 1024 * 1024 - 100] + '..."数据被截断"}'
                        
                        cursor.execute("""
                            UPDATE user_files 
                            SET nsfc_json_data = %s, nsfc_json_updated_at = CURRENT_TIMESTAMP
                            WHERE file_id = %s AND user_id = %s
                        """, (json_str, file_id, user_id))
                        conn.commit()
                        conn.close()
                        smart_print(f"[PDF处理] NSFC JSON已保存", LogLevel.INFO)
                except Exception as e:
                    smart_print(f"[PDF处理] 保存NSFC JSON失败: {e}", LogLevel.WARNING)
        
        # 完成
        if progress_callback:
            progress_callback(100, "处理完成")
        
        smart_print(f"[PDF处理] 文件处理完成: {file_id}", LogLevel.INFO)
        return True
        
    except Exception as e:
        smart_print(f"[PDF处理] 处理异常: {e}", LogLevel.ERROR)
        return False


def process_multiple_pdf_files_parallel(file_list: List[Dict[str, Any]], user_id: int, 
                                        mineru_api_key: str, siliconflow_api_key: str,
                                        parent_task_id: Optional[str] = None,
                                        max_workers: int = 2) -> Dict[str, Any]:
    """并行处理多个PDF文件
    
    Args:
        file_list: 文件列表，每个元素包含file_id, filename等信息
        user_id: 用户ID
        mineru_api_key: MinerU API密钥
        siliconflow_api_key: SiliconFlow API密钥
        parent_task_id: 父任务ID（可选）
        max_workers: 最大并行数（默认2）
        
    Returns:
        dict: 包含处理结果的字典
            - total: 总文件数
            - success: 成功数量
            - failed: 失败数量
            - results: 每个文件的处理结果列表
    """
    global global_active_tasks
    
    smart_print(f"[并行处理] 开始处理 {len(file_list)} 个文件", LogLevel.INFO)
    
    results = {
        'total': len(file_list),
        'success': 0,
        'failed': 0,
        'results': []
    }
    
    # 创建线程池
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {}
        
        for file_info in file_list:
            file_id = file_info['file_id']
            filename = file_info.get('filename', 'unknown')
            
            # 创建子任务ID
            task_id = f"{parent_task_id}_{file_id}" if parent_task_id else file_id
            
            # 提交任务
            future = executor.submit(
                process_single_pdf_file,
                file_id,
                user_id,
                mineru_api_key,
                siliconflow_api_key,
                task_id,
                None  # 暂不使用进度回调
            )
            
            future_to_file[future] = {
                'file_id': file_id,
                'filename': filename,
                'task_id': task_id
            }
        
        # 等待所有任务完成
        for future in future_to_file:
            file_info = future_to_file[future]
            file_id = file_info['file_id']
            filename = file_info['filename']
            
            try:
                success = future.result()
                
                if success:
                    results['success'] += 1
                    smart_print(f"[并行处理] ✅ 文件处理成功: {filename}", LogLevel.INFO)
                else:
                    results['failed'] += 1
                    smart_print(f"[并行处理] ❌ 文件处理失败: {filename}", LogLevel.WARNING)
                
                results['results'].append({
                    'file_id': file_id,
                    'filename': filename,
                    'success': success
                })
                
            except Exception as e:
                results['failed'] += 1
                smart_print(f"[并行处理] ❌ 文件处理异常: {filename}, 错误: {e}", LogLevel.ERROR)
                results['results'].append({
                    'file_id': file_id,
                    'filename': filename,
                    'success': False,
                    'error': str(e)
                })
    
    smart_print(f"[并行处理] 全部完成，成功: {results['success']}, 失败: {results['failed']}", LogLevel.INFO)
    
    return results


print("[PDF处理器] 模块已加载 - 完整处理流程")


# ==================== 模块6: 高级API接口 ====================

class PDFProcessor:
    """PDF处理器类 - 提供高级API接口"""
    
    def __init__(self, mineru_api_key: str, siliconflow_api_key: str):
        """初始化PDF处理器
        
        Args:
            mineru_api_key: MinerU API密钥
            siliconflow_api_key: SiliconFlow API密钥
        """
        self.mineru_api_key = mineru_api_key
        self.siliconflow_api_key = siliconflow_api_key
        smart_print("[PDF处理器] 初始化完成", LogLevel.INFO)
    
    def process_file(self, file_id: str, user_id: int, task_id: Optional[str] = None) -> bool:
        """处理单个文件
        
        Args:
            file_id: 文件ID
            user_id: 用户ID
            task_id: 任务ID（可选）
            
        Returns:
            bool: 处理成功返回True
        """
        return process_single_pdf_file(
            file_id, 
            user_id, 
            self.mineru_api_key, 
            self.siliconflow_api_key,
            task_id
        )
    
    def process_files_parallel(self, file_list: List[Dict[str, Any]], user_id: int,
                              parent_task_id: Optional[str] = None) -> Dict[str, Any]:
        """并行处理多个文件
        
        Args:
            file_list: 文件列表
            user_id: 用户ID
            parent_task_id: 父任务ID（可选）
            
        Returns:
            dict: 处理结果
        """
        return process_multiple_pdf_files_parallel(
            file_list,
            user_id,
            self.mineru_api_key,
            self.siliconflow_api_key,
            parent_task_id,
            max_workers=GLOBAL_MAX_PARALLEL_TASKS
        )
    
    def extract_table(self, md_content: str, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """从Markdown中提取表格数据
        
        Args:
            md_content: Markdown内容
            user_id: 用户ID（可选）
            
        Returns:
            dict: 提取的JSON数据，失败返回None
        """
        table_content = extract_basic_info_table(md_content)
        if not table_content:
            return None
        
        result = process_table_with_llm(table_content, self.siliconflow_api_key, None, user_id)
        return result.get('json_data') if result.get('success') else None
    
    def extract_nsfc(self, md_content: str, user_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """从Markdown中提取NSFC内容
        
        Args:
            md_content: Markdown内容
            user_id: 用户ID（可选）
            
        Returns:
            dict: 提取的JSON数据，失败返回None
        """
        nsfc_content = extract_report_content_for_nsfc(md_content)
        if not nsfc_content:
            return None
        
        result = process_nsfc_content_with_llm(nsfc_content, self.siliconflow_api_key, None, user_id)
        return result.get('json_data') if result.get('success') else None


print("[PDF处理器] 模块已加载 - 高级API接口")
print("[PDF处理器] ✅ 所有模块加载完成")
print("[PDF处理器] 版本: 1.0.0")
print("[PDF处理器] 功能: MinerU集成 + LLM智能提取 + 并行处理")
