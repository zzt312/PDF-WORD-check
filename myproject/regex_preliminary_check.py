"""
正则化初筛规则检查模块
实现可以通过正则表达式快速检查的规则

【重要】所有检查都直接从完整markdown文档中用正则提取，严禁使用JSON数据，严禁分割文档
支持两种表格格式：
  - Markdown | 表格（MinerU pipeline模型输出）
  - HTML <table> 表格（MinerU vlm模型输出）
"""
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple


# ==================== 参考文献区域定位（共用） ====================

def _locate_reference_section(md_content: str) -> Optional[Tuple[str, str, int]]:
    """定位参考文献区域（供A6/A7/C1/C2共用）
    
    策略：
    1. 优先查找"参考文献"/"References"标题行
    2. 若无标题，回退查找行首连续[1],[2],...的参考文献列表区域
       （需包含期刊标记如 [J],[M],[C] 等来区分正文内联引用）
    
    Returns:
        (ref_section_text, body_text, ref_start_position) 或 None
    """
    # ---- 策略1: 有标题 ----
    ref_match = re.search(
        r'(?:#{1,6}\s*)?(?:参考文献|参\s*考\s*文\s*献|References?)(.*)$',
        md_content, re.DOTALL | re.IGNORECASE
    )
    if ref_match:
        return ref_match.group(), md_content[:ref_match.start()], ref_match.start()
    
    # ---- 策略2: 无标题，回退查找连续[n]条目 ----
    # 找到第一个行首 [1] 且后面包含期刊类型标记的位置
    # 期刊标记：[J],[M],[C],[D],[P],[R],[S],[G],[A],[N],[EB],[OL],[DB]
    journal_marker_re = r'\[(?:J|M|C|D|P|R|S|G|A|N|EB|OL|DB)\]'
    
    # 查找所有行首 [数字] 的位置
    line_ref_matches = list(re.finditer(r'(?:^|\n)\s*\[(\d+)\]\s*(.+)', md_content))
    if not line_ref_matches:
        return None
    
    # 找第一个包含期刊标记的 [1] 或 [n]
    first_ref_pos = None
    for m in line_ref_matches:
        ref_no = int(m.group(1))
        ref_text = m.group(2)
        # 必须包含期刊/文献类型标记，排除正文内联 [1] 引用
        if re.search(journal_marker_re, ref_text, re.IGNORECASE):
            first_ref_pos = m.start()
            break
        # 也接受包含年份+页码模式的条目（如 "2021, 223: 107817"）
        if re.search(r'\d{4}[,，]\s*\d+', ref_text) and len(ref_text) > 40:
            first_ref_pos = m.start()
            break
    
    if first_ref_pos is None:
        return None
    
    ref_section = md_content[first_ref_pos:]
    body_text = md_content[:first_ref_pos]
    print(f"[参考文献定位] 无标题模式 - 从位置{first_ref_pos}开始检测到参考文献列表")
    return ref_section, body_text, first_ref_pos


# ==================== HTML表格辅助函数 ====================

def _find_html_cell_value(content, key_text: str, exact: bool = False) -> Optional[str]:
    """在HTML表格中查找包含key_text的<td>之后的下一个<td>的文本内容
    
    Args:
        content: 包含HTML <table>标签的文本，支持传入字符串或字符串列表（依次尝试）
        key_text: 要查找的关键词（如"申请代码"）
        exact: 是否精确匹配。False时使用包含匹配（如搜"关键词"可匹配"中文关键词"）
        
    Returns:
        找到的值文本，未找到返回None
    """
    # 支持传入列表：依次在每个内容中查找，第一个找到即返回
    if isinstance(content, (list, tuple)):
        for c in content:
            if c:
                result = _find_html_cell_value(c, key_text, exact)
                if result is not None:
                    return result
        return None
    
    if not content:
        return None
    if exact:
        pattern = rf'<td[^>]*>\s*{re.escape(key_text)}\s*</td>\s*<td[^>]*>\s*(.*?)\s*</td>'
    else:
        # 包含匹配：<td>内容包含key_text即可
        pattern = rf'<td[^>]*>[^<]*{re.escape(key_text)}[^<]*</td>\s*<td[^>]*>\s*(.*?)\s*</td>'
    match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
    if match:
        # 去除内部HTML标签
        value = re.sub(r'<[^>]+>', '', match.group(1))
        # 移除HTML转义空白符 &nbsp; 及其他空白
        value = value.replace('&nbsp;', ' ').strip()
        return value if value else None
    return None


def _count_html_table_data_rows(table_html: str) -> int:
    """统计HTML表格中有实际内容的数据行数（排除表头行和全空行）
    
    Args:
        table_html: <table>...</table>之间的HTML内容
        
    Returns:
        有内容的数据行数
    """
    tr_list = list(re.finditer(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL))
    if len(tr_list) <= 1:
        return 0  # 只有表头或空表
    
    data_count = 0
    for tr in tr_list[1:]:  # 跳过第一行（表头）
        cells = re.findall(r'<td[^>]*>(.*?)</td>', tr.group(1), re.DOTALL | re.IGNORECASE)
        cell_texts = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
        if any(t for t in cell_texts):  # 至少有一个非空单元格
            data_count += 1
    return data_count


def check_application_code_from_md(md_content: str, vlm_content: str = None) -> Optional[Dict]:
    """检查申请代码格式（规则1）- 从完整markdown中提取
    
    规则：第一个申请代码必须是4位数
    支持 Markdown |..| 表格和 HTML <table> 两种格式
    """
    contents = [md_content, vlm_content]  # 主内容 + VLM回退
    # 从markdown中查找申请代码
    # 常见格式：申请代码：1234 或 |申请代码|1234| 或 申请代码: A123
    patterns = [
        r'申请代码[：:]\s*([A-Za-z0-9]+)',
        r'\|\s*申请代码\s*\|\s*([A-Za-z0-9]+)\s*\|',
        r'申请代码\s+([A-Za-z0-9]+)',
    ]
    
    code = None
    for pattern in patterns:
        match = re.search(pattern, md_content)
        if match:
            code = match.group(1).strip()
            break
    # VLM回退：正则在VLM内容中查找
    if not code and vlm_content:
        for pattern in patterns:
            match = re.search(pattern, vlm_content)
            if match:
                code = match.group(1).strip()
                break
    
    # 尝试HTML表格格式（MinerU vlm模型输出的<table>格式）
    if not code:
        html_value = _find_html_cell_value(contents, '申请代码')
        if html_value:
            # 提取第一个连续字母数字串作为申请代码
            code_match = re.match(r'([A-Za-z0-9]+)', html_value)
            if code_match:
                code = code_match.group(1).strip()
    
    if not code:
        # 未找到申请代码，不报错（可能文档格式不同）
        return None
    
    # 检查是否为4位数字
    if not re.match(r'^\d{4}$', code):
        return {
            'rule_name': '申请代码格式检查',
            'severity': 'high',
            'error_text': f'申请代码"{code}"不符合4位数字格式要求',
            'location': '基本信息表',
            'suggestion': '申请代码必须为4位数字，请检查并修正'
        }
    return None


def check_cooperative_unit_from_md(md_content: str) -> List[Dict]:
    """检查合作单位中是否包含附属医院（规则2）- 从完整markdown中提取
    
    规则：合作单位中不应包含学校的附属医院（附属医院应列为依托单位）
    支持 Markdown |..| 表格和 HTML <table> 两种格式
    """
    violations = []
    
    # 从markdown中查找合作单位信息
    # 常见格式：合作研究单位：XXX医院 或 |合作单位|XXX医院|
    patterns = [
        r'(?:合作研究单位|合作单位)[：:]\s*([^\n\|]+)',
        r'\|\s*(?:合作研究单位|合作单位)\s*\|\s*([^\|]+)\s*\|',
        r'合作(?:研究)?单位名称[：:]\s*([^\n\|]+)',
        r'\|\s*合作(?:研究)?单位名称\s*\|\s*([^\|]+)\s*\|',
    ]
    
    cooperative_units = []
    for pattern in patterns:
        matches = re.findall(pattern, md_content)
        cooperative_units.extend(matches)
    
    # HTML表格格式（MinerU vlm模型输出）
    # 典型格式：<td>合作研究单位信息</td><td>单位名称</td></tr><tr><td>XXX大学</td></tr>
    html_coop_matches = re.findall(
        r'单位名称\s*</td>\s*</tr>\s*<tr[^>]*>\s*<td[^>]*>\s*([^<]*?)\s*</td>',
        md_content, re.IGNORECASE
    )
    for unit in html_coop_matches:
        unit = unit.strip()
        if unit:
            cooperative_units.append(unit)
    
    # 检查每个合作单位是否包含附属医院关键词
    for unit in cooperative_units:
        unit = unit.strip()
        if unit and re.search(r'附属医院|附院', unit):
            violations.append({
                'rule_name': '合作单位规范检查',
                'severity': 'medium',
                'error_text': f'合作单位中包含附属医院：{unit}',
                'location': '基本信息表',
                'suggestion': '学校的附属医院应列为"依托单位"而非"合作单位"'
            })
    
    return violations


def check_participant_count_from_md(md_content: str, vlm_content: str = None) -> Optional[Dict]:
    """检查主要参与者人数统计（规则3）- 从完整markdown中提取
    
    规则：主要参与者表格中的实际人数应与声明人数一致
    支持 Markdown |..| 表格和 HTML <table> 两种格式
    """
    try:
        # === 1. 从markdown中查找声明的参与人数 ===
        declared_patterns = [
            r'(?:主要参与者|参与者|项目组成员)(?:人数)?[：:]\s*(\d+)\s*人?',
            r'\|\s*(?:主要参与者|参与者)(?:人数)?\s*\|\s*(\d+)\s*人?\s*\|',
            r'参与人数[：:]\s*(\d+)',
        ]
        
        declared_count = None
        declared_is_total = False  # 标记来源是否为"总人数统计"（含申请人）
        
        for pattern in declared_patterns:
            match = re.search(pattern, md_content)
            if match:
                declared_count = int(match.group(1))
                break
        
        # HTML表格格式：从"总人数统计"表格提取声明人数（主内容+VLM回退）
        if declared_count is None:
            total_section = None
            for _content in [md_content, vlm_content]:
                if not _content:
                    continue
                total_section = re.search(
                    r'总人数统计.*?<table[^>]*>(.*?)</table>',
                    _content, re.DOTALL | re.IGNORECASE
                )
                if total_section:
                    break
            if total_section:
                table_html = total_section.group(1)
                tr_list = list(re.finditer(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL))
                if len(tr_list) >= 2:
                    # 第一行是表头（总人数、高级职称...），第二行是数据
                    data_row = tr_list[1].group(1)
                    first_td = re.search(r'<td[^>]*>\s*(\d+)\s*</td>', data_row)
                    if first_td:
                        declared_count = int(first_td.group(1))
                        declared_is_total = True  # 总人数包含申请人
        
        # === 2. 统计实际参与者表格行数 ===
        participant_section_pattern = r'(?:#{1,6}\s*)?(?:主要参与者|项目组成员|研究队伍).*?(?=\n#{1,3}[^#]|\Z)'
        participant_section = re.search(participant_section_pattern, md_content, re.DOTALL | re.IGNORECASE)
        # VLM回退：主内容未找到参与者节时尝试VLM内容
        if not participant_section and vlm_content:
            participant_section = re.search(participant_section_pattern, vlm_content, re.DOTALL | re.IGNORECASE)
        
        actual_count = 0
        if participant_section:
            section_content = participant_section.group()
            
            # 方法1: Markdown |..| 表格行（MinerU pipeline输出）
            table_rows = re.findall(r'^\|[^\n]+\|$', section_content, re.MULTILINE)
            data_rows = []
            header_passed = False
            for row in table_rows:
                if re.match(r'^\|[\s\-\|:]+\|$', row):
                    header_passed = True
                    continue
                if header_passed:
                    data_rows.append(row)
            actual_count = len(data_rows)
            
            # 方法2: HTML <table> 行（MinerU vlm输出，仅在Markdown方式未找到时使用）
            if actual_count == 0:
                html_table = re.search(r'<table[^>]*>(.*?)</table>', section_content, re.DOTALL | re.IGNORECASE)
                if html_table:
                    actual_count = _count_html_table_data_rows(html_table.group(1))
        
        # === 3. 比较声明人数与实际人数 ===
        if declared_count is not None and declared_count > 0:
            # 如果声明来自"总人数统计"，需要减1（总人数包含申请人，但主要参与者表不含申请人）
            expected_participants = declared_count - 1 if declared_is_total else declared_count
            
            if actual_count == 0 and expected_participants > 0:
                return {
                    'rule_name': '主要参与者人数统计',
                    'severity': 'medium',
                    'error_text': f'声明{"总" if declared_is_total else "参与"}人数为{declared_count}人{"（含申请人）" if declared_is_total else ""}，但未找到有效的参与者信息',
                    'location': '基本信息表/参与者表格',
                    'suggestion': '请确保主要参与者表格存在且格式正确'
                }
            elif actual_count != expected_participants and expected_participants >= 0:
                return {
                    'rule_name': '主要参与者人数统计',
                    'severity': 'high',
                    'error_text': f'声明{"总" if declared_is_total else "参与"}人数为{declared_count}人{"（含申请人）" if declared_is_total else ""}，实际表格列出{actual_count}人，数量不一致',
                    'location': '基本信息表/参与者表格',
                    'suggestion': f'请核对参与人数，确保声明人数与实际列出人员一致（预期主要参与者{expected_participants}人，实际{actual_count}人）'
                }
        
    except Exception as e:
        print(f"[正则检查] 参与者人数统计检查异常: {e}")
    
    return None


def check_required_chapters_from_md(md_content: str) -> List[Dict]:
    """检查必需章节是否存在（规则4.1）- 从完整markdown中检查
    
    规则：报告正文，最新模板，没缺项
    
    最新模板要求申请书正文包括：立项依据、研究内容、研究基础 三部分
    """
    missing_core = []  # 缺失的核心章节
    
    # 新模板必需的3个核心章节
    core_chapters = ['立项依据', '研究内容', '研究基础']
    
    # 检查核心章节（模糊匹配关键词）
    for chapter in core_chapters:
        if chapter not in md_content:
            missing_core.append(chapter)
    
    violations = []
    
    # 如果有缺失核心章节
    if missing_core:
        violations.append({
            'rule_name': '报告正文最新模板章节检查',
            'severity': 'high',
            'error_text': f"缺少必需章节：{', '.join(missing_core)}",
            'location': '报告正文',
            'suggestion': f"新模板要求正文必须包含：立项依据、研究内容、研究基础"
        })
    
    return violations


def check_blank_pages_from_md(md_content: str) -> List[Dict]:
    """检查空白页（规则4.2）- 从完整markdown中检查
    
    规则：报告正文无空白页（连续15个以上换行才视为空白页）
    PDF转Markdown后页面间天然有多个换行，阈值需足够高以避免误报。
    """
    violations = []
    
    # 尝试只检查报告正文部分（从"立项依据"或"项目的"开始到末尾）
    body_start_pattern = r'(?:^|\n)#*\s*[（(]?[一1][\s\S]{0,5}(?:立项依据|项目的)'
    body_match = re.search(body_start_pattern, md_content)
    check_content = md_content[body_match.start():] if body_match else md_content
    
    # 阈值：连续15个以上换行才视为可能的空白页
    pattern = r'\n{15,}'
    matches = list(re.finditer(pattern, check_content))
    
    # 最多报告5处
    max_reports = 5
    for i, match in enumerate(matches[:max_reports], 1):
        blank_count = match.group().count('\n')
        violations.append({
            'rule_name': '报告正文空白页检查',
            'severity': 'medium',
            'error_text': f'检测到连续{blank_count}个换行符（可能存在空白页）',
            'location': f'第{i}处空白区域（共检测到{len(matches)}处）',
            'suggestion': '请删除多余的空白页，确保文档紧凑'
        })
    return violations


def check_h18_special_content_from_md(md_content: str, vlm_content: str = None) -> List[Dict]:
    """检查H18专项特殊要求（规则4.3）- 从完整markdown中检查
    
    规则：H18的面上、源于临床实践的科学问题探索研究专项在立项依据前要单独添加内容
    """
    violations = []
    contents = [md_content, vlm_content]
    
    # 检查是否为H18专项（申请代码以H18开头）
    h18_pattern = r'申请代码[：:]\s*H18'
    is_h18 = bool(re.search(h18_pattern, md_content))
    if not is_h18 and vlm_content:
        is_h18 = bool(re.search(h18_pattern, vlm_content))
    # HTML表格回退
    if not is_h18:
        h18_html = _find_html_cell_value(contents, '申请代码')
        if h18_html and 'H18' in h18_html.upper():
            is_h18 = True
    if not is_h18:
        return violations
    
    # 查找立项依据章节位置
    lijian_pattern = r'#{1,6}\s*[（\(]?[一二三四五六七八九十\d.\s]*[）\)]?\s*立项依据'
    lijian_match = re.search(lijian_pattern, md_content)
    
    if lijian_match:
        # 获取立项依据前的内容
        before_lijian = md_content[:lijian_match.start()]
        
        # 检查是否有"源于临床实践的科学问题"相关内容
        clinical_keywords = ['源于临床实践', '临床实践', '科学问题探索', '临床问题']
        has_clinical_content = any(keyword in before_lijian for keyword in clinical_keywords)
        
        if not has_clinical_content:
            violations.append({
                'rule_name': 'H18专项特殊内容检查',
                'severity': 'high',
                'error_text': 'H18专项应在立项依据前单独说明源于临床实践的科学问题',
                'location': '报告正文（立项依据前）',
                'suggestion': 'H18的面上、源于临床实践的科学问题探索研究专项需在立项依据前单独添加相关内容说明'
            })
    
    return violations


def check_optional_chapters_from_md(md_content: str) -> List[Dict]:
    """检查容易漏写的章节（规则4.4）- 从完整markdown中检查
    
    规则：检查容易漏写的可行性分析、预期研究结果、技术路线图
    """
    missing_optional = []
    
    # 容易漏写的章节
    optional_chapters = ['可行性分析', '预期研究结果', '技术路线图']
    
    # 检查容易漏写的章节
    for chapter in optional_chapters:
        if chapter not in md_content:
            missing_optional.append(chapter)
    
    violations = []
    
    # 如果有缺失的可选章节
    if missing_optional:
        violations.append({
            'rule_name': '容易漏写章节检查',
            'severity': 'medium',
            'error_text': f"未找到容易漏写的章节：{', '.join(missing_optional)}",
            'location': '报告正文',
            'suggestion': '建议检查是否遗漏：可行性分析、预期研究结果、技术路线图'
        })
    
    return violations


def check_annual_plan_time_match_from_md(md_content: str, project_start: datetime, project_end: datetime, time_periods: list) -> List[Dict]:
    """检查年度研究计划时间与项目执行期一致（规则5.1）
    
    规则：年度研究计划时间与项目执行期一致
    """
    violations = []
    
    if not time_periods:
        return violations
    
    # 检查时间一致性，合并起始和结束检查为一个violation
    first_start = time_periods[0][0]
    last_end = time_periods[-1][1]
    
    errors = []
    if first_start != project_start:
        errors.append(f'年度计划起始时间为{first_start.strftime("%Y年%m月")}，项目执行期起始时间为{project_start.strftime("%Y年%m月")}，不一致')
    if last_end != project_end:
        errors.append(f'年度计划结束时间为{last_end.strftime("%Y年%m月%d日")}，项目执行期结束时间为{project_end.strftime("%Y年%m月%d日")}，不一致')
    
    if errors:
        violations.append({
            'rule_name': '年度计划与项目执行期时间一致性检查',
            'severity': 'high',
            'error_text': '；'.join(errors),
            'location': '年度研究计划',
            'suggestion': f'年度计划时间应与项目执行期保持一致：{project_start.strftime("%Y年%m月")}-{project_end.strftime("%Y年%m月%d日")}'
        })
    
    return violations


def check_annual_plan_continuity_from_md(md_content: str, time_periods: list) -> List[Dict]:
    """检查年度研究计划时间衔接（规则5.2）
    
    规则：年度研究计划时间衔接不能少1天
    """
    violations = []
    
    # 检查时间段之间是否连续（不能少1天）
    for i in range(len(time_periods) - 1):
        current_end = time_periods[i][1]
        next_start = time_periods[i + 1][0]
        
        # 下一个时间段应该从当前时间段结束后的第二天开始
        expected_next_start = current_end + timedelta(days=1)
        
        if next_start != expected_next_start:
            gap_days = (next_start - current_end).days - 1
            if gap_days > 0:
                violations.append({
                    'rule_name': '年度计划时间衔接检查',
                    'severity': 'high',
                    'error_text': f'第{i+1}年度结束于{current_end.strftime("%Y年%m月%d日")}，第{i+2}年度开始于{next_start.strftime("%Y年%m月%d日")}，中间缺少{gap_days}天',
                    'location': '年度研究计划',
                    'suggestion': f'年度计划时间应连续衔接，第{i+2}年度应从{expected_next_start.strftime("%Y年%m月%d日")}开始，不能少1天'
                })
            elif gap_days < 0:
                violations.append({
                    'rule_name': '年度计划时间衔接检查',
                    'severity': 'high',
                    'error_text': f'第{i+1}年度和第{i+2}年度时间重叠{abs(gap_days+1)}天',
                    'location': '年度研究计划',
                    'suggestion': '年度计划时间不应重叠，请检查时间段设置'
                })
    
    return violations


def check_annual_plan_from_md(md_content: str, vlm_content: str = None) -> List[Dict]:
    """检查年度研究计划（规则5）- 从完整markdown中提取
    
    规则：年度研究计划，时间与项目执行期一致，时间衔接，不能少1天
    拆分为：
    5.1 年度研究计划时间与项目执行期一致
    5.2 年度研究计划时间衔接不能少1天
    """
    violations = []
    
    try:
        # 从markdown中提取项目执行期限
        # 常见格式：研究期限：2025年1月-2027年12月 或 执行期限：2025.01-2027.12 或 2025年1月至2027年9月
        duration_patterns = [
            # 精确日期格式: 2027年01月01日--2030年12月31日（PDF常见）
            r'(?:研究期限|执行期限|项目周期|起止年月)[^\d]*(\d{4})年(\d{1,2})月\d{1,2}日\s*[-—~至]{1,3}\s*(\d{4})年(\d{1,2})月\d{1,2}日',
            r'(?:研究期限|执行期限|项目周期|起止年月)[：:]\s*(\d{4})[.年](\d{1,2})[月]?\s*[-~至]\s*(\d{4})[.年](\d{1,2})[月]?',
            r'\|\s*(?:研究期限|执行期限)\s*\|\s*(\d{4})[.年](\d{1,2})[月]?\s*[-~至]\s*(\d{4})[.年](\d{1,2})[月]?\s*\|',
            # 精确日期无标签: 2027年01月01日--2030年12月31日
            r'(\d{4})年(\d{1,2})月\d{1,2}日\s*[-—~至]{1,3}\s*(\d{4})年(\d{1,2})月\d{1,2}日',
            r'(\d{4})年(\d{1,2})月至(\d{4})年(\d{1,2})月',
            r'选择(\d{4})年(\d{1,2})月至(\d{4})年(\d{1,2})月',
        ]
        
        # 也尝试从HTML表格提取研究期限（主内容 + VLM回退）
        contents = [md_content, vlm_content]
        html_duration = _find_html_cell_value(contents, '研究期限')
        
        project_start = None
        project_end = None
        
        if html_duration:
            dur_match = re.search(r'(\d{4})年(\d{1,2})月.*?[-—~至]{1,3}.*?(\d{4})年(\d{1,2})月', html_duration)
            if dur_match:
                project_start = datetime(int(dur_match.group(1)), int(dur_match.group(2)), 1)
                project_end_year = int(dur_match.group(3))
                project_end_month = int(dur_match.group(4))
                if project_end_month == 12:
                    project_end = datetime(project_end_year + 1, 1, 1) - timedelta(days=1)
                else:
                    project_end = datetime(project_end_year, project_end_month + 1, 1) - timedelta(days=1)
                print(f"[正则检查] 从HTML表格找到项目执行期限: {project_start.strftime('%Y.%m')} - {project_end.strftime('%Y.%m')}")
        
        if not project_start:
            # 在主内容和VLM回退中依次尝试正则匹配
            for _content in [md_content, vlm_content]:
                if not _content or project_start:
                    continue
                for pattern in duration_patterns:
                    match = re.search(pattern, _content)
                    if match:
                        project_start = datetime(int(match.group(1)), int(match.group(2)), 1)
                        project_end_year = int(match.group(3))
                        project_end_month = int(match.group(4))
                        # 计算该月的最后一天
                        if project_end_month == 12:
                            project_end = datetime(project_end_year + 1, 1, 1) - timedelta(days=1)
                        else:
                            project_end = datetime(project_end_year, project_end_month + 1, 1) - timedelta(days=1)
                        print(f"[正则检查] 找到项目执行期限: {project_start.strftime('%Y.%m')} - {project_end.strftime('%Y.%m')}")
                        break
        
        if not project_start or not project_end:
            # 未找到项目执行期限，但不跳过全部检查，尝试继续查找年度计划进行内部逻辑校验
            print("[正则检查] 未找到项目执行期限，将仅检查年度计划内部时间衔接")
        
        # 查找年度计划章节 - 改进版逻辑（根据标题层级截取内容）
        annual_plan_content = ""
        # 匹配标题行，捕获 '#' 符号及其数量
        # group(1): 换行符或开始, group(2): '#'符号串(可能为空)
        head_pattern = r'(?:^|\n)((#{1,6})\s+)?(?:[（\(]?[一二三四五六七八九十\d.\s]*[）\)]?\s*)?[【\[]?年度研究计划[】\]]?\s*[：:]*\s*(?=\n)'
        head_match = re.search(head_pattern, md_content, re.IGNORECASE)

        if head_match:
            # 确定标题级别
            hashes = head_match.group(2)
            level = len(hashes) if hashes else 0
            
            start_pos = head_match.end()
            
            if level > 0:
                # 有明确层级：内容截止到下一个同级或更高级标题
                # 正则：换行 + 1到level个# + 空格
                end_pattern = rf'\n\s*#{{1,{level}}}\s+'
                end_match = re.search(end_pattern, md_content[start_pos:])
                if end_match:
                    annual_plan_content = md_content[start_pos : start_pos + end_match.start()]
                else:
                    annual_plan_content = md_content[start_pos:]
            else:
                # 无明确层级（如PDF转MD无标题符）：尝试提取到下一个疑似大标题或文件尾
                # 假设下一个大标题是以#开头，或者特定的章节名
                # 这里简单处理：提取后续所有内容，或者直到遇到 # 标题
                end_match = re.search(r'\n\s*#{1,6}\s+', md_content[start_pos:])
                if end_match:
                    annual_plan_content = md_content[start_pos : start_pos + end_match.start()]
                else:
                    annual_plan_content = md_content[start_pos:]
        
        if not annual_plan_content or len(annual_plan_content) < 10:
             # 回退：使用旧的简单宽泛匹配
            annual_plan_match = re.search(r'(?:^|\n)\s*(?:#{1,6}\s*)?年度研究计划.*?\n(.*?)(?=\n#{1,6}|\Z)', md_content, re.DOTALL | re.IGNORECASE)
            annual_plan_content = annual_plan_match.group(1) if annual_plan_match else ""

        if not annual_plan_content:
            # 未找到年度计划章节
            return violations
        
        print(f"[正则检查] 找到年度研究计划章节，长度: {len(annual_plan_content)} 字符")
        
        # 提取所有年度计划的时间段
        # 使用统一模式，第二个年份可选（缩写格式如"2030年1-12月"省略第二个年份）
        time_pattern = r'(\d{4})\s*[.年]\s*(\d{1,2})\s*[月]?(?:\s*\d{1,2}日)?\s*[-—~至]{1,3}\s*(?:(\d{4})\s*[.年]\s*)?(\d{1,2})\s*月?'
        time_matches_raw = list(re.finditer(time_pattern, annual_plan_content))
        
        # 标准化：如果结束年份（group3）为空，使用起始年份（group1）
        class _NormalizedMatch:
            def __init__(self, m):
                self._m = m
            def group(self, n=0):
                if n == 0: return self._m.group(0)
                if n == 3: return self._m.group(3) or self._m.group(1)  # 缩写时用起始年份
                return self._m.group(n)
        time_matches = [_NormalizedMatch(m) for m in time_matches_raw]
        
        if not time_matches:
            violations.append({
                'rule_name': '年度研究计划时间连续性检查',
                'severity': 'high',
                'error_text': '年度研究计划中未找到时间段信息',
                'location': '年度研究计划',
                'suggestion': '请在年度研究计划中明确标注各年度的起止时间'
            })
            return violations
        
        # 解析所有时间段
        time_periods = []
        for match in time_matches:
            start_year, start_month = int(match.group(1)), int(match.group(2))
            end_year, end_month = int(match.group(3)), int(match.group(4))
            
            try:
                # 校验月份合法性
                if not (1 <= start_month <= 12 and 1 <= end_month <= 12):
                    continue
                    
                start_date = datetime(start_year, start_month, 1)
                # 计算结束日期（该月最后一天）
                if end_month == 12:
                    end_date = datetime(end_year + 1, 1, 1) - timedelta(days=1)
                else:
                    end_date = datetime(end_year, end_month + 1, 1) - timedelta(days=1)
                
                time_periods.append((start_date, end_date, match.group()))
            except ValueError:
                continue # 跳过非法日期
        
        print(f"[正则检查] 年度计划中找到 {len(time_periods)} 个时间段")
        
        # 规则5.1：检查时间与项目执行期一致（仅当项目期限已知时）
        if project_start and project_end:
            violations.extend(check_annual_plan_time_match_from_md(md_content, project_start, project_end, time_periods))
        
        # 规则5.2：检查时间衔接（总是执行）
        violations.extend(check_annual_plan_continuity_from_md(md_content, time_periods))
    
    except Exception as e:
        print(f"[正则检查] 年度计划时间检查异常: {e}")
    
    return violations


def check_phone_format_from_md(md_content: str) -> List[Dict]:
    """检查电话号码格式 - 从完整markdown中提取"""
    violations = []
    
    # 查找电话号码
    phone_patterns = [
        r'(?:办公电话|联系电话|单位电话|电话)[：:]\s*([^\n\|]+)',
        r'\|\s*(?:办公电话|联系电话|单位电话|电话)\s*\|\s*([^\|]+)\s*\|',
    ]
    
    for pattern in phone_patterns:
        matches = re.findall(pattern, md_content)
        for phone in matches:
            phone = phone.strip()
            # 忽略明显不是电话号码的内容（如包含“依托单位”、“Email”或过长）
            if not phone or phone == '-' or phone == '无' or '依托单位' in phone or 'Email' in phone or '邮箱' in phone or len(phone) > 25:
                continue
                
            # 检查格式：11位手机号或固定电话格式
            if not re.match(r'^\d{11}$|^\d{3,4}-\d{7,8}$', phone):
                violations.append({
                    'rule_name': '联系方式格式检查',
                    'severity': 'low',
                    'error_text': f'电话号码"{phone}"格式不正确',
                    'location': '基本信息表',
                    'suggestion': '电话号码应为11位手机号或固定电话格式（如0xx-xxxxxxxx）'
                })
    
    return violations


def check_email_format_from_md(md_content: str) -> List[Dict]:
    """检查邮箱格式 - 从完整markdown中提取"""
    violations = []
    
    # 查找邮箱
    email_patterns = [
        r'(?:电子邮箱|邮箱|E-?mail)[：:]\s*([^\n\|\s]+)',
        r'\|\s*(?:电子邮箱|邮箱)\s*\|\s*([^\|\s]+)\s*\|',
    ]
    
    for pattern in email_patterns:
        matches = re.findall(pattern, md_content, re.IGNORECASE)
        for email in matches:
            email = email.strip()
            if email and email != '-' and email != '无':
                # 检查邮箱格式
                if not re.match(r'^[\w\.-]+@[\w\.-]+\.\w+$', email):
                    violations.append({
                        'rule_name': '联系方式格式检查',
                        'severity': 'low',
                        'error_text': f'邮箱"{email}"格式不正确',
                        'location': '基本信息表',
                        'suggestion': '邮箱格式应为：example@domain.com'
                    })
    
    return violations


def check_organization_code_from_md(md_content: str) -> List[Dict]:
    """检查组织机构代码格式 - 从完整markdown中提取"""
    violations = []
    
    # 查找组织机构代码/统一社会信用代码
    code_patterns = [
        r'(?:组织机构代码|统一社会信用代码)[：:]\s*([A-Za-z0-9]+)',
        r'\|\s*(?:组织机构代码|统一社会信用代码)\s*\|\s*([A-Za-z0-9]+)\s*\|',
    ]
    
    for pattern in code_patterns:
        matches = re.findall(pattern, md_content)
        for code in matches:
            code = code.strip()
            if code and code != '-' and code != '无':
                # 检查格式：18位数字和大写字母组合
                if not re.match(r'^[0-9A-Z]{18}$', code):
                    violations.append({
                        'rule_name': '依托单位组织机构代码检查',
                        'severity': 'low',
                        'error_text': f'组织机构代码"{code}"格式不正确',
                        'location': '基本信息表',
                        'suggestion': '统一社会信用代码应为18位数字和大写字母组合'
                    })
    
    return violations


# ==================== 新增10条正则检查规则 ====================


def check_budget_consistency_from_md(md_content: str, vlm_content: str = None) -> List[Dict]:
    """检查预算总额与分项合计一致性（规则A1）

    从经费申请表中提取各分项金额和总额，校验二者是否一致。
    支持 Markdown | 表格和 HTML <table> 两种格式。
    """
    violations = []

    try:
        # === 1. 查找经费/预算相关区域 ===
        budget_section = None
        # 尝试定位经费申请表区域
        section_match = re.search(
            r'(?:#{1,6}\s*)?(?:经费申请表|经费预算|资金预算|申请经费).*?(?=\n#{1,3}[^#]|\Z)',
            md_content, re.DOTALL | re.IGNORECASE
        )
        if section_match:
            budget_section = section_match.group()
        else:
            # 退而求其次，搜索含有"万元"和多个金额数字的区域
            budget_section = md_content

        if not budget_section:
            return violations

        # === 2. 提取"合计"或"总计"金额 ===
        total_amount = None
        # Markdown表格: | 合计 | 123.45 | 或 | 合  计 | 123.45 |
        total_patterns = [
            r'\|\s*合\s*计\s*\|\s*([\d.]+)\s*\|',
            r'\|\s*总\s*计\s*\|\s*([\d.]+)\s*\|',
            r'合\s*计[：:]\s*([\d.]+)',
            r'总\s*计[：:]\s*([\d.]+)',
        ]
        for pattern in total_patterns:
            match = re.search(pattern, budget_section)
            if match:
                total_amount = float(match.group(1))
                break

        # HTML表格：支持"XX费用合计"等包含"合计"的内容
        if total_amount is None:
            html_total = re.search(
                r'<td[^>]*>[^<]*合\s*计[^<]*</td>\s*<td[^>]*>\s*([\d.]+)\s*</td>',
                budget_section, re.DOTALL | re.IGNORECASE
            )
            if html_total:
                total_amount = float(html_total.group(1))

        if total_amount is None or total_amount <= 0:
            return violations  # 未找到合计金额，跳过

        # === 3. 提取各分项金额 ===
        # 常见经费科目行：设备费、材料费、测试化验加工费、燃料动力费、差旅费、会议费、
        #   国际合作与交流费、出版/文献/信息传播/知识产权事务费、劳务费、专家咨询费、其他
        budget_items = [
            '设备费', '材料费', '测试化验加工费', '燃料动力费', '差旅费',
            '会议费', '国际合作与交流费', '出版', '劳务费', '专家咨询费',
            '间接费用', '管理费', '业务费'
        ]
        item_amounts = []
        for item in budget_items:
            # Markdown表格
            md_match = re.search(
                rf'\|\s*[^|]*{re.escape(item)}[^|]*\|\s*([\d.]+)\s*\|',
                budget_section
            )
            if md_match:
                try:
                    item_amounts.append(float(md_match.group(1)))
                except ValueError:
                    pass
                continue
            # HTML表格
            html_match = re.search(
                rf'<td[^>]*>[^<]*{re.escape(item)}[^<]*</td>\s*<td[^>]*>\s*([\d.]+)\s*</td>',
                budget_section, re.DOTALL | re.IGNORECASE
            )
            if html_match:
                try:
                    item_amounts.append(float(html_match.group(1)))
                except ValueError:
                    pass

        if len(item_amounts) < 2:
            return violations  # 分项太少，不做判断

        # === 4. 比较 ===
        items_sum = round(sum(item_amounts), 2)
        if abs(items_sum - total_amount) > 0.01:  # 允许0.01万元误差
            violations.append({
                'rule_name': '预算总额与分项合计一致性检查',
                'severity': 'high',
                'error_text': f'经费分项合计 {items_sum} 万元与总计 {total_amount} 万元不一致（差额 {round(abs(items_sum - total_amount), 2)} 万元）',
                'location': '经费申请表',
                'suggestion': '请核对各分项经费金额，确保分项之和等于合计金额'
            })

    except Exception as e:
        print(f"[正则检查] 预算一致性检查异常: {e}")

    return violations


def check_project_duration_from_md(md_content: str, vlm_content: str = None) -> List[Dict]:
    """检查项目起止年限合理性（规则A2）

    规则：执行期 ≤5 年；起始年份 ≥ 当前年份
    """
    violations = []

    try:
        duration_patterns = [
            # 精确日期格式: 2027年01月01日--2030年12月31日（PDF常见）
            r'(?:研究期限|执行期限|项目周期|起止年月)[^\d]*(\d{4})年(\d{1,2})月\d{1,2}日\s*[-—~至]{1,3}\s*(\d{4})年(\d{1,2})月\d{1,2}日',
            r'(?:研究期限|执行期限|项目周期|起止年月)[：:]\s*(\d{4})[.年](\d{1,2})[月]?\s*[-~至]\s*(\d{4})[.年](\d{1,2})',
            r'\|\s*(?:研究期限|执行期限)\s*\|\s*(\d{4})[.年](\d{1,2})[月]?\s*[-~至]\s*(\d{4})[.年](\d{1,2})',
            r'选择(\d{4})年(\d{1,2})月至(\d{4})年(\d{1,2})月',
            r'(\d{4})年(\d{1,2})月\d{1,2}日\s*[-—~至]{1,3}\s*(\d{4})年(\d{1,2})月\d{1,2}日',
            r'(\d{4})年(\d{1,2})月至(\d{4})年(\d{1,2})月',
        ]

        # 先尝试从HTML表格提取研究期限（主内容 + VLM回退）
        contents = [md_content, vlm_content]
        html_duration = _find_html_cell_value(contents, '研究期限')
        if html_duration:
            dur_match = re.search(r'(\d{4})年(\d{1,2})月.*?[-—~至]{1,3}.*?(\d{4})年(\d{1,2})月', html_duration)
            if dur_match:
                start_year = int(dur_match.group(1))
                start_month = int(dur_match.group(2))
                end_year = int(dur_match.group(3))
                end_month = int(dur_match.group(4))
                current_year = datetime.now().year
                duration_months = (end_year - start_year) * 12 + (end_month - start_month)
                duration_years = duration_months / 12.0

                if duration_years > 5:
                    violations.append({
                        'rule_name': '项目执行期限合理性检查',
                        'severity': 'high',
                        'error_text': f'项目执行期为 {duration_years:.1f} 年（{start_year}.{start_month:02d}-{end_year}.{end_month:02d}），超过5年上限',
                        'location': '基本信息表',
                        'suggestion': 'NSFC项目执行期一般不超过5年，请检查起止时间'
                    })
                if start_year < current_year:
                    violations.append({
                        'rule_name': '项目执行期限合理性检查',
                        'severity': 'medium',
                        'error_text': f'项目起始年份 {start_year} 早于当前年份 {current_year}',
                        'location': '基本信息表',
                        'suggestion': '项目起始年份通常不应早于当前年份，请核实'
                    })
                return violations

        # 在主内容和VLM回退中依次尝试正则匹配
        for _content in [md_content, vlm_content]:
            if not _content:
                continue
            regex_matched = False
            for pattern in duration_patterns:
                match = re.search(pattern, _content)
                if match:
                    regex_matched = True
                    start_year = int(match.group(1))
                    start_month = int(match.group(2))
                    end_year = int(match.group(3))
                    end_month = int(match.group(4))
                    current_year = datetime.now().year

                    # 计算时长（月）
                    duration_months = (end_year - start_year) * 12 + (end_month - start_month)
                    duration_years = duration_months / 12.0

                    if duration_years > 5:
                        violations.append({
                            'rule_name': '项目执行期限合理性检查',
                            'severity': 'high',
                            'error_text': f'项目执行期为 {duration_years:.1f} 年（{start_year}.{start_month:02d}-{end_year}.{end_month:02d}），超过5年上限',
                            'location': '基本信息表',
                            'suggestion': 'NSFC项目执行期一般不超过5年，请检查起止时间'
                        })

                    if start_year < current_year:
                        violations.append({
                            'rule_name': '项目执行期限合理性检查',
                            'severity': 'medium',
                            'error_text': f'项目起始年份 {start_year} 早于当前年份 {current_year}',
                            'location': '基本信息表',
                            'suggestion': '项目起始年份通常不应早于当前年份，请核实'
                        })

                    break  # 只检查第一个匹配
            if regex_matched:
                break

    except Exception as e:
        print(f"[正则检查] 项目年限检查异常: {e}")

    return violations


def check_id_card_format_from_md(md_content: str) -> List[Dict]:
    """检查身份证号格式校验（规则A3）

    规则：18位身份证号格式正确+校验位正确
    """
    violations = []

    try:
        # 查找所有可能的身份证号（18位数字/X）
        id_matches = re.finditer(r'(?<!\d)(\d{17}[\dXx])(?!\d)', md_content)

        for m in id_matches:
            id_num = m.group(1).upper()

            # 基本格式验证
            # 地区码（前6位）、出生日期（7-14位）
            area_code = id_num[:6]
            birth_str = id_num[6:14]

            # 验证出生日期合法性
            try:
                birth_date = datetime.strptime(birth_str, '%Y%m%d')
                if birth_date.year < 1900 or birth_date > datetime.now():
                    continue  # 可能不是身份证号，跳过
            except ValueError:
                continue  # 日期不合法，可能不是身份证号

            # 校验位验证
            weights = [7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2]
            check_chars = '10X98765432'
            total = sum(int(id_num[i]) * weights[i] for i in range(17))
            expected_check = check_chars[total % 11]

            if id_num[17] != expected_check:
                violations.append({
                    'rule_name': '身份证号格式校验',
                    'severity': 'high',
                    'error_text': f'身份证号 {id_num[:6]}****{id_num[-4:]} 校验位不正确（第18位应为"{expected_check}"，实际为"{id_num[17]}"）',
                    'location': '基本信息表/参与者信息',
                    'suggestion': '请核对身份证号是否填写正确，校验位不匹配'
                })

    except Exception as e:
        print(f"[正则检查] 身份证号格式检查异常: {e}")

    return violations


def check_required_fields_from_md(md_content: str, vlm_content: str = None) -> List[Dict]:
    """检查基本信息表必填字段是否为空（规则A11）
    
    三层检查：
    1. HTML表格（最准确，优先）
    2. Markdown表格（次之）
    3. 普通键值对格式（备选）

    规则：主要研究领域等关键字段不能为空
    """
    violations = []

    try:
        # 检查的必填字段列表: (字段名, 严重度, 提示)
        required_fields = [
            ('主要研究领域', 'high', '请填写主要研究领域，该字段为必填项'),
        ]

        contents = [md_content, vlm_content]

        for field_name, severity, suggestion in required_fields:
            field_checked = False  # 记录该字段是否已被检查并添加违规
            
            # === 方法1: HTML表格（最准确，优先） ===
            # 直接在HTML中查找 <td>字段名</td><td>值</td> 格式
            html_pattern = rf'<td[^>]*>\s*{re.escape(field_name)}\s*</td>\s*<td[^>]*>\s*(.*?)\s*</td>'
            
            for content in contents:
                if not content or field_checked:
                    continue
                
                matches = list(re.finditer(html_pattern, content, re.DOTALL | re.IGNORECASE))
                for match in matches:
                    value = match.group(1).strip()
                    # 去除HTML标签和空白符
                    value = re.sub(r'<[^>]+>', '', value)
                    value = value.replace('&nbsp;', '').strip()
                    # 移除常见占位符
                    if value in ['无', '-', '']:
                        value = ''
                    
                    if not value:
                        violations.append({
                            'rule_name': '基本信息必填字段检查',
                            'severity': severity,
                            'error_text': f'"{field_name}"字段为空，未填写内容',
                            'location': '基本信息表',
                            'suggestion': suggestion
                        })
                        field_checked = True
                        break
            
            if field_checked:
                continue

            # === 方法2: Markdown表格 - |字段名|值| 格式 ===
            md_pattern = rf'\|\s*{re.escape(field_name)}\s*\|\s*([^\|\n]*?)\s*\|'
            
            for content in contents:
                if not content or field_checked:
                    continue
                
                matches = list(re.finditer(md_pattern, content))
                for match in matches:
                    value = match.group(1).strip()
                    value = value.replace('&nbsp;', '').strip()
                    if value in ['无', '-', '']:
                        value = ''
                    
                    if not value:
                        violations.append({
                            'rule_name': '基本信息必填字段检查',
                            'severity': severity,
                            'error_text': f'"{field_name}"字段为空，未填写内容',
                            'location': '基本信息表',
                            'suggestion': suggestion
                        })
                        field_checked = True
                        break
            
            if field_checked:
                continue

            # === 方法3: 键值对格式 (Key: Value 或 Key：Value) ===
            kv_pattern = rf'(?:^|\n)\s*{re.escape(field_name)}\s*[：:]\s*([^\n]*)'
            
            for content in contents:
                if not content or field_checked:
                    continue
                
                matches = list(re.finditer(kv_pattern, content, re.MULTILINE))
                for match in matches:
                    value = match.group(1).strip()
                    # 避免匹配到表格行
                    if value.startswith('|'):
                        continue
                    
                    value = value.replace('&nbsp;', '').strip()
                    if value in ['无', '-', '']:
                        value = ''
                    
                    if not value:
                        violations.append({
                            'rule_name': '基本信息必填字段检查',
                            'severity': severity,
                            'error_text': f'"{field_name}"字段为空，未填写内容',
                            'location': '基本信息表',
                            'suggestion': suggestion
                        })
                        field_checked = True
                        break

    except Exception as e:
        print(f"[正则检查] 必填字段检查异常: {e}")

    return violations


def check_work_months_from_md(md_content: str, vlm_content: str = None) -> List[Dict]:
    """检查参与者每年工作月数合理性（规则A4）

    规则：每人每年投入月数 ≤12
    """
    violations = []

    try:
        # 在主要参与者表格中查找工作时间（月）
        # Markdown表格：常见列为 "每年工作月数" 或 "工作时间" 或 "每年工作(月)"
        participant_section = None
        for _content in [md_content, vlm_content]:
            if not _content:
                continue
            participant_section = re.search(
                r'(?:#{1,6}\s*)?(?:主要参与者|项目组成员|研究队伍|研究人员|参与人员|主要成员|课题组成员|项目组主要成员).*?(?=\n#{1,3}[^#]|\Z)',
                _content, re.DOTALL | re.IGNORECASE
            )
            if participant_section:
                break
        if not participant_section:
            return violations

        section = participant_section.group()

        # 方法1: Markdown表格 - 查找包含"工作月数"相关列的数据
        # 先找到表头行，确定工作月数所在的列索引
        # 注意：必须排除"出生年月"列，避免将出生年份误读为工作月数
        header_match = re.search(r'^\|(.+)\|$', section, re.MULTILINE)
        if header_match:
            headers = [h.strip() for h in header_match.group(1).split('|')]
            month_col_idx = None
            for idx, h in enumerate(headers):
                if re.search(r'出生', h):
                    continue  # 跳过"出生年月"列
                if re.search(r'工作.*月|投入.*月|每年.*月|月.*工作|工作时间|投入时间', h):
                    month_col_idx = idx
                    break

            if month_col_idx is not None:
                # 跳过分隔行，遍历数据行
                table_rows = re.findall(r'^\|(.+)\|$', section, re.MULTILINE)
                for row_str in table_rows:
                    if re.match(r'^[\s\-\|:]+$', row_str):
                        continue  # 跳过分隔行
                    cols = [c.strip() for c in row_str.split('|')]
                    if month_col_idx < len(cols):
                        month_str = cols[month_col_idx].strip()
                        # 提取数字
                        month_num = re.search(r'(\d+(?:\.\d+)?)', month_str)
                        if month_num:
                            months = float(month_num.group(1))
                            if months > 12:
                                # 试图获取姓名（通常在第1列或第2列）
                                name = cols[0].strip() if cols[0].strip() else (cols[1].strip() if len(cols) > 1 else '未知')
                                violations.append({
                                    'rule_name': '参与者工作时间合理性检查',
                                    'severity': 'high',
                                    'error_text': f'参与者"{name}"每年工作月数为 {months} 个月，超过12个月上限',
                                    'location': '主要参与者信息表',
                                    'suggestion': '每人每年投入工作月数不应超过12个月'
                                })

        # 方法2: HTML表格
        html_table = re.search(r'<table[^>]*>(.*?)</table>', section, re.DOTALL | re.IGNORECASE)
        if html_table and not violations:
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html_table.group(1), re.DOTALL)
            if len(rows) > 1:
                # 找月份列
                header_cells = re.findall(r'<t[hd][^>]*>(.*?)</t[hd]>', rows[0], re.DOTALL | re.IGNORECASE)
                header_texts = [re.sub(r'<[^>]+>', '', c).strip() for c in header_cells]
                month_col_idx = None
                for idx, h in enumerate(header_texts):
                    if re.search(r'出生', h):
                        continue  # 跳过"出生年月"列
                    if re.search(r'工作.*月|投入.*月|每年.*月|月.*工作|工作时间|投入时间', h):
                        month_col_idx = idx
                        break

                if month_col_idx is not None:
                    for row_html in rows[1:]:
                        cells = re.findall(r'<td[^>]*>(.*?)</td>', row_html, re.DOTALL | re.IGNORECASE)
                        cell_texts = [re.sub(r'<[^>]+>', '', c).strip() for c in cells]
                        if month_col_idx < len(cell_texts):
                            month_num = re.search(r'(\d+(?:\.\d+)?)', cell_texts[month_col_idx])
                            if month_num:
                                months = float(month_num.group(1))
                                if months > 12:
                                    name = cell_texts[0] if cell_texts[0] else '未知'
                                    violations.append({
                                        'rule_name': '参与者工作时间合理性检查',
                                        'severity': 'high',
                                        'error_text': f'参与者"{name}"每年工作月数为 {months} 个月，超过12个月上限',
                                        'location': '主要参与者信息表',
                                        'suggestion': '每人每年投入工作月数不应超过12个月'
                                    })

    except Exception as e:
        print(f"[正则检查] 工作月数检查异常: {e}")

    return violations


def check_keywords_count_from_md(md_content: str, vlm_content: str = None) -> List[Dict]:
    """检查关键词数量（规则A5）

    规则：NSFC 要求关键词 3-5 个
    """
    violations = []

    try:
        # 查找关键词行
        kw_patterns = [
            r'关键词[：:]\s*([^\n]+)',
            r'\|\s*关键词\s*\|\s*([^\|]+)\s*\|',
            r'Keywords?[：:]\s*([^\n]+)',
        ]

        kw_text = None
        for _content in [md_content, vlm_content]:
            if not _content or kw_text:
                continue
            for pattern in kw_patterns:
                match = re.search(pattern, _content, re.IGNORECASE)
                if match:
                    kw_text = match.group(1).strip()
                    break

        # HTML表格（主内容 + VLM回退）
        if not kw_text:
            kw_text_html = _find_html_cell_value([md_content, vlm_content], '关键词')
            if kw_text_html:
                kw_text = kw_text_html

        if not kw_text:
            return violations

        # 统计关键词数量（分隔符：分号、逗号、顿号）
        # 去掉前后空白
        kw_text = kw_text.strip().rstrip('。.;；')
        keywords = re.split(r'[;；,，、\s]\s*', kw_text)
        keywords = [k.strip() for k in keywords if k.strip()]

        if len(keywords) < 3:
            violations.append({
                'rule_name': '关键词数量检查',
                'severity': 'medium',
                'error_text': f'关键词仅 {len(keywords)} 个（{"; ".join(keywords)}），少于3个',
                'location': '基本信息',
                'suggestion': 'NSFC 要求填写 3-5 个关键词，请补充关键词'
            })
        elif len(keywords) > 5:
            violations.append({
                'rule_name': '关键词数量检查',
                'severity': 'medium',
                'error_text': f'关键词有 {len(keywords)} 个，超过5个',
                'location': '基本信息',
                'suggestion': 'NSFC 要求填写 3-5 个关键词，请精简关键词数量'
            })

    except Exception as e:
        print(f"[正则检查] 关键词检查异常: {e}")

    return violations


def check_reference_numbering_from_md(md_content: str) -> List[Dict]:
    """检查参考文献序号连续性（规则A6）

    规则：参考文献列表的编号应从[1]开始连续递增，不能跳号
    """
    violations = []

    try:
        # 查找参考文献列表区域（使用共用定位函数，支持无标题情况）
        ref_result = _locate_reference_section(md_content)
        if not ref_result:
            return violations

        ref_text = ref_result[0]

        # 提取所有 [n] 编号（文献列表行首的编号）
        # 匹配行首或段首的 [数字]
        ref_numbers = []
        for m in re.finditer(r'(?:^|\n)\s*\[(\d+)\]', ref_text):
            ref_numbers.append(int(m.group(1)))

        if len(ref_numbers) < 2:
            return violations

        # 检查起始编号
        if ref_numbers[0] != 1:
            violations.append({
                'rule_name': '参考文献序号连续性检查',
                'severity': 'medium',
                'error_text': f'参考文献编号起始为 [{ref_numbers[0]}]，应从 [1] 开始',
                'location': '参考文献',
                'suggestion': '参考文献序号应从[1]开始'
            })

        # 检查连续性
        missing = []
        for i in range(len(ref_numbers) - 1):
            expected_next = ref_numbers[i] + 1
            actual_next = ref_numbers[i + 1]
            if actual_next != expected_next:
                # 收集缺失的编号
                for n in range(expected_next, actual_next):
                    missing.append(n)

        if missing:
            if len(missing) <= 5:
                missing_str = ', '.join(f'[{n}]' for n in missing)
            else:
                missing_str = ', '.join(f'[{n}]' for n in missing[:5]) + f' 等共{len(missing)}处'
            violations.append({
                'rule_name': '参考文献序号连续性检查',
                'severity': 'high',
                'error_text': f'参考文献编号不连续，缺少：{missing_str}',
                'location': '参考文献',
                'suggestion': '参考文献序号应连续递增，不能跳号'
            })

    except Exception as e:
        print(f"[正则检查] 参考文献序号检查异常: {e}")

    return violations


def check_reference_citation_coverage_from_md(md_content: str) -> List[Dict]:
    """检查参考文献正文引用覆盖（规则A7）

    规则：
    - 文末列出的参考文献应在正文中被引用
    - 正文中引用的编号应在文末有对应条目
    """
    violations = []

    try:
        # === 1. 定位参考文献区域（使用共用定位函数，支持无标题情况） ===
        ref_result = _locate_reference_section(md_content)
        if not ref_result:
            return violations

        ref_section, body_text, ref_start_pos = ref_result

        # === 2. 提取参考文献列表中的编号 ===
        ref_list_numbers = set()
        for m in re.finditer(r'(?:^|\n)\s*\[(\d+)\]', ref_section):
            ref_list_numbers.add(int(m.group(1)))

        if not ref_list_numbers:
            return violations

        # === 3. 提取正文中引用的编号 ===
        # 匹配 [1], [2,3], [1-3], [1,3-5] 等
        body_citation_numbers = set()
        for m in re.finditer(r'\[([\d,\-\s]+)\]', body_text):
            citation_str = m.group(1)
            # 解析 "1,2,3-5" 格式
            for part in citation_str.split(','):
                part = part.strip()
                range_match = re.match(r'(\d+)\s*-\s*(\d+)', part)
                if range_match:
                    start, end = int(range_match.group(1)), int(range_match.group(2))
                    for n in range(start, end + 1):
                        body_citation_numbers.add(n)
                elif re.match(r'^\d+$', part):
                    body_citation_numbers.add(int(part))

        # === 4. 比较 ===
        # 文末有但正文未引用
        unreferenced = ref_list_numbers - body_citation_numbers
        # 正文引用但文末无条目
        missing_in_list = body_citation_numbers - ref_list_numbers

        if unreferenced:
            nums_sorted = sorted(unreferenced)
            if len(nums_sorted) <= 5:
                nums_str = ', '.join(f'[{n}]' for n in nums_sorted)
            else:
                nums_str = ', '.join(f'[{n}]' for n in nums_sorted[:5]) + f' 等共{len(nums_sorted)}条'
            violations.append({
                'rule_name': '参考文献引用覆盖检查',
                'severity': 'medium',
                'error_text': f'文末列出但正文中未引用的参考文献：{nums_str}',
                'location': '参考文献',
                'suggestion': '文末参考文献列表中的每一条都应在正文中被引用'
            })

        if missing_in_list:
            nums_sorted = sorted(missing_in_list)
            # 过滤掉过大的编号（可能是误匹配，如年份 [2024]）
            nums_sorted = [n for n in nums_sorted if n <= max(ref_list_numbers) + 10]
            if nums_sorted:
                if len(nums_sorted) <= 5:
                    nums_str = ', '.join(f'[{n}]' for n in nums_sorted)
                else:
                    nums_str = ', '.join(f'[{n}]' for n in nums_sorted[:5]) + f' 等共{len(nums_sorted)}条'
                violations.append({
                    'rule_name': '参考文献引用覆盖检查',
                    'severity': 'high',
                    'error_text': f'正文中引用但文末缺少对应条目：{nums_str}',
                    'location': '参考文献',
                    'suggestion': '正文中引用的每一个编号都应在文末参考文献列表中有对应条目'
                })

    except Exception as e:
        print(f"[正则检查] 参考文献引用覆盖检查异常: {e}")

    return violations


def check_abstract_length_from_md(md_content: str, vlm_content: str = None) -> List[Dict]:
    """检查摘要字数限制（规则A8）

    规则：中文摘要 ≤400 字，英文摘要 ≤500 words
    """
    violations = []

    try:
        contents = [md_content, vlm_content]

        # === 中文摘要 ===
        cn_abstract_patterns = [
            r'(?:#{1,6}\s*)?(?:中文)?摘\s*要[：:]*\s*\n(.*?)(?=\n#{1,6}|关键词|Keywords|Abstract|英文摘要)',
            r'(?:#{1,6}\s*)?项目摘要[：:]*\s*\n(.*?)(?=\n#{1,6}|关键词|Keywords)',
        ]
        cn_abstract = None
        for _content in contents:
            if not _content or cn_abstract:
                continue
            for pattern in cn_abstract_patterns:
                match = re.search(pattern, _content, re.DOTALL | re.IGNORECASE)
                if match:
                    cn_abstract = match.group(1).strip()
                    break

        # HTML表格中也可能有摘要（主内容 + VLM回退）
        if not cn_abstract:
            abstract_html = _find_html_cell_value(contents, '摘要')
            if not abstract_html:
                abstract_html = _find_html_cell_value(contents, '项目摘要')
            if abstract_html:
                cn_abstract = abstract_html

        if cn_abstract:
            # 统计中文字符数（不含空格、标点、英文）
            cn_chars = len(re.findall(r'[\u4e00-\u9fa5]', cn_abstract))
            if cn_chars > 400:
                violations.append({
                    'rule_name': '摘要字数限制检查',
                    'severity': 'medium',
                    'error_text': f'中文摘要约 {cn_chars} 个汉字，超过400字限制',
                    'location': '项目摘要',
                    'suggestion': 'NSFC 要求中文摘要不超过400个汉字，请精简'
                })

        # === 英文摘要 ===
        en_abstract_patterns = [
            r'(?:#{1,6}\s*)?(?:英文)?Abstract[：:]*\s*\n(.*?)(?=\n#{1,6}|Keywords|关键词|\Z)',
            r'(?:#{1,6}\s*)?英文摘要[：:]*\s*\n(.*?)(?=\n#{1,6}|Keywords|关键词|\Z)',
        ]
        en_abstract = None
        for _content in contents:
            if not _content or en_abstract:
                continue
            for pattern in en_abstract_patterns:
                match = re.search(pattern, _content, re.DOTALL | re.IGNORECASE)
                if match:
                    en_abstract = match.group(1).strip()
                    break

        # HTML表格回退（主内容 + VLM回退）
        if not en_abstract:
            en_html = _find_html_cell_value(contents, '英文摘要')
            if not en_html:
                en_html = _find_html_cell_value(contents, 'Abstract')
            if en_html:
                en_abstract = en_html

        if en_abstract:
            # 统计英文单词数
            en_words = len(re.findall(r'[a-zA-Z]+', en_abstract))
            if en_words > 500:
                violations.append({
                    'rule_name': '摘要字数限制检查',
                    'severity': 'medium',
                    'error_text': f'英文摘要约 {en_words} 个单词，超过500词限制',
                    'location': '英文摘要',
                    'suggestion': 'NSFC 要求英文摘要不超过500个单词，请精简'
                })

    except Exception as e:
        print(f"[正则检查] 摘要字数检查异常: {e}")

    return violations


def check_title_consistency_from_md(md_content: str, vlm_content: str = None) -> List[Dict]:
    """检查项目名称中英文一致性（规则A9）

    基础规则：中英文标题长度比是否在合理范围内
    """
    violations = []

    try:
        contents = [md_content, vlm_content]

        # 提取中文标题
        cn_title = None
        cn_title_patterns = [
            r'(?:项目名称|课题名称|中文项目名称)[：:]\s*([^\n\|]+)',
            r'\|\s*(?:项目名称|课题名称)\s*\|\s*([^\|]+)\s*\|',
        ]
        for _content in contents:
            if not _content or cn_title:
                continue
            for pattern in cn_title_patterns:
                match = re.search(pattern, _content)
                if match:
                    cn_title = match.group(1).strip()
                    break

        if not cn_title:
            cn_title_html = _find_html_cell_value(contents, '项目名称')
            if not cn_title_html:
                cn_title_html = _find_html_cell_value(contents, '课题名称')
            if cn_title_html:
                cn_title = cn_title_html

        # 提取英文标题
        en_title = None
        en_title_patterns = [
            r'(?:英文项目名称|英文名称|Project Title|English Title)[：:]\s*([^\n\|]+)',
            r'\|\s*(?:英文项目名称|英文名称)\s*\|\s*([^\|]+)\s*\|',
        ]
        for _content in contents:
            if not _content or en_title:
                continue
            for pattern in en_title_patterns:
                match = re.search(pattern, _content, re.IGNORECASE)
                if match:
                    en_title = match.group(1).strip()
                    break

        if not en_title:
            en_title_html = _find_html_cell_value(contents, '英文项目名称')
            if not en_title_html:
                en_title_html = _find_html_cell_value(contents, '英文名称')
            if en_title_html:
                en_title = en_title_html

        if not cn_title or not en_title:
            return violations

        # 中文字符数
        cn_char_count = len(re.findall(r'[\u4e00-\u9fa5]', cn_title))
        # 英文单词数
        en_word_count = len(re.findall(r'[a-zA-Z]+', en_title))

        if cn_char_count == 0 or en_word_count == 0:
            return violations

        # 一般中文:英文词 比例在 1:0.5 ~ 1:3 之间
        ratio = en_word_count / cn_char_count

        if ratio < 0.3:
            violations.append({
                'rule_name': '项目名称中英文一致性检查',
                'severity': 'medium',
                'error_text': f'英文标题过短（{en_word_count}词），中文标题有{cn_char_count}字，英文/中文比 {ratio:.2f} 异常偏低',
                'location': '基本信息',
                'suggestion': '英文标题长度明显过短，可能翻译不完整，请核对中英文标题是否对应'
            })
        elif ratio > 4.0:
            violations.append({
                'rule_name': '项目名称中英文一致性检查',
                'severity': 'medium',
                'error_text': f'英文标题过长（{en_word_count}词），中文标题仅{cn_char_count}字，英文/中文比 {ratio:.2f} 异常偏高',
                'location': '基本信息',
                'suggestion': '英文标题长度明显过长，可能包含了额外信息，请核对中英文标题是否对应'
            })

    except Exception as e:
        print(f"[正则检查] 标题一致性检查异常: {e}")

    return violations


def check_duplicate_paragraphs_from_md(md_content: str) -> List[Dict]:
    """检查正文中重复段落（规则A10）

    使用滑动窗口哈希比对，以句子为单位检测大段重复内容。
    """
    violations = []

    try:
        # 提取正文内容（跳过表格区域和参考文献区域）
        # 识别参考文献区域的开始位置
        ref_header_pattern = re.compile(r'#+\s*(?:参考文献|References|Bibliography)', re.IGNORECASE)
        ref_match = ref_header_pattern.search(md_content)
        
        check_content = md_content
        if ref_match:
            # 只检查参考文献之前的正文，避免将重复识别的文献当成重复段落
            check_content = md_content[:ref_match.start()]
            
        # 分割成段落
        paragraphs = re.split(r'\n{2,}', check_content)

        # 只检查足够长的段落（≥50字符，避免短句误报）
        MIN_PARA_LEN = 50
        long_paras = []
        for p in paragraphs:
            text = p.strip()
            # 跳过表格行、标题行、HTML标签行
            if text.startswith('|') or text.startswith('#') or text.startswith('<'):
                continue
            # 去掉行内引用标记
            text_clean = re.sub(r'\[\d+(?:[-,]\d+)*\]', '', text)
            text_clean = re.sub(r'\s+', '', text_clean)  # 去掉空白便于比较
            if len(text_clean) >= MIN_PARA_LEN:
                long_paras.append((text_clean, text[:80]))  # (normalized, display_preview)

        if len(long_paras) < 2:
            return violations

        # 检测重复（精确子串匹配，取较短段落检测是否被包含）
        reported = set()
        for i in range(len(long_paras)):
            for j in range(i + 1, len(long_paras)):
                text_i, preview_i = long_paras[i]
                text_j, preview_j = long_paras[j]

                # 计算最长公共子串长度（简化版：检测是否有≥50字符的重复）
                shorter = text_i if len(text_i) <= len(text_j) else text_j
                longer = text_j if len(text_i) <= len(text_j) else text_i

                # 使用滑动窗口检测重复
                window_size = min(50, len(shorter))
                if window_size < 40:
                    continue

                found_dup = False
                for k in range(0, len(shorter) - window_size + 1, 10):
                    window = shorter[k:k + window_size]
                    if window in longer and (k > 0 or shorter != longer):
                        # 确认不是同一段落
                        if text_i != text_j or i != j:
                            dup_key = (min(i, j), max(i, j))
                            if dup_key not in reported:
                                found_dup = True
                                reported.add(dup_key)
                            break

                if found_dup:
                    violations.append({
                        'rule_name': '正文重复段落检测',
                        'severity': 'medium',
                        'error_text': f'检测到两处段落存在大段重复内容（≥{window_size}字符）："{preview_i[:40]}..." 与 "{preview_j[:40]}..."',
                        'location': '报告正文',
                        'suggestion': '正文中存在明显重复段落，请检查是否为复制粘贴遗留'
                    })

                    if len(violations) >= 3:  # 最多报3处重复
                        return violations

    except Exception as e:
        print(f"[正则检查] 重复段落检测异常: {e}")

    return violations


def check_reference_timeliness_and_selfcite(md_content: str, api_key: str = None, model_name: str = None, vlm_content: str = None) -> List[Dict]:
    """检查参考文献时效性（C1）和自引率（C2）——合并为一个函数

    策略：先用正则提取全部信息，仅在正则无法判别英文姓名对应关系时调用一次LLM。

    C1 - 参考文献时效性：
        - 提取每条参考文献的出版年份
        - 近5年文献占比 < 30% → warning
        - 存在≥15年的老旧文献 → info提示
    C2 - 自引率：
        - 从申请书提取申请人/负责人姓名
        - 对每条参考文献提取作者列表
        - 判断申请人是否出现在作者中
        - 自引率 > 40% → warning
    """
    violations = []

    try:
        current_year = datetime.now().year

        # ==================== 定位参考文献区域（支持无标题情况） ====================
        ref_result = _locate_reference_section(md_content)
        if not ref_result:
            return violations

        ref_section, body_text, _ref_start = ref_result

        # 提取单条参考文献（以 [n] 开头的行或段落）
        ref_entries = re.findall(
            r'\[(\d+)\]\s*(.+?)(?=\n\s*\[\d+\]|\Z)',
            ref_section, re.DOTALL
        )
        if not ref_entries:
            return violations

        # ==================== C1: 提取年份，评估时效性 ====================
        ref_years = []  # [(ref_no, year, ref_text_preview)]
        for ref_no_str, ref_text in ref_entries:
            ref_no = int(ref_no_str)
            # 提取年份：优先匹配 ", YYYY" 或 ". YYYY" 模式
            year_match = re.search(r'[,，.．]\s*([12]\d{3})\b', ref_text)
            if not year_match:
                # 回退：匹配任意四位年份
                year_match = re.search(r'\b([12]\d{3})\b', ref_text)
            if year_match:
                year = int(year_match.group(1))
                if 1900 <= year <= current_year + 1:
                    ref_years.append((ref_no, year, ref_text.strip()[:60]))

        if ref_years:
            total_with_year = len(ref_years)
            recent_5 = sum(1 for _, y, _ in ref_years if current_year - y <= 5)
            very_old = [(no, y) for no, y, _ in ref_years if current_year - y >= 15]

            recent_ratio = recent_5 / total_with_year if total_with_year > 0 else 0

            if recent_ratio < 0.30 and total_with_year >= 5:
                violations.append({
                    'rule_name': '参考文献时效性检查',
                    'severity': 'medium',
                    'error_text': f'近5年文献仅 {recent_5}/{total_with_year} 篇（占比 {recent_ratio:.0%}），建议补充最新研究成果',
                    'location': '参考文献',
                    'suggestion': '国自然申请建议近5年文献占比 ≥ 30%，以体现对前言进展的关注'
                })

            if very_old:
                # 调整老旧文献判罚标准：20年（1900-2006）定义为老旧
                REALLY_OLD = 20
                old_list = ', '.join(f'[{no}]({y}年)' for no, y in very_old if current_year - y >= REALLY_OLD)[:80]
                if old_list:
                    extra = f' 等' if len(very_old) > 5 else ''
                    violations.append({
                        'rule_name': '参考文献时效性检查',
                        'severity': 'low',
                        'error_text': f'存在发表超过{REALLY_OLD}年的老旧文献：{old_list}{extra}',
                        'location': '参考文献',
                        'suggestion': '建议检查老旧文献是否确实必要，若为经典文献可保留'
                    })

        # ==================== C2: 自引率检查 ====================
        # 步骤1: 提取申请人姓名
        applicant_name = None
        # 中文姓名
        name_patterns = [
            r'(?:申请人|项目负责人|负责人|课题负责人)\s*[:：]\s*([\u4e00-\u9fa5]{2,4})',
            r'(?:申\s*请\s*人|项目负责人)\s*[:：]?\s*([\u4e00-\u9fa5]{2,4})',
        ]
        for pat in name_patterns:
            m = re.search(pat, body_text)
            if m:
                applicant_name = m.group(1).strip()
                break

        # 也提取可能的英文名
        applicant_en_name = None
        en_name_match = re.search(
            r'(?:申请人|项目负责人).*?(?:英文名|English\s*name)\s*[:：]\s*([A-Za-z][\w\s\-\.]+)',
            md_content, re.IGNORECASE
        )
        if en_name_match:
            applicant_en_name = en_name_match.group(1).strip()

        if not applicant_name:
            # 从表格中提取（主内容 + VLM回退）
            table_name = None
            for _content in [md_content, vlm_content]:
                if not _content or table_name:
                    continue
                table_name = re.search(
                    r'(?:申\s*请\s*人|申请人|项目负责人)\s*[|｜]\s*([\u4e00-\u9fa5]{2,4})',
                    _content
                )
            if not table_name:
                table_name = _find_html_cell_value([md_content, vlm_content], r'申请人|项目负责人')
                if table_name:
                    cn_match = re.search(r'([\u4e00-\u9fa5]{2,4})', table_name)
                    applicant_name = cn_match.group(1) if cn_match else None
            else:
                applicant_name = table_name.group(1).strip()

        if applicant_name and ref_entries:
            # 步骤2: 对每条参考文献提取作者部分并匹配
            self_cite_count = 0
            self_cite_refs = []
            uncertain_refs = []  # 需LLM辅助判断的（英文名）

            for ref_no_str, ref_text in ref_entries:
                ref_no = int(ref_no_str)
                ref_clean = ref_text.strip()

                # 提取作者部分（参考文献开头到标题标记 [ 之前，或第一个句号之前）
                author_part_match = re.match(
                    r'(.+?)(?:\[(?:[JMCDPRSGAN]|EB|OL|DB))',
                    ref_clean, re.IGNORECASE
                )
                if not author_part_match:
                    author_part_match = re.match(r'(.+?)[.．。]', ref_clean)
                author_part = author_part_match.group(1) if author_part_match else ref_clean[:80]

                # 中文姓名精确匹配
                if applicant_name in author_part:
                    self_cite_count += 1
                    self_cite_refs.append(ref_no)
                    continue

                # 英文姓名匹配（如果有中文名对应的拼音或英文名）
                if applicant_en_name:
                    # 简单匹配：英文名出现在作者部分
                    en_parts = applicant_en_name.lower().split()
                    author_lower = author_part.lower()
                    if any(p in author_lower for p in en_parts if len(p) > 1):
                        self_cite_count += 1
                        self_cite_refs.append(ref_no)
                        continue

                # 中文姓氏 + 英文作者部分的拼音匹配
                if applicant_name and len(applicant_name) >= 2:
                    surname = applicant_name[0]
                    # 检查是否有纯英文/拼音作者列表（如 "Zhang S, Li M, ..."）
                    has_latin_authors = bool(re.search(r'[A-Za-z]{2,}', author_part))
                    if has_latin_authors and not any('\u4e00' <= c <= '\u9fa5' for c in author_part):
                        # 纯英文参考文献，标记为不确定
                        uncertain_refs.append((ref_no, author_part[:80]))

            # 步骤3: 如果有不确定的英文参考文献且提供了API，用一次LLM判断
            if uncertain_refs and api_key and model_name:
                try:
                    import requests
                    llm_self_cites = _llm_check_selfcite(
                        applicant_name, applicant_en_name, uncertain_refs,
                        api_key, model_name
                    )
                    self_cite_count += llm_self_cites
                except Exception as e:
                    print(f"[正则检查] 自引率LLM辅助判断失败（降级为仅正则结果）: {e}")

            # 步骤4: 计算自引率
            total_refs = len(ref_entries)
            if total_refs >= 5:
                self_cite_ratio = self_cite_count / total_refs
                if self_cite_ratio > 0.40:
                    violations.append({
                        'rule_name': '参考文献自引率检查',
                        'severity': 'medium',
                        'error_text': f'自引文献 {self_cite_count}/{total_refs} 篇（自引率 {self_cite_ratio:.0%}），比例偏高',
                        'location': '参考文献',
                        'suggestion': '自引率建议控制在40%以内，过高的自引率可能影响评审印象'
                    })
                elif self_cite_ratio > 0.30:
                    violations.append({
                        'rule_name': '参考文献自引率检查',
                        'severity': 'low',
                        'error_text': f'自引文献 {self_cite_count}/{total_refs} 篇（自引率 {self_cite_ratio:.0%}），略高',
                        'location': '参考文献',
                        'suggestion': '自引率相对较高，建议适当增加他引文献'
                    })

    except Exception as e:
        print(f"[正则检查] 参考文献时效性/自引率检查异常: {e}")

    return violations


def _llm_check_selfcite(applicant_name: str, applicant_en_name: str,
                         uncertain_refs: list, api_key: str, model_name: str) -> int:
    """使用一次LLM调用判断多条英文参考文献中申请人是否为作者

    设计原则：尽可能少消耗token，仅传入必要信息。

    Args:
        applicant_name: 申请人中文名
        applicant_en_name: 申请人英文名（可为None）
        uncertain_refs: [(ref_no, author_part), ...] 待判断的参考文献
        api_key: SiliconFlow API密钥
        model_name: 模型名称

    Returns:
        int: 被判定为自引的条数
    """
    import requests

    # 构造极简 prompt，只传作者片段
    ref_lines = '\n'.join(f'[{no}] {author}' for no, author in uncertain_refs[:15])  # 最多15条
    en_hint = f'，英文名可能为 {applicant_en_name}' if applicant_en_name else ''

    prompt = f"""判断以下参考文献的作者中是否包含"{applicant_name}"{en_hint}。
仅回复JSON数组，每项为参考文献编号，如 [3,7,12]。若全不包含回复 []。

{ref_lines}"""

    # 使用统一的LLM配置函数（支持本地LLM和硅基流动）
    from md_content_processor import _get_llm_config
    api_url, headers, actual_model, server_name = _get_llm_config(api_key, model_name)
    
    request_data = {
        "model": actual_model,
        "messages": [
            {"role": "system", "content": "你是一个学术论文作者姓名匹配专家。只回复JSON数组，不加任何解释。"},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "max_tokens": 200,
        "stream": False
    }

    response = requests.post(api_url, json=request_data, headers=headers, timeout=30)
    if response.status_code != 200:
        print(f"[自引率LLM] API返回状态码 {response.status_code}")
        return 0

    resp_data = response.json()
    ai_content = resp_data['choices'][0]['message']['content'].strip()

    # 解析返回的编号数组
    import json as _json
    # 清理 markdown 代码块
    ai_content = re.sub(r'```(?:json)?\s*', '', ai_content).strip()
    try:
        result = _json.loads(ai_content)
        if isinstance(result, list):
            count = len([x for x in result if isinstance(x, int)])
            print(f"[自引率LLM] 判定 {count} 条为自引（共 {len(uncertain_refs)} 条待判断）")
            return count
    except Exception:
        # 尝试提取数字
        nums = re.findall(r'\d+', ai_content)
        if nums:
            return len(nums)

    return 0


def check_funding_amount_limit_from_md(md_content: str, vlm_content: str = None) -> List[Dict]:
    """检查资助类别金额限制（规则A12）
    
    规则：
    - 青年科学基金 ≤ 30万元
    - 面上项目 ≤ 80万元（直接费用）
    - 地区科学基金 ≤ 40万元
    """
    violations = []
    try:
        contents = [md_content, vlm_content]
        
        # 1. 提取资助类别
        category = None
        cat_patterns = [
            r'(?:资助类别|项目类别|申请类别)[：:]\s*([^\n\|]+)',
            r'\|\s*(?:资助类别|项目类别)\s*\|\s*([^\|]+)\s*\|',
        ]
        for c in contents:
            if not c or category: continue
            for p in cat_patterns:
                m = re.search(p, c)
                if m:
                    category = m.group(1).strip()
                    break
        
        if not category:
            return violations

        # 2. 提取申请经费（总额或直接费用）
        amount = None
        amount_patterns = [
            r'(?:申请经费|直接费用|申请总额)[：:]\s*(\d+(?:\.\d+)?)',
            r'\|\s*(?:申请经费|直接费用)\s*\|\s*(\d+(?:\.\d+)?)\s*\|',
        ]
        for c in contents:
            if not c or amount: continue
            for p in amount_patterns:
                m = re.search(p, c)
                if m:
                    amount = float(m.group(1))
                    break
        
        if amount is None:
            return violations
            
        # 3. 校验规则
        limit = None
        rule_type = ""
        
        if "青年" in category:
            limit = 30.0
            rule_type = "青年科学基金"
        elif "面上" in category:
            limit = 80.0
            rule_type = "面上项目"
        elif "地区" in category:
            limit = 40.0
            rule_type = "地区科学基金"
            
        if limit and amount > limit:
            violations.append({
                'rule_name': '资助类别金额限制检查',
                'severity': 'high',
                'error_text': f'{rule_type}申请经费为 {amount} 万元，超过上限 {limit} 万元',
                'location': '基本信息表',
                'suggestion': f'请核对{rule_type}的经费预算是否符合指南要求（通常≤{limit}万元）'
            })

    except Exception as e:
        print(f"[正则检查] 金额限制检查异常: {e}")
        
    return violations


def check_funding_duration_limit_from_md(md_content: str, vlm_content: str = None) -> List[Dict]:
    """检查资助类别年限限制（规则A13）
    
    规则：
    - 青年科学基金 ≤ 3年
    - 面上项目 ≤ 4年
    - 地区科学基金 ≤ 4年
    """
    violations = []
    try:
        contents = [md_content, vlm_content]
        
        # 1. 提取资助类别
        category = None
        cat_patterns = [
            r'(?:资助类别|项目类别|申请类别)[：:]\s*([^\n\|]+)',
            r'\|\s*(?:资助类别|项目类别)\s*\|\s*([^\|]+)\s*\|',
        ]
        for c in contents:
            if not c or category: continue
            for p in cat_patterns:
                m = re.search(p, c)
                if m:
                    category = m.group(1).strip()
                    break
        
        if not category:
            return violations

        # 2. 提取并计算项目年限（复用已有逻辑提取起止时间）
        duration_years = None
        # ... 复用 check_project_duration_from_md 中的提取逻辑 ...
        # 这里简化重写一次查找
        duration_patterns = [
             r'(\d{4})年(\d{1,2})月\d{1,2}日\s*[-—~至]{1,3}\s*(\d{4})年(\d{1,2})月\d{1,2}日',
             r'(\d{4})[.年](\d{1,2})[月]?\s*[-~至]\s*(\d{4})[.年](\d{1,2})',
             r'(\d{4})年(\d{1,2})月至(\d{4})年(\d{1,2})月',
        ]
        
        start_date = None
        end_date = None
        
        for c in contents:
            if not c or start_date: continue
            for p in duration_patterns:
                m = re.search(p, c)
                if m:
                    start_year, start_month = int(m.group(1)), int(m.group(2))
                    end_year, end_month = int(m.group(3)), int(m.group(4))
                    duration_months = (end_year - start_year) * 12 + (end_month - start_month)
                    duration_years = duration_months / 12.0
                    break
        
        if duration_years is None:
            return violations
            
        # 3. 校验规则
        limit_years = None
        rule_type = ""
        
        if "青年" in category:
            limit_years = 3.0
            rule_type = "青年科学基金"
        elif "面上" in category:
            limit_years = 4.0
            rule_type = "面上项目"
        elif "地区" in category:
            limit_years = 4.0
            rule_type = "地区科学基金"
            
        if limit_years and duration_years > limit_years:  # 严格大于
             # 考虑到月份差异，给予 0.1 年的宽限（如计算出 4.08 年可能是正常的）
             if duration_years > limit_years + 0.1:
                violations.append({
                    'rule_name': '资助类别年限限制检查',
                    'severity': 'high',
                    'error_text': f'{rule_type}执行期限为 {duration_years:.1f} 年，超过上限 {limit_years} 年',
                    'location': '基本信息表',
                    'suggestion': f'请核对{rule_type}的执行期限是否符合指南要求（通常≤{limit_years}年）'
                })

    except Exception as e:
        print(f"[正则检查] 年限限制检查异常: {e}")
        
    return violations


def check_personnel_sum_from_md(md_content: str, vlm_content: str = None) -> List[Dict]:
    """检查总人数与分项之和的一致性（人员统计规则）
    
    规则：总人数 = 高级 + 中级 + 初级 + 博士后 + 博士生 + 硕士生 + 本科生 + 其他
    支持 Markdown |..| 表格和 HTML <table> 两种格式
    """
    violations = []
    try:
        contents = [md_content, vlm_content]
        
        # === 1. 尝试从 HTML 表格提取 (VLM输出) ===
        table_html = None
        for c in contents:
            if not c: continue
            # 查找包含"总人数"及"高级"等关键词的表格
            m = re.search(r'总人数统计.*?<table[^>]*>(.*?)</table>', c, re.DOTALL | re.IGNORECASE)
            if not m: # 有时标题可能不在table标签紧邻处，尝试直接找含特定表头的table
                m = re.search(r'<table[^>]*>(.*?)总人数(.*?)</table>', c, re.DOTALL | re.IGNORECASE)
                if m:
                    table_html = m.group(0) # 修正为整个table匹配
            else:
                table_html = m.group(1)
            
            if table_html: break
        
        values = []
        is_html_parsed = False

        if table_html:
            rows = re.findall(r'<tr[^>]*>(.*?)</tr>', table_html, re.DOTALL)
            # 找到包含"总人数"及"高级"的表头行索引
            header_idx = -1
            for i, row in enumerate(rows):
                if "总人数" in row and "高级" in row:
                    header_idx = i
                    break
            
            if header_idx != -1 and len(rows) > header_idx + 1:
                # 假设表头行的下一行是数据行
                data_row = rows[header_idx + 1]
                cells = re.findall(r'<td[^>]*>(.*?)</td>', data_row, re.DOTALL | re.IGNORECASE)
                # 解析数值
                for cell in cells:
                    txt = re.sub(r'<[^>]+>', '', cell).strip()
                    # 移除非数字字符（如 "3人" -> "3"）
                    txt_clean = re.sub(r'[^\d]', '', txt)
                    try:
                        if txt_clean:
                            values.append(int(txt_clean))
                        else:
                            values.append(0)
                    except:
                        values.append(0)
                is_html_parsed = True

        # === 2. 尝试从 Markdown 表格提取 (Pipeline输出) ===
        if not is_html_parsed or not values:
            # 查找包含"总人数"和"高级"的表格行
            # 格式：| 总人数 | 高级 | 中级 | ... |
            for c in contents:
                if not c: continue
                # 查找表头行
                header_match = re.search(r'^\|\s*总人数\s*\|\s*高级.*?\|', c, re.MULTILINE)
                if header_match:
                    # 获取表头后的内容
                    post_header = c[header_match.end():]
                    # 跳过可能的分割行 |---|---|
                    lines = post_header.strip().split('\n')
                    if not lines: continue
                    
                    data_line = None
                    for line in lines:
                        if re.match(r'^\|\s*[-:]+\s*\|', line): # 分割行
                            continue
                        if re.match(r'^\|\s*\d+', line) or re.match(r'^\|\s*[\d\s|]+', line): # 数据行
                            data_line = line
                            break
                        if line.strip() == "": continue
                        break # 遇到非表格行则停止

                    if data_line:
                        # 提取数据
                        cells = [x.strip() for x in data_line.strip().split('|') if x.strip() != '']
                        # 清洗数据
                        values = []
                        for cell in cells:
                            txt_clean = re.sub(r'[^\d]', '', cell)
                            try:
                                if txt_clean:
                                    values.append(int(txt_clean))
                                else:
                                    values.append(0)
                            except:
                                values.append(0)
                        break

        # === 3. 校验逻辑 ===
        # 通常列顺序：总人数(0), 高级(1), 中级(2), 初级(3), 博士后(4), 博士生(5), 硕士生(6), 本科生(7), 其他(8)
        # 即使列数略有增加，通常第一列是总数，后面是分项
        if len(values) >= 5: # 至少要有总人数和几个主要分项
            total = values[0]
            # 计算后面所有列的和
            sub_sum = sum(values[1:])
            
            if total != sub_sum:
                violations.append({
                    'rule_name': '总人数统计校验',
                    'severity': 'high',
                    'error_text': f'人员统计表总人数({total}) 与 分项之和({sub_sum}) 不一致',
                    'location': '基本信息表',
                    'suggestion': '请核对人员统计表，确保 总人数 = 高级+中级+初级+博士后+博士生+硕士生+本科生+其他'
                })
    except Exception as e:
        print(f"[正则检查] 人员统计校验异常: {e}")
        
    return violations


def run_regex_preliminary_check(md_content: str = '', table_content: str = '', text_content: str = '',
                                 json_data: dict = None, api_key: str = None, model_name: str = None,
                                 vlm_md_content: str = None) -> List[Dict]:
    """
    运行所有正则化初筛检查
    
    【重要】所有检查都直接从完整markdown文档中用正则提取，不使用JSON，不分割文档
    
    初筛项：
    （1） 第一个申请代码：4位数
    （2） 合作单位，名称写依托单位。（学校的附院，不是合作单位）
    （3） 主要参与者表格，人数没统计错。
    （4） 报告正文，最新模板、没缺项、无空白页。
    （5） 年度研究计划，时间与项目执行期一致，时间衔接，不能少1天。
    （6~8） 联系方式格式检查（电话/邮箱）、组织机构代码检查。
    
    新增10条（A1~A10）：
    （A1） 预算总额与分项合计一致性。
    （A2） 项目起止年限合理性（≤5年，起始≥当前年）。
    （A3） 身份证号格式校验（18位+校验位）。
    （A4） 参与者每年工作月数≤12。
    （A5） 关键词数量3~5个。
    （A6） 参考文献序号连续性。
    （A7） 参考文献正文引用覆盖。
    （A8） 摘要字数限制（中文≤400字，英文≤500词）。
    （A9） 项目名称中英文一致性（长度比）。
    （A10）正文重复段落检测。

    混合检查（C1~C2，正则为主+可选LLM辅助）：
    （C1） 参考文献时效性（近5年文献占比、老旧文献提示）。
    （C2） 参考文献自引率（申请人在作者中出现的比例）。
    
    Args:
        md_content: 完整的markdown文档内容（优先使用，通常为MinerU原始内容）
        table_content: 表格部分内容（兼容旧调用）
        text_content: 正文部分内容（兼容旧调用）
        json_data: 忽略，不使用
        api_key: SiliconFlow API密钥（可选，用于C2自引率LLM辅助判断）
        model_name: 模型名称（可选，来自分组配置）
        vlm_md_content: VLM处理后的markdown内容（可选，作为HTML表格检查的回退源）
    
    Returns:
        违规项列表
    """
    # 优先使用完整md_content，如果没有则合并table_content和text_content
    if not md_content:
        if table_content or text_content:
            md_content = (table_content or '') + '\n' + (text_content or '')
    
    if not md_content:
        print("[正则检查] 警告：markdown内容为空")
        return []
    
    print(f"[正则检查] 开始检查完整markdown文档，长度: {len(md_content)} 字符")
    if vlm_md_content:
        print(f"[正则检查] VLM回退内容长度: {len(vlm_md_content)} 字符")
    
    violations = []
    
    # (1) 申请代码格式检查：4位数
    result = check_application_code_from_md(md_content, vlm_content=vlm_md_content)
    if result:
        violations.append(result)
    
    # (2) 合作单位检查：学校的附院不是合作单位
    violations.extend(check_cooperative_unit_from_md(md_content))
    
    # (3) 主要参与者人数统计检查
    result = check_participant_count_from_md(md_content, vlm_content=vlm_md_content)
    if result:
        violations.append(result)
    
    # (4) 报告正文检查（拆分为4个子规则）
    # 4.1 最新模板章节检查
    violations.extend(check_required_chapters_from_md(md_content))
    # 4.2 空白页检查
    violations.extend(check_blank_pages_from_md(md_content))
    # 4.3 H18专项特殊内容检查
    violations.extend(check_h18_special_content_from_md(md_content, vlm_content=vlm_md_content))
    # 4.4 容易漏写章节检查
    violations.extend(check_optional_chapters_from_md(md_content))
    
    # (5) 年度研究计划检查（拆分为2个子规则，在函数内部调用）
    # 5.1 时间与项目执行期一致
    # 5.2 时间衔接不能少1天
    violations.extend(check_annual_plan_from_md(md_content, vlm_content=vlm_md_content))
    
    # 额外保留：联系方式格式检查
    violations.extend(check_phone_format_from_md(md_content))
    violations.extend(check_email_format_from_md(md_content))
    
    # 额外保留：组织机构代码检查
    violations.extend(check_organization_code_from_md(md_content))
    
    # ==================== 新增10条正则检查规则 ====================
    # (A1) 预算总额与分项合计一致性
    violations.extend(check_budget_consistency_from_md(md_content, vlm_content=vlm_md_content))
    # (A2) 项目起止年限合理性
    violations.extend(check_project_duration_from_md(md_content, vlm_content=vlm_md_content))
    # (A3) 身份证号格式校验
    violations.extend(check_id_card_format_from_md(md_content))
    # (A4) 参与者工作月数合理性
    violations.extend(check_work_months_from_md(md_content, vlm_content=vlm_md_content))
    # (A11) 基本信息必填字段检查（主要研究领域等）
    violations.extend(check_required_fields_from_md(md_content, vlm_content=vlm_md_content))
    # (A5) 关键词数量检查
    violations.extend(check_keywords_count_from_md(md_content, vlm_content=vlm_md_content))
    # (A6) 参考文献序号连续性
    violations.extend(check_reference_numbering_from_md(md_content))
    # (A7) 参考文献正文引用覆盖
    violations.extend(check_reference_citation_coverage_from_md(md_content))
    # (A8) 摘要字数限制
    violations.extend(check_abstract_length_from_md(md_content, vlm_content=vlm_md_content))
    # (A9) 项目名称中英文一致性
    violations.extend(check_title_consistency_from_md(md_content, vlm_content=vlm_md_content))
    # (A10) 正文重复段落检测
    violations.extend(check_duplicate_paragraphs_from_md(md_content))

    # (A12) 资助类别金额限制
    violations.extend(check_funding_amount_limit_from_md(md_content, vlm_content=vlm_md_content))
    # (A13) 资助类别年限限制
    violations.extend(check_funding_duration_limit_from_md(md_content, vlm_content=vlm_md_content))
    # (人员) 总人数统计校验
    violations.extend(check_personnel_sum_from_md(md_content, vlm_content=vlm_md_content))

    # ==================== 混合检查规则（正则为主 + 可选LLM辅助） ====================
    # (C1+C2) 参考文献时效性 + 自引率（合并为一个函数）
    violations.extend(check_reference_timeliness_and_selfcite(md_content, api_key, model_name, vlm_content=vlm_md_content))

    print(f"[正则检查] 检查完成，发现 {len(violations)} 处违规")
    
    return violations
