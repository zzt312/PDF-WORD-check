"""
标题优化处理器模块
专门处理国家自然基金申请书格式的标题优化和内容提取
"""

import re
import traceback
from typing import List


class TitleEnhancer:
    """标题优化处理器 - 专门处理国家自然基金申请书格式"""
    
    @staticmethod
    def extract_important_content(content: str) -> str:
        """提取重要内容：保留申请书核心内容，过滤承诺书和简历等附加内容"""
        try:
            lines = content.split('\n')
            start_idx = -1
            end_idx = len(lines)
            
            # 寻找申请书开始位置
            for i, line in enumerate(lines):
                line_stripped = line.strip()
                # 寻找申请书标题或第一个实际内容标题
                if (re.search(r'^\s*#+\s*申请书\s*$', line_stripped) or
                    re.search(r'^\s*#+\s*国家自然科学基金\s*$', line_stripped) or
                    re.search(r'^\s*#+\s*基本信息\s*$', line_stripped) or
                    (i < 50 and line_stripped.startswith('#') and len(line_stripped) > 5)):
                    start_idx = i
                    print(f"[重要内容提取] 找到申请书开始位置({i+1}): {line_stripped[:50]}...")
                    break
            
            # 如果没找到明确的申请书开始，从第一个有意义的标题开始
            if start_idx == -1:
                for i, line in enumerate(lines):
                    if line.strip().startswith('#') and len(line.strip()) > 3:
                        start_idx = i
                        break
                if start_idx == -1:
                    start_idx = 0
            
            # 寻找需要过滤的内容开始位置（按优先级检测）
            commitment_found = False
            
            # 从后往前检查，找到最后的有效内容位置
            for i in range(len(lines) - 1, -1, -1):
                line_stripped = lines[i].strip()
                
                # 1. 检测承诺书标题
                if "国家自然科学基金项目申请人和参与者承诺书" in line_stripped:
                    end_idx = i
                    commitment_found = True
                    print(f"[重要内容提取] 从后检测到申请人承诺书({i+1}): {line_stripped[:50]}...")
                    break
                    
                # 2. 检测申请单位承诺书
                if "国家自然科学基金项目申请单位承诺书" in line_stripped:
                    end_idx = i
                    commitment_found = True
                    print(f"[重要内容提取] 从后检测到单位承诺书({i+1}): {line_stripped[:50]}...")
                    break
                
                # 3. 检测简历部分
                if ("简历" in line_stripped and "BRID" in line_stripped) or "教育经历" in line_stripped:
                    end_idx = i
                    commitment_found = True
                    print(f"[重要内容提取] 从后检测到简历部分({i+1}): {line_stripped[:50]}...")
                    break
                
                # 4. 检测附件信息
                if "附件信息" in line_stripped or "附件名称" in line_stripped:
                    end_idx = i
                    commitment_found = True
                    print(f"[重要内容提取] 从后检测到附件信息({i+1}): {line_stripped[:50]}...")
                    break
            
            # 如果从后检测没找到，从前往后检测承诺书特征内容
            if not commitment_found:
                for i, line in enumerate(lines[start_idx:], start_idx):
                    line_stripped = line.strip()
                    
                    # 检测承诺书开始的特征文本
                    commitment_indicators = [
                        "为了维护国家自然科学基金项目评审公平、公正",
                        "本人在此郑重承诺：严格遵守",
                        "切实贯彻《国家自然科学基金委员会",
                        "我单位就做好国家自然科学基金申请工作"
                    ]
                    
                    for indicator in commitment_indicators:
                        if indicator in line_stripped:
                            end_idx = i
                            commitment_found = True
                            print(f"[重要内容提取] 检测到承诺书开始内容({i+1}): {line_stripped[:50]}...")
                            break
                    
                    if commitment_found:
                        break
            
            # 智能删除承诺书内容（支持容错匹配）
            if not commitment_found:
                content_text = '\n'.join(lines)
                
                # 方法1：基于关键短语的模糊匹配删除
                commitment_key_phrases = [
                    "国家自然科学基金项目申请人和参与者承诺书",
                    "为了维护国家自然科学基金项目评审公平、公正",
                    "本人在此郑重承诺：严格遵守",
                    "国家自然科学基金项目申请单位承诺书",
                    "我单位就做好国家自然科学基金申请工作做出以下承诺",
                    "如违背上述承诺，本人愿接受",
                    "如违背上述承诺，本单位愿接受",
                    "依托单位公章：日期：",
                    "申请人签字：",
                    "项目名称："
                ]
                
                # 查找承诺书开始位置
                commitment_start_idx = -1
                for i, line in enumerate(lines):
                    line_stripped = line.strip()
                    for phrase in commitment_key_phrases[:4]:  # 只检查开始短语
                        if phrase in line_stripped:
                            commitment_start_idx = i
                            print(f"[重要内容提取] 通过关键短语检测到承诺书开始({i+1}): {phrase}")
                            break
                    if commitment_start_idx != -1:
                        break
                
                # 如果找到承诺书开始，删除从该位置到文档末尾的所有内容
                if commitment_start_idx != -1:
                    lines = lines[:commitment_start_idx]
                    commitment_found = True
                    print(f"[重要内容提取] 承诺书内容已从第{commitment_start_idx+1}行开始删除")
                
                # 方法2：如果方法1没有找到，使用正则表达式模糊匹配删除特定段落
                if not commitment_found:
                    # 删除包含承诺书特征的段落
                    filtered_lines = []
                    skip_mode = False
                    
                    for line in lines:
                        line_stripped = line.strip()
                        
                        # 检查是否进入承诺书相关段落
                        commitment_patterns = [
                            r'.*承诺书.*',
                            r'.*为了维护国家自然科学基金.*',
                            r'.*本人在此郑重承诺.*',
                            r'.*严格遵守.*国家自然科学基金条例.*',
                            r'.*杜绝以下行为.*',
                            r'.*抄袭、剽窃.*',
                            r'.*购买、代写申请书.*',
                            r'.*如违背上述承诺.*',
                            r'.*申请人签字.*',
                            r'.*依托单位公章.*',
                            r'.*资助类型.*青年科学基金.*',
                            r'.*申请代码.*'
                        ]
                        
                        # 检查当前行是否匹配承诺书模式
                        is_commitment_line = False
                        for pattern in commitment_patterns:
                            if re.match(pattern, line_stripped, re.IGNORECASE):
                                is_commitment_line = True
                                skip_mode = True
                                break
                        
                        # 检查是否退出承诺书模式（遇到新的有效标题）
                        if skip_mode and line_stripped.startswith('#') and not is_commitment_line:
                            # 如果是非承诺书的标题，可能是新章节，退出跳过模式
                            non_commitment_title = True
                            for pattern in commitment_patterns:
                                if re.match(pattern, line_stripped, re.IGNORECASE):
                                    non_commitment_title = False
                                    break
                            if non_commitment_title:
                                skip_mode = False
                        
                        # 保留非承诺书内容
                        if not skip_mode and not is_commitment_line:
                            filtered_lines.append(line)
                        elif is_commitment_line:
                            print(f"[重要内容提取] 删除承诺书相关行: {line_stripped[:50]}...")
                    
                    if len(filtered_lines) < len(lines):
                        lines = filtered_lines
                        commitment_found = True
                        print(f"[重要内容提取] 通过模式匹配删除了 {len(lines) - len(filtered_lines)} 行承诺书内容")
            
            # 处理各种情况
            if start_idx >= end_idx:
                print(f"[重要内容提取] 检测到无有效内容或全为承诺书内容")
                return "# 文档处理说明\n\n此文档主要包含承诺书或附加内容，核心申请书内容已被自动过滤。"
            
            print(f"[重要内容提取] 提取范围: 第{start_idx+1}行到第{end_idx}行，共{end_idx-start_idx}行")
            
            # 提取并返回有效内容
            extracted_lines = lines[start_idx:end_idx]
            result = '\n'.join(extracted_lines).strip()
            
            # 额外清理：删除任何剩余的承诺书相关内容
            result = TitleEnhancer._clean_remaining_commitment_content(result)
            
            # 确保结果不为空
            if not result or len(result.strip()) < 50:
                return "# 文档处理说明\n\n未找到有效的申请书内容。"
            
            return result
            
        except Exception as e:
            print(f"提取重要内容失败: {e}")
            return content
    
    @staticmethod
    def optimize_headers_with_extractor(content: str) -> str:
        """标题优化处理 - 独立实现，不依赖外部模块，增强数字编号识别"""
        try:
            print(f"[标题优化] 开始处理，输入内容长度: {len(content)}")
            lines = content.split('\n')
            processed_lines = []
            
            # 第一步：识别并转换潜在的标题行（包括正文中的编号）
            header_count = 0
            for i, line in enumerate(lines):
                stripped_line = line.strip()
                original_line = line
                
                # 检测并处理已有的标题行
                if stripped_line.startswith('#'):
                    header_count += 1
                    # 标准化标题格式：确保#号后有一个空格
                    header_match = re.match(r'^(#+)\s*(.*)', stripped_line)
                    if header_match:
                        level_marks = header_match.group(1)
                        title_text = header_match.group(2).strip()
                        
                        # 清理并标准化标题文本（包括数字编号处理）
                        original_title = title_text
                        title_text = TitleEnhancer._clean_title_text(title_text)
                        
                        # 检测缺少空格的情况
                        if original_title != title_text:
                            print(f"[标题清理] '{original_title}' -> '{title_text}'")
                        
                        if title_text:  # 只保留有内容的标题
                            # 再次确保#后有空格
                            if not level_marks.endswith(' '):
                                processed_lines.append(f"{level_marks} {title_text}")
                            else:
                                processed_lines.append(f"{level_marks}{title_text}")
                        continue
                
                # 检测正文中应该转换为标题的编号行
                potential_header = TitleEnhancer._detect_content_header(stripped_line, i, lines)
                if potential_header:
                    header_count += 1
                    processed_lines.append(potential_header)
                    print(f"[内容转标题] '{stripped_line}' -> '{potential_header}'")
                    continue
                
                # 保留非标题行
                processed_lines.append(original_line)
            
            print(f"[标题优化] 第一步完成，发现 {header_count} 个标题行")
            
            # 第二步：优化标题层级（包括基于数字编号的智能层级推断）
            optimized_lines = TitleEnhancer._optimize_heading_levels(processed_lines)
            print(f"[标题优化] 第二步层级优化完成")
            
            # 第三步：清理空标题和重复空行
            final_lines = []
            prev_empty = False
            
            for line in optimized_lines:
                stripped = line.strip()
                
                # 跳过空标题
                if re.match(r'^\s*#+\s*$', stripped):
                    continue
                
                # 处理空行：避免连续空行
                if not stripped:
                    if not prev_empty:
                        final_lines.append(line)
                        prev_empty = True
                else:
                    final_lines.append(line)
                    prev_empty = False
            
            result = '\n'.join(final_lines)
            print(f"[标题优化] 处理完成，输出内容长度: {len(result)}")
            return result
            
        except Exception as e:
            print(f"标题优化失败: {e}")
            traceback.print_exc()
            return content
    
    @staticmethod
    def _detect_content_header(line: str, line_index: int, all_lines: List[str]) -> str:
        """检测正文中应该转换为标题的编号行"""
        if not line:
            return ""
        
        # 检测各种编号格式，并判断是否应该转换为标题
        
        # 0. 检测中文数字编号："一、代表性论著..." 这种格式
        if re.match(r'^[一二三四五六七八九十]+、', line):
            # 中文数字编号通常是重要的一级标题
            level = 1
            cleaned_text = TitleEnhancer._clean_title_text(line)
            return f"{'#' * level} {cleaned_text}"
        
        # 1. 检测 "3.2技术路线图" 这种格式
        if re.match(r'^[0-9]+\.[0-9]+[^\s]', line):
            # 确保是独立的一行，且内容较短（可能是标题）
            if len(line) < 50 and not line.endswith('。') and not line.endswith('：'):
                level = 3  # 设为三级标题
                cleaned_text = TitleEnhancer._clean_title_text(line)
                return f"{'#' * level} {cleaned_text}"
        
        # 2. 检测 "4.1 内容..." 这种段落开头的编号
        if re.match(r'^[0-9]+\.[0-9]+\s', line):
            # 检查是否是段落开头（前面是空行或标题）
            prev_line = all_lines[line_index - 1].strip() if line_index > 0 else ""
            next_line = all_lines[line_index + 1].strip() if line_index < len(all_lines) - 1 else ""
            
            # 如果前面是空行、标题，或者这行很短且独立，可能是标题
            if (not prev_line or prev_line.startswith('#') or 
                (len(line) < 100 and (not next_line or next_line.startswith('#')))):
                level = 3  # 设为三级标题
                cleaned_text = TitleEnhancer._clean_title_text(line)
                return f"{'#' * level} {cleaned_text}"
        
        # 3. 检测 "5.2 针对本项目..." 这种格式
        if re.match(r'^[0-9]+\.[0-9]+\s.*[:：]$', line):
            # 以冒号结尾的编号行，很可能是标题
            level = 3
            # 移除结尾的冒号
            cleaned_line = re.sub(r'[:：]+$', '', line).strip()
            cleaned_text = TitleEnhancer._clean_title_text(cleaned_line)
            return f"{'#' * level} {cleaned_text}"
        
        return ""
    
    @staticmethod
    def _clean_title_text(title_text: str) -> str:
        """清理并标准化标题文本，特别处理数字编号格式"""
        original_text = title_text
        
        # 检测和标准化数字编号格式
        # 匹配各种数字编号格式：1. 1.1 1.1.1 （一） 等
        number_patterns = [
            # 多级数字编号：1.1.1, 2.3.4 等
            (r'^([0-9]+(?:\.[0-9]+)+)\s*(.*)', r'\1 \2'),
            # 单级数字编号后跟点号和内容：1. 研究内容
            (r'^([0-9]+)\.\s+(.+)', r'\1. \2'),
            # 单级数字编号后只有点号（空内容）：保持原样
            (r'^([0-9]+)\.\s*$', r'\1.'),
            # 单级数字编号无点号但后面直接跟文字：1研究 2工作 等
            (r'^([0-9]+)([^\s\.].*)', r'\1. \2'),
            # 数字编号后缺少空格：1.研究 2.工作 等
            (r'^([0-9]+)\.([^\s].*)', r'\1. \2'),
            # 多级编号后缺少空格：1.1研究 2.2工作 等
            (r'^([0-9]+\.[0-9]+)([^\s].*)', r'\1 \2'),
            # 三级编号后缺少空格：3.1.1研究对象
            (r'^([0-9]+\.[0-9]+\.[0-9]+)([^\s].*)', r'\1 \2'),
        ]
        
        # 应用数字编号标准化
        for pattern, replacement in number_patterns:
            if re.match(pattern, title_text):
                title_text = re.sub(pattern, replacement, title_text)
                if title_text != original_text:
                    print(f"[标题标准化] '{original_text}' -> '{title_text}'")
                break
        
        # 处理中文编号：（一）（二）等
        chinese_number_match = re.match(r'^(（[一二三四五六七八九十]+）)\s*(.*)', title_text)
        if chinese_number_match:
            chinese_part = chinese_number_match.group(1)
            text_part = chinese_number_match.group(2)
            if text_part and not text_part.startswith(' '):
                title_text = f"{chinese_part} {text_part}"
                if title_text != original_text:
                    print(f"[中文编号标准化] '{original_text}' -> '{title_text}'")
        
        # 处理中文数字编号：一、二、三、等
        chinese_dot_match = re.match(r'^([一二三四五六七八九十]+、)\s*(.*)', title_text)
        if chinese_dot_match:
            chinese_part = chinese_dot_match.group(1)
            text_part = chinese_dot_match.group(2)
            if text_part and not text_part.startswith(' '):
                title_text = f"{chinese_part} {text_part}"
                if title_text != original_text:
                    print(f"[中文数字编号标准化] '{original_text}' -> '{title_text}'")
        
        # 清理多余的空格，但保留标题编号后的单个空格
        title_text = re.sub(r'\s+', ' ', title_text)
        
        # 只移除结尾的多余标点和空格，但保护有意义的编号点号
        # 如果是单纯的数字编号（如"3."），不要移除点号
        if not re.match(r'^[0-9]+\.$', title_text.strip()):
            title_text = re.sub(r'[\s·•。．…]+$', '', title_text)
        
        title_text = title_text.strip()
        
        return title_text
    
    @staticmethod
    def _clean_remaining_commitment_content(content: str) -> str:
        """清理残留的承诺书相关内容"""
        try:
            lines = content.split('\n')
            cleaned_lines = []
            
            # 定义更全面的承诺书关键词
            commitment_keywords = [
                '承诺书', '承诺', '郑重承诺', '申请人签字', '依托单位公章',
                '资助类型', '申请代码', '项目名称：成人斯蒂尔病',
                '青年科学基金项目', '医学免疫学',
                '为了维护国家自然科学基金', '恪守职业规范', '科学道德',
                '抄袭、剽窃', '购买、代写', '弄虚作假',
                '如违背上述承诺', '处理决定', '撤销科学基金',
                '科研诚信', '党纪政务处分', '年月日'
            ]
            
            for line in lines:
                line_stripped = line.strip()
                
                # 检查是否包含承诺书关键词
                contains_commitment = False
                for keyword in commitment_keywords:
                    if keyword in line_stripped:
                        contains_commitment = True
                        break
                
                # 只保留不包含承诺书关键词的行
                if not contains_commitment:
                    cleaned_lines.append(line)
                else:
                    print(f"[清理残留] 删除包含承诺书关键词的行: {line_stripped[:50]}...")
            
            result = '\n'.join(cleaned_lines)
            
            # 清理多余的空行
            result = re.sub(r'\n\s*\n\s*\n+', '\n\n', result)
            result = result.strip()
            
            return result
            
        except Exception as e:
            print(f"清理残留承诺书内容失败: {e}")
            return content
    
    @staticmethod
    def _optimize_heading_levels(lines: list) -> list:
        """优化标题层级，确保层级递进合理，特别处理数字编号"""
        optimized_lines = []
        heading_stack = []  # 记录标题层级栈
        
        for line in lines:
            stripped_line = line.strip()
            
            if stripped_line.startswith('#'):
                # 解析标题层级
                header_match = re.match(r'^(#+)\s*(.*)', stripped_line)
                if header_match:
                    original_level = len(header_match.group(1))
                    title_text = header_match.group(2).strip()
                    
                    if not title_text:  # 跳过空标题
                        continue
                    
                    # 特殊处理："【参考文献】"设置为五级标题
                    if '参考文献' in title_text and ('【' in title_text or '】' in title_text):
                        adjusted_level = 5
                        print(f"[标题优化] 特殊处理参考文献: '{title_text}' -> 五级标题")
                        # 更新层级栈
                        heading_stack = [l for l in heading_stack if l < adjusted_level]
                        heading_stack.append(adjusted_level)
                    else:
                        # 根据数字编号智能推断层级
                        inferred_level = TitleEnhancer._infer_level_from_numbering(title_text)
                        
                        if inferred_level > 0:
                            # 使用推断的层级，但确保不超过合理范围
                            adjusted_level = min(inferred_level, 6)  # 最多6级标题
                            
                            if adjusted_level != original_level:
                                print(f"[标题优化] 基于编号调整层级: '{title_text}' {original_level}级 -> {adjusted_level}级")
                        else:
                            # 无法从编号推断，使用原有逻辑调整
                            adjusted_level = TitleEnhancer._adjust_heading_level(original_level, heading_stack)
                            
                            if adjusted_level != original_level:
                                print(f"[标题优化] 常规调整层级: '{title_text}' {original_level}级 -> {adjusted_level}级")
                        
                        # 更新层级栈
                        heading_stack = [l for l in heading_stack if l < adjusted_level]
                        heading_stack.append(adjusted_level)
                    
                    # 生成调整后的标题
                    adjusted_header = '#' * adjusted_level + ' ' + title_text
                    optimized_lines.append(adjusted_header)
                else:
                    optimized_lines.append(line)
            else:
                optimized_lines.append(line)
        
        return optimized_lines
    
    @staticmethod
    def _infer_level_from_numbering(title_text: str) -> int:
        """从标题编号推断合适的层级"""
        # 中文大标题编号：（一）（二）等 -> 1级
        if re.match(r'^（[一二三四五六七八九十]+）', title_text):
            return 1
        
        # 中文数字编号：一、二、三、等 -> 1级标题
        if re.match(r'^[一二三四五六七八九十]+、', title_text):
            return 1
        
        # 数字编号分析
        number_match = re.match(r'^([0-9]+(?:\.[0-9]+)*)', title_text)
        if number_match:
            number_part = number_match.group(1)
            # 统计层级深度：1->1级, 1.1->2级, 1.1.1->3级
            level_depth = number_part.count('.') + 1
            
            # 根据编号特征调整
            if re.match(r'^[0-9]+\.$', number_part + '.'):  # 1. 2. 3. 格式
                return 2  # 主要章节标题
            elif re.match(r'^[0-9]+\.[0-9]+$', number_part):  # 1.1 1.2 格式
                return 3  # 二级章节标题  
            elif re.match(r'^[0-9]+\.[0-9]+\.[0-9]+$', number_part):  # 1.1.1 格式
                return 4  # 三级章节标题
            else:
                # 更深层级
                return min(level_depth + 2, 6)  # 最多6级
        
        return 0  # 无法推断
    
    @staticmethod
    def _adjust_heading_level(current_level: int, heading_stack: list) -> int:
        """调整标题层级，确保层级递进合理"""
        if not heading_stack:
            # 第一个标题，设为1级
            return 1
        
        last_level = heading_stack[-1]
        
        # 如果当前层级比上一级深度超过1，调整为上一级+1
        if current_level > last_level + 1:
            return last_level + 1
        
        # 如果当前层级比上一级浅或相等，保持原层级
        if current_level <= last_level:
            return current_level
        
        # 正常递进
        return current_level
