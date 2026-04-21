"""
环境变量加载器 - 支持从.env文件加载配置
"""

import os
from pathlib import Path

def load_env_file(env_file_path=None):
    """
    加载.env文件中的环境变量
    
    Args:
        env_file_path: .env文件路径，默认为当前目录下的.env文件
    """
    if env_file_path is None:
        env_file_path = Path(__file__).parent / '.env'
    
    if not os.path.exists(env_file_path):
        print(f"警告: 环境变量文件 {env_file_path} 不存在")
        return
    
    try:
        with open(env_file_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # 跳过空行和注释行
                if not line or line.startswith('#'):
                    continue
                
                # 解析key=value格式
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # 移除引号
                    if value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    elif value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    
                    # 只有在环境变量不存在时才设置
                    if key not in os.environ:
                        os.environ[key] = value
        
        print(f"成功加载环境变量文件: {env_file_path}")
        
    except Exception as e:
        print(f"加载环境变量文件失败: {e}")

def get_env_var(key, default=None, var_type=str):
    """
    获取环境变量并转换类型
    
    Args:
        key: 环境变量名
        default: 默认值
        var_type: 变量类型（str, int, bool等）
    
    Returns:
        转换后的环境变量值
    """
    value = os.getenv(key, default)
    
    if value is None:
        return None
    
    if var_type == bool:
        return str(value).lower() in ('true', '1', 'yes', 'on')
    elif var_type == int:
        try:
            return int(value)
        except ValueError:
            return default
    elif var_type == float:
        try:
            return float(value)
        except ValueError:
            return default
    else:
        return str(value)

# 在应用启动时自动加载环境变量
load_env_file()
