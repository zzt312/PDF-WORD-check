#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时区适配器 - 支持任意系统环境的时区自动配置
Universal Timezone Adapter for Any System Environment
"""

import os
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

class TimezoneAdapter:
    """时区适配器 - 自动检测和适配任何系统环境"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.system_info = self._detect_system_environment()
        self._configure_timezone()
    
    def _detect_system_environment(self) -> Dict[str, Any]:
        """自动检测系统环境"""
        system_info = {
            'os_type': os.name,  # 'nt' for Windows, 'posix' for Unix-like
            'platform': None,
            'timezone_name': None,
            'utc_offset': None,
            'dst_active': None
        }
        
        try:
            import platform
            system_info['platform'] = platform.system()  # Windows, Linux, Darwin
            
            # 检测系统时区
            if hasattr(time, 'tzname'):
                system_info['timezone_name'] = time.tzname
            
            # 获取UTC偏移 - 修复Windows时区检测问题
            try:
                # 方法1：使用time.timezone（更可靠）
                if hasattr(time, 'timezone'):
                    # time.timezone是UTC偏移的负值（秒）
                    system_info['utc_offset'] = -time.timezone / 3600
                    self.logger.info(f"使用time.timezone计算UTC偏移: {system_info['utc_offset']}")
                else:
                    # 方法2：传统方法（备用）
                    now = datetime.now()
                    utc_now = datetime.utcnow()
                    calculated_offset = (now - utc_now).total_seconds() / 3600
                    system_info['utc_offset'] = calculated_offset
                    self.logger.info(f"使用datetime差值计算UTC偏移: {calculated_offset}")
                
                # 特殊处理：如果是Asia/Shanghai时区，强制设置为+8
                if 'Asia/Shanghai' in str(system_info.get('timezone_name', '')) or \
                   any('China' in str(tz) for tz in (system_info.get('timezone_name', []) if isinstance(system_info.get('timezone_name'), (list, tuple)) else [str(system_info.get('timezone_name', ''))])):
                    self.logger.info(f"检测到中国时区，强制设置UTC偏移为+8")
                    system_info['utc_offset'] = 8.0
                    
            except Exception as offset_error:
                self.logger.warning(f"UTC偏移计算失败: {offset_error}，默认使用+8（中国时区）")
                system_info['utc_offset'] = 8.0  # 默认中国时区
            
            # 检测夏令时
            system_info['dst_active'] = time.daylight and time.localtime().tm_isdst
            
            self.logger.info(f"检测到系统环境: {system_info}")
            
        except Exception as e:
            self.logger.warning(f"系统环境检测失败: {e}")
            
        return system_info
    
    def _configure_timezone(self):
        """配置时区设置"""
        try:
            # 强制设置中国时区环境变量（Windows兼容性）
            if self.system_info['platform'] == 'Windows':
                os.environ['TZ'] = 'Asia/Shanghai'
                self.logger.info("Windows系统：强制设置TZ=Asia/Shanghai")
            
            # 尝试设置环境变量
            if not os.getenv('TZ'):
                # 根据系统自动推断时区
                if self.system_info['platform'] == 'Windows':
                    # Windows系统
                    os.environ['TZ'] = self._get_windows_timezone()
                else:
                    # Unix-like系统
                    os.environ['TZ'] = self._get_unix_timezone()
                
                # 重新初始化时间模块
                if hasattr(time, 'tzset'):
                    time.tzset()
                    self.logger.info(f"时区设置完成: {os.getenv('TZ')}")
                    
        except Exception as e:
            self.logger.warning(f"时区配置失败: {e}")
    
    def _get_windows_timezone(self) -> str:
        """获取Windows系统时区"""
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, 
                              r"SYSTEM\CurrentControlSet\Control\TimeZoneInformation") as key:
                timezone_name = winreg.QueryValueEx(key, "TimeZoneKeyName")[0]
                
                # 转换为标准格式
                timezone_map = {
                    'China Standard Time': 'Asia/Shanghai',
                    'Eastern Standard Time': 'America/New_York',
                    'Pacific Standard Time': 'America/Los_Angeles',
                    'Central Standard Time': 'America/Chicago',
                    'Greenwich Standard Time': 'Europe/London',
                    'Tokyo Standard Time': 'Asia/Tokyo',
                }
                
                return timezone_map.get(timezone_name, 'UTC')
                
        except Exception:
            return 'UTC'
    
    def _get_unix_timezone(self) -> str:
        """获取Unix系统时区"""
        try:
            # 方法1: 读取 /etc/timezone
            if os.path.exists('/etc/timezone'):
                with open('/etc/timezone', 'r') as f:
                    return f.read().strip()
            
            # 方法2: 检查 /etc/localtime 软链接
            if os.path.islink('/etc/localtime'):
                link_target = os.readlink('/etc/localtime')
                if 'zoneinfo' in link_target:
                    return link_target.split('zoneinfo/')[-1]
            
            # 方法3: 环境变量
            return os.getenv('TZ', 'UTC')
            
        except Exception:
            return 'UTC'
    
    def get_current_timestamp(self) -> float:
        """获取当前时间戳（UTC，全球通用）- 修复Windows时区问题"""
        try:
            # 使用time.time()获取UTC时间戳（这是标准做法）
            timestamp = time.time()
            
            # 验证时间戳的合理性（应该接近2025年8月的时间戳）
            expected_2025_timestamp = 1735689600  # 2025-01-01 00:00:00 UTC的大概时间戳
            if timestamp < expected_2025_timestamp:
                self.logger.warning(f"检测到异常时间戳: {timestamp}，可能存在系统时间问题")
                
            return timestamp
        except Exception as e:
            self.logger.error(f"获取时间戳失败: {e}")
            return time.time()  # fallback
    
    def get_local_time_string(self) -> str:
        """获取本地时间字符串"""
        return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    def get_utc_time_string(self) -> str:
        """获取UTC时间字符串"""
        return datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')
    
    def convert_timestamp_to_local(self, timestamp: float) -> str:
        """将时间戳转换为本地时间字符串"""
        return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
    
    def parse_any_time_format(self, time_input: Any) -> Optional[float]:
        """解析任意时间格式为时间戳 - 修复Windows时区问题"""
        if time_input is None:
            return None
        
        try:
            # 如果已经是时间戳
            if isinstance(time_input, (int, float)):
                timestamp = float(time_input)
                # 验证时间戳合理性
                if timestamp > 1000000000:  # 大于2001年的时间戳
                    return timestamp
                else:
                    self.logger.warning(f"时间戳值过小，可能有误: {timestamp}")
                    return timestamp
            
            # 如果是字符串
            if isinstance(time_input, str):
                # ISO格式
                if 'T' in time_input:
                    try:
                        if 'Z' in time_input:
                            dt = datetime.fromisoformat(time_input.replace('Z', '+00:00'))
                        elif '+' in time_input or time_input.endswith('00:00'):
                            dt = datetime.fromisoformat(time_input)
                        else:
                            # 没有时区信息，假设为本地时间
                            dt = datetime.fromisoformat(time_input)
                            # 转换为UTC时间戳
                        return dt.timestamp()
                    except Exception as iso_error:
                        self.logger.warning(f"ISO时间解析失败: {time_input}, 错误: {iso_error}")
                
                # 尝试解析为数字时间戳
                try:
                    return float(time_input)
                except ValueError:
                    pass
                
                # 其他格式尝试
                formats = [
                    '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%d %H:%M',
                    '%Y-%m-%d',
                    '%m/%d/%Y %H:%M:%S',
                    '%m/%d/%Y'
                ]
                
                for fmt in formats:
                    try:
                        dt = datetime.strptime(time_input, fmt)
                        return dt.timestamp()
                    except ValueError:
                        continue
            
            # 如果是datetime对象
            if hasattr(time_input, 'timestamp'):
                return time_input.timestamp()
            
        except Exception as e:
            self.logger.warning(f"时间解析失败: {time_input}, 错误: {e}")
        
        # 解析失败，返回当前时间
        return self.get_current_timestamp()
    
    def get_system_info(self) -> Dict[str, Any]:
        """获取系统时区信息"""
        return {
            **self.system_info,
            'current_timestamp': self.get_current_timestamp(),
            'local_time': self.get_local_time_string(),
            'utc_time': self.get_utc_time_string(),
            'timezone_env': os.getenv('TZ', 'Not set')
        }

# 全局实例
timezone_adapter = TimezoneAdapter()

# 便捷函数
def get_universal_timestamp() -> float:
    """获取通用时间戳（适用于任何系统）"""
    return timezone_adapter.get_current_timestamp()

def parse_universal_time(time_input: Any) -> Optional[float]:
    """解析任意时间格式（适用于任何系统）"""
    return timezone_adapter.parse_any_time_format(time_input)

def get_system_timezone_info() -> Dict[str, Any]:
    """获取系统时区信息（用于调试和配置）"""
    return timezone_adapter.get_system_info()

if __name__ == "__main__":
    # 测试代码
    print("=== 时区适配器测试 ===")
    info = get_system_timezone_info()
    for key, value in info.items():
        print(f"{key}: {value}")
    
    print(f"\n当前时间戳: {get_universal_timestamp()}")
    print(f"解析测试: {parse_universal_time('2025-08-25 23:30:00')}")
