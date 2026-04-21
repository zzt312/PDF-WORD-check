#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库连接日志清理脚本
自动替换噪音日志为智能日志
"""

import os
import re
import glob
from typing import List, Dict
from datetime import datetime

class DatabaseLogCleaner:
    """数据库日志清理器"""
    
    def __init__(self, workspace_path: str):
        self.workspace_path = workspace_path
        self.patterns_to_replace = {
            # 数据库连接成功日志
            r'print\s*\(\s*["\']数据库连接成功[^"\']*["\'].*?\)': 
                'smart_print("数据库连接成功", LogLevel.NOISE)',
            
            # 通用数据库连接状态
            r'print\s*\(\s*["\'].*?连接.*?成功.*?["\'].*?\)':
                'smart_print("数据库连接状态", LogLevel.NOISE)',
            
            # 查询执行日志
            r'print\s*\(\s*["\']执行查询.*?["\'].*?\)':
                'smart_print("执行数据库查询", LogLevel.DEBUG)',
            
            # cursor相关日志
            r'print\s*\(\s*["\'].*?cursor.*?["\'].*?\)':
                'smart_print("数据库游标操作", LogLevel.NOISE)',
            
            # SELECT 1 测试查询
            r'print\s*\(\s*["\'].*?SELECT\s+1.*?["\'].*?\)':
                'smart_print("数据库连接测试", LogLevel.NOISE)',
        }
        
        self.files_to_process = [
            '*.py'
        ]
        
        self.changes_made = {}
    
    def find_python_files(self) -> List[str]:
        """查找所有Python文件"""
        python_files = []
        for pattern in self.files_to_process:
            files = glob.glob(os.path.join(self.workspace_path, '**', pattern), recursive=True)
            python_files.extend(files)
        return python_files
    
    def analyze_file(self, file_path: str) -> Dict[str, List[str]]:
        """分析文件中的日志模式"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except:
            try:
                with open(file_path, 'r', encoding='gbk') as f:
                    content = f.read()
            except Exception as e:
                print(f"无法读取文件 {file_path}: {e}")
                return {}
        
        matches = {}
        for pattern, replacement in self.patterns_to_replace.items():
            found = re.findall(pattern, content, re.MULTILINE | re.IGNORECASE)
            if found:
                matches[pattern] = found
        
        return matches
    
    def clean_file(self, file_path: str, dry_run: bool = True) -> bool:
        """清理单个文件"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                original_content = f.read()
        except:
            try:
                with open(file_path, 'r', encoding='gbk') as f:
                    original_content = f.read()
            except Exception as e:
                print(f"无法读取文件 {file_path}: {e}")
                return False
        
        content = original_content
        changes = []
        
        for pattern, replacement in self.patterns_to_replace.items():
            matches = re.findall(pattern, content, re.MULTILINE | re.IGNORECASE)
            if matches:
                content = re.sub(pattern, replacement, content, flags=re.MULTILINE | re.IGNORECASE)
                changes.extend(matches)
        
        if changes:
            self.changes_made[file_path] = changes
            
            if not dry_run:
                # 确保导入smart_logger
                if 'from smart_logger import smart_print, LogLevel' not in content:
                    # 在文件开头添加导入
                    import_line = 'from smart_logger import smart_print, LogLevel\n'
                    if content.startswith('#!/'):
                        lines = content.split('\n')
                        # 找到第一个非shebang行
                        insert_pos = 1
                        while insert_pos < len(lines) and lines[insert_pos].startswith('#'):
                            insert_pos += 1
                        lines.insert(insert_pos, import_line)
                        content = '\n'.join(lines)
                    else:
                        content = import_line + content
                
                # 写回文件
                try:
                    with open(file_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    print(f"✅ 已清理: {os.path.basename(file_path)} ({len(changes)} 处修改)")
                except Exception as e:
                    print(f"❌ 写入失败 {file_path}: {e}")
                    return False
            else:
                print(f"🔍 发现: {os.path.basename(file_path)} ({len(changes)} 处需要修改)")
        
        return len(changes) > 0
    
    def clean_all_files(self, dry_run: bool = True):
        """清理所有文件"""
        python_files = self.find_python_files()
        
        print(f"智能日志清理器")
        print(f"{'='*50}")
        print(f"模式: {'预览' if dry_run else '执行'}")
        print(f"目标路径: {self.workspace_path}")
        print(f"发现 {len(python_files)} 个Python文件")
        print()
        
        modified_files = 0
        total_changes = 0
        
        for file_path in python_files:
            if self.clean_file(file_path, dry_run):
                modified_files += 1
                total_changes += len(self.changes_made.get(file_path, []))
        
        print()
        print(f"结果统计:")
        print(f"  受影响文件: {modified_files}")
        print(f"  总计修改: {total_changes}")
        
        if dry_run:
            print()
            print("📋 详细预览:")
            for file_path, changes in self.changes_made.items():
                print(f"\n📁 {os.path.basename(file_path)}:")
                for change in changes[:3]:  # 只显示前3个
                    print(f"  - {change[:80]}...")
                if len(changes) > 3:
                    print(f"  ... 还有 {len(changes) - 3} 处修改")
        
        return modified_files, total_changes
    
    def generate_report(self) -> str:
        """生成清理报告"""
        report = []
        report.append("数据库日志清理报告")
        report.append("=" * 40)
        report.append(f"处理时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"处理文件数: {len(self.changes_made)}")
        
        total_changes = sum(len(changes) for changes in self.changes_made.values())
        report.append(f"总计修改: {total_changes}")
        report.append("")
        
        for file_path, changes in self.changes_made.items():
            report.append(f"文件: {os.path.basename(file_path)}")
            report.append(f"修改数: {len(changes)}")
            for change in changes[:2]:  # 只显示前2个
                report.append(f"  - {change}")
            if len(changes) > 2:
                report.append(f"  ... 还有 {len(changes) - 2} 处")
            report.append("")
        
        return "\n".join(report)

def main():
    """主函数"""
    import sys
    from datetime import datetime
    
    workspace = r"c:\Users\15950\Desktop\check_markdown"
    cleaner = DatabaseLogCleaner(workspace)
    
    print("🧹 数据库日志智能清理工具")
    print("=" * 50)
    
    # 首先预览
    print("第一步: 分析预览")
    modified_files, total_changes = cleaner.clean_all_files(dry_run=True)
    
    if total_changes == 0:
        print("✅ 没有发现需要清理的日志")
        return
    
    print(f"\n发现 {total_changes} 处需要清理的日志")
    
    # 询问是否执行
    if len(sys.argv) > 1 and sys.argv[1] == '--execute':
        execute = True
    else:
        response = input("\n是否执行清理? (y/N): ").strip().lower()
        execute = response in ['y', 'yes', '是']
    
    if execute:
        print("\n第二步: 执行清理")
        cleaner.changes_made.clear()  # 重置记录
        modified_files, total_changes = cleaner.clean_all_files(dry_run=False)
        
        print(f"\n✅ 清理完成!")
        print(f"   修改文件: {modified_files}")
        print(f"   总计修改: {total_changes}")
        
        # 生成报告
        report = cleaner.generate_report()
        report_file = os.path.join(workspace, "log_cleanup_report.txt")
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(report)
        print(f"   报告保存: {report_file}")
    else:
        print("\n取消执行，仅完成预览分析")

if __name__ == "__main__":
    main()
