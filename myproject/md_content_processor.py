"""
MD内容分离与处理模块
用于将Markdown文档分离为表格和正文两部分，并提供独立的LLM处理功能
包含JSON结构硬编码补救函数
支持VLM（视觉语言模型）直接从PDF图片提取表格信息
"""
import re
import json
import requests
import time
import base64
import tempfile
import os
from json_repair import repair_json


# ==================== VLM 服务器配置 ====================

# 本地 vLLM 服务器（VLM - 视觉模型，首选）
# Qwen2.5-VL-7B，max_model_len=20024
LOCAL_VLM_CONFIG = {
    "api_url": "http://172.16.135.211:60606/v1/chat/completions",
    "metrics_url": "http://172.16.135.211:60606/metrics",
    "models_url": "http://172.16.135.211:60606/v1/models",
    "model": "Qwen2.5-VL-7B",
    "max_tokens": 3000,
    "dpi": 200,
    "needs_api_key": False,
    "name": "本地VLM服务器(7B)",
}

# 硅基流动 API（VLM备用）
SILICONFLOW_VLM_CONFIG = {
    "api_url": "https://api.siliconflow.cn/v1/chat/completions",
    "model": "Qwen/Qwen2.5-VL-72B-Instruct",
    "max_tokens": 4000,
    "dpi": 150,
    "needs_api_key": True,
    "name": "硅基流动API",
}

# ==================== 本地 LLM（纯文本模型）配置 ====================

# 本地 vLLM 服务器（LLM - 纯文本模型）
# 注意：模型名以 vLLM 实际加载的名称为准，可通过 /v1/models 接口确认
LOCAL_LLM_CONFIG = {
    "api_url": "http://222.193.29.85:60687/v1/chat/completions",
    "models_url": "http://222.193.29.85:60687/v1/models",
    "metrics_url": "http://222.193.29.85:60687/metrics",
    "model": "Qwen2.5-32B",
    "max_tokens": 6000,
    "needs_api_key": False,
    "name": "本地LLM服务器",
}

# ==================== 本地模型全局并发控制 ====================
import threading

# 本地LLM (Qwen2.5-32B) 串行信号量
# 本地LLM在并发请求下容易超时，强制串行以提升稳定性。
_local_llm_semaphore = threading.Semaphore(1)

# 本地VLM (Qwen2.5-VL-7B) 并发信号量
# GPU KV cache: num_gpu_blocks=1257, block_size=16, 总容量=20112 tokens
# 每个请求平均 ~5800 tokens (~363 blocks)
# 2并发 × 363 blocks = 726 blocks，安全
_local_vlm_semaphore = threading.Semaphore(2)


def _is_local_llm(api_url):
    """判断是否为本地LLM（需要并发控制）"""
    return api_url == LOCAL_LLM_CONFIG["api_url"]


def _is_local_vlm(api_url):
    """判断是否为本地VLM（需要并发控制）"""
    return api_url == LOCAL_VLM_CONFIG["api_url"]


def _check_local_vlm_available():
    """检查本地VLM服务器是否可用，并打印运行状态
    
    Returns:
        bool: True=可用, False=不可用
    """
    try:
        resp = requests.get(LOCAL_VLM_CONFIG["models_url"], timeout=5)
        if resp.status_code != 200:
            print(f"[VLM状态] ❌ 本地服务器不可用 (HTTP {resp.status_code})")
            return False
        
        models_data = resp.json()
        model_list = [m.get("id") for m in models_data.get("data", [])]
        if LOCAL_VLM_CONFIG["model"] not in model_list:
            print(f"[VLM状态] ❌ 本地服务器模型 {LOCAL_VLM_CONFIG['model']} 不存在，可用模型: {model_list}")
            return False
        
        # 获取 max_model_len
        model_info = models_data["data"][0]
        max_model_len = model_info.get("max_model_len", "未知")
        
        # 尝试获取运行指标
        running = waiting = gpu_usage = "N/A"
        try:
            metrics_resp = requests.get(LOCAL_VLM_CONFIG["metrics_url"], timeout=3)
            if metrics_resp.status_code == 200:
                for line in metrics_resp.text.split('\n'):
                    if line.startswith('vllm:num_requests_running{'):
                        running = line.split()[-1].replace('.0', '')
                    elif line.startswith('vllm:num_requests_waiting{'):
                        waiting = line.split()[-1].replace('.0', '')
                    elif line.startswith('vllm:gpu_cache_usage_perc{'):
                        gpu_val = float(line.split()[-1])
                        gpu_usage = f"{gpu_val * 100:.1f}%"
        except Exception:
            pass
        
        print(f"[VLM状态] ✅ 本地服务器可用")
        print(f"[VLM状态]   模型: {LOCAL_VLM_CONFIG['model']}  |  上下文长度: {max_model_len}")
        print(f"[VLM状态]   运行中: {running}  |  排队中: {waiting}  |  GPU缓存: {gpu_usage}")
        return True
        
    except requests.exceptions.ConnectionError:
        print(f"[VLM状态] ❌ 本地服务器无法连接 ({LOCAL_VLM_CONFIG['api_url']})")
        return False
    except requests.exceptions.Timeout:
        print(f"[VLM状态] ❌ 本地服务器连接超时")
        return False
    except Exception as e:
        print(f"[VLM状态] ❌ 本地服务器检查异常: {e}")
        return False


def _check_local_llm_available():
    """检查本地LLM（纯文本模型）服务器是否可用
    
    Returns:
        bool: True=可用, False=不可用
    """
    try:
        resp = requests.get(LOCAL_LLM_CONFIG["models_url"], timeout=5)
        if resp.status_code != 200:
            print(f"[LLM状态] ❌ 本地LLM服务器不可用 (HTTP {resp.status_code})")
            return False
        
        models_data = resp.json()
        model_list = [m.get("id") for m in models_data.get("data", [])]
        
        # 检查是否有纯文本LLM模型（非VL模型）
        target_model = LOCAL_LLM_CONFIG["model"]
        if target_model in model_list:
            print(f"[LLM状态] ✅ 本地LLM可用: {target_model}")
            return True
        
        # 模糊匹配：vLLM可能加载为不同名称
        for m in model_list:
            if 'Qwen2.5' in m and '32B' in m and 'VL' not in m:
                print(f"[LLM状态] ✅ 本地LLM可用（模糊匹配）: {m}")
                LOCAL_LLM_CONFIG["model"] = m  # 自动修正模型名
                return True
        
        print(f"[LLM状态] ❌ 本地LLM模型 {target_model} 不存在，可用模型: {model_list}")
        return False
        
    except requests.exceptions.ConnectionError:
        print(f"[LLM状态] ❌ 本地LLM服务器无法连接 ({LOCAL_LLM_CONFIG['api_url']})")
        return False
    except requests.exceptions.Timeout:
        print(f"[LLM状态] ❌ 本地LLM服务器连接超时")
        return False
    except Exception as e:
        print(f"[LLM状态] ❌ 本地LLM服务器检查异常: {e}")
        return False


def _get_llm_config(api_key=None, model_name=None):
    """根据模型名称判断使用本地LLM还是硅基流动API
    
    Args:
        api_key: 硅基流动API密钥（可选）
        model_name: 模型名称，若以 'local:' 开头则使用本地LLM
    
    Returns:
        tuple: (api_url, headers, actual_model_name, server_name)
    """
    # 检查是否配置为使用本地LLM
    use_local = False
    if model_name and model_name.startswith('local:'):
        # 显式指定本地模型，格式: "local:Qwen2.5-32B"
        local_model = model_name[6:]  # 去掉 "local:" 前缀
        if _check_local_llm_available():
            use_local = True
            actual_model = local_model or LOCAL_LLM_CONFIG["model"]
        else:
            print(f"[LLM配置] ⚠️ 指定本地LLM但服务器不可用，回退到硅基流动")
    
    if use_local:
        api_url = LOCAL_LLM_CONFIG["api_url"]
        headers = {"Content-Type": "application/json"}
        server_name = LOCAL_LLM_CONFIG["name"]
        print(f"[LLM配置] → 使用本地LLM: {actual_model}")
        return api_url, headers, actual_model, server_name
    else:
        # 使用硅基流动API
        api_url = "https://api.siliconflow.cn/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        actual_model = model_name if model_name and not model_name.startswith('local:') else "Qwen/Qwen3-30B-A3B-Instruct-2507"
        server_name = "硅基流动API"
        print(f"[LLM配置] → 使用硅基流动: {actual_model}")
        return api_url, headers, actual_model, server_name


def _get_llm_request_timeout(api_url):
    """获取LLM请求超时时间（秒）

    本地LLM在长文档提取时推理耗时更久，超时放宽到900秒；
    远端API保持300秒。
    """
    return 900 if _is_local_llm(api_url) else 300


def _compute_dynamic_max_tokens(input_text, api_url, fallback_max_tokens=4000):
    """根据输入长度动态计算max_tokens上限。

    规则：
    - 输入越长，允许输出上限越高；
    - 本地LLM上限不超过 LOCAL_LLM_CONFIG["max_tokens"]；
    - 远端API默认上限不超过 fallback_max_tokens。
    """
    text = input_text or ""
    # 粗略估算：中文约2字符/Token，英文约4字符/Token，取中间值保守估计。
    estimated_input_tokens = max(1, len(text) // 3)
    dynamic_cap = int(estimated_input_tokens * 0.8) + 1200

    if _is_local_llm(api_url):
        upper_bound = int(LOCAL_LLM_CONFIG.get("max_tokens", 6000))
    else:
        upper_bound = int(fallback_max_tokens)

    return max(1200, min(dynamic_cap, upper_bound))


def _print_vlm_usage_after_call(resp_data, server_name):
    """API调用后打印token使用信息"""
    usage = resp_data.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", prompt_tokens + completion_tokens)
    print(f"[VLM用量] 服务器: {server_name}  |  "
          f"输入: {prompt_tokens} tokens  |  输出: {completion_tokens} tokens  |  "
          f"总计: {total_tokens} tokens")


# ==================== VLM表格提取相关 ====================

# VLM表格提取专用提示词（逐页版本，仅输出Markdown）
# 本地VLM更稳定地产生Markdown，后续交给本地LLM做结构化JSON提取。
VLM_TABLE_EXTRACTION_PROMPT = """你是专业的NSFC申请书PDF信息提取助手。仔细看这张国家自然科学基金申请书PDF页面图片。

【任务】
将当前页所有可见内容完整转为Markdown格式。

要求：
1. 表格必须使用标准Markdown表格语法：| 列1 | 列2 | 并包含分隔行 |---|---|
2. 标题使用 # / ## / ### 层级
3. 保留原文，不得编造，不得遗漏
4. 只输出Markdown，不要输出JSON，不要输出解释文字

【输出格式】
只输出一个markdown代码块，禁止输出其他内容：

```markdown
（此处放Markdown）
```"""


def _parse_vlm_dual_output(text: str) -> dict:
    """解析VLM输出（仅Markdown）
    
    兼容历史格式：若返回中包含markdown代码块则提取代码块，否则提取正文文本。
    
    Args:
        text: VLM返回的完整文本
        
    Returns:
        dict: {'json_data': None, 'md_content': str}
    """
    md_content = ''
    
    # 提取 ```markdown ... ``` 块
    md_block_match = re.search(r'```markdown\s*\n(.*?)```', text, re.DOTALL)
    if md_block_match:
        md_content = md_block_match.group(1).strip()
        print(f"[VLM解析] ✅ Markdown块提取成功，{len(md_content)} 字符")
    else:
        # 没有markdown代码块时，清理围栏后直接作为Markdown正文
        cleaned = text.strip()
        cleaned = re.sub(r'^```\w*\s*\n?', '', cleaned)
        cleaned = re.sub(r'\n?```\s*$', '', cleaned)
        if len(cleaned) > 20:
            md_content = cleaned
            print(f"[VLM解析] ✅ 直接文本作为MD内容，{len(md_content)} 字符")
    
    return {'json_data': None, 'md_content': md_content}


def call_vlm_for_table_extraction(pdf_data, api_key=None, task_check_func=None, progress_callback=None):
    """
    使用VLM（视觉语言模型）从PDF前几页逐页提取NSFC基本信息表JSON+Markdown
    
    **优先使用本地vLLM服务器**，不可用时自动回退到硅基流动API。
    
    **逐页模式**：每页单独调用一次VLM API，每页同时输出JSON和Markdown两种格式，
    最后合并所有页的JSON为完整结构，拼接所有页的Markdown用于替换MinerU残缺内容。
    
    Args:
        pdf_data: PDF文件二进制数据（bytes）
        api_key: 硅基流动API密钥（可选，仅在回退到硅基流动时需要）
        task_check_func: 任务检查函数，返回True时中断
        progress_callback: 进度回调函数 callback(progress, message)，progress∈[0,100]
        
    Returns:
        dict: {
            'success': True/False,
            'json_data': {...},           # 合并后的完整JSON
            'vlm_md_content': str,        # 拼接后的前N页Markdown内容
            'server': str,                # 使用的服务器名称
            'error': '...'
        }
    """
    MAX_TABLE_PAGES = 3  # NSFC基本信息表通常在前3页
    
    # 选择VLM服务器：优先本地，不可用时回退硅基流动
    print(f"[VLM表格提取] ========== VLM服务器选择 ==========")
    local_available = _check_local_vlm_available()
    
    if local_available:
        vlm_config = LOCAL_VLM_CONFIG
        print(f"[VLM表格提取] → 使用本地vLLM服务器")
    elif api_key:
        vlm_config = SILICONFLOW_VLM_CONFIG
        print(f"[VLM表格提取] → 本地不可用，回退到硅基流动API")
    else:
        print(f"[VLM表格提取] ❌ 本地服务器不可用，且未配置硅基流动API密钥")
        return {'success': False, 'error': '本地VLM服务器不可用，且未配置硅基流动API密钥'}
    
    VLM_MODEL = vlm_config["model"]
    API_URL = vlm_config["api_url"]
    DPI = vlm_config["dpi"]
    MAX_TOKENS = vlm_config["max_tokens"]
    SERVER_NAME = vlm_config["name"]
    
    print(f"[VLM表格提取] 模型: {VLM_MODEL}  |  DPI: {DPI}  |  max_tokens: {MAX_TOKENS}")
    print(f"[VLM表格提取] =====================================")
    
    try:
        import fitz  # type: ignore[import]
    except ImportError:
        return {'success': False, 'error': 'PyMuPDF (fitz) 未安装，无法使用VLM表格提取'}
    
    def _render_pdf_pages(config):
        """渲染PDF前N页为base64图片列表"""
        _dpi = config["dpi"]
        _server_name = config["name"]
        
        tmp_path = None
        page_images = []
        try:
            with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp:
                tmp.write(pdf_data)
                tmp_path = tmp.name
            
            doc = fitz.open(tmp_path)
            total_pages = min(doc.page_count, MAX_TABLE_PAGES)
            print(f"[VLM表格提取] PDF共 {doc.page_count} 页，渲染前 {total_pages} 页 (DPI={_dpi})")
            
            if task_check_func and task_check_func():
                doc.close()
                return None  # 已取消
            
            for page_idx in range(total_pages):
                page = doc[page_idx]
                zoom = _dpi / 72.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat)
                img_bytes = pix.tobytes("png")
                b64_str = base64.b64encode(img_bytes).decode("utf-8")
                page_images.append((page_idx + 1, b64_str))
                print(f"[VLM表格提取]   第 {page_idx + 1} 页渲染完成，图片大小: {len(img_bytes):,} bytes")
                if progress_callback:
                    render_pct = int(15 * (page_idx + 1) / total_pages)
                    progress_callback(render_pct, f'🔍 表格识别：渲染第 {page_idx + 1}/{total_pages} 页...')
            
            doc.close()
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
        
        return page_images
    
    def _vlm_single_page_call(page_num, b64_str, _model, _api_url, _headers, _max_tokens, _server_name):
        """单页VLM API调用，返回原始文本输出"""
        messages = [{
            "role": "user",
            "content": [
                {"type": "text", "text": VLM_TABLE_EXTRACTION_PROMPT},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64_str}"}}
            ]
        }]
        
        payload = {
            "model": _model,
            "messages": messages,
            "max_tokens": _max_tokens,
            "temperature": 0.1,
            "top_p": 0.7,
            "stream": False
        }
        
        max_attempts = 3
        for attempt in range(max_attempts):
            if task_check_func and task_check_func():
                return None  # 已取消
            
            try:
                if attempt > 0:
                    print(f"[VLM逐页]   第{attempt + 1}次重试... ({_server_name})")
                    time.sleep(3 * attempt)
                
                resp = requests.post(_api_url, json=payload, headers=_headers, timeout=180)
                
                if resp.status_code == 200:
                    resp_data = resp.json()
                    choices = resp_data.get("choices", [])
                    if choices:
                        text_output = choices[0].get("message", {}).get("content", "")
                        _print_vlm_usage_after_call(resp_data, _server_name)
                        return text_output
                elif resp.status_code == 429:
                    print(f"[VLM逐页]   ⚠️ API限流(429)，等待重试... ({_server_name})")
                    time.sleep(5 * (attempt + 1))
                elif resp.status_code in (500, 502, 503, 504):
                    print(f"[VLM逐页]   ⚠️ 服务端错误(HTTP {resp.status_code})，重试中... ({_server_name})")
                    time.sleep(3 * (attempt + 1))
                else:
                    print(f"[VLM逐页]   ❌ API返回 {resp.status_code} ({_server_name})")
                    if attempt == max_attempts - 1:
                        return ""
            except requests.exceptions.Timeout:
                if attempt == max_attempts - 1:
                    print(f"[VLM逐页]   ❌ 第 {page_num} 页API请求超时 ({_server_name})")
            except requests.exceptions.RequestException as e:
                if attempt == max_attempts - 1:
                    print(f"[VLM逐页]   ❌ 第 {page_num} 页网络请求失败: {e} ({_server_name})")
        return ""
    
    def _vlm_batch_call(page_images, _model, _api_url, _headers, _max_tokens, _server_name):
        """批量模式：所有页面图片放入一次VLM API调用（仅用于硅基流动等云端API）
        
        Returns:
            dict: {'success': True/False, 'vlm_md_content': str, 'error': '...'}
        """
        content_parts = [{"type": "text", "text": VLM_TABLE_EXTRACTION_PROMPT}]
        for page_num, b64_str in page_images:
            content_parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64_str}"}
            })
        
        messages = [{"role": "user", "content": content_parts}]
        payload = {
            "model": _model,
            "messages": messages,
            "max_tokens": _max_tokens,
            "temperature": 0.1,
            "top_p": 0.7,
            "stream": False
        }
        
        max_attempts = 3
        for attempt in range(max_attempts):
            if task_check_func and task_check_func():
                return {'success': False, 'error': '任务已被取消', 'cancelled': True}
            
            try:
                if attempt > 0:
                    print(f"[VLM批量] 第{attempt + 1}次重试... ({_server_name})")
                    time.sleep(3 * attempt)
                
                resp = requests.post(_api_url, json=payload, headers=_headers, timeout=180)
                
                if resp.status_code == 200:
                    resp_data = resp.json()
                    choices = resp_data.get("choices", [])
                    if choices:
                        text_output = choices[0].get("message", {}).get("content", "")
                        _print_vlm_usage_after_call(resp_data, _server_name)
                        
                        parsed = _parse_vlm_dual_output(text_output)
                        if parsed['md_content']:
                            return {
                                'success': True,
                                'vlm_md_content': parsed['md_content']
                            }
                        else:
                            return {'success': False, 'error': '批量模式未提取到有效Markdown'}
                    else:
                        return {'success': False, 'error': 'API返回空choices'}
                elif resp.status_code == 429:
                    print(f"[VLM批量] ⚠️ API限流(429)，等待重试... ({_server_name})")
                    time.sleep(5 * (attempt + 1))
                elif resp.status_code in (413, 400):
                    print(f"[VLM批量] ❌ API返回 {resp.status_code}（可能图片过大），放弃批量模式 ({_server_name})")
                    return {'success': False, 'error': f'API返回{resp.status_code}，图片数据可能过大'}
                elif resp.status_code in (500, 502, 503, 504):
                    print(f"[VLM批量] ⚠️ 服务端错误(HTTP {resp.status_code})，重试中... ({_server_name})")
                    time.sleep(3 * (attempt + 1))
                else:
                    print(f"[VLM批量] ❌ API返回 {resp.status_code} ({_server_name})")
                    if attempt == max_attempts - 1:
                        return {'success': False, 'error': f'API请求失败，状态码: {resp.status_code}'}
            except requests.exceptions.Timeout:
                if attempt == max_attempts - 1:
                    return {'success': False, 'error': '批量模式API请求超时'}
            except requests.exceptions.RequestException as e:
                if attempt == max_attempts - 1:
                    return {'success': False, 'error': f'网络请求失败: {str(e)}'}
        
        return {'success': False, 'error': '批量模式所有重试均失败'}
    
    def _vlm_per_page_call(page_images, _model, _api_url, _headers, _max_tokens, _server_name):
        """逐页模式：每页单独调用一次VLM API，合并结果
        
        Returns:
            dict: {'success': True/False, 'vlm_md_content': str, 'error': '...'}
        """
        all_page_mds = []
        
        for idx, (page_num, b64_str) in enumerate(page_images):
            if task_check_func and task_check_func():
                return {'success': False, 'error': '任务已被取消', 'cancelled': True}
            
            print(f"[VLM逐页] 处理第 {page_num} 页... ({_server_name})")
            if progress_callback:
                page_pct = 15 + int(75 * idx / len(page_images))
                progress_callback(page_pct, f'🔍 智能逐页识别：第 {page_num}/{len(page_images)} 页...')
            
            text_output = _vlm_single_page_call(page_num, b64_str, _model, _api_url, _headers, _max_tokens, _server_name)
            
            if text_output is None:  # 任务取消
                return {'success': False, 'error': '任务已被取消', 'cancelled': True}
            
            if text_output:
                parsed = _parse_vlm_dual_output(text_output)
                if parsed['md_content']:
                    all_page_mds.append(parsed['md_content'])
                    print(f"[VLM逐页]   第 {page_num} 页Markdown: {len(parsed['md_content'])} 字符")
            
            if progress_callback:
                done_pct = 15 + int(75 * (idx + 1) / len(page_images))
                progress_callback(done_pct, f'🔍 智能逐页识别：第 {page_num}/{len(page_images)} 页完成')
        
        vlm_md = '\n\n---\n\n'.join(all_page_mds) if all_page_mds else ''
        if not vlm_md:
            return {'success': False, 'error': '逐页模式未能从任何页面提取到有效Markdown'}
        print(f"[VLM逐页] 合并完成 ({_server_name})，MD: {len(vlm_md)} 字符")
        return {'success': True, 'vlm_md_content': vlm_md}
    
    def _try_with_config(config, key):
        """使用指定配置进行VLM提取
        
        策略：
        - 本地vLLM：纯逐页模式（避免HTTP 400图片过大问题）
        - 硅基流动：批量优先，失败回退逐页模式
        """
        _model = config["model"]
        _api_url = config["api_url"]
        _max_tokens = config["max_tokens"]
        _server_name = config["name"]
        _is_local = not config["needs_api_key"]  # 本地服务器不需要API密钥
        _headers = {"Content-Type": "application/json"}
        if config["needs_api_key"] and key:
            _headers["Authorization"] = f"Bearer {key}"
        elif not config["needs_api_key"]:
            _headers["Authorization"] = "Bearer none"
        
        try:
            if progress_callback:
                progress_callback(0, f'🔍 智能表格提取：准备PDF页面...')
            
            # 1. 渲染PDF页面
            page_images = _render_pdf_pages(config)
            if page_images is None:
                return {'success': False, 'error': '任务已被取消', 'cancelled': True}
            if not page_images:
                return {'success': False, 'error': 'PDF渲染失败，未获得任何页面图片'}
            
            if task_check_func and task_check_func():
                return {'success': False, 'error': '任务已被取消', 'cancelled': True}
            
            # 2. 根据服务器类型选择调用策略
            if _is_local:
                # ===== 本地vLLM：纯逐页模式（避免HTTP 400） =====
                print(f"[VLM表格提取] 本地服务器 → 逐页模式：{len(page_images)} 页 → {len(page_images)} 次API调用")
                if progress_callback:
                    progress_callback(15, f'🔍 表格识别：逐页识别 {len(page_images)} 页...')
                
                result = _vlm_per_page_call(page_images, _model, _api_url, _headers, _max_tokens, _server_name)
            else:
                # ===== 硅基流动：批量优先，失败回退逐页 =====
                print(f"[VLM表格提取] 云端API → 批量模式：{len(page_images)} 页 → 1次API调用 ({_server_name})")
                if progress_callback:
                    progress_callback(15, f'🔍 表格识别：批量识别 {len(page_images)} 页...')
                
                result = _vlm_batch_call(page_images, _model, _api_url, _headers, _max_tokens, _server_name)
                
                if not result.get('success') and not result.get('cancelled'):
                    print(f"[VLM表格提取] ⚠️ 批量模式失败({result.get('error')})，回退到逐页模式")
                    if progress_callback:
                        progress_callback(20, f'⚠️ 批量识别失败，切换逐页识别...')
                    result = _vlm_per_page_call(page_images, _model, _api_url, _headers, _max_tokens, _server_name)
            
            if result.get('success'):
                result['server'] = _server_name
                print(f"[VLM表格提取] ✅ 提取完成 ({_server_name})，"
                      f"MD: {len(result.get('vlm_md_content', ''))} 字符")
                if progress_callback:
                    progress_callback(95, f'✅ 表格识别成功，结构补全中...')
            
            return result
            
        except Exception as e:
            print(f"[VLM表格提取] ❌ {_server_name} 提取异常: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': f'{_server_name}提取失败: {str(e)}'}
    
    # === 主流程：先本地，失败则回退硅基流动 ===
    try:
        result = _try_with_config(vlm_config, api_key)
        
        # 如果本地服务器失败且硅基流动可用，尝试回退
        if not result.get('success') and not result.get('cancelled'):
            if local_available and api_key:
                print(f"[VLM表格提取] ⚠️ 本地服务器提取失败，尝试回退到硅基流动API...")
                result = _try_with_config(SILICONFLOW_VLM_CONFIG, api_key)
        
        return result
        
    except Exception as e:
        print(f"[VLM表格提取] ❌ VLM表格提取异常: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': f'VLM表格提取失败: {str(e)}'}


def _parse_vlm_json_output(text: str) -> dict:
    """解析VLM输出的JSON文本（兼容旧格式，供其他调用方使用）
    
    优先尝试JSON解析，失败后尝试从markdown表格提取键值对转换为JSON。
    
    Args:
        text: VLM返回的文本（可能包含markdown标记或markdown表格）
        
    Returns:
        解析后的dict，失败返回空dict
    """
    # --- 第一步：尝试JSON提取 ---
    try:
        cleaned = text.strip()
        # 清理markdown代码块标记
        if cleaned.startswith('```json'):
            cleaned = cleaned[7:]
        if cleaned.startswith('```'):
            cleaned = cleaned[3:]
        if cleaned.endswith('```'):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        
        # 提取JSON对象
        json_match = re.search(r'\{.*\}', cleaned, re.DOTALL)
        if json_match:
            json_str = json_match.group()
            result = safe_json_parse(json_str)
            if result:
                print(f"[VLM表格提取] ✅ JSON直接解析成功，{len(result)} 个顶层键")
                return result
    except (json.JSONDecodeError, Exception) as e:
        print(f"[VLM表格提取] JSON解析失败: {e}，尝试markdown表格转换...")
    
    # --- 第二步：尝试从markdown表格提取 ---
    md_result = _convert_vlm_markdown_to_json(text)
    if md_result:
        print(f"[VLM表格提取] ✅ Markdown表格转JSON成功，{len(md_result)} 个顶层键")
        return md_result
    
    print(f"[VLM表格提取] ❌ JSON解析和Markdown表格转换均失败")
    return {}


def _extract_kv_from_markdown_tables(text: str) -> list:
    """从markdown表格文本中提取所有键值对
    
    支持2列/4列/6列等偶数列表格（视为key-value交替排列）。
    
    Args:
        text: 包含markdown表格的文本
        
    Returns:
        [(key, value), ...] 键值对列表
    """
    pairs = []
    lines = text.strip().split('\n')
    
    for line in lines:
        line = line.strip()
        if not line.startswith('|'):
            # 检测"key: value"或"key：value"格式的行（VLM有时输出此格式）
            kv_match = re.match(r'^([^:：\n]{1,30})[：:]\s*(.+)$', line)
            if kv_match:
                key = kv_match.group(1).strip()
                value = kv_match.group(2).strip()
                if key and value and not re.match(r'^[-=\s*#]+$', key):
                    pairs.append((key, value))
            continue
        
        # 跳过分隔行 |---|---|
        if re.match(r'^\|[\s\-:| ]+\|$', line):
            continue
        
        # 拆分单元格（去掉首尾空的|分割结果）
        cells = [c.strip() for c in line.split('|')]
        # split('|') 对 "|a|b|" 结果是 ['', 'a', 'b', '']
        if cells and cells[0] == '':
            cells = cells[1:]
        if cells and cells[-1] == '':
            cells = cells[:-1]
        
        if not cells:
            continue
        
        # 过滤纯分隔线单元格
        if all(re.match(r'^[-:\s]*$', c) for c in cells):
            continue
        
        # 偶数列：视为 key-value 交替 (2列、4列、6列等)
        if len(cells) >= 2 and len(cells) % 2 == 0:
            for i in range(0, len(cells), 2):
                key = cells[i].strip()
                value = cells[i + 1].strip() if i + 1 < len(cells) else ''
                # 跳过空key和分隔线
                if key and not re.match(r'^[-:\s]*$', key):
                    pairs.append((key, value))
        # 奇数列（如3列 | 序号 | 字段 | 值 |）：取后两列
        elif len(cells) >= 3 and len(cells) % 2 == 1:
            for i in range(1, len(cells), 2):
                key = cells[i].strip() if i < len(cells) else ''
                value = cells[i + 1].strip() if i + 1 < len(cells) else ''
                if key and not re.match(r'^[-:\s]*$', key):
                    pairs.append((key, value))
    
    return pairs


def _convert_vlm_markdown_to_json(text: str) -> dict:
    """将VLM输出的markdown表格内容转换为NSFC表格JSON结构
    
    根据已知的NSFC基本信息表字段名，将markdown表格中的键值对
    映射到标准的 {项目信息, 基本信息} JSON结构中。
    
    Args:
        text: VLM返回的包含markdown表格的文本
        
    Returns:
        转换后的dict，如果无法提取有效键值对则返回空dict
    """
    pairs = _extract_kv_from_markdown_tables(text)
    if not pairs:
        return {}
    
    print(f"[VLM MD转JSON] 从markdown表格提取到 {len(pairs)} 个键值对")
    
    # ---- 字段名 → 分类 映射 ----
    # 项目信息字段
    project_fields = {
        "亚类说明", "附注说明", "项目名称", "申请人", "办公电话",
        "依托单位", "通讯地址", "邮政编码", "单位电话", "电子邮箱",
        "资助类别", "亚类说明"
    }
    # 申请人信息字段
    applicant_fields = {
        "姓名", "性别", "出生年月", "民族", "学位", "职称",
        "研究领域", "主要研究方向", "电话", "手机", "身份证号",
        "每年工作时间", "学历", "最高学历", "博士毕业年", "工作单位",
        "最后学位", "最后学历", "正在主持的项目", "学科专长"
    }
    # 依托单位信息字段
    institution_fields = {
        "联系人", "依托单位联系人"  # "名称"会和项目名称冲突，用模糊匹配
    }
    # 项目基本信息字段
    project_basic_fields = {
        "申请代码", "研究期限", "申请直接费用", "申请经费", "资助期限",
        "研究方向", "申请金额", "研究年限", "直接费用", "间接费用",
        "合计经费"
    }
    
    result = {"项目信息": {}, "基本信息": {}}
    basic = result["基本信息"]
    
    for key, value in pairs:
        # 清理key中可能的加粗/强调标记
        key = re.sub(r'\*+', '', key).strip()
        value = re.sub(r'\*+', '', value).strip() if value else ''
        
        if not key:
            continue
        
        # 中文摘要 / 英文摘要（特殊处理，可能跨行）
        if "摘要" in key:
            if "英文" in key or "Abstract" in key.lower() or "english" in key.lower():
                basic["英文摘要"] = value
            else:
                basic["中文摘要"] = value
            continue
        
        # 关键词
        if "关键词" in key or "keyword" in key.lower():
            kw_list = [v.strip() for v in re.split(r'[;；,，]', value) if v.strip()]
            if "英文" in key or "English" in key or "keyword" in key.lower():
                basic["英文关键词"] = kw_list
            else:
                basic["中文关键词"] = kw_list
            continue
        
        # 合作研究单位
        if "合作" in key and "单位" in key:
            if "合作研究单位信息" not in basic:
                basic["合作研究单位信息"] = {}
            basic["合作研究单位信息"]["单位名称"] = value
            continue
        
        # 依托单位（精确匹配或包含"依托"）
        if key == "依托单位" or ("依托" in key and "单位" in key and "联系" not in key):
            result["项目信息"]["依托单位"] = value
            if "依托单位信息" not in basic:
                basic["依托单位信息"] = {}
            basic["依托单位信息"]["名称"] = value
            continue
        
        # 分类匹配
        matched = False
        
        # 项目信息字段
        for f in project_fields:
            if key == f or f in key:
                result["项目信息"][f if key == f else key] = value
                matched = True
                break
        if matched:
            continue
        
        # 申请人信息
        for f in applicant_fields:
            if key == f or f in key:
                if "申请人信息" not in basic:
                    basic["申请人信息"] = {}
                basic["申请人信息"][f if key == f else key] = value
                matched = True
                break
        if matched:
            continue
        
        # 依托单位信息
        for f in institution_fields:
            if key == f or f in key:
                if "依托单位信息" not in basic:
                    basic["依托单位信息"] = {}
                basic["依托单位信息"][f if key == f else key] = value
                matched = True
                break
        if matched:
            continue
        
        # 项目基本信息
        for f in project_basic_fields:
            if key == f or f in key:
                if "项目基本信息" not in basic:
                    basic["项目基本信息"] = {}
                basic["项目基本信息"][f if key == f else key] = value
                matched = True
                break
        if matched:
            continue
        
        # 未匹配的字段放入项目信息（兜底）
        result["项目信息"][key] = value
    
    # 验证是否有有效数据
    has_data = (
        any(v for v in result["项目信息"].values()) or 
        any(v for v in basic.values() if isinstance(v, str) and v) or
        any(v for v in basic.values() if isinstance(v, dict) and any(v.values())) or
        any(v for v in basic.values() if isinstance(v, list) and v)
    )
    
    if has_data:
        print(f"[VLM MD转JSON] 转换完成: 项目信息 {len(result['项目信息'])} 字段, "
              f"基本信息 {len(basic)} 字段")
        return result
    
    return {}


def _deep_merge_json(target: dict, source: dict):
    """深度合并两个JSON字典，source的非空值补充或覆盖target的空值
    
    Args:
        target: 目标字典（会被原地修改）
        source: 源字典
    """
    for key, value in source.items():
        if key not in target:
            target[key] = value
        elif isinstance(target[key], dict) and isinstance(value, dict):
            _deep_merge_json(target[key], value)
        elif isinstance(target[key], list) and isinstance(value, list):
            for item in value:
                if item not in target[key]:
                    target[key].append(item)
        elif isinstance(value, str) and value:
            # 非空字符串：覆盖空值或保留更长的内容
            if not target[key] or (isinstance(target[key], str) and len(value) > len(target[key])):
                target[key] = value
        elif value and not target[key]:
            target[key] = value

def fix_malformed_json(json_str: str) -> str:
    """修复常见的JSON格式错误
    
    Args:
        json_str: 待修复的JSON字符串
        
    Returns:
        修复后的JSON字符串
    """
    # 1. 移除BOM和特殊字符
    json_str = json_str.replace('\ufeff', '')
    
    # 2. 修复常见的逗号问题
    # 修复缺失的逗号（字段间）- 匹配 "}\n  "xxxx" 模式
    json_str = re.sub(r'"\s*\n\s*"', '",\n  "', json_str)
    
    # 修复缺失的逗号（数组/对象后）
    json_str = re.sub(r'}\s*\n\s*{', '},\n  {', json_str)
    json_str = re.sub(r']\s*\n\s*{', '],\n  {', json_str)
    json_str = re.sub(r'}\s*\n\s*\[', '},\n  [', json_str)
    
    # 3. 修复多余的逗号
    # 移除对象/数组结尾的多余逗号
    json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)
    
    # 4. 修复未转义的引号
    # 在字符串值中的未转义引号（简单处理）
    # 注意：这是一个简化版本，复杂情况可能需要更智能的处理
    
    # 5. 修复未闭合的引号/括号（基本检查）
    open_braces = json_str.count('{')
    close_braces = json_str.count('}')
    if open_braces > close_braces:
        json_str += '}' * (open_braces - close_braces)
        print(f"[JSON修复] 补全了 {open_braces - close_braces} 个闭合大括号")
    
    open_brackets = json_str.count('[')
    close_brackets = json_str.count(']')
    if open_brackets > close_brackets:
        json_str += ']' * (open_brackets - close_brackets)
        print(f"[JSON修复] 补全了 {open_brackets - close_brackets} 个闭合中括号")
    
    # 6. 移除注释（JSON不支持注释）
    json_str = re.sub(r'//.*?\n', '\n', json_str)
    json_str = re.sub(r'/\*.*?\*/', '', json_str, flags=re.DOTALL)
    
    # 7. 修复非法转义序列（如 LaTeX 中的 \alpha, \mathrm, \% 等）
    # JSON 仅允许 \" \\ \/ \b \f \n \r \t \uXXXX，其余 \X 均非法
    # 将非法的 \X 替换为 \\X（双反斜杠），使其成为合法的字面反斜杠
    json_str = re.sub(r'\\(?!["\\/bfnrtu])', r'\\\\', json_str)
    
    return json_str


def safe_json_parse(json_str: str, max_attempts: int = 3) -> dict:
    """安全解析JSON，带自动修复功能
    
    修复策略（4层递进）：
    1. 直接解析
    2. json_repair 智能修复（处理截断、单引号、多余逗号、未闭合括号等）
    3. 手动 fix_malformed_json + 解析
    4. 提取最大JSON片段 + json_repair
    
    Args:
        json_str: JSON字符串
        max_attempts: 最大尝试次数（兼容参数，实际固定4层）
        
    Returns:
        解析后的JSON对象
        
    Raises:
        json.JSONDecodeError: 所有尝试都失败后抛出
    """
    # 第1层：直接解析
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        print(f"[JSON解析] 第1层直接解析失败: {e}")
    
    # 第2层：json_repair 智能修复（堵截断/单引号/多余逗号/未闭合括号/注释/markdown标记）
    try:
        result = repair_json(json_str, return_objects=True)
        if isinstance(result, dict) and len(result) > 0:
            print(f"[JSON解析] 第2层 json_repair 修复成功，获得 {len(result)} 个顶层key")
            return result
        elif isinstance(result, dict):
            print(f"[JSON解析] 第2层 json_repair 返回空dict，继续尝试...")
        else:
            print(f"[JSON解析] 第2层 json_repair 返回非dict类型({type(result).__name__})，继续尝试...")
    except Exception as e:
        print(f"[JSON解析] 第2层 json_repair 失败: {e}")
    
    # 第3层：手动修复后解析
    try:
        fixed_json = fix_malformed_json(json_str)
        return json.loads(fixed_json)
    except json.JSONDecodeError as e:
        print(f"[JSON解析] 第3层 fix_malformed_json 失败: {e}")
    
    # 第4层：提取最大JSON片段 + json_repair
    try:
        match = re.search(r'\{.*\}', json_str, re.DOTALL)
        if match:
            fragment = match.group()
            result = repair_json(fragment, return_objects=True)
            if isinstance(result, dict) and len(result) > 0:
                print(f"[JSON解析] 第4层 提取片段+json_repair 成功，获得 {len(result)} 个顶层key")
                return result
    except Exception as e:
        print(f"[JSON解析] 第4层失败: {e}")
    
    # 所有尝试都失败
    print(f"[JSON解析] 全4层修复均失败")
    raise json.JSONDecodeError("无法解析JSON，全4层修复均失败", json_str[:200], 0)


# ==================== JSON结构硬编码补救函数 ====================

def ensure_complete_json_structure(json_data: dict) -> dict:
    """硬编码确保JSON结构包含所有必需的一级和二级标题（补救措施）
    
    Args:
        json_data: LLM返回的JSON数据
        
    Returns:
        补全后的JSON数据
    """
    print("[JSON修复] 开始验证和补全JSON结构...")
    
    # 确保一级标题存在
    if "项目信息" not in json_data:
        print("[JSON修复] 缺少一级标题：项目信息，已补全")
        json_data["项目信息"] = {}
    
    if "基本信息" not in json_data:
        print("[JSON修复] 缺少一级标题：基本信息，已补全")
        json_data["基本信息"] = {}
    
    # 确保"项目信息"下的必需字段
    required_project_fields = {
        "亚类说明": "",
        "附注说明": "",
        "项目名称": "",
        "申请人": "",
        "办公电话": "",
        "依托单位": "",
        "通讯地址": "",
        "邮政编码": "",
        "单位电话": "",
        "电子邮箱": ""
    }
    
    for key, default_value in required_project_fields.items():
        if key not in json_data["项目信息"]:
            print(f"[JSON修复] 缺少项目信息字段：{key}，已补全")
            json_data["项目信息"][key] = default_value
    
    # 确保"基本信息"下的二级标题存在
    required_second_level = {
        "申请人信息": {},
        "依托单位信息": {},
        "合作研究单位信息": {},
        "项目基本信息": {},
        "中文关键词": [],
        "英文关键词": [],
        "中文摘要": "",
        "英文摘要": ""
    }
    
    for key, default_value in required_second_level.items():
        if key not in json_data["基本信息"]:
            print(f"[JSON修复] 缺少基本信息字段：{key}，已补全")
            json_data["基本信息"][key] = default_value
    
    # 按照固定顺序重组JSON（确保顺序，同时保留LLM提取的所有其他字段）
    ordered_json = {
        "项目信息": {},
        "基本信息": {}
    }
    
    # 先按固定顺序添加"项目信息"的必需字段
    for key in required_project_fields.keys():
        ordered_json["项目信息"][key] = json_data["项目信息"].get(key, "")
    
    # 再添加LLM提取的其他字段（保留所有额外字段）
    for key, value in json_data["项目信息"].items():
        if key not in ordered_json["项目信息"]:
            ordered_json["项目信息"][key] = value
    
    # 按固定顺序添加"基本信息"的必需字段
    for key in required_second_level.keys():
        ordered_json["基本信息"][key] = json_data["基本信息"].get(key, required_second_level[key])
    
    # 再添加LLM提取的其他字段（保留所有额外字段）
    for key, value in json_data["基本信息"].items():
        if key not in ordered_json["基本信息"]:
            ordered_json["基本信息"][key] = value
    
    print(f"[JSON修复] 结构验证完成，项目信息包含{len(ordered_json['项目信息'])}个字段，基本信息包含{len(ordered_json['基本信息'])}个字段")
    return ordered_json


def extract_heading_numbers_from_markdown(markdown_text: str) -> dict:
    """从markdown文本中提取标题及其原始序号映射
    
    Args:
        markdown_text: markdown文本内容
        
    Returns:
        dict: {清理后的标题文本: 原始标题（含序号）}
    """
    heading_map = {}
    
    # 匹配各种标题格式的正则（按优先级排序）
    # 注意：使用\d{1,3}限制数字为1-3位，避免匹配4位年份(如2026)
    patterns = [
        r'^#+\s+(.+)$',  # markdown标题 # ## ###
        r'^([（(]?[一二三四五六七八九十百千万]+[)）]\s*.+)$',  # 中文序号
        r'^(\d{1,3}\.\d{1,3}\.\d{1,3}[\.\、]?\s*.+)$',  # 三级数字序号 1.1.1
        r'^(\d{1,3}\.\d{1,3}[\.\、]?\s*.+)$',  # 二级数字序号 1.1
        r'^(\d{1,3}[\.\、]\s*.+)$',  # 一级数字序号 1.
        r'^([(（]\d{1,3}[)）]\s*.+)$',  # 括号数字 (1)
        r'^([A-Za-z][\)\.]\s*.+)$',  # 字母序号 a)
        r'^([ivxIVX]+\.\s*.+)$',  # 罗马数字 i.
    ]
    
    for line in markdown_text.split('\n'):
        line = line.strip()
        if not line:
            continue
        
        for pattern in patterns:
            match = re.match(pattern, line)
            if match:
                original_heading = match.group(1).strip()
                
                # 清理序号得到纯标题文本（同样限制1-3位数字）
                clean_heading = original_heading
                clean_heading = re.sub(r'^[（(]?[一二三四五六七八九十百千万]+[)）]\s*', '', clean_heading)
                clean_heading = re.sub(r'^\d{1,3}\.\d{1,3}\.\d{1,3}[\.\、]?\s*', '', clean_heading)  # 1.1.1
                clean_heading = re.sub(r'^\d{1,3}\.\d{1,3}[\.\、]?\s*', '', clean_heading)  # 1.1
                clean_heading = re.sub(r'^\d{1,3}[\.\、]\s*', '', clean_heading)  # 1.
                clean_heading = re.sub(r'^\d{1,3}\s+', '', clean_heading)  # 单独数字
                clean_heading = re.sub(r'^[A-Za-z][\)\.]\s*', '', clean_heading)
                clean_heading = re.sub(r'^[(（]\d{1,3}[)）]\s*', '', clean_heading)
                clean_heading = re.sub(r'^[ivxIVX]+\.\s*', '', clean_heading)
                clean_heading = re.sub(r'^#+\s+', '', clean_heading)  # 去除markdown #
                clean_heading = clean_heading.strip()
                
                if clean_heading:
                    # 保存映射：清理后的文本 -> 原始标题
                    heading_map[clean_heading] = original_heading
                    # 也保存带#的markdown格式映射
                    if original_heading.startswith('#'):
                        heading_map[clean_heading] = original_heading
                break
    
    print(f"[标题序号提取] 从markdown中提取了 {len(heading_map)} 个标题序号映射")
    return heading_map


def extract_number_prefix(text: str) -> tuple:
    """提取标题的序号前缀和类型
    
    Args:
        text: 标题文本
        
    Returns:
        (序号前缀, 序号类型, 序号值)
        序号类型: 'chinese', 'number', 'multi_number', 'bracket', 'letter', 'roman', 'none'
    """
    # 中文序号
    match = re.match(r'^([（(]?[一二三四五六七八九十百千万]+[)）])\s*', text)
    if match:
        return (match.group(1), 'chinese', match.group(1))
    
    # 多级数字 1.1.1（限制1-3位，避免匹配年份）
    match = re.match(r'^(\d{1,3}\.\d{1,3}\.\d{1,3})[\.\、]?\s*', text)
    if match:
        return (match.group(1), 'multi_number_3', match.group(1))
    
    # 二级数字 1.1（限制1-3位，避免匹配年份）
    match = re.match(r'^(\d{1,3}\.\d{1,3})[\.\、]?\s*', text)
    if match:
        return (match.group(1), 'multi_number_2', match.group(1))
    
    # 一级数字 1.（限制1-3位）
    match = re.match(r'^(\d{1,3})[\.\、]\s*', text)
    if match:
        return (match.group(1), 'number', int(match.group(1)))
    
    # 括号数字 (1)（限制1-3位）
    match = re.match(r'^([(（]\d{1,3}[)）])\s*', text)
    if match:
        return (match.group(1), 'bracket', match.group(1))
    
    # 字母 a)
    match = re.match(r'^([A-Za-z])[\)\.]\s*', text)
    if match:
        return (match.group(1), 'letter', match.group(1))
    
    # 罗马数字 i.
    match = re.match(r'^([ivxIVX]+)\.\s*', text)
    if match:
        return (match.group(1), 'roman', match.group(1))
    
    return ('', 'none', None)


def unify_level_numbering(json_data: dict, level: int = 1) -> dict:
    """第二次编号：统一同层级序号格式，检查连贯性
    
    规则：
    1. 如果同层级大部分标题有序号，无序号的应该添加序号保持统一
    2. 如果序号已经连贯（如1,2,3），中间突然出现无序号的，忽略不重新编号
    3. 优先保留原文序号
    
    Args:
        json_data: 第一次编号后的JSON
        level: 当前层级
        
    Returns:
        统一编号后的JSON
    """
    if not isinstance(json_data, dict):
        return json_data
    
    result = {}
    
    # 分析同层级所有标题的序号情况
    keys = list(json_data.keys())
    number_types = []
    has_number = []
    
    for key in keys:
        prefix, num_type, num_val = extract_number_prefix(key)
        number_types.append(num_type)
        has_number.append(num_type != 'none')
    
    # 统计序号使用情况
    numbered_count = sum(has_number)
    total_count = len(keys)
    
    # 如果大部分（>50%）有序号，找出主导序号类型
    dominant_type = None
    if numbered_count > total_count / 2:
        type_counts = {}
        for nt in number_types:
            if nt != 'none':
                type_counts[nt] = type_counts.get(nt, 0) + 1
        if type_counts:
            dominant_type = max(type_counts, key=type_counts.get)
    
    # 检查数字序号的连贯性
    is_continuous = False
    if dominant_type == 'number':
        numbers = []
        for key in keys:
            _, num_type, num_val = extract_number_prefix(key)
            if num_type == 'number':
                numbers.append(num_val)
        if len(numbers) >= 2:
            # 检查是否连续
            numbers.sort()
            is_continuous = all(numbers[i+1] - numbers[i] == 1 for i in range(len(numbers)-1))
    
    print(f"[第二次编号] L{level}: {numbered_count}/{total_count}有序号, 主导类型:{dominant_type}, 连贯:{is_continuous}")
    
    # 处理每个键
    counter = 0
    for key, value in json_data.items():
        prefix, num_type, num_val = extract_number_prefix(key)
        # 限制数字为1-3位，避免匹配4位年份(如2026)
        clean_key = re.sub(r'^[（(]?[一二三四五六七八九十百千万]+[)）]\s*', '', key)
        clean_key = re.sub(r'^\d{1,3}\.\d{1,3}\.\d{1,3}[\.\、]?\s*', '', clean_key)
        clean_key = re.sub(r'^\d{1,3}\.\d{1,3}[\.\、]?\s*', '', clean_key)
        clean_key = re.sub(r'^\d{1,3}[\.\、]\s*', '', clean_key)
        clean_key = re.sub(r'^[(（]\d{1,3}[)）]\s*', '', clean_key)
        clean_key = re.sub(r'^[A-Za-z][\)\.]\s*', '', clean_key)
        clean_key = re.sub(r'^[ivxIVX]+\.\s*', '', clean_key)
        clean_key = clean_key.strip()
        
        new_key = key
        
        # 如果当前无序号，但同层级应该统一序号
        if num_type == 'none' and dominant_type and not is_continuous:
            # 只在序号不连贯时才添加序号
            if dominant_type == 'number':
                counter += 1
                new_key = f'{counter}. {clean_key}'
                print(f"[第二次编号] 补充序号: {key} -> {new_key}")
            elif dominant_type == 'bracket':
                counter += 1
                new_key = f'（{counter}）{clean_key}'
                print(f"[第二次编号] 补充序号: {key} -> {new_key}")
        elif num_type == 'number':
            counter = num_val  # 跟踪最大序号
        
        # 递归处理子级
        result[new_key] = unify_level_numbering(value, level+1) if isinstance(value, dict) else value
    
    return result


def normalize_content_json_headings(json_data: dict, level: int = 1, parent_key: str = '', heading_map: dict = None) -> dict:
    """正文JSON标题序号规范化
    
    关键规则：
    1. 一级标题：包含"立项依据"、"研究内容"、"研究基础"或已有（一）（二）（三）格式
    2. 保留LLM返回的嵌套结构，不要扁平化
    3. 二级及以下标题优先从heading_map获取原文序号
    4. _开头的字段完全过滤
    5. 清理重复键
    
    Args:
        json_data: 从LLM API获取并合并后的完整JSON数据
        level: 当前处理的层级（1=最高级，2=第二级，3+=更低级）
        parent_key: 父级键名（用于调试）
        heading_map: 标题序号映射表 {清理后的标题: 原始标题（含序号）}
        
    Returns:
        规范化后的JSON数据（保持原有嵌套结构）
    """
    if not isinstance(json_data, dict):
        return json_data
    
    if heading_map is None:
        heading_map = {}
    
    normalized = {}
    chinese_nums = ['一', '二', '三', '四', '五', '六', '七', '八', '九', '十']
    
    # 定义合法的一级标题关键词
    valid_level1_keywords = ['立项依据', '研究内容', '研究基础', '其他需要说明']
    
    # 检测是否已经有（一）（二）（三）格式的一级标题
    has_chinese_numbered = any(re.match(r'^[（(][一二三四五六七八九十]+[)）]', k) for k in json_data.keys())
    
    counter = 0
    seen_clean_keys = set()  # 用于检测重复的清理后的键
    
    for key, value in json_data.items():
        # 1. 过滤下划线开头的字段（完全不保存）
        if key.startswith('_'):
            print(f"[正文JSON标题补救] 已过滤：{key}")
            continue
        
        # 2. 获取不带序号的标题文本（用于匹配和去重）
        clean_key = key
        # 移除所有可能的序号格式（按顺序，先移除复杂的）
        # 限制数字为1-3位，避免匹配4位年份(如2026)
        clean_key = re.sub(r'^[（(]?[一二三四五六七八九十百千万]+[)）]\s*', '', clean_key)
        clean_key = re.sub(r'^\d{1,3}\.\d{1,3}\.\d{1,3}[\.\、]?\s*', '', clean_key)  # 1.1.1
        clean_key = re.sub(r'^\d{1,3}\.\d{1,3}[\.\、]?\s*', '', clean_key)  # 1.1
        clean_key = re.sub(r'^\d{1,3}[\.\、]\s*', '', clean_key)  # 1.
        clean_key = re.sub(r'^\d{1,3}\s+', '', clean_key)
        clean_key = re.sub(r'^[A-Za-z][\)\.]\s*', '', clean_key)
        clean_key = re.sub(r'^[(（]\d{1,3}[)）]\s*', '', clean_key)
        clean_key = re.sub(r'^[ivxIVX]+\.\s*', '', clean_key)
        clean_key = re.sub(r'^#+\s+', '', clean_key)  # 去除markdown #
        clean_key = clean_key.strip()
        
        if not clean_key:
            clean_key = key
        
        # 3. 检测重复键（基于clean_key）
        if clean_key in seen_clean_keys:
            print(f"[正文JSON标题补救] 已去重：'{key}' (清理后: '{clean_key}')")
            continue
        seen_clean_keys.add(clean_key)
        
        # 4. 判断当前键是否是一级标题格式
        is_level1_format = re.match(r'^[（(][一二三四五六七八九十]+[)）]', key) is not None
        is_level1_keyword = any(kw in clean_key for kw in valid_level1_keywords)
        
        # 5. 根据情况处理
        if level == 1:
            if is_level1_format:
                # 已经有（一）格式，保持原样
                new_key = key
                normalized[new_key] = normalize_content_json_headings(value, level=2, parent_key=new_key, heading_map=heading_map) if isinstance(value, dict) else value
                print(f"[正文JSON标题补救] L1已有序号: {key}")
            elif is_level1_keyword and not has_chinese_numbered:
                # 是一级关键词但没有序号，且全局没有中文序号格式，添加序号
                if counter < len(chinese_nums):
                    new_key = f'（{chinese_nums[counter]}）{clean_key}'
                else:
                    new_key = f'（{counter+1}）{clean_key}'
                counter += 1
                normalized[new_key] = normalize_content_json_headings(value, level=2, parent_key=new_key, heading_map=heading_map) if isinstance(value, dict) else value
                print(f"[正文JSON标题补救] L1添加序号: {key} -> {new_key}")
            else:
                # 不是一级标题，保留原始key（包括其序号）
                # 这意味着LLM返回了扁平结构，需要保留原始格式
                new_key = key
                normalized[new_key] = normalize_content_json_headings(value, level=level+1, parent_key=new_key, heading_map=heading_map) if isinstance(value, dict) else value
                
        else:
            # 二级及以下：保留原文的key（包括序号）
            # 如果能从heading_map找到，使用原文格式
            if clean_key in heading_map:
                original_heading = heading_map[clean_key]
                original_heading = re.sub(r'^#+\s+', '', original_heading)
                new_key = original_heading
                print(f"[正文JSON标题补救] L{level}使用原文序号: {key} -> {new_key}")
            else:
                # 保留LLM返回的原始key
                new_key = key
            
            # 递归处理子级
            normalized[new_key] = normalize_content_json_headings(value, level=level+1, parent_key=new_key, heading_map=heading_map) if isinstance(value, dict) else value
    
    return normalized

# ==================== JSON结构硬编码补救函数结束 ====================


# ==================== VLM JSON → MD表格转换 ====================

def convert_table_json_to_md_table(json_data):
    """将VLM提取的表格JSON转换为Markdown文档中可显示的HTML表格
    
    当MinerU未能识别出表格时，调用此函数将VLM提取的JSON数据生成可读的HTML表格，
    用于替换MD文档中"# 报告正文"前的表格区域。生成格式与MinerU原生HTML表格兼容。
    
    Args:
        json_data: VLM提取的表格JSON，结构为 {"项目信息": {...}, "基本信息": {...}}
        
    Returns:
        str: HTML表格字符串，可直接嵌入Markdown文档；若无有效数据则返回空字符串
    """
    if not json_data or not isinstance(json_data, dict):
        return ''
    
    html_parts = []
    
    # 生成"项目信息"表格
    project_info = json_data.get('项目信息', {})
    if project_info and any(v for v in project_info.values() if v):
        rows = ['<table>']
        rows.append('<tr><td colspan="4"><b>项目信息</b></td></tr>')
        items = [(k, v) for k, v in project_info.items() if v]
        # 每行放2组key-value
        for i in range(0, len(items), 2):
            k1, v1 = items[i]
            if i + 1 < len(items):
                k2, v2 = items[i + 1]
                rows.append(f'<tr><td>{k1}</td><td>{v1}</td><td>{k2}</td><td>{v2}</td></tr>')
            else:
                rows.append(f'<tr><td>{k1}</td><td colspan="3">{v1}</td></tr>')
        rows.append('</table>')
        html_parts.append('\n'.join(rows))
    
    # 生成"基本信息"表格
    basic_info = json_data.get('基本信息', {})
    if basic_info:
        rows = ['<table>']
        rows.append('<tr><td colspan="4"><b>基本信息</b></td></tr>')
        
        for section_name, section_data in basic_info.items():
            if isinstance(section_data, dict):
                # 申请人信息、依托单位信息、项目基本信息等子字典
                filled = {k: v for k, v in section_data.items() if v}
                if filled:
                    rows.append(f'<tr><td colspan="4"><b>{section_name}</b></td></tr>')
                    items = list(filled.items())
                    for i in range(0, len(items), 2):
                        k1, v1 = items[i]
                        if i + 1 < len(items):
                            k2, v2 = items[i + 1]
                            rows.append(f'<tr><td>{k1}</td><td>{v1}</td><td>{k2}</td><td>{v2}</td></tr>')
                        else:
                            rows.append(f'<tr><td>{k1}</td><td colspan="3">{v1}</td></tr>')
            elif isinstance(section_data, list):
                # 中文关键词、英文关键词
                keywords = '；'.join(str(kw) for kw in section_data if kw)
                if keywords:
                    rows.append(f'<tr><td>{section_name}</td><td colspan="3">{keywords}</td></tr>')
            elif isinstance(section_data, str) and section_data.strip():
                # 中文摘要、英文摘要
                rows.append(f'<tr><td>{section_name}</td><td colspan="3">{section_data}</td></tr>')
        
        rows.append('</table>')
        html_parts.append('\n'.join(rows))
    
    return '\n\n'.join(html_parts)


def replace_md_table_with_vlm(md_content, vlm_html_table):
    """用VLM生成的HTML表格替换MD文档中"# 报告正文（202x 版）"前的所有内容
    
    当MinerU未识别出表格时，将VLM的表格结果写入MD文档的表格区域，
    使MD显示器能正确展示表格内容。
    
    Args:
        md_content: 原始MD文档内容
        vlm_html_table: VLM生成的HTML表格字符串
        
    Returns:
        str: 替换后的MD内容；若找不到"# 报告正文"标记则返回None
    """
    if not md_content or not vlm_html_table:
        return None
    
    lines = md_content.split('\n')
    report_line_idx = -1
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        if re.match(r'^#+\s*报告正文', stripped, re.IGNORECASE):
            report_line_idx = i
            break
    
    if report_line_idx == -1:
        print(f"[VLM替换] 未找到'# 报告正文'标记行，无法替换")
        return None
    
    # 构建新内容：VLM注释 + VLM表格 + 空行 + 报告正文行及之后的内容
    new_lines = [
        '<!-- VLM表格提取结果（MinerU未识别到表格，已自动使用VLM替换） -->',
        '',
        vlm_html_table,
        '',
    ]
    new_lines.extend(lines[report_line_idx:])
    
    result = '\n'.join(new_lines)
    print(f"[VLM替换] MD内容已替换：原 {len(md_content)} 字符 → 新 {len(result)} 字符")
    return result

# ==================== VLM JSON → MD表格转换结束 ====================


def separate_tables_and_text(md_content):
    """
    从Markdown内容中分离表格和正文
    根据NSFC申请书格式：
    - "(2025版)"后、"# 报告正文"前的所有内容视为表格（不包含这两行标记）
    - "# 报告正文"后的所有内容视为正文（包含该标题行）
    
    参数:
        md_content: 完整的Markdown文档内容
        
    返回:
        tuple: (table_content, text_content)
            - table_content: 表格区域的内容
            - text_content: 正文区域的内容
    """
    if not md_content:
        return "", ""
    
    lines = md_content.split('\n')
    
    # 查找关键标记行
    version_line_idx = -1  # "(2025版)" 所在行
    report_line_idx = -1   # "# 报告正文" 所在行
    
    for i, line in enumerate(lines):
        stripped = line.strip()
        
        # 查找版本标记行（兼容多年份：2025版、2026版等）
        if version_line_idx == -1 and re.search(r'\(20\d{2}版\)', stripped):
            version_line_idx = i
            print(f"[分离] 找到版本标记行: 第{i+1}行 - {stripped}")
        
        # 查找报告正文标记行（兼容带年份后缀：# 报告正文 或 # 报告正文（2026 版））
        if report_line_idx == -1 and re.match(r'^#+\s*报告正文', stripped, re.IGNORECASE):
            report_line_idx = i
            print(f"[分离] 找到报告正文标记行: 第{i+1}行 - {stripped}")
            break  # 找到后就可以停止查找
    
    # 根据标记行划分内容
    table_lines = []
    text_lines = []
    
    # 查找正文区域的结束标记（简历/附件信息/科研诚信承诺 之前截断）
    text_end_idx = len(lines)  # 默认到文档末尾
    if report_line_idx != -1:
        for i in range(report_line_idx + 1, len(lines)):
            stripped = lines[i].strip()
            # 简历行（如 "# 朱毅 ( BRID: ... ) 简历"  或  "卢晶 ( BRID: ... ) 简历"）
            if '简历' in stripped and ('BRID' in stripped or re.search(r'简历', stripped)):
                text_end_idx = i
                print(f"[分离] 找到正文结束标记(简历): 第{i+1}行 - {stripped[:60]}")
                break
            # 附件信息
            if stripped == '附件信息':
                text_end_idx = i
                print(f"[分离] 找到正文结束标记(附件信息): 第{i+1}行")
                break
            # 科研诚信承诺书
            if '科研诚信承诺' in stripped:
                text_end_idx = i
                print(f"[分离] 找到正文结束标记(科研诚信): 第{i+1}行")
                break
    
    if version_line_idx != -1 and report_line_idx != -1:
        # 找到了两个标记，按照规则划分
        # 表格区域: version_line_idx+1 到 report_line_idx-1（不包含两个标记行）
        table_lines = lines[version_line_idx + 1 : report_line_idx]
        # 正文区域: report_line_idx 到正文结束标记（不含简历/附件/承诺）
        text_lines = lines[report_line_idx:text_end_idx]
        
        print(f"[分离] 表格区域: 第{version_line_idx+2}行 到 第{report_line_idx}行，共{len(table_lines)}行")
        print(f"[分离] 正文区域: 第{report_line_idx+1}行 到 第{text_end_idx}行，共{len(text_lines)}行")
    
    elif report_line_idx != -1:
        # 只找到报告正文标记，从该行开始到正文结束标记
        text_lines = lines[report_line_idx:text_end_idx]
        table_lines = lines[:report_line_idx]
        print(f"[分离] 未找到版本标记，以报告正文为分界")
        print(f"[分离] 表格区域: 第1行 到 第{report_line_idx}行，共{len(table_lines)}行")
        print(f"[分离] 正文区域: 第{report_line_idx+1}行 到 第{len(lines)}行，共{len(text_lines)}行")
    
    else:
        # 未找到标记，使用备用策略：检测HTML表格和Markdown表格
        print(f"[分离] 警告: 未找到标准标记行，使用备用分离策略")
        in_html_table = False
        
        for line in lines:
            stripped = line.strip()
            
            # 检测HTML表格开始
            if '<table>' in stripped.lower():
                in_html_table = True
            
            # 如果在HTML表格中
            if in_html_table:
                table_lines.append(line)
                # 检测HTML表格结束
                if '</table>' in stripped.lower():
                    in_html_table = False
            # 检测Markdown表格（以|开头的行）
            elif stripped.startswith('|'):
                table_lines.append(line)
            # 其他都是正文
            else:
                text_lines.append(line)
    
    table_content = '\n'.join(table_lines)
    text_content = '\n'.join(text_lines)
    
    return table_content, text_content


def extract_tables_details(md_content):
    """
    提取表格详细信息
    
    返回字典包含:
        - html_tables: HTML表格列表
        - markdown_tables: Markdown表格列表
        - html_count: HTML表格数量
        - markdown_count: Markdown表格数量
        - total_count: 总表格数量
    """
    # 提取HTML表格
    html_pattern = r'<table>.*?</table>'
    html_tables = re.findall(html_pattern, md_content, re.DOTALL | re.IGNORECASE)
    
    # 提取Markdown表格（连续的以|开头的行）
    markdown_tables = []
    lines = md_content.split('\n')
    current_table = []
    
    for line in lines:
        if line.strip().startswith('|'):
            current_table.append(line)
        else:
            if current_table:
                markdown_tables.append('\n'.join(current_table))
                current_table = []
    
    if current_table:  # 处理最后一个表格
        markdown_tables.append('\n'.join(current_table))
    
    return {
        'html_tables': html_tables,
        'markdown_tables': markdown_tables,
        'html_count': len(html_tables),
        'markdown_count': len(markdown_tables),
        'total_count': len(html_tables) + len(markdown_tables)
    }


def call_llm_for_table_extraction(table_content, api_key, model_name, task_check_func=None, pdf_data=None, progress_callback=None):
    """
    调用LLM进行表格重点提取并转JSON
    
    如果提供了pdf_data，优先使用VLM模型直接从PDF图片提取（更准确）；
    如果VLM失败或未提供pdf_data，回退到传统文本LLM方式。
    
    参数:
        table_content: 表格内容（文本）
        api_key: SiliconFlow API密钥
        model_name: 使用的模型名称（文本LLM回退时使用）
        task_check_func: 任务检查函数
        pdf_data: PDF文件二进制数据（可选，提供时启用VLM优先策略）
        progress_callback: 进度回调函数 callback(progress, message)，进度[0-100]
        
    返回:
        dict: {'success': True/False, 'json_data': {...}, 'error': '...'}
    """
    # === VLM优先策略：如果有PDF原始数据，先尝试VLM（仅Markdown），再交给LLM转JSON ===
    if pdf_data:
        print(f"[表格提取] 检测到PDF原始数据，优先使用VLM模型提取...")
        vlm_result = call_vlm_for_table_extraction(pdf_data, api_key, task_check_func, progress_callback=progress_callback)
        if vlm_result.get('success'):
            vlm_md = vlm_result.get('vlm_md_content', '')
            if vlm_md and len(vlm_md.strip()) > 20:
                print(f"[表格提取] ✅ VLM模型提取Markdown成功，转交LLM进行JSON结构化...")
                llm_result = call_llm_for_table_extraction(
                    table_content=vlm_md,
                    api_key=api_key,
                    model_name='local:' + LOCAL_LLM_CONFIG['model'],
                    task_check_func=task_check_func,
                    pdf_data=None,
                    progress_callback=progress_callback
                )
                if llm_result.get('success'):
                    llm_result['vlm_md_content'] = vlm_md
                    return llm_result
                print(f"[表格提取] ⚠️ VLM->本地LLM转换失败({llm_result.get('error')})，回退到常规文本LLM...")
            else:
                print(f"[表格提取] ⚠️ VLM提取成功但Markdown为空，回退到常规文本LLM...")
        elif vlm_result.get('cancelled'):
            return vlm_result
        else:
            print(f"[表格提取] ⚠️ VLM提取失败({vlm_result.get('error')})，回退到文本LLM...")
    
    # === 回退：使用传统文本LLM方式 ===
    try:
        # 根据model_name判断使用本地LLM还是硅基流动
        api_url, headers, actual_model, server_name = _get_llm_config(api_key, model_name)
        
        system_prompt = """你是一个专业的表格数据分析专家，专门负责将国家自然科学基金申请书的基本信息表格转换为结构化JSON格式。

## 核心任务：
精确提取表格中的所有字段和值，转换为须严格遵守的清晰的JSON结构：

  "项目信息": {
    "亚类说明": "",
    "附注说明": "",
    "项目名称": "...",
    "申请人": "...",
    "办公电话": "...",
    "依托单位": "...",
    "通讯地址": "...",
    "邮政编码": "...",
    "单位电话": "...",
    "电子邮箱": "..."
  },
  "基本信息": {
    "申请人信息": {},
    "依托单位信息": {},
    "合作研究单位信息": {},
    "项目基本信息": {},
    "中文关键词": [],
    "英文关键词": [],
    "中文摘要": "完整的中文摘要...",
    "英文摘要": "完整的英文摘要..."
  }
}

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
严格的JSON格式，不包含任何解释文字或markdown标记。"""

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

        request_data = {
            "model": actual_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.1,
            "max_tokens": _compute_dynamic_max_tokens(
                table_content,
                api_url,
                fallback_max_tokens=4000
            ),
            "top_p": 0.9,
            "stream": False
        }
        
        print(f"[表格提取LLM] 开始调用{server_name}，模型: {actual_model}")
        
        # 发送请求（带完整重试：覆盖超时、网络异常、429限流、5xx服务端错误）
        max_retries = 3
        response = None
        
        for attempt in range(max_retries):
            if task_check_func and task_check_func():
                print(f"[表格提取LLM] 任务已被取消")
                return {'success': False, 'error': '任务已被取消', 'cancelled': True}
            
            try:
                if attempt > 0:
                    retry_delay = min(5 * (2 ** (attempt - 1)), 30)  # 指数退避: 5s, 10s, 20s...
                    print(f"[表格提取LLM] 第{attempt + 1}次重试（等待{retry_delay}s）...")
                    time.sleep(retry_delay)
                
                # 本地LLM并发控制：限制同时请求数防止GPU OOM
                _llm_acquired = False
                try:
                    if _is_local_llm(api_url):
                        _local_llm_semaphore.acquire()
                        _llm_acquired = True
                        time.sleep(1)  # 增加1秒请求间隔，缓解瞬时高负载
                    response = requests.post(
                        api_url,
                        json=request_data,
                        headers=headers,
                        timeout=_get_llm_request_timeout(api_url)
                    )
                finally:
                    if _llm_acquired:
                        _local_llm_semaphore.release()
                
                # 在循环内检查状态码，可恢复错误触发重试
                if response.status_code == 200:
                    break  # 成功，跳出重试循环
                elif response.status_code == 429:
                    wait = min(10 * (2 ** attempt), 60)
                    print(f"[表格提取LLM] ⚠️ API限流(429)，等待{wait}s后重试...")
                    time.sleep(wait)
                    continue
                elif response.status_code in (500, 502, 503, 504):
                    print(f"[表格提取LLM] ⚠️ 服务端错误(HTTP {response.status_code})，重试中...")
                    continue
                else:
                    # 4xx客户端错误（非429），不可恢复，直接失败
                    return {'success': False, 'error': f'API请求失败，状态码: {response.status_code}'}
                
            except requests.exceptions.Timeout:
                print(f"[表格提取LLM] ⚠️ 请求超时（attempt {attempt + 1}/{max_retries}）")
                if attempt == max_retries - 1:
                    return {'success': False, 'error': 'API请求超时（已重试3次）'}
                continue
            except requests.exceptions.RequestException as e:
                print(f"[表格提取LLM] ⚠️ 网络异常（attempt {attempt + 1}/{max_retries}）: {str(e)[:100]}")
                if attempt == max_retries - 1:
                    return {'success': False, 'error': f'网络请求失败: {str(e)}'}
                continue
        
        if response is None or response.status_code != 200:
            status = response.status_code if response else 'no response'
            return {'success': False, 'error': f'API请求失败，状态码: {status}（已重试{max_retries}次）'}
        
        response_data = response.json()
        
        if 'choices' not in response_data or not response_data['choices']:
            return {'success': False, 'error': 'API响应格式错误'}
        
        ai_content = response_data['choices'][0]['message']['content'].strip()
        
        print(f"[表格提取LLM] API返回内容长度: {len(ai_content)}")
        
        # 解析JSON
        json_match = re.search(r'\{.*\}', ai_content, re.DOTALL)
        if json_match:
            ai_content = json_match.group()
        
        # 清理markdown标记
        if ai_content.startswith('```json'):
            ai_content = ai_content[7:]
        if ai_content.startswith('```'):
            ai_content = ai_content[3:]
        if ai_content.endswith('```'):
            ai_content = ai_content[:-3]
        
        ai_content = ai_content.strip()
        
        # 使用安全解析函数，带自动修复
        json_data = safe_json_parse(ai_content)
        
        print(f"[表格提取LLM] JSON解析成功，包含 {len(json_data)} 个顶层键")
        
        # 硬编码补救：确保JSON结构完整性（函数在本模块内）
        json_data = ensure_complete_json_structure(json_data)
        print(f"[表格提取LLM] 补救完成，最终包含 {len(json_data)} 个顶层键")
        
        return {'success': True, 'json_data': json_data}
        
    except json.JSONDecodeError as e:
        print(f"[表格提取LLM] JSON解析错误: {e}")
        return {'success': False, 'error': f'JSON解析失败: {str(e)}'}
    except Exception as e:
        print(f"[表格提取LLM] 处理错误: {e}")
        return {'success': False, 'error': str(e)}


def call_llm_for_text_extraction(text_content, api_key, model_name, task_check_func=None, progress_callback=None):
    """
    调用LLM进行正文重点提取并转JSON
    
    参数:
        text_content: 正文内容
        api_key: SiliconFlow API密钥
        model_name: 使用的模型名称
        task_check_func: 任务检查函数
        progress_callback: 进度回调函数
        
    返回:
        dict: {'success': True/False, 'json_data': {...}, 'error': '...'}
    """
    try:
        # 根据model_name判断使用本地LLM还是硅基流动
        api_url, headers, actual_model, server_name = _get_llm_config(api_key, model_name)
        
        system_prompt = """你是一个专业的文档分析专家，专门负责整理层级有轻微问题的国家自然科学基金申请书的正文章节层次，转换为结构化JSON格式，同时进行内容的简单评估。
        我传给你的是已经分割好的章节片段！
## 核心任务：
1. **保留或优化标题层次结构**：
   最多五级标题，
   一级标题一定具有“（一）”或“（二）”或“（三）”序号，标题文本一般为：立项依据、研究内容、研究基础，可能组合出现也可能单独出现；
   二级、三级均不确定；
   标题判断与是否是段落开头无关，仅与结构相关，有时候标题可能缺少“#”或序号或末尾的“；”or“：”，需要你分析出标题层级并进行修正。
   转换为须严格遵守的清晰的JSON结构。
2. **同时评估新模板要求（在JSON中添加"_content_quality_check"字段）**：
   - rule_4_1_1: 如果有立项依据章节，评估是否说清楚"为什么要开展此项研究，研究的价值何在"
   - rule_4_1_2: 如果有研究内容章节，评估是否根据自己的研究思路和逻辑自主撰写（而非套用固定模板）
   - rule_4_1_3: 如果有研究基础章节，评估是否展示了前期的工作积累
   （ **重要**：如果某个章节不存在于当前内容中，该规则状态应为"not_applicable"）

## 处理原则：
1. **完整性**：必须保留原文序号！！！必须保留全部标题文字！！！必须保留全部段落文字！！！
2. **层次性**：不要将段落首句误认为标题！必须根据行文逻辑或原文编号思路思考标题层级！！！保持原文的章节结构！！！
3. **结构化**：使用清晰的JSON格式组织
4. **质量评估**：评估新模板三点要求（rule_4_1_1/2/3），给出是否符合的判断

## 输出格式：
严格的JSON格式，包含：
1. 正文各章节的提取内容
示例（序号不一定是这样的）：
```json
{
  "（一）立项依据": {
    "1.研究背景": {
      "研究现状": "...",  // 三级标题，无序号
      "存在问题": "..."   // 三级标题，无序号
    },
    "2.研究意义": "..."
  }
}
```
2. _content_quality_check 字段（注意：此字段以下划线开头，会被前端过滤不显示），包含三条评估结果：
   - rule_4_1_1: {status: "passed"/"failed"/"not_applicable", reason: "详细评估原因或说明章节不存在"}
   - rule_4_1_2: {status: "passed"/"failed"/"not_applicable", reason: "详细评估原因或说明章节不存在"}
   - rule_4_1_3: {status: "passed"/"failed"/"not_applicable", reason: "详细评估原因或说明章节不存在"}

不要有markdown标记。"""

        # 导入分割函数（补救函数已在本模块内）
        from app_pdf_md import split_report_text_by_sections
        
        # 分割为多个section
        sections = split_report_text_by_sections(text_content)
        
        if not sections:
            print(f"[正文提取LLM] 未找到章节标记，将整体处理")
            sections = [{'section_id': '完整正文', 'title': '报告正文', 'content': text_content}]
        
        print(f"[正文提取LLM] 分割为 {len(sections)} 个章节")
        
        # 第一步：从原始文本提取标题序号映射
        print(f"[正文提取LLM] 开始从原文提取标题序号映射...")
        heading_map = extract_heading_numbers_from_markdown(text_content)
        print(f"[正文提取LLM] 提取到 {len(heading_map)} 个标题映射")
        
        # 计算每个批次的进度范围（40%-100%）
        batch_progress_start = 40
        batch_progress_range = 60
        batch_progress_per_section = batch_progress_range / len(sections) if sections else 0
        
        # #5/#20 并行处理各section（max_workers=3）
        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        progress_lock = threading.Lock()
        completed_count = [0]  # 用列表以便在闭包中修改
        
        def process_one_section(idx, section):
            """处理单个section的LLM调用（线程安全）"""
            if task_check_func and task_check_func():
                return None, '任务已被取消'
            
            section_id = section['section_id']
            section_content = section['content']
            
            print(f"[正文提取LLM] 开始处理章节 {idx}/{len(sections)} ({section_id})")
            
            user_prompt = f"""请从以下国家自然科学基金申请书正文章节中提取信息并转为JSON格式，同时评估新模板要求：

正文内容：
{section_content}

要求：
1. 根据文章逻辑优化标题层级
2. 保持原文的逻辑结构
3. 使用中文键名
4. 添加 _content_quality_check 字段评估新模板要求（如果某章节不存在，该规则标记为not_applicable）
5. 输出标准JSON格式

请直接输出JSON结果："""

            request_data = {
                "model": actual_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                "temperature": 0.2,
                "max_tokens": _compute_dynamic_max_tokens(
                    section_content,
                    api_url,
                    fallback_max_tokens=6000
                ),
                "top_p": 0.9,
                "stream": False
            }
            
            # JSON质量重试：如果LLM返回的内容无法解析为JSON，重新请求（最多2次）
            max_json_attempts = 2
            section_json = None
            last_json_error = None
            
            for json_attempt in range(max_json_attempts):
                if json_attempt > 0:
                    print(f"[正文提取LLM] 章节 {section_id} JSON解析失败，第{json_attempt + 1}次尝试...")
                
                # 发送请求（带完整重试：覆盖超时、网络异常、429限流、5xx服务端错误）
                max_retries = 3
                response = None
                
                for attempt in range(max_retries):
                    if task_check_func and task_check_func():
                        return None, '任务已被取消'
                    
                    try:
                        if attempt > 0:
                            retry_delay = min(5 * (2 ** (attempt - 1)), 30)
                            print(f"[正文提取LLM] 章节 {section_id} 第{attempt + 1}次重试（等待{retry_delay}s）...")
                            time.sleep(retry_delay)
                        
                        # 本地LLM并发控制：限制同时请求数防止GPU OOM
                        _llm_acquired = False
                        try:
                            if _is_local_llm(api_url):
                                _local_llm_semaphore.acquire()
                                _llm_acquired = True
                            response = requests.post(
                                api_url,
                                json=request_data,
                                headers=headers,
                                timeout=_get_llm_request_timeout(api_url)
                            )
                        finally:
                            if _llm_acquired:
                                _local_llm_semaphore.release()
                        
                        if response.status_code == 200:
                            break
                        elif response.status_code == 429:
                            wait = min(10 * (2 ** attempt), 60)
                            print(f"[正文提取LLM] 章节 {section_id} ⚠️ API限流(429)，等待{wait}s后重试...")
                            time.sleep(wait)
                            continue
                        elif response.status_code in (500, 502, 503, 504):
                            print(f"[正文提取LLM] 章节 {section_id} ⚠️ 服务端错误(HTTP {response.status_code})，重试中...")
                            continue
                        else:
                            return None, f'章节 {section_id} API请求失败，状态码: {response.status_code}'
                        
                    except requests.exceptions.Timeout:
                        print(f"[正文提取LLM] 章节 {section_id} ⚠️ 请求超时（attempt {attempt + 1}/{max_retries}）")
                        if attempt == max_retries - 1:
                            return None, f'章节 {section_id} API请求超时（已重试3次）'
                        continue
                    except requests.exceptions.RequestException as e:
                        print(f"[正文提取LLM] 章节 {section_id} ⚠️ 网络异常（attempt {attempt + 1}/{max_retries}）: {str(e)[:100]}")
                        if attempt == max_retries - 1:
                            return None, f'章节 {section_id} 网络请求失败: {str(e)}'
                        continue
                
                if response is None or response.status_code != 200:
                    status = response.status_code if response else 'no response'
                    return None, f'章节 {section_id} API请求失败，状态码: {status}（已重试{max_retries}次）'
                
                response_data = response.json()
                
                if 'choices' not in response_data or not response_data['choices']:
                    return None, f'章节 {section_id} API响应格式错误'
                
                ai_content = response_data['choices'][0]['message']['content'].strip()
                finish_reason = response_data['choices'][0].get('finish_reason', '')
                
                # 解析JSON
                json_match = re.search(r'\{.*\}', ai_content, re.DOTALL)
                if json_match:
                    ai_content = json_match.group()
                
                # 清理markdown标记
                if ai_content.startswith('```json'):
                    ai_content = ai_content[7:]
                if ai_content.startswith('```'):
                    ai_content = ai_content[3:]
                if ai_content.endswith('```'):
                    ai_content = ai_content[:-3]
                
                ai_content = ai_content.strip()
                
                # 使用安全解析函数，带自动修复
                try:
                    section_json = safe_json_parse(ai_content)
                    break  # JSON解析成功，退出重试循环
                except json.JSONDecodeError as e:
                    last_json_error = str(e)
                    print(f"[正文提取LLM] 章节 {section_id} JSON解析失败 (attempt {json_attempt + 1}/{max_json_attempts}), finish_reason={finish_reason}: {e}")
                    if json_attempt < max_json_attempts - 1:
                        print(f"[正文提取LLM] 章节 {section_id} 将重新请求LLM...")
                    else:
                        with open(f'debug_json_error_section_{section_id}.txt', 'w', encoding='utf-8') as f:
                            f.write(ai_content)
            
            if section_json is None:
                return None, f'章节 {section_id} JSON解析失败（已重试{max_json_attempts}次）: {last_json_error}'
            
            # 线程安全的进度更新
            with progress_lock:
                completed_count[0] += 1
                current_progress = batch_progress_start + completed_count[0] * batch_progress_per_section
                progress_message = f"正文提取：已完成 {completed_count[0]}/{len(sections)} 个章节"
                print(f"[正文提取LLM] {progress_message}，进度: {int(current_progress)}%")
                if progress_callback:
                    progress_callback(int(current_progress), progress_message)
            
            return {
                'section_id': section_id,
                'title': section.get('title', ''),
                'data': section_json
            }, None
        
        # 分章节执行LLM调用（本地模型通常串行，远端最多3线程）
        all_section_jsons = []
        section_error = None
        
        # 本地LLM强制串行，避免章节并发导致超时
        max_concurrent = 1 if (model_name and model_name.startswith('local:')) else 3
        max_workers = min(max_concurrent, len(sections))
        print(f"[正文提取LLM] 启动 {max_workers} 个处理线程，章节数: {len(sections)}")
        
        if progress_callback:
            progress_callback(int(batch_progress_start), f'正文提取：开始处理 {len(sections)} 个章节...')
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 提交所有任务，保持顺序映射
            future_to_idx = {}
            for idx, section in enumerate(sections, 1):
                future = executor.submit(process_one_section, idx, section)
                future_to_idx[future] = idx
            
            # 收集结果（按完成顺序）
            results_by_idx = {}
            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    result, error = future.result()
                    if error:
                        section_error = error
                        if '取消' in error:
                            # 取消所有剩余任务
                            for f in future_to_idx:
                                f.cancel()
                            break
                    else:
                        results_by_idx[idx] = result
                except Exception as e:
                    section_error = f'章节处理异常: {str(e)}'
                    print(f"[正文提取LLM] 线程异常: {e}")
        
        if section_error and '取消' in section_error:
            return {'success': False, 'error': section_error, 'cancelled': True}
        
        if section_error and not results_by_idx:
            return {'success': False, 'error': section_error}
        
        # 按原始顺序排列结果
        for idx in sorted(results_by_idx.keys()):
            all_section_jsons.append(results_by_idx[idx])
        
        print(f"[正文提取LLM] 章节处理完成，成功 {len(all_section_jsons)}/{len(sections)} 个章节")
        
        # 合并所有section的JSON
        print(f"[正文提取LLM] 开始合并 {len(all_section_jsons)} 个章节的JSON")
        merged_json = {}
        
        def smart_merge(target, source, path=""):
            """智能合并JSON，避免重复和覆盖"""
            for key, value in source.items():
                # 跳过下划线字段
                if key.startswith('_'):
                    if key not in target:  # 只保留第一次出现的
                        target[key] = value
                    continue
                
                if key in target:
                    # 键已存在，需要合并
                    if isinstance(target[key], dict) and isinstance(value, dict):
                        # 递归合并字典
                        smart_merge(target[key], value, f"{path}/{key}")
                    elif isinstance(target[key], list) and isinstance(value, list):
                        # 合并列表，去重
                        for item in value:
                            if item not in target[key]:
                                target[key].append(item)
                    elif isinstance(target[key], str) and isinstance(value, str):
                        # 字符串：如果内容不同，拼接（避免完全覆盖）
                        if target[key] != value and value not in target[key]:
                            print(f"[正文提取LLM] 警告：检测到重复键但内容不同 '{path}/{key}'")
                            # 保留较长的内容
                            if len(value) > len(target[key]):
                                target[key] = value
                    else:
                        # 其他情况：保留后出现的值
                        print(f"[正文提取LLM] 警告：键冲突 '{path}/{key}'，保留后出现的值")
                        target[key] = value
                else:
                    target[key] = value
        
        for section_info in all_section_jsons:
            section_data = section_info['data']
            if isinstance(section_data, dict):
                smart_merge(merged_json, section_data)
        
        print(f"[正文提取LLM] JSON合并完成，包含 {len(merged_json)} 个顶层键")
        
        # 提取质量检查数据（在normalize之前，因为normalize会删除下划线字段）
        quality_check_data = None
        if '_content_quality_check' in merged_json:
            quality_check_data = merged_json['_content_quality_check']
            print(f"[正文提取LLM] 提取到质量检查数据: {len(quality_check_data)} 条规则")
        
        # 第二步：硬编码补救，使用heading_map标准化正文JSON标题序号
        # 一级标题强制（一）（二）（三），二级及以下使用原文序号
        print(f"[正文提取LLM] 开始第一次编号（使用原文序号映射）...")
        merged_json = normalize_content_json_headings(merged_json, heading_map=heading_map)
        print(f"[正文提取LLM] 第一次编号完成")
        
        # 第三步：第二次编号，统一同层级序号格式，检查连贯性
        print(f"[正文提取LLM] 开始第二次编号（同层级统一+连贯性检查）...")
        merged_json = unify_level_numbering(merged_json)
        print(f"[正文提取LLM] 第二次编号完成")
        
        # 完成时更新到99%，最终100%由外层落库完成后统一给出。
        if progress_callback:
            progress_callback(99, "正文提取：完成")
        
        # 返回结果，包含质量检查数据
        result = {'success': True, 'json_data': merged_json}
        if quality_check_data:
            result['quality_check'] = quality_check_data
        
        return result
        
    except json.JSONDecodeError as e:
        print(f"[正文提取LLM] JSON解析错误: {e}")
        return {'success': False, 'error': f'JSON解析失败: {str(e)}'}
    except Exception as e:
        print(f"[正文提取LLM] 处理错误: {e}")
        return {'success': False, 'error': str(e)}
