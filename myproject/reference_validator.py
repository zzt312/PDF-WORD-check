"""
参考文献引用格式验证器
基于GB/T 7714-2015标准
"""
import re
import unicodedata
import requests
import time
import json
import os
from json_repair import repair_json
import string
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

class CitationSystem(Enum):
    """引用标注体系"""
    NUMERIC = "numeric"  # 顺序编码制
    AUTHOR_YEAR = "author_year"  # 著者-出版年制
    MIXED = "mixed"  # 混合使用
    UNKNOWN = "unknown"  # 未识别


@dataclass
class ValidationError:
    """验证错误"""
    error_type: str
    message: str
    position: Optional[int] = None
    severity: str = "error"  # error, info
    suggestion: Optional[str] = None
    correct_format: Optional[str] = None  # 通用正确格式
    corrected_reference: Optional[str] = None  # 修正后的具体引用

# 错误代码到自然语言的映射
ERROR_TYPE_DESCRIPTIONS = {
    # 通用规则 (G) - 所有文献
    "G.L1.01": "参考文献缺少文献类型标识（如[M], [J]等）。",
    "G.L1.02": "参考文献缺少必要的数字对象唯一标识符（DOI）。",
    "G.L2.01": "无法将参考文献解析为标准著录项目。",
    "G.L2.02": "无法从参考文献中识别出\"主要责任者\"。",
    "G.L2.03": "无法从参考文献中识别出\"题名\"。",
    "G.L2.04": "无法从参考文献中识别出\"出版年\"。",
    "G.L2.05": "文献缺少必备字段（通用检查）。",
    "G.L3.01": "主要责任者超过3个时，未按规定著录为\"前3个责任者, 等\"。",
    "G.L3.02": "主要责任者不足3个，但错误地使用了\"等\"。",
    "G.L3.03": "汉语拼音人名格式不规范，姓氏未全大写或名的缩写不正确。",
    "G.L3.04": "其他责任者著录不规范。",
    "G.L3.05": "题名中的其他题名信息（副标题）格式不规范。",
    "G.L3.06": "引文页码格式不规范。",
    "G.L3.07": "标点符号使用不规范。",
    
    # 专著类规则 (M)
    "M.L2.01": "专著缺少必要的出版者信息。",
    "M.L2.02": "专著缺少必要的出版地信息。",
    "M.L3.01": "版本项著录不规范，第1版被错误著录。",
    "M.L3.02": "出版地或出版者不详时，未按规定使用\"[出版地不详]\"或\"[s.n.]\"等方括号标识。",
    
    # 析出文献规则 (A)
    "A.L2.01": "析出文献缺少必要的出处文献题名。",
    "A.L2.02": "析出文献缺少必要的出版地信息。",
    "A.L2.03": "析出文献缺少必要的出版者信息。",
    "A.L2.04": "析出文献缺少必要的页码信息。",
    "A.L3.01": "析出文献与其出处文献的分隔符使用错误。",
    "A.L3.02": "析出文献的页码格式不规范。",
    
    # 期刊规则 (J)
    "J.L2.01": "期刊析出文献缺少必要的出处信息（期刊名）。",
    "J.L3.01": "期刊的年、卷、期、页码格式不规范。",
    "J.L3.02": "期刊题名缩写不符合ISO 4规范。",
    
    # 报纸规则 (N)
    "N.L2.01": "报纸析出文献缺少必要的出处信息（报纸名）。",
    "N.L3.01": "报纸的出版日期和版次格式不规范。",
    "N.L3.02": "报纸版次著录格式不正确。",
    
    # 专利规则 (P)
    "P.L2.01": "专利文献缺少专利号。",
    "P.L2.02": "专利文献缺少公告日期。",
    "P.L3.01": "专利公告日期格式不正确，应为YYYY-MM-DD。",
    "P.L3.02": "专利题名与专利号之间的分隔符不是\":\"。",
    
    # 标准文献规则 (S)
    "S.L2.01": "标准文献缺少必要的标准编号。",
    "S.L2.02": "标准文献缺少必要的出版地信息。",
    "S.L2.03": "标准文献缺少必要的出版者信息。",
    "S.L3.01": "标准编号格式不规范或位置不正确。",
    
    # 学位论文规则 (D)
    "D.L2.01": "学位论文缺少保存单位（学校）信息。",
    "D.L2.02": "学位论文缺少出版地信息。",
    "D.L3.01": "学位论文的保存地与保存单位格式不规范。",
    
    # 会议论文规则 (C)
    "C.L2.01": "会议论文集缺少必要的出版者信息。",
    "C.L2.02": "会议论文集缺少必要的出版地信息。",
    "C.L2.03": "会议论文集缺少必要的出版年信息。",
    "C.L3.01": "会议论文格式不规范。",
    "C.L3.02": "会议论文集编者信息可能缺失或位置不正确。",
    "C.L3.03": "会议日期格式不规范。",
    "C.L3.04": "会议论文建议包含会议名称。",
    "C.L3.05": "会议地点格式不规范。",
    "C.L3.06": "会议论文建议包含页码信息。",
    
    # 报告文献规则 (R)
    "R.L2.01": "报告文献缺少必要的出版者（报告发布机构）信息。",
    "R.L2.02": "报告文献缺少必要的出版地信息。",
    "R.L3.01": "报告编号格式不规范或位置不正确。",
    
    # 电子资源规则 (E) - 仅电子资源
    "E.L1.01": "电子资源缺少必要的获取和访问路径（URL）。",
    "E.L2.01": "电子资源缺少URL。",
    "E.L2.02": "电子资源缺少引用日期。",
    "E.L3.01": "电子资源的引用日期格式不正确或未使用方括号。",
    "E.L3.02": "电子资源的载体类型标识不规范（应为[OL]、[CD]、[MT]等）。",
    
    # 档案文献规则 (Archive) - 档案文献
    "Archive.L2.01": "档案文献缺少档案保存地。",
    "Archive.L2.02": "档案文献缺少档案馆名称。",
    "Archive.L3.01": "档案文献标识符\"[A]\"缺失或位置不正确。",
    "Archive.L3.02": "档案文献的档案号格式不规范。",
    
    # 辅助检查 (INFO) - 提示性信息
    "bilingual_format_check": "检测到中英文混合著录，请确认格式符合双语著录要求。"
}

def get_user_friendly_error_type(error_code: str) -> str:
    """将错误代码转换为用户友好的描述"""
    return ERROR_TYPE_DESCRIPTIONS.get(error_code, error_code)

@dataclass
@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    citation_system: CitationSystem
    errors: List[ValidationError]
    warnings: List[ValidationError]
    suggestions: List[str]
    confidence: float = 0.0
    parsed_data: Optional[Dict] = None  # LLM解析的结构化数据

class GBT7714Validator:
    """GB/T 7714-2015参考文献格式验证器"""
    
    def __init__(self):
        self.citation_patterns = {
            'numeric': r'\[(\d+(?:-\d+)?(?:,\s*\d+(?:-\d+)?)*)\]',
            'author_year': r'\(([^,)]+(?:\s+et\s+al\.?)?),?\s*(19|20)\d{2}[a-z]?\)',
            'chinese_author': r'[\u4e00-\u9fa5]{1,4}(?:\s+[\u4e00-\u9fa5]{1,4})*',
            'english_author': r'[A-Z][a-zA-Z\'\-\.]+(?:\s+[A-Z]\.?)*',
            'pinyin_author': r'[A-Z]{2,}\s+[A-Z](?:\s*[A-Z])*'
        }
        
        # 文献类型标识模式（更全面）
        self.doc_type_patterns = {
            'monograph': r'\[M(?:/[A-Z]+)?\]',
            'journal': r'\[J(?:/[A-Z]+)?\]',
            'conference': r'\[C(?:/[A-Z]+)?\]',
            'dissertation': r'\[D(?:/[A-Z]+)?\]',
            'report': r'\[R(?:/[A-Z]+)?\]',
            'standard': r'\[S(?:/[A-Z]+)?\]',
            'patent': r'\[P(?:/[A-Z]+)?\]',
            'newspaper': r'\[N(?:/[A-Z]+)?\]',
            'archive': r'\[A(?:/[A-Z]+)?\]',
            'cartographic': r'\[CM(?:/[A-Z]+)?\]',
            'dataset': r'\[DS(?:/[A-Z]+)?\]',
            'electronic_monograph': r'\[M/(?:CD|DK|MT|OL)\]',
            'electronic_journal': r'\[J/(?:CD|DK|MT|OL)\]',
            'electronic_database': r'\[DB/(?:CD|DK|MT|OL)\]',
            'electronic_bulletin': r'\[EB/(?:CD|DK|MT|OL)\]',
            'electronic_program': r'\[CP/(?:CD|DK|MT|OL)\]',
            'electronic_document': r'\[OL\]',
            'other': r'\[Z(?:/[A-Z]+)?\]'
        }
        
        # 载体标识代码
        self.carrier_codes = {
            'CD': '光盘',
            'DK': '磁盘',
            'MT': '磁带',
            'OL': '联机网络'
        }
        
        # 必备字段检查（严格依照GB/T 7714-2015标准）
        # 注意：DOI由G.L1.02一级规则检查（原始文献字符串级别），不在此L2级别的required_fields中重复
        self.required_fields = {
            # 专著类（4.1专著）- 必备：主要责任者、题名、出版地、出版者、出版年
            'M': ['authors', 'title', 'publish_place', 'publisher', 'publish_year'],  # 专著
            'C': ['authors', 'title', 'publish_place', 'publisher', 'publish_year'],  # 会议论文集（按4.1专著著录，不强制要求host_title和pages）
            'D': ['authors', 'title', 'publish_place', 'school', 'publish_year'],      # 学位论文（出版者改为school）
            'R': ['authors', 'title', 'publish_place', 'publisher', 'publish_year'],  # 报告
            'S': ['title', 'standard_number', 'publish_place', 'publisher', 'publish_year'],  # 标准（主要责任者任选）
            'CM': ['authors', 'title', 'publish_place', 'publisher', 'publish_year'], # 舆图
            
            # 析出文献类（4.2专著中的析出文献）- 必备：析出文献主要责任者、析出文献题名、专著主要责任者、专著题名、出版地、出版者、出版年、页码
            'A': ['authors', 'title', 'host_title', 'publish_place', 'publisher', 'publish_year', 'pages'],  # 专著中的析出文献
            
            # 连续出版物中的析出文献（4.4）- 必备：主要责任者、析出文献题名、连续出版物题名、出版年/日期（卷号期号页码任选）
            'J': ['authors', 'title', 'journal', 'publish_year'],  # 期刊文章（无需出版地、出版者）
            'N': ['authors', 'title', 'journal', 'newspaper_date'],  # 报纸文章
            
            # 专利文献（4.5）- 必备：专利申请者、题名、专利号、专利日期（国别任选）
            'P': ['authors', 'title', 'patent_number', 'patent_date'],  # 专利（patent_country任选）
            
            # 电子资源（4.6）- 必备：主要责任者、题名、URL、引用日期
            'DS': ['authors', 'title', 'url', 'access_date'],      # 数据集
            'DB/OL': ['authors', 'title', 'url', 'access_date'],  # 电子数据库
            'EB/OL': ['authors', 'title', 'url', 'access_date'],  # 电子公告
            'CP/OL': ['authors', 'title', 'url', 'access_date'],  # 电子计算机程序
            'M/OL': ['authors', 'title', 'url', 'access_date'],   # 电子专著（无需出版地、出版者）
            'J/OL': ['authors', 'title', 'journal', 'publish_year', 'url', 'access_date'],  # 电子期刊（需期刊名、年份、URL、引用日期）
            'OL': ['authors', 'title', 'url', 'access_date'],      # 联机网络文献
            
            # 其他
            'Z': ['authors', 'title']  # 其他（最小要求）
        }
        
        # 标点符号规则
        self.punctuation_rules = {
            'author_separator': ', ',  # 多个作者之间
            'author_end': '. ',  # 作者后
            'title_end': '. ',  # 题名后（无其他题名信息时）
            'title_with_subtitle': ': ',  # 题名与其他题名信息之间
            'type_end': '. ',  # 文献类型标识后
            'publisher_separator': ': ',  # 出版地与出版者之间
            'year_separator': ', ',  # 出版者与出版年之间
            'pages_separator': ': ',  # 出版年与页码之间
            'url_prefix': '. ',  # URL前
            'access_date_format': r'\[\d{4}-\d{2}-\d{2}\]'  # 引用日期格式
        }

    def detect_citation_system(self, text: str) -> CitationSystem:
        """检测引用标注体系"""
        numeric_count = len(re.findall(self.citation_patterns['numeric'], text))
        author_year_count = len(re.findall(self.citation_patterns['author_year'], text))
        
        if numeric_count > 0 and author_year_count > 0:
            return CitationSystem.MIXED
        elif numeric_count > author_year_count:
            return CitationSystem.NUMERIC
        elif author_year_count > 0:
            return CitationSystem.AUTHOR_YEAR
        else:
            return CitationSystem.UNKNOWN

    def validate_punctuation(self, reference: str, parsed_ref: Optional[Dict] = None) -> List[ValidationError]:
        """
        验证标点符号规范性 (A.L3.01, P.L3.02)
        - A.L3.01: 专著析出文献的'//'和连续出版物析出文献的'.'
        - P.L3.02: 专利文献的':'
        """
        errors = []

        # L3 规则需要解析后的数据
        if not parsed_ref:
            return errors

        # A.L3.01: 析出文献分隔符 - 专著中的析出文献
        if parsed_ref.get("host_title") and parsed_ref.get("document_type") == "M":
             if "//" not in reference:
                errors.append(ValidationError(
                    error_type="A.L3.01",
                    severity="info",
                    message="专著中的析出文献，其出处项前未使用“//”符号。",
                    suggestion="请在析出文献题名与专著题名之间添加“//”分隔符。"
                ))

        # A.L3.01: 析出文献分隔符 - 连续出版物中的析出文献
        if parsed_ref.get("host_title") and parsed_ref.get("document_type") == "J":
             # 检查析出文献题名与期刊名之间的点
             title = parsed_ref.get("title", "")
             journal = parsed_ref.get("journal", "")
             if title and journal:
                 # 🔧 修复：确保字段是字符串类型
                 title_str = str(title)
                 journal_str = str(journal)
                 # 查找 'Title. Journal' 模式
                 if not re.search(re.escape(title_str) + r'\.\s*' + re.escape(journal_str), reference):
                    errors.append(ValidationError(
                        error_type="A.L3.01",
                        severity="info",
                        message="连续出版物中的析出文献，其刊名信息前未使用“.”符号。",
                        suggestion="请在析出文献题名后使用句点“.”与期刊信息分隔。"
                    ))

        # P.L3.02: 专利题名与专利号分隔符
        if parsed_ref.get("document_type") == "P":
            title = parsed_ref.get("title", "")
            patent_number = parsed_ref.get("patent_number", "")
            if title and patent_number:
                # 🔧 修复：确保字段是字符串类型
                title_str = str(title)
                patent_number_str = str(patent_number)
                if not re.search(re.escape(title_str) + r'\s*:\s*' + re.escape(patent_number_str), reference):
                    errors.append(ValidationError(
                        error_type="P.L3.02",
                        severity="info",
                        message="专利文献的专利号与题名之间的分隔符不是“:”。",
                        suggestion="专利题名和专利号之间应使用冒号“:”分隔。"
                    ))
        
        return errors

    def get_format_examples(self, doc_type: str) -> Dict[str, str]:
        """获取不同文献类型的格式示例（基于新分类系统）"""
        examples = {
            # G类 - 通用格式要求
            'G': {
                'format': "所有文献都必须包含：[文献类型标识] 和 DOI信息",
                'required': "文献类型标识符([M]、[J]等)、DOI",
                'rules': ["G.L1.01: 文献类型标识检查", "G.L1.02: DOI检查", "G.L2.x: 基础信息完整性", "G.L3.x: 作者格式规范"]
            },
            
            # M类 - 专著
            'M': {
                'format': "[序号] 主要责任者. 题名[M]. 版本项. 出版地: 出版者, 出版年. DOI: xxx",
                'required': "主要责任者、题名、出版地、出版者、出版年、DOI",
                'rules': ["M.L2.01: 出版信息完整性", "M.L3.01: 版本信息格式", "M.L3.02: 出版社格式"]
            },
            
            # A类 - 析出文献（专著中的章节）
            'A': {
                'format': "[序号] 主要责任者. 析出文献题名[M]//专著题名. 出版地: 出版者, 出版年: 页码. DOI: xxx",
                'required': "析出文献题名、专著题名、//分隔符、页码、DOI",
                'rules': ["A.L3.01: 析出文献分隔符检查"]
            },
            
            # J类 - 期刊文章
            'J': {
                'format': "[序号] 主要责任者. 题名[J]. 期刊名, 年, 卷(期): 起止页码. DOI: xxx",
                'required': "主要责任者、题名、期刊名、年、DOI",
                'rules': ["J.L2.01: 期刊名检查", "J.L3.01: 年卷期格式"]
            },
            
            # N类 - 报纸文章
            'N': {
                'format': "[序号] 主要责任者. 题名[N]. 报纸名, 年-月-日(版次). DOI: xxx",
                'required': "主要责任者、题名、报纸名、具体日期、DOI",
                'rules': ["N.L2.01: 报纸名检查", "N.L3.01: 日期格式"]
            },
            
            # P类 - 专利文献
            'P': {
                'format': "[序号] 申请人. 专利题名: 专利号[P]. 公告日期. DOI: xxx",
                'required': "申请人、专利题名、专利号、公告日期、DOI",
                'rules': ["P.L2.01: 专利信息完整性", "P.L3.01: 申请人格式", "P.L3.02: 专利号格式"]
            },
            
            # E类 - 电子资源
            'E': {
                'format': "[序号] 主要责任者. 题名[文献类型/OL]. [引用日期]. URL. DOI: xxx",
                'required': "主要责任者、题名、引用日期、URL、DOI",
                'rules': ["E.L1.01: URL检查"]
            }
        }
        
        # 支持传统文献类型代码映射到新分类
        type_mapping = {
            'M': 'M',   # 专著
            'J': 'J',   # 期刊
            'C': 'A',   # 会议论文集中的析出文献
            'D': 'M',   # 学位论文视为专著
            'R': 'M',   # 报告视为专著
            'S': 'M',   # 标准视为专著
            'P': 'P',   # 专利
            'N': 'N',   # 报纸
            'DB': 'E',  # 数据库
            'EB': 'E',  # 电子公告
            'OL': 'E'   # 在线资源
        }
        
        mapped_type = type_mapping.get(doc_type, doc_type)
        return examples.get(mapped_type, {
            'format': f'文献类型 {doc_type} 应遵循通用规则(G类)要求。',
            'required': '文献类型标识符、DOI、基础书目信息',
            'rules': ['参考G类通用规则']
        })

    def validate_reference_format(self, reference: str) -> ValidationResult:
        """L1级检查：只做基础格式验证，不调用LLM"""
        errors = []
        
        # === L1级检查（基础格式验证）===
        # G.L1.01: 文献类型标识 - 所有文献必备（硬性阻断）
        doc_type_errors = self.validate_g_l1_01(reference)
        if doc_type_errors:
            return ValidationResult(
                is_valid=False,
                citation_system=CitationSystem.UNKNOWN,
                errors=doc_type_errors,
                warnings=[], suggestions=[], confidence=0.0
            )
        
        # G.L1.02: DOI检查 - 报错但不阻断后续检查
        doi_errors = self.validate_g_l1_02(reference)
        if doi_errors:
            errors.extend(doi_errors)  # 记录错误但继续
        
        # 🔧 已移除E.L1.01（URL原文检查）
        # 原因：E.L2.01（URL字段检查）+ URL后备提取机制已充分覆盖
        # 避免重复提示"电子资源缺少URL"
        
        # L1阶段完成，返回结果
        # 注意：有DOI错误时 is_valid=False，但允许后续L2/L3检查
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            citation_system=CitationSystem.NUMERIC,
            warnings=[], suggestions=[], 
            confidence=1.0 if len(errors) == 0 else 0.5
        )

    def _pre_extract_document_type(self, reference: str) -> str:
        """
        本地预提取参考文献类型，使用正则表达式识别。
        优先级：C > A > J > M > D > R > S > P > 电子资源(EB/OL等) > N > Archive
        
        返回值：M | J | C | D | R | S | P | N | A | Archive | EB/OL | DB/OL | CP/OL | M/OL | J/OL | DS | OL | Unknown
        """
        import re
        
        # 清理参考文献文本
        ref = reference.strip()
        
        # 1. 会议论文(C) - 最高优先级
        # 关键词：Proceedings, Conference, Symposium, Workshop, 会议, 学术会议
        conference_patterns = [
            r'\b(Proceedings?|Conference|Symposium|Workshop)\b',
            r'会议|学术会议',
            r'\[C\]',  # 明确标注
        ]
        for pattern in conference_patterns:
            if re.search(pattern, ref, re.IGNORECASE):
                return 'C'
        
        # 2. 析出文献(A) - 第二优先级
        # 特征：//（双斜杠）表示析出关系，或明确标注[A]
        if '//' in ref or re.search(r'\[A\]', ref):
            return 'A'
        
        # 3. 期刊(J)
        # 特征：年份, 卷(期): 页码 格式，或明确标注[J]
        journal_patterns = [
            r'\d{4},\s*\d+\(\d+\)\s*:\s*\d+',  # 2023, 45(3): 123
            r'\[J\]',
        ]
        for pattern in journal_patterns:
            if re.search(pattern, ref):
                return 'J'
        
        # 4. 学位论文(D)
        if re.search(r'\[D\]|学位论文|dissertation|thesis', ref, re.IGNORECASE):
            return 'D'
        
        # 5. 报告(R)
        if re.search(r'\[R\]|报告|report', ref, re.IGNORECASE):
            return 'R'
        
        # 6. 标准(S)
        if re.search(r'\[S\]|标准|standard', ref, re.IGNORECASE):
            return 'S'
        
        # 7. 专利(P)
        if re.search(r'\[P\]|专利|patent', ref, re.IGNORECASE):
            return 'P'
        
        # 8. 电子资源 - 需在报纸(N)之前检查，返回具体复合类型
        # 包括：[EB/OL]电子公告、[DB/OL]数据库、[CP/OL]程序、[M/OL]、[J/OL]、[DS]数据集等
        
        # 优先匹配完整复合类型
        electronic_match = re.search(r'\[(EB|DB|CP|M|J|DS)/OL\]', ref, re.IGNORECASE)
        if electronic_match:
            return electronic_match.group(1).upper() + '/OL'  # 返回如"EB/OL"
        
        # 匹配数据集[DS]
        if re.search(r'\[DS\]', ref, re.IGNORECASE):
            return 'DS'
        
        # 匹配通用在线资源[OL]
        if re.search(r'\[OL\]|http[s]?://', ref, re.IGNORECASE):
            return 'OL'
        
        # 9. 报纸(N)
        if re.search(r'\[N\]|报纸|newspaper', ref, re.IGNORECASE):
            return 'N'
        
        # 10. 档案(Archive)
        if re.search(r'\[Archive\]|档案', ref, re.IGNORECASE):
            return 'Archive'
        
        # 11. 专著(M) - 默认兜底
        # 特征：出版地: 出版者, 年份 格式，或明确标注[M]
        if re.search(r'\[M\]|[^:]+:\s*[^,]+,\s*\d{4}', ref):
            return 'M'
        
        # 无法识别时返回Unknown
        return 'Unknown'

    def _parse_references_with_llm(self, references: List[str], user_id: int, progress_callback=None) -> Tuple[List[Optional[Dict]], List[ValidationError]]:
        """
        使用LLM批量解析参考文献，实现L2.01规则。
        如果解析失败，则返回L2.01错误。
        
        改进：预提取文献类型，减少LLM提取难度。
        
        支持任务取消：
        - progress_callback返回False时会立即停止处理
        - 已提交的批次会继续完成，但不会提交新批次
        """
        # 获取用户的LLM API配置（优先本地LLM，回退到硅基流动）
        use_local_llm = False
        api_key = None
        try:
            from db_operations import get_active_api_key
            # 先检查是否配置了本地LLM
            local_llm_info = get_active_api_key(user_id, 'local_llm')
            if local_llm_info and local_llm_info.get('api_token'):
                # 配置了本地LLM，检查是否可用
                from md_content_processor import _check_local_llm_available
                if _check_local_llm_available():
                    use_local_llm = True
                    print(f"[API配置] 使用本地LLM服务器")
                else:
                    print(f"[API配置] 本地LLM不可用，回退到硅基流动")
            
            if not use_local_llm:
                api_key_info = get_active_api_key(user_id, 'siliconflow')
                if api_key_info and api_key_info.get('api_token'):
                    api_key = api_key_info['api_token']
                    
        except ImportError:
            # 无法导入数据库操作函数
            pass
        except Exception as e:
            # 其他错误
            print(f"[API密钥] 获取密钥时发生错误: {e}")
        
        if not use_local_llm and not api_key:
            # 返回G.L2.01错误，表明无法获取API密钥
            l2_01_errors = []
            for i in range(len(references)):
                l2_01_errors.append(ValidationError(
                    error_type="G.L2.01",
                    message="无法将参考文献解析为标准著录项目。",
                    suggestion="未配置有效的LLM服务（本地LLM不可用且未配置硅基流动API密钥）。"
                ))
            return [None] * len(references), l2_01_errors
        
        api_key = api_key if not use_local_llm else "not-needed"
        parsed_results = [None] * len(references)
        errors = [[] for _ in range(len(references))]
        
        # 🆕 预提取所有参考文献的类型
        print(f"[预提取] 开始预提取{len(references)}条参考文献的类型...")
        pre_extracted_types = []
        for ref in references:
            doc_type = self._pre_extract_document_type(ref)
            pre_extracted_types.append(doc_type)
        
        # 统计类型分布
        from collections import Counter
        type_counts = Counter(pre_extracted_types)
        print(f"[预提取] 类型分布: {dict(type_counts)}")
        
        # 动态获取API地址和模型名称
        if use_local_llm:
            from md_content_processor import LOCAL_LLM_CONFIG
            api_url = LOCAL_LLM_CONFIG["api_url"]
            model_name = LOCAL_LLM_CONFIG["model"]
            print(f"[LLM解析] 使用本地LLM: {model_name}")
        else:
            api_url = "https://api.siliconflow.cn/v1/chat/completions"
            default_model = "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B"  # 默认模型
            
            # 尝试从用户分组获取配置的模型
            model_name = default_model
            if user_id:
                try:
                    from db_operations import get_user_siliconflow_model
                    user_model = get_user_siliconflow_model(user_id)
                    if user_model:
                        model_name = user_model
                        print(f"[LLM解析] 使用用户分组配置的模型: {model_name}")
                    else:
                        print(f"[LLM解析] 用户未配置模型，使用默认模型: {model_name}")
                except Exception as e:
                    print(f"[LLM解析] 获取用户模型配置失败，使用默认模型: {e}")
            else:
                print(f"[LLM解析] 未提供用户ID，使用默认模型: {model_name}")
        
        system_prompt = """你是专业的参考文献字段提取系统，不参考任何标准仅只客观提取。

⚠️ 核心任务：
1. 【第一步】验证预提取的文献类型是否正确，错误则修正
2. 【第二步】从参考文献中提取所有31个字段，有值填值，无值填null
3. 【第三步】输出完整的31字段JSON对象

⚠️ 输出规则：
- 严禁添加Markdown标记（如```json）
- 返回纯JSON数组，数量与输入完全一致

【31个字段完整清单】
1. authors（字符串）: 主要责任者
   - 保留"等."或"et al."
   - 机构名不分割
   - 多作者逗号分隔
   - 示例："Zhang S., Li M., et al."
2. title（字符串）: 文献题名
   - 不含期刊名、年份
   - 保留副标题（冒号分隔）
   - 示例："Deep learning for NLP: a survey"
3. document_type（字符串）: 文献类型标识
   - 枚举值：M | J | C | D | R | S | P | N | A | Archive | EB/OL | DB/OL | CP/OL | M/OL | J/OL | DS | OL
   - ⚠️ 你将收到预提取的类型，请先判断是否正确
   - 判断优先级：C > A（含"Proceedings/Conference/会议"字样优先C）
   - 电子资源识别：优先保留完整标识（如[EB/OL]、[DB/OL]、[M/OL]等）
   - 修正后保留在此字段
   - 示例：
     * [EB/OL] → "EB/OL"（电子公告/在线）
     * [DB/OL] → "DB/OL"（数据库/在线）
     * [M/OL] → "M/OL"（电子专著）
     * [J/OL] → "J/OL"（电子期刊）
     * [J] → "J"（纸质期刊）
4. publish_year（字符串或数字）: 出版年份
   - 四位数字年份
   - 可以是字符串"2023"或数字2023
   - ⚠️ 必须准确提取，不要遗漏
5. journal（字符串）: 期刊名
   - 不含年卷期信息
   - 示例："Nature", "中华糖尿病杂志"
6. volume（字符串）: 卷号
   - ⚠️ 必须为纯数字字符串
   - 正确："45", "183", "3"
   - 错误："PAMI-1", "Vol.30"
   - 特殊：如"PAMI-1(2)"，提取"1"
7. issue（字符串）: 期号
   - 从括号内提取
   - 示例："4", "06", "Feb"
8. journal_format_valid（布尔值或null）: 期刊格式规范性
   - ⚠️ 判断标准必须严格遵守，相同模式必须给出相同判断！
   - ⚠️ 优先判断为true，只在明确不符合时判断为false
   - 判断流程（按顺序执行）：
     第1步：检查是否为期刊文献（document_type是否为J）
       - 如果不是J，则journal_format_valid = null
     第2步：检查volume（卷号）是否为纯数字
       - 如果volume包含字母或特殊符号（如"PAMI-1", "Vol.30"），则journal_format_valid = false
       - 如果volume为纯数字（如"45", "183"），继续下一步
     第3步：检查格式完整性
       - 如果符合"年, 卷(期): 页码"或"年, 卷: 页码"格式，则journal_format_valid = true
       - 如果有期号但无卷号（如"年(期): 页码"），则journal_format_valid = false
       - 其他情况，journal_format_valid = null
   - 示例：
     ✓ "2023, 45(3): 123-456" → volume="45", journal_format_valid=true
     ✗ "2023, PAMI-1(2): 123-456" → volume="1", journal_format_valid=false
     ✗ "2023(4): 10-19" → volume=null, journal_format_valid=false
9. pages（字符串）: 页码范围
   - ⚠️ 极易遗漏，必须仔细提取
   - 从末尾冒号后提取
   - 格式："起始-结束"或单页
   - 示例："123-456", "108", "195:1-195:35"
10. publisher（字符串）: 出版者
    - 示例："Springer", "科学出版社"
11. publish_place（字符串）: 出版地
    - 城市名
    - 会议论文：从conference_location提取城市（逗号前）
    - 示例："北京", "New York", "Minneapolis"
12. doi（字符串）: DOI标识符
    - 格式："10.xxxx/xxxxx"
13. url（字符串）: 网址链接
14. access_date（字符串）: 访问日期
    - 格式：YYYY-MM-DD
15. analytical_title（字符串）: 析出文献题名
    - 析出文献自身的题名
16. host_title（字符串）: 析出文献出处题名
    - 论文集名、专著名
17. conference_name（字符串）: 会议名称
    - 示例："Advances in Neural Information Processing Systems"
18. conference_location（字符串）: 会议地点
    - ⚠️ 提取完整信息，含城市和州/省
    - 示例："Minneapolis, Minnesota", "Copenhagen, Denmark"
    - 提取优先级：明确标注 > 冒号前地名 > 会议名后地点
19. conference_date（字符串）: 会议年份
20. conference_editors（字符串）: 会议论文集编者
    - 格式同authors
21. school（字符串）: 学位论文保存单位
22. standard_number（字符串）: 标准编号
23. report_number（字符串）: 报告编号
24. newspaper_date（字符串）: 报纸出版日期
25. newspaper_edition（字符串）: 报纸版次
26. archive_location（字符串）: 档案保存地
27. archive_holder（字符串）: 档案保存单位
28. archive_number（字符串）: 档案号
29. edition（字符串）: 版本信息
30. other_contributors（字符串）: 其他责任者
31. author_name_types（数组）: 作者名类型
    - ⚠️ 每个作者必须对应一个类型标识
    - ⚠️ 数组长度必须等于作者数量（按逗号分隔）
    - 元素枚举：organization（明显的机构名，无论字符类型） | chinese_pinyin（第一个单词翻译成中文，符合中国人姓氏习惯的均视作拼音。名可能是缩写。） | chinese_characters（中文字符） | foreign（不是拼音的英文字符）

【提取要点总结】
⚠️ 特别注意（高频错误）：
- publish_year: 必须提取，不要遗漏
- pages: 极易遗漏，务必从末尾冒号后认真提取
- volume: 只能纯数字，"PAMI-1"提取"1"
- journal_format_valid: 严格按判断流程，不要随意改变
- conference_location: 提取完整信息，不要只提取城市
- document_type: 验证预提取类型，C > A优先级

✓ 无论什么类型，都尝试提取全部31个字段
✓ 找不到的字段用null填充"""

        if use_local_llm:
            headers = {
                "Content-Type": "application/json"
            }
        else:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }

        # 批量处理 - 首先计算总批次数
        batch = []
        batch_indices = []
        batch_types = []  # 🆕 添加预提取的类型列表
        current_batch_char_count = 0
        
        # 🎯 L0级别优化配置：根据模型TPM限额动态调整
        # ⚠️ 考虑2个任务并行：总压力 = 单任务 × 2
        # 策略：根据模型能力动态调整批次大小，平衡质量和效率
        # 🆕 根据模型TPM限额分配批次大小（大幅提升，支持多条参考文献/批次）
        if model_name in ["deepseek-ai/DeepSeek-V3.2", "deepseek-ai/DeepSeek-R1"]:
            max_chars_per_batch = 2500  # TPM=100,000，高吞吐，每批约8-12条参考文献
        elif model_name == "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B":
            max_chars_per_batch = 2000  # TPM=50,000，每批约6-10条参考文献
        elif model_name in ["deepseek-ai/DeepSeek-R1-Distill-Qwen-14B", "Qwen/Qwen3-30B-A3B-Thinking-2507"]:
            max_chars_per_batch = 1800  # TPM=40,000，每批约5-8条参考文献
        elif model_name in ["Qwen/Qwen2.5-72B-Instruct", "Qwen/Qwen2.5-72B-Instruct-128K"]:
            max_chars_per_batch = 1200  # TPM=20,000，每批约4-6条参考文献
        elif use_local_llm:
            max_chars_per_batch = 1200  # 本地LLM：缩小批次粒度，减轻显存压力
        else:
            max_chars_per_batch = 1500  # 默认: 适中配置
        
        print(f"[模型优化] 模型 {model_name} 使用批次大小: {max_chars_per_batch}字符")
        
        # 预计算批次数量
        total_batches = 0
        temp_batch_char_count = 0
        for ref in references:
            if temp_batch_char_count + len(ref) > max_chars_per_batch and temp_batch_char_count > 0:
                total_batches += 1
                temp_batch_char_count = 0
            temp_batch_char_count += len(ref)
        if temp_batch_char_count > 0:
            total_batches += 1
        
        print(f"[LLM解析] 将{len(references)}条参考文献分成{total_batches}批处理（每批最多{max_chars_per_batch}字符）")
        
        # 🚀 并发优化：收集所有批次数据
        all_batches = []
        current_batch_number = 0
        for i, ref in enumerate(references):
            if current_batch_char_count + len(ref) > max_chars_per_batch and batch:
                all_batches.append((batch.copy(), batch_indices.copy(), batch_types.copy()))  # 🆕 包含类型信息
                batch = []
                batch_indices = []
                batch_types = []  # 🆕 重置类型列表
                current_batch_char_count = 0

            batch.append(ref)
            batch_indices.append(i)
            batch_types.append(pre_extracted_types[i])  # 🆕 添加对应的预提取类型
            current_batch_char_count += len(ref)

        if batch:
            all_batches.append((batch.copy(), batch_indices.copy(), batch_types.copy()))  # 🆕 包含类型信息
        
        # 🚀 使用ThreadPoolExecutor并发处理批次
        # L0级别配置：RPM=1000, TPM=50,000
        # ⚠️ 2任务并行（全局限制） + max_tokens=3000: 单任务并发根据模型动态调整
        # 预估压力：DeepSeek-R1-0528: 2并发×2任务=4总并发，TPM~16,000 (安全范围)
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading
        
        completed_batches = 0
        lock = threading.Lock()
        cancelled_flag = threading.Event()  # 🆕 取消标志
        
        def process_single_batch_wrapper(batch_data, batch_num):
            """包装函数：处理单个批次并更新进度（支持空数组重试）"""
            nonlocal completed_batches
            
            # 🆕 检查取消标志
            if cancelled_flag.is_set():
                print(f"[LLM并发] 批次 {batch_num} 已跳过（任务已取消）")
                return
            
            batch, batch_indices, batch_types = batch_data  # 🆕 解包包含类型信息
            
            # 🔧 优化进度显示 - 开始处理时不更新进度，避免并发跳跃
            print(f"[LLM并发] 开始处理批次 {batch_num}/{total_batches} (共{len(batch)}条参考文献)")
            
            # 🔄 添加空数组重试机制（最多重试2次）
            max_empty_retries = 2
            for retry_attempt in range(max_empty_retries + 1):
                try:
                    # 处理批次
                    self._process_llm_batch(batch, batch_indices, batch_types, parsed_results, errors, api_url, headers, model_name, system_prompt)
                    # 成功处理，跳出重试循环
                    break
                except ValueError as e:
                    # 检查是否是空数组错误
                    if "LLM返回空数组" in str(e) and retry_attempt < max_empty_retries:
                        print(f"🔄 批次{batch_num}返回空数组，重试 {retry_attempt + 1}/{max_empty_retries}...")
                        time.sleep(2)  # 等待2秒后重试
                        continue
                    elif "LLM返回空数组" in str(e):
                        # 重试次数用尽，标记所有条目为错误
                        print(f"❌ 批次{batch_num}重试{max_empty_retries}次后仍返回空数组，标记为失败")
                        for i in batch_indices:
                            errors[i].append(ValidationError(
                                error_type="G.L2.01",
                                message="无法将参考文献解析为标准著录项目。",
                                suggestion=f"LLM多次返回空结果（重试{max_empty_retries}次），可能是输入格式过于复杂"
                            ))
                        break
                    else:
                        # 其他ValueError，不重试
                        raise
            
            # 🔧 优化进度显示 - 只在完成时更新进度，确保递增
            with lock:
                completed_batches += 1
                if progress_callback:
                    # 计算平滑的进度百分比
                    batch_progress = (completed_batches / total_batches) * 100
                    # 显示当前批次进度
                    callback_result = progress_callback(batch_progress, f"LLM解析 {completed_batches}/{total_batches}")
                    # 调试日志保留批次号信息
                    print(f"[LLM进度] {batch_progress:.1f}% - 已完成{completed_batches}/{total_batches}批（批次{batch_num}）")
                    
                    # 🆕 检查progress_callback的返回值
                    if callback_result is False:
                        print(f"[LLM并发] 收到取消信号，设置取消标志")
                        cancelled_flag.set()
        
        # 🆕 根据模型TPM限额动态设置并发线程数
        if model_name in ["deepseek-ai/DeepSeek-V3.2", "deepseek-ai/DeepSeek-R1"]:
            max_workers = 5  # TPM=100,000，支持高并发
        elif model_name == "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B":
            max_workers = 3  # TPM=50,000，适度并发
        elif model_name in ["deepseek-ai/DeepSeek-R1-Distill-Qwen-14B", "Qwen/Qwen3-30B-A3B-Thinking-2507"]:
            max_workers = 3  # TPM=40,000，适度并发
        elif model_name in ["Qwen/Qwen2.5-72B-Instruct", "Qwen/Qwen2.5-72B-Instruct-128K"]:
            max_workers = 2  # TPM=20,000，低并发避免限流
        elif use_local_llm:
            max_workers = 3  # 本地LLM：RTX6000单卡，适度并发
        else:
            max_workers = 3  # 其他模型: 默认3并发
        
        print(f"[并发配置] 模型 {model_name} 使用 {max_workers} 个并发线程处理 {len(all_batches)} 个批次")
        
        # 使用线程池并发处理
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {}
            for batch_num, batch_data in enumerate(all_batches, 1):
                # 🆕 在提交新批次前检查取消标志
                if cancelled_flag.is_set():
                    print(f"[LLM并发] 任务已取消，不再提交新批次（剩余{len(all_batches) - batch_num + 1}批）")
                    break
                
                future = executor.submit(process_single_batch_wrapper, batch_data, batch_num)
                futures[future] = batch_num
            
            # 等待所有已提交的批次完成（按完成顺序处理）
            for future in as_completed(futures):
                batch_num = futures[future]
                try:
                    future.result()  # 获取结果，如果有异常会在这里抛出
                except Exception as e:
                    print(f"[LLM并发] 批次{batch_num}处理异常: {e}")
                    import traceback
                    traceback.print_exc()
        
        # 🆕 取消时的处理
        if cancelled_flag.is_set():
            print(f"[LLM解析] 任务已取消，已完成{completed_batches}/{total_batches}批")
            if progress_callback:
                progress_callback(100, f"任务已取消 {completed_batches}/{total_batches}")
        else:
            # 最终进度更新
            if progress_callback:
                progress_callback(100, f"LLM解析完成 {total_batches}/{total_batches}")

        # 展平错误列表
        final_errors = []
        for err_list in errors:
            final_errors.extend(err_list)
            
        return parsed_results, final_errors

    def _process_llm_batch(self, batch: List[str], indices: List[int], batch_types: List[str], parsed_results: list, errors: list, api_url: str, headers: dict, model_name: str, system_prompt: str):
        """处理单个LLM批次（增强版：预提取类型 + 详细日志 + 部分成功处理）"""
        import time
        
        # 🆕 构建带类型信息的用户消息
        user_prompt_lines = []
        for ref, doc_type in zip(batch, batch_types):
            user_prompt_lines.append(f"[预提取类型: {doc_type}]\n{ref}")
        user_prompt = "\n---\n".join(user_prompt_lines)
        
        # 📊 记录批次信息
        print(f"\n{'='*70}")
        print(f"📦 LLM批次处理:")
        print(f"   索引: {indices[0]}-{indices[-1]} (共{len(batch)}条)")
        print(f"   字符: {len(user_prompt)} chars (平均{len(user_prompt)//len(batch)}/条)")
        print(f"   类型: {', '.join(batch_types)}")  # 🆕 显示类型信息
        print(f"   预览: {batch[0][:60]}...")
        print(f"{'='*70}")
        
        request_data = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            # 🎯 优化参数以提高多次运行的一致性
            "temperature": 0.05, # 降低温度以减少随机性
            "top_p": 1.0,  
            "frequency_penalty": 0.0,  # 不惩罚重复，保持格式一致性
            "presence_penalty": 0.0,  # 不惩罚已出现的token，保持结构稳定
            "max_tokens": 4096,  # 🎯 保持充足输出空间，避免截断（批次1500字符需要~1800 tokens）
            # 注意：如果API支持seed参数，取消下面的注释可进一步提高一致性
            "seed": 42,  # 固定随机种子，确保相同输入产生相同输出（需要API支持）
            "stream": False,  # 🆕 禁用流式输出，确保完整响应
        }

        try:
            start_time = time.time()
            print(f"⏳ 发送请求...")
            
            # 🆕 增加重试机制和更长的超时时间
            max_retries = 3
            timeout_seconds = 900  # 15分钟超时
            retry_count = 0
            last_error = None
            response = None
            
            while retry_count < max_retries:
                try:
                    # 本地LLM并发控制：限制同时请求数防止GPU OOM
                    _llm_acquired = False
                    try:
                        from md_content_processor import _local_llm_semaphore, _is_local_llm
                        if _is_local_llm(api_url):
                            _local_llm_semaphore.acquire()
                            _llm_acquired = True
                            time.sleep(1)  # 增加1秒请求间隔，缓解瞬时高负载
                    except ImportError:
                        pass
                    try:
                        response = requests.post(
                            api_url, 
                            json=request_data, 
                            headers=headers, 
                            timeout=timeout_seconds
                        )
                    finally:
                        if _llm_acquired:
                            _local_llm_semaphore.release()
                    elapsed = time.time() - start_time
                    print(f"✅ 收到响应 (耗时{elapsed:.1f}秒, 状态{response.status_code})")
                    
                    # 🆕 检查状态码，对于服务器错误和429限流错误进行重试
                    if response.status_code == 200:
                        break  # 成功，跳出重试循环
                    elif response.status_code == 429:
                        # 🆕 429 限流错误，需要重试
                        retry_count += 1
                        if retry_count < max_retries:
                            # 对429使用更长的等待时间，因为是限流
                            wait_time = min(10 * (2 ** (retry_count - 1)), 60)  # 10秒、20秒、60秒
                            print(f"⚠️ 请求限流 (429 Too Many Requests)，重试 {retry_count}/{max_retries}...")
                            print(f"   响应: {response.text[:200]}")
                            print(f"   等待 {wait_time} 秒后重试（限流退避）...")
                            time.sleep(wait_time)
                        else:
                            print(f"❌ 请求限流，已重试{max_retries}次，放弃")
                            break  # 退出循环，在外部处理错误
                    elif response.status_code >= 500:
                        # 服务器错误，值得重试
                        retry_count += 1
                        if retry_count < max_retries:
                            # 🆕 指数退避策略：给服务器充足的恢复时间
                            wait_time = min(5 * (2 ** (retry_count - 1)), 30)  # 5秒、10秒、30秒
                            print(f"⚠️ 服务器错误 (状态码{response.status_code})，重试 {retry_count}/{max_retries}...")
                            print(f"   响应: {response.text[:200]}")
                            print(f"   等待 {wait_time} 秒后重试（指数退避）...")
                            time.sleep(wait_time)
                        else:
                            print(f"❌ 服务器错误，已重试{max_retries}次，放弃")
                            break  # 退出循环，在外部处理错误
                    elif response.status_code >= 400:
                        # 其他客户端错误（如401, 403等），不重试
                        print(f"❌ 客户端错误 (状态码{response.status_code})，不进行重试")
                        break
                    else:
                        # 其他状态码，不重试
                        break
                    
                except requests.exceptions.Timeout as e:
                    retry_count += 1
                    last_error = e
                    elapsed = time.time() - start_time
                    
                    if retry_count < max_retries:
                        print(f"⚠️ 请求超时 (耗时{elapsed:.1f}秒)，重试 {retry_count}/{max_retries}...")
                        time.sleep(2)  # 等待2秒再重试
                    else:
                        print(f"❌ 请求超时，已重试{max_retries}次，放弃")
                        raise  # 重新抛出异常
                        
                except requests.exceptions.RequestException as e:
                    retry_count += 1
                    last_error = e
                    elapsed = time.time() - start_time
                    
                    if retry_count < max_retries:
                        print(f"⚠️ 请求失败 ({str(e)[:100]})，重试 {retry_count}/{max_retries}...")
                        time.sleep(2)
                    else:
                        print(f"❌ 请求失败，已重试{max_retries}次，放弃")
                        raise
            
            # 检查是否成功获取响应
            if response is None:
                raise Exception("未能获取有效响应")
            
            if response.status_code == 200:
                response_data = response.json()
                llm_output = response_data['choices'][0]['message']['content'].strip()
                
                # 🚨 检测是否因token限制被截断
                finish_reason = response_data['choices'][0].get('finish_reason', 'unknown')
                if finish_reason == 'length':
                    print(f"⚠️⚠️⚠️ 警告：LLM输出因达到max_tokens限制被截断！")
                    print(f"   finish_reason: {finish_reason}")
                    print(f"   当前max_tokens: 4096")
                    print(f"   建议：减小批次大小或增加max_tokens")
                elif finish_reason == 'stop':
                    print(f"✅ LLM正常完成 (finish_reason: stop)")
                else:
                    print(f"⚠️ LLM完成原因: {finish_reason}")
                
                print(f"📄 LLM返回长度: {len(llm_output)} chars")
                print(f"   前200字符: {llm_output[:200]}...")
                
                # 清理和解析JSON
                original_output = llm_output
                if llm_output.startswith('```json'):
                    llm_output = llm_output[7:]
                    print(f"   🧹 移除 ```json 前缀")
                if llm_output.endswith('```'):
                    llm_output = llm_output[:-3]
                    print(f"   🧹 移除 ``` 后缀")
                llm_output = llm_output.strip()

                try:
                    # 🔧 修复：LLM可能返回两种格式
                    # 格式1（标准）: [{"authors":"...","title":"..."}, {...}, ...]
                    # 格式2（错误）: {"authors":"...","title":"..."}\n{...}\n{...}
                    
                    # 先尝试标准JSON数组格式
                    try:
                        parsed_batch = json.loads(llm_output)
                    except json.JSONDecodeError as e:
                        # 如果失败，检查是否是每行一个JSON对象的格式
                        if "Extra data" in str(e):
                            print(f"   ⚠️ 检测到多行JSON格式，尝试分行解析...")
                            parsed_batch = []
                            for line in llm_output.split('\n'):
                                line = line.strip()
                                if line:
                                    try:
                                        parsed_batch.append(json.loads(line))
                                    except json.JSONDecodeError:
                                        continue
                            print(f"   ✅ 分行解析成功，得到{len(parsed_batch)}条记录")
                        else:
                            # 使用 json_repair 尝试修复
                            print(f"   ⚠️ JSON解析失败，尝试 json_repair 修复...")
                            repaired = repair_json(llm_output, return_objects=True)
                            if isinstance(repaired, list) and len(repaired) > 0:
                                parsed_batch = repaired
                                print(f"   ✅ json_repair 修复成功，得到{len(parsed_batch)}条记录")
                            elif isinstance(repaired, dict) and len(repaired) > 0:
                                parsed_batch = [repaired]
                                print(f"   ✅ json_repair 修复成功（dict→list），得到1条记录")
                            else:
                                raise
                    
                    # 📊 验证返回格式
                    if isinstance(parsed_batch, dict):
                        # 🔧 LLM可能返回单个字典对象（当批次只有1条时）
                        print(f"   ⚠️ LLM返回字典类型，转换为数组")
                        parsed_batch = [parsed_batch]
                    
                    if isinstance(parsed_batch, list):
                        returned_count = len(parsed_batch)
                        expected_count = len(batch)
                        
                        print(f"📊 解析结果: 返回{returned_count}条, 预期{expected_count}条")
                        
                        if returned_count == 0:
                            # 🔄 空数组 - 抛出异常触发重试机制
                            print(f"⚠️ LLM返回空数组，将触发重试")
                            raise ValueError(f"LLM返回空数组，预期{expected_count}条")
                        elif returned_count == expected_count:
                            # ✅ 完全匹配 - 理想情况
                            for i, parsed_item in enumerate(parsed_batch):
                                original_index = indices[i]
                                # 标准化数据类型
                                parsed_results[original_index] = self._normalize_parsed_data(parsed_item)
                            print(f"✅ 批次完全成功! ({returned_count}/{expected_count})")
                            
                        elif returned_count > 0:
                            # ⚠️ 部分匹配 - 尽可能保存
                            matched_count = min(returned_count, expected_count)
                            for i in range(matched_count):
                                original_index = indices[i]
                                # 标准化数据类型
                                parsed_results[original_index] = self._normalize_parsed_data(parsed_batch[i])
                            
                            print(f"⚠️ 批次部分成功: {matched_count}/{expected_count} (保存{matched_count}条)")
                            
                            # 对未匹配的条目记录错误
                            for i in range(matched_count, expected_count):
                                errors[indices[i]].append(ValidationError(
                                    error_type="G.L2.01",
                                    message="无法将参考文献解析为标准著录项目。",
                                    suggestion=f"LLM返回数量不足，第{i+1}条缺失（批次返回{returned_count}条，预期{expected_count}条）"
                                ))
                    else:
                        raise ValueError(f"LLM返回非数组类型: {type(parsed_batch)}")
                        
                except (json.JSONDecodeError, ValueError) as e:
                    print(f"❌ JSON解析失败: {type(e).__name__} - {str(e)}")
                    print(f"   原始返回(前500字符):\n{original_output[:500]}")
                    
                    # G.L2.01 错误: LLM解析失败
                    for i in indices:
                        errors[i].append(ValidationError(
                            error_type="G.L2.01",
                            message="无法将参考文献解析为标准著录项目。",
                            suggestion=f"LLM JSON解析失败: {type(e).__name__}"
                        ))
            else:
                print(f"❌ API请求失败: 状态码{response.status_code}")
                print(f"   响应: {response.text[:200]}")
                
                # 🆕 根据状态码提供更详细的错误信息
                if response.status_code >= 500:
                    error_msg = f"API服务器错误{response.status_code}（已重试{retry_count}次）: {response.text[:100]}"
                elif response.status_code == 429:
                    error_msg = f"API请求频率限制（状态码429）: {response.text[:100]}"
                elif response.status_code == 401:
                    error_msg = f"API认证失败（状态码401）: 请检查API密钥是否有效"
                elif response.status_code >= 400:
                    error_msg = f"API客户端错误{response.status_code}: {response.text[:100]}"
                else:
                    error_msg = f"API错误{response.status_code}: {response.text[:100]}"
                
                # API请求失败
                for i in indices:
                    errors[i].append(ValidationError(
                        error_type="G.L2.01",
                        message="无法将参考文献解析为标准著录项目。",
                        suggestion=error_msg
                    ))
                    
        except requests.exceptions.Timeout:
            elapsed = time.time() - start_time
            print(f"❌ 请求最终超时 (耗时{elapsed:.1f}秒, 超时设置{timeout_seconds}秒)")
            for i in indices:
                errors[i].append(ValidationError(
                    error_type="G.L2.01",
                    message="无法将参考文献解析为标准著录项目。",
                    suggestion=f"API请求超时（已重试{max_retries}次，每次{timeout_seconds}秒）"
                ))
                
        except requests.exceptions.RequestException as e:
            print(f"❌ 网络异常: {type(e).__name__} - {str(e)}")
            for i in indices:
                errors[i].append(ValidationError(
                    error_type="G.L2.01",
                    message="无法将参考文献解析为标准著录项目。",
                    suggestion=f"网络错误: {type(e).__name__}"
                ))
        
        print(f"{'='*70}\n")

    def validate_references_list(self, references: List[str], user_id: int = None, progress_callback=None) -> Dict[str, ValidationResult]:
        """验证参考文献列表（支持L1/L2/L3规则）
        
        进度分配：
        - 0-1%: L1格式检查（快速检查，占比很小）
        - 1-90%: LLM批量解析（主要耗时，占89个百分点）
        - 90-100%: L2/L3规则检查+生成报告（占10个百分点）
        """
        results = {}
        l1_passed_indices = []
        l1_passed_refs = []
        
        # L1规则检查 - 同时进行筛选，一次循环完成
        total_refs = len(references)
        for i, reference in enumerate(references):
            if progress_callback:
                l1_progress = ((i + 1) / total_refs) * 1  # L1检查占0-1%
                progress_callback(l1_progress, f"L1检查 {i+1}/{total_refs}")
            
            # L1检查
            result = self.validate_reference_format(reference)
            results[f"ref_{i+1}"] = result
            
            # 同时判断是否可以进行L2/L3检查（只排除G.L1.01硬性错误）
            has_l1_01_error = any(err.error_type == "G.L1.01" for err in result.errors)
            if not has_l1_01_error:
                l1_passed_indices.append(i)
                l1_passed_refs.append(reference)
        
        print(f"L1通过的参考文献索引: {l1_passed_indices}") # 调试信息
        print(f"其中 {len([r for r in results.values() if not r.is_valid])} 条有L1错误但允许继续检查") # 调试信息

        # 如果提供了用户ID且有可继续检查的文献，则执行L2/L3规则
        if user_id and l1_passed_refs:
                # 创建LLM进度回调 - LLM解析占1%-90% (89个百分点)
                def llm_progress_callback(batch_progress, message):
                    if progress_callback:
                        overall_progress = 1 + (batch_progress * 0.89)
                        result = progress_callback(overall_progress, message)  # 直接传递message，避免重复前缀
                        return result  # 🆕 传递返回值以支持任务取消
                    return True  # 如果没有callback，返回True表示继续
                
                parsed_refs, l2_errors = self._parse_references_with_llm(l1_passed_refs, user_id, llm_progress_callback)
                
                # 将L2错误添加回对应的结果中
                error_idx = 0
                total_l1_passed = len(parsed_refs)
                
                # L2/L3规则检查占90%-100% (10个百分点)
                for i, parsed_ref in enumerate(parsed_refs):
                    # 更新L2/L3检查进度
                    if progress_callback:
                        l2_l3_progress = 90 + ((i + 1) / total_l1_passed) * 10
                        progress_callback(l2_l3_progress, f"L2/L3检查 {i+1}/{total_l1_passed}")
                    
                    original_ref_index = l1_passed_indices[i]
                    ref_key = f"ref_{original_ref_index + 1}"

                    # 存储LLM解析结果到ValidationResult中
                    results[ref_key].parsed_data = parsed_ref

                    if parsed_ref is None:
                        # 这意味着G.L2.01发生
                        # 查找属于这个文献的G.L2.01错误
                        while error_idx < len(l2_errors) and l2_errors[error_idx].position != original_ref_index:
                            error_idx += 1
                        if error_idx < len(l2_errors):
                             results[ref_key].errors.append(l2_errors[error_idx])
                             results[ref_key].is_valid = False
                    else:
                        # L2级检查 - 使用新的调度方法
                        original_ref = references[original_ref_index]
                        
                        # 页码提取后备方案: 如果LLM未返回页码,尝试从原文提取
                        if not parsed_ref.get('pages'):
                            extracted_pages = self._extract_pages_from_reference(original_ref)
                            if extracted_pages:
                                parsed_ref['pages'] = extracted_pages
                                print(f"  [参考文献 {ref_key}] LLM未返回页码,已从原文提取: {extracted_pages}")
                            else:
                                print(f"  [参考文献 {ref_key}] LLM未返回页码,原文也未找到页码信息")
                        
                        # 出版年提取后备方案: 如果LLM未返回出版年,尝试从原文提取
                        if not parsed_ref.get('publish_year'):
                            extracted_year = self._extract_year_from_reference(original_ref)
                            if extracted_year:
                                parsed_ref['publish_year'] = int(extracted_year)  # 转换为整数类型
                                print(f"  [参考文献 {ref_key}] LLM未返回出版年,已从原文提取: {extracted_year}")
                            else:
                                print(f"  [参考文献 {ref_key}] LLM未返回出版年,原文也未找到出版年信息")
                        
                        # 出版地提取后备方案: 从conference_location提取(仅会议论文)
                        doc_type = parsed_ref.get('document_type', '')
                        if not parsed_ref.get('publish_place'):
                            if doc_type in ['C', 'A']:
                                conference_location = parsed_ref.get('conference_location')
                                if conference_location and isinstance(conference_location, str):
                                    # 从会议地点提取出版地(通常是逗号前的城市名)
                                    publish_place = conference_location.split(',')[0].strip()
                                    parsed_ref['publish_place'] = publish_place
                                    print(f"  [参考文献 {ref_key}] 从会议地点提取出版地: {publish_place}")
                        
                        # URL提取后备方案: 如果LLM未返回URL且是电子资源,尝试从原文提取
                        if not parsed_ref.get('url') and self._is_electronic_resource(original_ref):
                            extracted_url = self._extract_url_from_reference(original_ref)
                            if extracted_url:
                                parsed_ref['url'] = extracted_url
                                print(f"  [参考文献 {ref_key}] LLM未返回URL,已从原文提取: {extracted_url}")
                            else:
                                print(f"  [参考文献 {ref_key}] LLM未返回URL,原文也未找到URL信息")
                        
                        # 学校/保存单位提取后备方案: 如果LLM未返回且是学位论文,尝试从原文提取
                        if not parsed_ref.get('school') and doc_type == 'D':
                            extracted_school = self._extract_school_from_reference(original_ref)
                            if extracted_school:
                                parsed_ref['school'] = extracted_school
                                print(f"  [参考文献 {ref_key}] LLM未返回学校/保存单位,已从原文提取: {extracted_school}")
                            else:
                                print(f"  [参考文献 {ref_key}] LLM未返回学校/保存单位,原文也未找到明确的机构名称")
                        
                        l2_errors = self.validate_l2_rules(parsed_ref, original_ref)
                        
                        # L3级检查 - 使用新的调度方法
                        l3_errors = self.validate_l3_rules(parsed_ref, original_ref)

                        if l2_errors or l3_errors:
                            results[ref_key].errors.extend(l2_errors)
                            results[ref_key].errors.extend(l3_errors)
                            results[ref_key].is_valid = False
        
        # 🎯 关键修复：对每个结果的 errors 和 warnings 列表进行确定性排序，提升一致性
        # 排序规则：1) error_code 2) message 3) position
        for ref_key, result in results.items():
            if result.errors:
                result.errors = sorted(
                    result.errors,
                    key=lambda e: (
                        e.error_type or "",  # 按错误代码排序
                        e.message or "",     # 相同代码按消息排序
                        e.position or 0      # 相同消息按位置排序
                    )
                )
            if result.warnings:
                result.warnings = sorted(
                    result.warnings,
                    key=lambda w: (
                        w.error_type or "",
                        w.message or "",
                        w.position or 0
                    )
                )

        return results

    def generate_validation_report(self, references: List[str], user_id: int = None) -> str:
        """生成基于新规则系统的验证报告"""
        results = self.validate_references_list(references, user_id=user_id)
        
        report = ["# 参考文献格式验证报告（GB/T 7714-2015新规则系统）\n"]
        
        # 统计信息
        total_refs = len(references)
        valid_count = sum(1 for r in results.values() if r.is_valid)
        invalid_count = total_refs - valid_count
        
        report.append(f"## 📊 验证概览\n")
        report.append(f"- **总文献数**: {total_refs}")
        report.append(f"- **✅ 格式正确**: {valid_count} ({(valid_count/total_refs*100):.1f}%)")
        report.append(f"- **❌ 需要修正**: {invalid_count} ({(invalid_count/total_refs*100):.1f}%)\n")
        
        # 错误分类统计
        error_stats = self._get_error_category_statistics(results)
        if error_stats:
            report.append("## 📈 错误分类统计\n")
            for category, count in error_stats.items():
                category_name = self._get_category_name(category)
                report.append(f"- **{category_name}**: {count}个错误")
            report.append("")
        
        # 规则覆盖度分析
        rule_coverage = self._get_rule_coverage_analysis(results)
        if rule_coverage:
            report.append("## 🎯 规则覆盖度分析\n")
            for rule_type, data in rule_coverage.items():
                report.append(f"### {rule_type}")
                report.append(f"- 检查项目数: {data['total']}")
                report.append(f"- 发现问题数: {data['errors']}")
                report.append(f"- 通过率: {data['pass_rate']:.1f}%\n")
        
        # 详细验证结果
        report.append("## 📋 详细验证结果\n")
        for i, (ref_id, result) in enumerate(results.items(), 1):
            doc_type = self._extract_document_type(ref_id, references[i-1] if i <= len(references) else "")
            
            report.append(f"### 📄 文献 {i} {f'[{doc_type}]' if doc_type else ''}")
            report.append(f"**状态**: {'✅ 格式规范' if result.is_valid else '❌ 需要修正'}")
            report.append(f"**置信度**: {result.confidence:.1f}%")
            
            if result.errors:
                report.append(f"\n**🚨 发现 {len(result.errors)} 个问题**:")
                # 按规则类别分组显示错误
                grouped_errors = self._group_errors_by_category(result.errors)
                for category, errors in grouped_errors.items():
                    category_name = self._get_category_name(category)
                    report.append(f"\n*{category_name}问题*:")
                    for error in errors:
                        report.append(f"- **{error.error_type}**: {error.message}")
                        if error.suggestion:
                            report.append(f"  💡 *建议*: {error.suggestion}")
            
            if result.warnings:
                report.append(f"\n**⚠️ 警告 ({len(result.warnings)}个)**:")
                for warning in result.warnings:
                    report.append(f"- {warning.message}")
            
            report.append("\n---\n")
        
        # 改进建议
        improvement_suggestions = self._generate_improvement_suggestions(results)
        if improvement_suggestions:
            report.append("## 💡 改进建议\n")
            for suggestion in improvement_suggestions:
                report.append(f"- {suggestion}")
            report.append("")
        
        report.append("## 📚 规则说明\n")
        report.append("- **G类规则**: 适用于所有文献的通用要求")
        report.append("- **M类规则**: 专著特有要求") 
        report.append("- **A类规则**: 析出文献特有要求")
        report.append("- **J类规则**: 期刊文章特有要求")
        report.append("- **N类规则**: 报纸文章特有要求")
        report.append("- **P类规则**: 专利文献特有要求")
        report.append("- **E类规则**: 电子资源特有要求")
        
        return "\n".join(report)
    
    def _get_error_category_statistics(self, results: Dict) -> Dict[str, int]:
        """获取错误分类统计"""
        categories = {}
        for result in results.values():
            for error in result.errors:
                category = error.error_type.split('.')[0] if '.' in error.error_type else 'OTHER'
                categories[category] = categories.get(category, 0) + 1
        return dict(sorted(categories.items()))
    
    def _get_category_name(self, category: str) -> str:
        """获取分类名称"""
        names = {
            'G': '通用规则',
            'M': '专著规则', 
            'A': '析出文献规则',
            'J': '期刊规则',
            'N': '报纸规则',
            'P': '专利规则',
            'E': '电子资源规则'
        }
        return names.get(category, f'{category}类规则')
    
    def _get_rule_coverage_analysis(self, results: Dict) -> Dict[str, Dict]:
        """获取规则覆盖度分析"""
        coverage = {}
        for result in results.values():
            for error in result.errors:
                if '.' in error.error_type:
                    parts = error.error_type.split('.')
                    rule_level = f"{parts[0]}.{parts[1]}"  # 如 G.L1, M.L3
                    if rule_level not in coverage:
                        coverage[rule_level] = {'total': 0, 'errors': 0}
                    coverage[rule_level]['total'] += 1
                    coverage[rule_level]['errors'] += 1
        
        # 计算通过率
        for data in coverage.values():
            data['pass_rate'] = ((data['total'] - data['errors']) / data['total'] * 100) if data['total'] > 0 else 100
        
        return coverage
    
    def _extract_document_type(self, ref_id: str, reference: str) -> str:
        """从参考文献中提取文献类型"""
        match = re.search(r'\[([A-Z/]+)\]', reference)
        return match.group(1) if match else ""
    
    def _normalize_parsed_data(self, parsed_item: Dict) -> Dict:
        """
        标准化LLM返回的解析数据
        - 统一publish_year为整数类型
        - 确保所有字段类型一致
        """
        if not parsed_item:
            return parsed_item
        
        # 标准化出版年为整数
        if 'publish_year' in parsed_item and parsed_item['publish_year'] is not None:
            try:
                if isinstance(parsed_item['publish_year'], str):
                    parsed_item['publish_year'] = int(parsed_item['publish_year'])
                elif not isinstance(parsed_item['publish_year'], int):
                    parsed_item['publish_year'] = int(str(parsed_item['publish_year']))
            except (ValueError, TypeError):
                # 如果转换失败,保持为None
                parsed_item['publish_year'] = None
        
        # 标准化其他可能的数字字段
        numeric_fields = ['volume', 'issue', 'edition']
        for field in numeric_fields:
            if field in parsed_item and parsed_item[field] is not None:
                # 这些字段可以保持字符串,但确保不是纯数字对象
                if isinstance(parsed_item[field], (int, float)):
                    parsed_item[field] = str(parsed_item[field])
        
        return parsed_item
    
    def _extract_pages_from_reference(self, reference: str) -> Optional[str]:
        """
        从原始参考文献文本中提取页码信息
        用作LLM解析失败时的后备方案
        
        提取规则:
        1. 优先从末尾冒号后提取 (如 ": 10-15.")
        2. 如果没有,尝试从年份后提取 (如 "2021: 25-30")
        3. 支持单页或页码范围
        
        Args:
            reference: 原始参考文献字符串
            
        Returns:
            提取到的页码字符串,如果未找到则返回None
            
        Examples:
            "Journal, 2023, 45(3): 10-15." -> "10-15"
            "Book: 32-36." -> "32-36"
            "Conference, 2021: 25-30." -> "25-30"
        """
        if not reference:
            return None
        
        # 模式1: 从末尾向前搜索 ":" 后面的数字或数字范围
        pattern1 = r':\s*(\d+(?:-\d+)?)\s*[.\s]*$'
        match = re.search(pattern1, reference)
        
        if match:
            pages = match.group(1).strip()
            print(f"    ✓ 从原文提取到页码: {pages}")
            return pages
        
        # 模式2: 查找年份后的页码 (如 "2021: 25-30")
        pattern2 = r'\b([12]\d{3})\s*:\s*(\d+(?:-\d+)?)'
        matches = list(re.finditer(pattern2, reference))
        if matches:
            # 取最后一个匹配(最可能是页码)
            pages = matches[-1].group(2).strip()
            print(f"    ✓ 从原文提取到页码: {pages}")
            return pages
        
        return None
    
    def _extract_year_from_reference(self, reference: str) -> Optional[str]:
        """
        从原始参考文献文本中提取出版年信息
        用作LLM解析失败时的后备方案
        
        提取规则:
        - 从文本末尾向前搜索最后一个逗号
        - 取逗号后的四位数字作为出版年
        - 四位数字需要是合理的年份范围(1900-2099)
        
        Args:
            reference: 原始参考文献字符串
            
        Returns:
            提取到的出版年字符串,如果未找到则返回None
            
        Examples:
            "作者. 题名[M]. 北京: 出版社, 2023: 10-15." -> "2023"
            "作者. 题名[J]. 期刊名, 2022, 45(3): 100-110." -> "2022"
            "作者. 题名[C]// 会议名. 地点: 出版社, 2021: 25-30." -> "2021"
        """
        if not reference:
            return None
        
        # 从后往前查找所有逗号的位置
        comma_positions = [i for i, char in enumerate(reference) if char == ',']
        if not comma_positions:
            return None
        
        # 从最后一个逗号开始向前尝试
        for comma_pos in reversed(comma_positions):
            # 取逗号后的文本
            text_after_comma = reference[comma_pos + 1:]
            
            # 匹配逗号后紧跟的四位数字(可能有空格)
            # 匹配模式: ", 2023" 或 ",2023" 后面可能跟着冒号、括号、空格等
            match = re.match(r'\s*([12]\d{3})(?=[\s:(\[]|$)', text_after_comma)
            if match:
                year = match.group(1)
                year_int = int(year)
                # 验证年份范围是否合理
                if 1900 <= year_int <= 2099:
                    print(f"    ✓ 从原文提取到出版年: {year} (从后往前第{len(comma_positions) - comma_positions.index(comma_pos)}个逗号后)")
                    return year
        
        return None
    
    def _extract_url_from_reference(self, reference: str) -> Optional[str]:
        """
        从原始参考文献文本中提取URL信息
        用作LLM解析失败时的后备方案
        
        提取规则:
        1. 优先提取标准URL格式 (http://, https://)
        2. 支持DOI链接 (doi.org, dx.doi.org)
        3. 取最后一个匹配的URL (最可能是引用路径)
        
        Args:
            reference: 原始参考文献字符串
            
        Returns:
            提取到的URL字符串,如果未找到则返回None
            
        Examples:
            "作者.题名[EB/OL].[2022-4-19].https://www.who.int/zh/..." -> "https://www.who.int/zh/..."
            "作者.题名[J/OL].期刊,2023.http://example.com/article" -> "http://example.com/article"
            "作者.题名[M/OL].DOI:10.1234/example" -> "https://doi.org/10.1234/example"
        """
        if not reference:
            return None
        
        # 模式1: 标准HTTP/HTTPS URL
        url_pattern = r'https?://[^\s,，。)\]）\]]*[^\s,，。)\]）\].!?]'
        urls = re.findall(url_pattern, reference, re.IGNORECASE)
        
        if urls:
            # 取最后一个URL (最可能是获取路径)
            url = urls[-1].strip()
            print(f"    ✓ 从原文提取到URL: {url}")
            return url
        
        # 模式2: DOI格式 (转换为标准URL)
        doi_pattern = r'(?:DOI|doi)[\s:：]+(\d+\.\S+)'
        doi_match = re.search(doi_pattern, reference)
        
        if doi_match:
            doi = doi_match.group(1).strip()
            # 移除末尾的标点符号
            doi = re.sub(r'[.,;。，；]+$', '', doi)
            url = f"https://doi.org/{doi}"
            print(f"    ✓ 从原文提取到DOI并转换为URL: {url}")
            return url
        
        return None
    
    def _extract_school_from_reference(self, reference: str) -> Optional[str]:
        """
        从原始参考文献文本中提取学校/保存单位信息
        用作LLM解析失败时的后备方案（仅学位论文[D]）
        
        提取规则（严格模式）:
        1. 查找包含明确机构关键词的完整词段
        2. 关键词：大学、学院、医院、研究院、研究所、University、College、Institute、Hospital
        3. 提取未被标点符号、空格分隔的完整词段
        4. 没有明确关键词时返回None（不做疑似推测）
        
        Args:
            reference: 原始参考文献字符串
            
        Returns:
            提取到的学校/保存单位字符串,如果未找到则返回None
            
        Examples:
            "李娟. 题名[D]. 山东:济南大学,2023." -> "济南大学"
            "作者. 题名[D]. 北京:清华大学,2020." -> "清华大学"
            "Author. Title[D]. Location:Tsinghua University,2020." -> "Tsinghua University"
            "作者. 题名[D]. 北京:某机构,2020." -> None (无明确关键词)
        """
        if not reference:
            return None
        
        # 定义机构关键词（中英文）
        # 中文关键词 - 按优先级排序（长词优先，避免误匹配）
        keywords_cn = [
            # 完整机构名称
            '研究院', '研究所', '设计院', '科学院', '工程院',
            # 教育机构
            '大学', '学院', '高校', '职业学院', '技术学院', '师范学院',
            # 医疗机构
            '医院', '医学院', '卫生学校', '医科大学', '中医院', '人民医院', '中心医院',
            # 科研机构
            '实验室', '研究中心', '技术中心', '工程中心',
            # 党校/军校
            '党校', '军校', '警校',
        ]
        
        # 英文关键词 - 按优先级排序
        keywords_en = [
            'University', 'College', 'Institute', 'Academy',
            'Hospital', 'School', 'Laboratory', 'Center',
            'Research', 'Medical', 'Polytechnic', 'Normal'
        ]
        
        # 构建正则模式：匹配包含关键词的完整词段
        # 词段定义：不被以下符号分隔的连续字符
        # 分隔符：逗号、句号、冒号、分号、括号、方括号、空格等
        separators = r'[,，.。:：;；\s\(\)\[\]（）【】]'
        
        # 模式1: 中文机构名（包含关键词的连续中文/字母/数字序列）
        for keyword in keywords_cn:
            # 匹配包含关键词的词段，前后不能有分隔符
            pattern = f'([^,，.。:：;；\\s\\(\\)\\[\\]（）【】]*{keyword}[^,，.。:：;；\\s\\(\\)\\[\\]（）【】]*)'
            matches = re.findall(pattern, reference)
            
            if matches:
                # 取最后一个匹配（通常是最接近出版信息的）
                school = matches[-1].strip()
                if school and len(school) >= len(keyword):  # 确保不是仅关键词本身
                    # 严格过滤：排除"某XX"、"XX等"等模糊表述
                    if not re.match(r'^某.+|.+等$', school):
                        print(f"    ✓ 从原文提取到学校/保存单位: {school} (关键词: {keyword})")
                        return school
        
        # 模式2: 英文机构名（包含关键词的连续英文/数字序列）
        # 注意：英文机构名允许包含空格，如"Oxford University", "Stanford Medical Center"
        for keyword in keywords_en:
            # 英文匹配，忽略大小写
            # 匹配模式：从冒号后或逗号后开始，到逗号或句号结束
            # 例如：": Oxford University," 或 ": Stanford Medical Center."
            pattern = f'[:：]([^,，.。;；]*{keyword}[^,，.。;；]*)[,，.。;；]'
            matches = re.findall(pattern, reference, re.IGNORECASE)
            
            if matches:
                # 取最后一个匹配，并清理前后空格
                school = matches[-1].strip()
                if school and len(school) >= len(keyword):
                    # 严格过滤：排除"Some XX"、"XX etc"等模糊表述
                    if not re.match(r'^(some|any|certain).+|.+(etc|et al)$', school, re.IGNORECASE):
                        print(f"    ✓ 从原文提取到学校/保存单位: {school} (关键词: {keyword})")
                        return school
        
        # 没有找到明确的机构关键词，返回None
        return None
    
    def _group_errors_by_category(self, errors: List) -> Dict[str, List]:
        """按分类分组错误"""
        grouped = {}
        for error in errors:
            category = error.error_type.split('.')[0] if '.' in error.error_type else 'OTHER'
            if category not in grouped:
                grouped[category] = []
            grouped[category].append(error)
        return grouped
    
    def _generate_improvement_suggestions(self, results: Dict) -> List[str]:
        """生成改进建议"""
        suggestions = []
        error_counts = self._get_error_category_statistics(results)
        
        if error_counts.get('G', 0) > 0:
            suggestions.append("重点关注通用规则(G类)：确保所有文献都有文献类型标识和DOI")
        
        if error_counts.get('M', 0) > 0:
            suggestions.append("专著类文献(M类)：检查出版社和版本信息格式是否规范")
        
        if error_counts.get('J', 0) > 0:
            suggestions.append("期刊类文献(J类)：确保期刊名称和年卷期格式正确")
        
        if error_counts.get('P', 0) > 0:
            suggestions.append("专利文献(P类)：核实专利号和申请人信息格式")
        
        total_errors = sum(error_counts.values())
        if total_errors > len(results) * 0.5:
            suggestions.append("错误较多，建议参考GB/T 7714-2015标准重新整理参考文献格式")
        
        return suggestions

    # === 通用辅助方法 ===
    
    def _check_required_field(self, parsed_ref: Dict, field: str, error_code: str, 
                             field_name_cn: str, suggestion: str) -> Optional[ValidationError]:
        """通用必备字段检查辅助方法"""
        field_value = parsed_ref.get(field)
        if not field_value or (isinstance(field_value, str) and not field_value.strip()):
            return ValidationError(
                error_type=error_code,
                message=f"{field_name_cn}缺失。" if "缺少" not in field_name_cn else field_name_cn,
                suggestion=suggestion
            )
        return None
    
    def _check_doc_type(self, parsed_ref: Dict, expected_type: str) -> bool:
        """检查文献类型是否匹配"""
        return parsed_ref.get("document_type") == expected_type
    
    def _is_electronic_doc_type(self, parsed_ref: Dict) -> bool:
        """检查是否为电子资源类型（含复合类型）"""
        doc_type = parsed_ref.get("document_type", "")
        # 匹配所有包含/OL的类型，或DS、OL单独类型
        return "/OL" in doc_type or doc_type in ["DS", "OL"]

    # === L2级别：完整性检查 ===

    def validate_g_l2_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """G.L2.02: 无法从参考文献中识别出\"主要责任者\"。"""
        errors = []
        authors = parsed_ref.get("authors")

        # 检查作者列表是否为空，或者所有作者都是无效的（空字符串或仅标点）
        import string
        is_author_invalid = not authors or all(
            not author or author.strip() in string.punctuation for author in authors
        )

        if is_author_invalid:
            # 对于标准[S]类型，作者不是必需的，不应报错
            if "[S]" not in original_ref:
                errors.append(ValidationError(
                    error_type="G.L2.02",
                    message="无法从参考文献中识别出\"主要责任者\"。",
                    suggestion="请补充有效的作者信息。"
                ))
        return errors

    def validate_g_l2_03(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """G.L2.03: 无法从参考文献中识别出\"题名\"。"""
        errors = []
        if not parsed_ref.get("title"):
            errors.append(ValidationError(
                error_type="G.L2.03",
                message="无法从参考文献中识别出\"题名\"。",
                suggestion="请补充题名信息。"
            ))
        return errors

    def validate_g_l2_04(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """G.L2.04: 无法从参考文献中识别出\"出版年\"。
        
        根据GB/T 7714-2015标准，某些期刊文章可能采用简化格式：
        - 在线首发文章：作者.题名[J].期刊名:页码.
        - 预印本文章或已接受但未分配卷期的文章
        因此不应过度严格要求所有期刊文章都必须有年份。
        """
        errors = []
        
        # 电子资源可能没有出版年，但有访问日期
        is_electronic = "/OL" in original_ref or "[EB/OL]" in original_ref or "[DB/OL]" in original_ref
        has_access_date = "access_date" in parsed_ref and parsed_ref["access_date"]
        
        # 基本年份缺失检查（排除电子资源有访问日期的情况）
        # 根据GB/T 7714-2015标准，所有期刊文献都必须包含出版年，无例外
        if not parsed_ref.get("publish_year") and not (is_electronic and has_access_date):
            errors.append(ValidationError(
                error_type="G.L2.04",
                message="无法从参考文献中识别出\"出版年\"。",
                suggestion="根据GB/T 7714-2015标准，参考文献必须包含4位数字的出版年份。"
            ))
        
        return errors

    def validate_g_l3_01_and_g_l3_02_author_count(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """
        L3.01: 主要责任者超过3个时，未按规定著录为“前3个责任者, 等”。
        L3.02: 主要责任者不足3个，但错误地使用了“等”。
        """
        errors = []
        authors = parsed_ref.get("authors")
        if not authors:
            return errors

        author_list = [a.strip() for a in "".join(authors).split(',')]
        
        # 🔧 优化：更健壮的 "等" 检测，容错处理尾部句号
        has_etal = False
        etal_variants = ["等", "等.", "et al", "et al."]
        for author in author_list:
            author_cleaned = author.strip().rstrip('.')
            if author_cleaned in ["等", "et al"] or author.strip() in etal_variants:
                has_etal = True
                break
        
        if has_etal:
            # G.L3.02: 责任者不足3个但使用"等"
            author_count_before_etal = 0
            for author in author_list:
                author_cleaned = author.strip().rstrip('.')
                if author_cleaned in ["等", "et al"] or author.strip() in etal_variants:
                    break
                author_count_before_etal += 1
            
            if author_count_before_etal < 3:
                errors.append(ValidationError(
                    error_type="G.L3.02",
                    severity="info",
                    message="主要责任者不足3个，但错误地使用了“等”。",
                    suggestion="当责任者少于3个时，应全部列出，不使用“等”。"
                ))
        else:
            # G.L3.01: 责任者超过3个未使用"等"
            # 🔧 优化：排除 "等" 的变体后再计数
            actual_author_count = 0
            for author in author_list:
                author_cleaned = author.strip().rstrip('.')
                if author_cleaned not in ["等", "et al"] and author.strip() not in etal_variants:
                    actual_author_count += 1
            
            if actual_author_count > 3:
                errors.append(ValidationError(
                    error_type="G.L3.01",
                    severity="info",
                    message="主要责任者超过3个时，未按规定著录为“前3个责任者, 等”。",
                    suggestion="当责任者多于3个时，应只著录前3个，然后加上“, 等”或“, et al.”。"
                ))
        return errors

    def validate_g_l3_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """G.L3.01: 主要责任者超过3个时，未按规定著录为"前3个责任者, 等"。"""
        authors = parsed_ref.get("authors")
        if not authors:
            return []

        author_list = [a.strip() for a in "".join(authors).split(',')]
        
        etal_variants = ["等", "等.", "et al", "et al."]
        has_etal = False
        for author in author_list:
            author_cleaned = author.strip().rstrip('.')
            if author_cleaned in ["等", "et al"] or author.strip() in etal_variants:
                has_etal = True
                break
        
        if not has_etal:
            actual_author_count = 0
            for author in author_list:
                author_cleaned = author.strip().rstrip('.')
                if author_cleaned not in ["等", "et al"] and author.strip() not in etal_variants:
                    actual_author_count += 1
            
            if actual_author_count > 3:
                return [ValidationError(
                    error_type="G.L3.01",
                    severity="info",
                    message="主要责任者超过3个时，未按规定著录为\"前3个责任者, 等\"。",
                    suggestion="当责任者多于3个时，应只著录前3个，然后加上\", 等\"或\", et al.\"。"
                )]
        
        return []
    
    def validate_g_l3_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """G.L3.02: 主要责任者不足3个，但错误地使用了"等"。"""
        authors = parsed_ref.get("authors")
        if not authors:
            return []

        author_list = [a.strip() for a in "".join(authors).split(',')]
        
        etal_variants = ["等", "等.", "et al", "et al."]
        has_etal = False
        for author in author_list:
            author_cleaned = author.strip().rstrip('.')
            if author_cleaned in ["等", "et al"] or author.strip() in etal_variants:
                has_etal = True
                break
        
        if has_etal:
            author_count_before_etal = 0
            for author in author_list:
                author_cleaned = author.strip().rstrip('.')
                if author_cleaned in ["等", "et al"] or author.strip() in etal_variants:
                    break
                author_count_before_etal += 1
            
            if author_count_before_etal < 3:
                return [ValidationError(
                    error_type="G.L3.02",
                    severity="info",
                    message="主要责任者不足3个，但错误地使用了\"等\"。",
                    suggestion="当责任者少于3个时，应全部列出，不使用\"等\"。"
                )]
        
        return []

    def _is_likely_person_name(self, text: str) -> bool:
        """Heuristic check to see if a string is likely a person's name and not a title or organization."""
        text_lower = text.strip().lower()
        
        # Rule 1: Exclude 'et al.' and '等'
        if text_lower in ['et al.', 'et al', '等']:
            return False
            
        # Rule 2: Exclude common title words
        title_words = {'a', 'an', 'the', 'on', 'in', 'of', 'for', 'and', 'with', 'survey', 'network', 'deep', 'learning', 'comprehensive', 'elements', 'statistical'}
        words = set(text_lower.split())
        if len(words.intersection(title_words)) > 1: # Allow one, but more suggests a title
            return False
            
        # Rule 3: Word count limit (most names are 2-4 words)
        if len(words) > 4:
            return False
            
        # Rule 4: Exclude if it contains URL-like or numeric-heavy content
        if 'http' in text_lower or any(char.isdigit() for char in text_lower):
            return False

        # Rule 5: Exclude single-word, likely acronyms/orgs (e.g., OpenAI)
        if ' ' not in text.strip() and not text.strip().isupper(): # Keep multi-letter all-caps names like 'ZHANG'
             if any(c.islower() for c in text.strip()): # e.g. 'OpenAI'
                return False

        return True

    def validate_g_l3_03(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """G.L3.03: 汉语拼音人名格式不规范，姓氏未全大写或名的缩写不正确。"""
        errors = []
        authors_data = parsed_ref.get("authors")
        author_name_types = parsed_ref.get("author_name_types")
        
        # 🔧 修复：确保author_name_types是列表，如果是None则设为空列表
        if author_name_types is None:
            author_name_types = []
        
        if not authors_data:
            return errors

        author_list = []
        if isinstance(authors_data, list):
            author_list = authors_data
        elif isinstance(authors_data, str):
            author_list = [name.strip() for name in authors_data.split(',')]

        # 只检查LLM标记为中国人汉语拼音的人名
        for i, author in enumerate(author_list):
            if not isinstance(author, str) or not author.strip():
                continue

            # 检查是否有对应的名称类型标记
            if i < len(author_name_types) and author_name_types[i] == "chinese_pinyin":
                author_clean = author.strip()
                
                # 检查汉语拼音格式是否正确：姓氏全大写，名可缩写
                # GB/T 7714-2015: 用汉语拼音书写的人名，姓全大写，其名可缩写，取每个汉字拼音的首字母
                name_parts = author_clean.split()
                if len(name_parts) >= 2:
                    surname = name_parts[0]
                    given_names = name_parts[1:]
                    
                    # 检查姓氏是否全大写
                    if not surname.isupper():
                        suggested_format = surname.upper() + ' ' + ' '.join(given_names)
                        errors.append(ValidationError(
                            error_type="G.L3.03",
                            severity="info",
                            message=f"汉语拼音人名格式不规范: {author}",
                            suggestion=f"姓氏应全部大写。建议格式: {suggested_format}"
                        ))
        return errors

    def validate_m_l3_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """M.L3.01: 版本项著录不规范，第1版被错误著录。"""
        errors = []
        edition = parsed_ref.get("edition")
        if edition and any(v in edition for v in ["第1版", "1版", "1st ed."]):
             errors.append(ValidationError(
                error_type="M.L3.01",
                message="版本项著录不规范，第1版不应著录。",
                severity="info",  # 改为提示级别
                suggestion="根据标准，第1版信息不需要在参考文献中列出，建议移除。"
            ))
        return errors

    def validate_m_l3_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """M.L3.02: 出版地不详或出版者不详时，未按规定使用方括号标识。
        注意：期刊文献([J])通常不需要出版地和出版者信息，此规则主要适用于图书等文献类型。"""
        errors = []
        doc_type = parsed_ref.get("document_type", "")
        
        # 期刊文献([J])、会议论文([C])等通常不需要出版地信息，跳过检查
        if doc_type in ["J", "C"]:
            return errors
        place = parsed_ref.get("publish_place")
        publisher = parsed_ref.get("publisher")

        # 只对需要出版地信息的文献类型进行检查（如图书[M]、标准[S]等）
        if doc_type in ["M", "S", "R", "D"] or doc_type == "":  # 图书、标准、报告、学位论文或未知类型
            if not place:
                if not re.search(r'\[出版地不详\]|\[S\.l\.\]', original_ref, re.IGNORECASE):
                    errors.append(ValidationError(
                    error_type="M.L3.02",
                    severity="info",
                    message="出版地不详时，未按规定使用“[出版地不详]”或“[S.l.]”标识。",
                    suggestion="请为未知的出版地添加标准占位符, 如 '[S.l.]'。"
                ))
            
            if not publisher:
                if not re.search(r'\[出版者不详\]|\[s\.n\.\]', original_ref, re.IGNORECASE):
                     errors.append(ValidationError(
                    error_type="M.L3.02",
                    severity="info",
                    message="出版者不详时，未按规定使用“[出版者不详]”或“[s.n.]”标识。",
                    suggestion="请为未知的出版者添加标准占位符, 如 '[s.n.]'。"
                ))
        return errors

    def validate_j_l3_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """J.L3.01: 期刊的年、卷、期、页码格式不规范。
        
        标准格式要求:
        1. 年, 卷(期): 页码 (如 2023, 45(3): 10-15) - 标准格式
        2. 年, 卷: 页码 (如 2022, 183: 109119) - 无期号的简化格式
        
        不规范情况:
        1. 缺少卷号: 年(期): 页码 (如 2023(4): 10-19) - 缺失卷号
        2. 卷号含非数字: 年, XXX-N(期): 页码 (如 1979, PAMI-1(2): 164-172)
        """
        if not self._check_doc_type(parsed_ref, "J"):
            return []
        
        errors = []
        journal_format_valid = parsed_ref.get("journal_format_valid")
        
        # 本地二次验证: 检查是否存在明显的格式错误
        volume = parsed_ref.get("volume")
        issue = parsed_ref.get("issue")
        publish_year = parsed_ref.get("publish_year")
        
        # 🆕 统一错误消息策略：所有期刊格式错误使用相同的消息文本
        # 避免因LLM判断波动导致错误消息不一致
        UNIFIED_MESSAGE = "期刊的年、卷、期、页码格式不符合GB/T 7714-2015标准。"
        UNIFIED_SUGGESTION = "标准格式应为 '年, 卷(期): 页码'，例如 '2023, 45(3): 10-15'。"
        
        # 检查1: 卷号不应包含非数字字符(除了空格和短横线)
        if volume and isinstance(volume, str):
            # 允许纯数字或空值,不允许字母等
            if not re.match(r'^[\d\s-]+$', volume.strip()):
                errors.append(ValidationError(
                    error_type="J.L3.01",
                    severity="info",
                    message=UNIFIED_MESSAGE,
                    suggestion=f"卷号'{volume}'包含非数字字符。{UNIFIED_SUGGESTION}"
                ))
                return errors  # 立即返回,避免重复报错
        
        # 检查2: 如果有期号但无卷号,属于格式不完整
        if issue and not volume:
            errors.append(ValidationError(
                error_type="J.L3.01",
                severity="info",
                message=UNIFIED_MESSAGE,
                suggestion=f"有期号但缺少卷号。{UNIFIED_SUGGESTION}"
            ))
            return errors
        
        # 检查3: 如果既无卷号也无期号,但是期刊文献,可能有问题
        if not volume and not issue and publish_year:
            # 这种情况下检查原文是否符合简化格式
            if not re.search(r'\d{4}[,\s]+\d+\s*:', original_ref):
                errors.append(ValidationError(
                    error_type="J.L3.01",
                    severity="info",
                    message=UNIFIED_MESSAGE,
                    suggestion=UNIFIED_SUGGESTION
                ))
                return errors
        
        # 🆕 简化LLM判断逻辑：只要journal_format_valid不是True，就报同样的错误
        # 消除False和None的区别，避免LLM波动导致消息不一致
        if journal_format_valid is False or journal_format_valid is None:
            # 放宽检查：允许逗号、冒号、括号前后有更多空格
            # 使用备用正则检查确认是否真的不规范
            journal_patterns = [
                r'\d{4}\s*,\s*\d+\s*\(\s*\d+\s*\)\s*:\s*\d+(-\d+)?',  # 2023, 45(3): 10-15
                r'\d{4}\s*,\s*\d+\s*:\s*\d+(-\d+)?',                  # 2022, 183: 109119
                r'\d{4}\s*,\s*\d+\s*\(\s*\d+\s*\)\s*:\s*\d+',        # 2022, 400(10367): 1907
            ]
            
            if not any(re.search(pattern, original_ref) for pattern in journal_patterns):
                # 宽松检查：至少包含年份和数字信息
                if not re.search(r'\d{4}.*\d+', original_ref):
                    errors.append(ValidationError(
                        error_type="J.L3.01",
                        severity="info",
                        message=UNIFIED_MESSAGE,
                        suggestion=UNIFIED_SUGGESTION
                    ))
        # 如果 journal_format_valid 为 True，则不报错
        # 已放宽：允许格式中的标点符号前后有更多空格
        return errors

    def validate_n_l3_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """N.L3.01: 报纸的出版日期和版次格式不规范。"""
        if not self._check_doc_type(parsed_ref, "N"):
            return []
        
        if not re.search(r'\d{4}-\d{2}-\d{2}\(\d+\)', original_ref):
            return [ValidationError(
                error_type="N.L3.01",
                severity="info",
                message="报纸的出版日期和版次格式不规范。",
                suggestion="请检查是否符合 'YYYY-MM-DD(版次)' 的标准格式, 例如 '2023-01-01(2)'。"
            )]
        return []

    def validate_a_l3_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:

        """A.L3.01: 析出文献与其出处文献的分隔符使用错误。"""
        errors = []
        
        # 检查是否为析出文献（同时有析出题名和出处题名）
        analytical_title = parsed_ref.get("analytical_title") or parsed_ref.get("title")
        host_title = parsed_ref.get("monograph_title") or parsed_ref.get("host_title") or parsed_ref.get("journal")
        doc_type = parsed_ref.get("document_type", "")
        
        if analytical_title and host_title and analytical_title != host_title:
            # 专著中的析出文献应使用"//"
            if doc_type == "M" and "//" not in original_ref:
                errors.append(ValidationError(
                    error_type="A.L3.01",
                    severity="info",
                    message="析出文献与其出处文献的分隔符使用错误。",
                    suggestion="专著中的析出文献应在出处项前使用\"//\"分隔符，格式如：析出文献题名//专著题名"
                ))
            # 期刊中的析出文献检查格式（放宽空格检查）
            elif doc_type == "J":
                # 放宽检查：允许[J]和.之间有任意空格
                title_escaped = re.escape(analytical_title[:30] if len(analytical_title) > 30 else analytical_title)
                # 修改正则：允许[J]前后、.前后有0个或多个空格
                if not re.search(rf'{title_escaped}\s*\[J\]\s*\.', original_ref, re.IGNORECASE):
                    if "[J]" not in original_ref.upper():
                        errors.append(ValidationError(
                            error_type="A.L3.01",
                            severity="info",
                            message="析出文献与其出处文献的分隔符使用错误。",
                            suggestion="期刊文献格式应为：作者.题名[J].期刊名,年,卷(期):页码"
                        ))
                # 删除对空格数量的严格要求
        
        return errors



    def validate_p_l3_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """P.L3.01: 专利公告日期格式不正确，应为YYYY-MM-DD"""
        errors = []
        
        doc_type = parsed_ref.get("document_type", "")
        
        if "P" in doc_type or "专利" in original_ref:
            # 检查公告日期字段
            publication_date = parsed_ref.get("publication", {}).get("date") if isinstance(parsed_ref.get("publication"), dict) else None
            if not publication_date:
                # 尝试其他可能的日期字段
                publication_date = parsed_ref.get("date") or parsed_ref.get("publication_date")
            
            if publication_date:
                # 检查日期格式是否为 YYYY-MM-DD
                if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(publication_date)):
                    errors.append(ValidationError(
                        error_type="P.L3.01",
                        severity="info",
                        message='专利公告日期格式不正确，应为YYYY-MM-DD。',
                        suggestion='专利公告日期应使用YYYY-MM-DD格式，例如：2023-05-15。'
                    ))
        
        return errors

    def validate_p_l3_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """P.L3.02: 专利文献的专利号与题名之间的分隔符不是":"。"""
        errors = []
        
        doc_type = parsed_ref.get("document_type", "")
        patent_number = parsed_ref.get("patent_number")
        title = parsed_ref.get("title")
        
        if ("P" in doc_type or "专利" in original_ref) and patent_number and title:
            # 放宽检查：允许冒号前后有任意空格
            # 查找可能的专利号模式
            patent_patterns = [patent_number]
            if patent_number:
                patent_patterns.append(patent_number.replace(" ", ""))
            
            found_colon_separator = False
            for pattern in patent_patterns:
                if pattern and ":" in original_ref:
                    # 放宽检查：允许冒号前后有0个或多个空格
                    if re.search(rf':\s*{re.escape(pattern)}', original_ref):
                        found_colon_separator = True
                        break
            
            if not found_colon_separator:
                errors.append(ValidationError(
                    error_type="P.L3.02",
                    severity="info",
                    message='专利文献的专利号与题名之间的分隔符不是":"。',
                    suggestion='专利题名和专利号之间应使用冒号分隔。'
                ))
            # 已经放宽：不检查空格数量
        
        return errors

    def validate_g_l2_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """G.L2.01: 无法将参考文献解析为标准著录项目。"""
        errors = []
        
        # 检查LLM解析结果的完整性
        essential_fields = ["title"]  # 最基本的必需字段
        missing_fields = []
        
        for field in essential_fields:
            if not parsed_ref.get(field):
                missing_fields.append(field)
        
        # 如果连基本字段都没有，说明LLM解析失败
        if missing_fields:
            errors.append(ValidationError(
                error_type="G.L2.01",
                message="无法将参考文献解析为标准著录项目（主要责任者、题名、出版项等）。",
                suggestion="请检查参考文献格式是否符合GB/T 7714-2015标准，确保包含必要的著录项目。"
            ))
        
        return errors

    # === 新增辅助方法 ===
    def _is_electronic_resource(self, reference: str) -> bool:
        """检查是否为电子资源"""
        return "/OL" in reference or any(
            pattern in reference.upper() for pattern in ["HTTP://", "HTTPS://", "DOI:", "URL:"]
        )
        """根据文献类型生成GB/T 7714-2015标准格式模板"""
        
        # 获取基本信息
        authors = parsed_ref.get("authors", [])
        title = parsed_ref.get("title", "")
        year = parsed_ref.get("publish_year", "")
        
        # 处理作者格式
        author_str = ""
        if authors:
            if len(authors) <= 3:
                author_str = ", ".join(authors)
            else:
                author_str = ", ".join(authors[:3]) + ", et al"
        
        # 根据文献类型生成标准格式
        if doc_type == "J":  # 期刊文章
            return self._generate_journal_template(parsed_ref, author_str, title, year)
        elif doc_type == "M":  # 专著
            return self._generate_monograph_template(parsed_ref, author_str, title, year)
        elif doc_type in ["A", "C"]:  # 会议论文/论文集
            return self._generate_conference_template(parsed_ref, author_str, title, year)
        elif doc_type == "D":  # 学位论文
            return self._generate_dissertation_template(parsed_ref, author_str, title, year)
        elif doc_type == "P":  # 专利
            return self._generate_patent_template(parsed_ref, author_str, title, year)
        elif doc_type == "S":  # 标准
            return self._generate_standard_document_template(parsed_ref, author_str, title, year)
        elif doc_type == "R":  # 报告
            return self._generate_report_template(parsed_ref, author_str, title, year)
        elif doc_type == "N":  # 报纸
            return self._generate_newspaper_template(parsed_ref, author_str, title, year)
        else:
            return ""

    def _generate_journal_template(self, parsed_ref: Dict, author_str: str, title: str, year: str) -> str:
        """生成期刊文章标准模板：主要责任者. 题名[J]. 刊名, 年, 卷(期): 页码."""
        journal = parsed_ref.get("journal", "")
        volume = parsed_ref.get("volume", "")
        issue = parsed_ref.get("issue", "")
        pages = parsed_ref.get("pages", "")
        
        template = f"{author_str}. {title}[J]. {journal}"
        
        if year:
            template += f", {year}"
            
        if volume:
            if issue:
                template += f", {volume}({issue})"
            else:
                template += f", {volume}"
        elif issue:
            template += f", ({issue})"
            
        if pages:
            template += f": {pages}"
            
        template += "."
        return template

    def _generate_monograph_template(self, parsed_ref: Dict, author_str: str, title: str, year: str) -> str:
        """生成专著标准模板：主要责任者. 题名[M]. 版本项. 出版地: 出版者, 出版年: 页码."""
        edition = parsed_ref.get("edition", "")
        place = parsed_ref.get("publish_place", "")
        publisher = parsed_ref.get("publisher", "")
        pages = parsed_ref.get("pages", "")
        
        template = f"{author_str}. {title}[M]"
        
        if edition:
            template += f". {edition}"
        
        if place and publisher:
            template += f". {place}: {publisher}"
        elif publisher:
            template += f". {publisher}"
            
        if year:
            template += f", {year}"
            
        if pages:
            template += f": {pages}"
            
        template += "."
        return template

    def _generate_conference_template(self, parsed_ref: Dict, author_str: str, title: str, year: str) -> str:
        """生成会议论文标准模板：主要责任者. 题名[A]. 会议名, 会议地点, 会议日期[C]. 出版地: 出版者, 出版年: 页码."""
        # 会议名可能在多个字段中
        conference = parsed_ref.get("conference_name", "") or parsed_ref.get("conference", "") or parsed_ref.get("host_title", "")
        conference_location = parsed_ref.get("conference_location", "")
        conference_date = parsed_ref.get("conference_date", "")
        place = parsed_ref.get("publish_place", "")
        publisher = parsed_ref.get("publisher", "")
        pages = parsed_ref.get("pages", "")
        
        template = f"{author_str}. {title}[A]"
        
        if conference:
            template += f". {conference}"
            # 添加会议地点和日期（如果有）
            conference_info = []
            if conference_location:
                conference_info.append(conference_location)
            if conference_date:
                conference_info.append(conference_date)
            if conference_info:
                template += f", {', '.join(conference_info)}"
            template += "[C]"
        
        if place and publisher:
            template += f". {place}: {publisher}"
        elif publisher:
            template += f". {publisher}"
            
        if year:
            template += f", {year}"
            
        if pages:
            template += f": {pages}"
            
        template += "."
        return template

    def _generate_dissertation_template(self, parsed_ref: Dict, author_str: str, title: str, year: str) -> str:
        """生成学位论文标准模板：作者. 题名[D]. 学位授予单位, 年份."""
        institution = parsed_ref.get("institution", "") or parsed_ref.get("publisher", "")
        
        template = f"{author_str}. {title}[D]"
        
        if institution:
            template += f". {institution}"
            
        if year:
            template += f", {year}"
            
        template += "."
        return template

    def _generate_patent_template(self, parsed_ref: Dict, author_str: str, title: str, year: str) -> str:
        """生成专利标准模板：专利申请者. 题名: 专利号[P]. 公告日期."""
        patent_number = parsed_ref.get("patent_number", "")
        
        template = f"{author_str}. {title}"
        
        if patent_number:
            template += f": {patent_number}[P]"
        else:
            template += "[P]"
            
        if year:
            template += f". {year}"
            
        template += "."
        return template

    def _generate_standard_document_template(self, parsed_ref: Dict, author_str: str, title: str, year: str) -> str:
        """生成标准文献模板：标准编号, 标准名称[S]. 出版地: 出版者, 年份."""
        standard_number = parsed_ref.get("standard_number", "")
        place = parsed_ref.get("publish_place", "")
        publisher = parsed_ref.get("publisher", "")
        
        template = ""
        
        if standard_number:
            template = f"{standard_number}, {title}[S]"
        else:
            template = f"{author_str}. {title}[S]"
        
        if place and publisher:
            template += f". {place}: {publisher}"
        elif publisher:
            template += f". {publisher}"
            
        if year:
            template += f", {year}"
            
        template += "."
        return template

    def _generate_report_template(self, parsed_ref: Dict, author_str: str, title: str, year: str) -> str:
        """生成报告文献模板：主要责任者. 题名: 报告编号[R]. 出版地: 出版者, 年份."""
        report_number = parsed_ref.get("report_number", "")
        place = parsed_ref.get("publish_place", "")
        publisher = parsed_ref.get("publisher", "")
        
        template = f"{author_str}. {title}"
        
        # 报告编号（如果有）
        if report_number:
            template += f": {report_number}"
        
        template += "[R]"
        
        # 出版信息
        if place and publisher:
            template += f". {place}: {publisher}"
        elif publisher:
            template += f". {publisher}"
            
        if year:
            template += f", {year}"
            
        template += "."
        return template

    def _generate_newspaper_template(self, parsed_ref: Dict, author_str: str, title: str, year: str) -> str:
        """生成报纸文献模板：主要责任者. 题名[N]. 报纸名, 出版日期(版次)."""
        newspaper = parsed_ref.get("journal", "")  # 报纸名使用journal字段
        newspaper_date = parsed_ref.get("newspaper_date", "")
        newspaper_edition = parsed_ref.get("newspaper_edition", "")
        
        template = f"{author_str}. {title}[N]"
        
        if newspaper:
            template += f". {newspaper}"
        
        # 报纸日期和版次
        if newspaper_date:
            template += f", {newspaper_date}"
            if newspaper_edition:
                template += f"({newspaper_edition})"
        
        template += "."
        return template

    def _check_bilingual_format(self, reference: str) -> List[ValidationError]:
        """检查双语著录格式"""
        warnings = []
        
        # 检测中英文混合
        has_chinese = bool(re.search(r'[\u4e00-\u9fa5]', reference))
        has_english = bool(re.search(r'[a-zA-Z]', reference))
        
        if has_chinese and has_english:
            # 排除常见的非双语情况
            # 移除文献类型标识符和常见符号
            cleaned_ref = re.sub(r'\[[A-Z]+(?:/[A-Z]+)?\]', '', reference)  # 移除 [J], [M], [C], [D/OL] 等
            cleaned_ref = re.sub(r'[.\-:,\s\d()\[\]/]+', ' ', cleaned_ref)  # 移除标点符号和数字
            
            # 重新检查清理后的文本
            has_chinese_content = bool(re.search(r'[\u4e00-\u9fa5]', cleaned_ref))
            has_english_content = bool(re.search(r'[a-zA-Z]{2,}', cleaned_ref))  # 至少2个连续字母才算英文内容
            
            # 只有真正包含中英文实质内容的才报告为双语著录
            if has_chinese_content and has_english_content:
                # 进一步检查：如果英文部分只是DOI、URL等标识符，也不算双语著录
                english_parts = re.findall(r'[a-zA-Z]{2,}[a-zA-Z\s]*', cleaned_ref)
                meaningful_english = any(
                    len(part.strip()) > 3 and not re.match(r'^(DOI|URL|HTTP|HTTPS|WWW|ORG|COM|NET|EDU)$', part.strip().upper())
                    for part in english_parts
                )
                
                if meaningful_english:
                    warnings.append(ValidationError(
                        error_type="bilingual_format_check",
                        message="检测到中英文混合著录，请确认格式符合双语著录要求",
                        severity="info",
                        suggestion="参考标准6.1双语著录规则"
                    ))
        
        return warnings

    def _detect_document_type(self, reference: str) -> Optional[str]:
        """检测文献类型（增强版）"""
        # 按优先级检测文献类型
        type_priority = [
            ('electronic_monograph', r'\[M/(?:CD|DK|MT|OL)\]'),
            ('electronic_journal', r'\[J/(?:CD|DK|MT|OL)\]'),
            ('electronic_database', r'\[DB/(?:CD|DK|MT|OL)\]'),
            ('electronic_bulletin', r'\[EB/(?:CD|DK|MT|OL)\]'),
            ('electronic_program', r'\[CP/(?:CD|DK|MT|OL)\]'),
            ('monograph', r'\[M\]'),
            ('journal', r'\[J\]'),
            ('conference', r'\[C\]'),
            ('dissertation', r'\[D\]'),
            ('report', r'\[R\]'),
            ('standard', r'\[S\]'),
            ('patent', r'\[P\]'),
            ('newspaper', r'\[N\]'),
            ('archive', r'\[A\]'),
            ('cartographic', r'\[CM\]'),
            ('dataset', r'\[DS\]'),
            ('electronic_document', r'\[OL\]'),
            ('other', r'\[Z\]')
        ]
        
        for doc_type, pattern in type_priority:
            if re.search(pattern, reference):
                # 提取具体的类型标识
                match = re.search(r'\[([A-Z]+(?:/[A-Z]+)?)\]', reference)
                return match.group(1) if match else doc_type.upper()
        
        return None

    def _normalize_author_name(self, author: str) -> str:
        """规范化作者姓名：Unicode标准化和空白字符处理"""
        if not author:
            return ""
        
        # Unicode标准化 (NFKC: 兼容性组合)
        author = unicodedata.normalize('NFKC', author)
        
        # 清理各种空白字符为普通空格，包括不间断空格
        author = re.sub(r'[\s\u00A0\u2000-\u200B\u2028\u2029\u202F\u205F\u3000\uFEFF]+', ' ', author)
        
        # 去除首尾空格
        author = author.strip()
        
        return author
        
        # 去除首尾空格
        author = author.strip()
        
        return author

    def _calculate_confidence(self, errors: List[ValidationError], warnings: List[ValidationError], reference: str) -> float:
        """计算验证置信度"""
        base_score = 1.0
        
        # 错误扣分更多
        error_penalty = len(errors) * 0.3
        warning_penalty = len(warnings) * 0.1
        
        # 长度奖励（较长的参考文献通常更完整）
        length_bonus = min(len(reference) / 200, 0.2)
        
        confidence = max(0.0, base_score - error_penalty - warning_penalty + length_bonus)
        return min(1.0, confidence)

    # === 新增辅助方法 ===
    def _is_electronic_resource(self, reference: str) -> bool:
        """判断是否为电子资源"""
        return '/OL' in reference

    def _is_analytical_document(self, parsed_ref: Dict) -> bool:
        """判断是否为析出文献（专著中的章节）
        
        注意区分：
        - 析出文献(A): 专著中的章节，document_type="A"
        - 会议论文(C): 会议论文集中的论文，document_type="C"，虽然也有host_title但不是析出文献
        """
        doc_type = parsed_ref.get("document_type", "")
        
        # 明确判断：只有document_type为"A"才是析出文献
        if doc_type == "A":
            return True
        
        # 其他类型明确不是析出文献（包括会议论文C）
        return False

    # === 🆕 语义层面的错误检测 ===
    def validate_semantic_consistency(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """
        语义一致性检查：检测格式正确但内容错误的情况
        
        检测内容:
        1. 作者列表中缺失的"et al."或"等"（原文有但提取时遗漏）
        2. 从标题中错误提取的年份
        3. 标题包含期刊名的情况
        4. 字段间的逻辑一致性
        """
        errors = []
        
        # 🔍 检测1: 作者中遗漏的"et al."或"等"
        authors = parsed_ref.get("authors", "")
        if authors:
            # 检查原文是否有"et al."或"等"
            original_has_etal = bool(
                re.search(r'\bet\s+al\.?', original_ref, re.IGNORECASE) or 
                '等' in original_ref
            )
            
            # 检查提取结果是否包含
            extracted_has_etal = bool(
                re.search(r'\bet\s+al\.?', str(authors), re.IGNORECASE) or 
                '等' in str(authors)
            )
            
            if original_has_etal and not extracted_has_etal:
                errors.append(ValidationError(
                    error_type="G.L2.02",
                    message='作者字段提取不完整：原文包含"et al."或"等"但提取结果中缺失。',
                    severity="error",
                    suggestion='作者列表应保留"et al."或"等"，表示还有其他作者未列出。'
                ))
        
        # 🔍 检测2: 从标题中错误提取的年份
        title = parsed_ref.get("title", "")
        publish_year = parsed_ref.get("publish_year")
        
        if title and publish_year:
            # 检查标题中是否包含年份数字
            year_in_title = re.search(r'\b(19|20)\d{2}\b', title)
            if year_in_title:
                year_from_title = int(year_in_title.group())
                
                # 如果出版年份与标题中的年份相同，可能是错误提取
                if publish_year == year_from_title:
                    # 进一步验证：检查原文中年份的位置
                    # 如果原文在标题部分就有这个年份，可能是误提取
                    title_section_match = re.search(
                        r'^[^\[]*?\b' + str(publish_year) + r'\b',
                        original_ref
                    )
                    if title_section_match:
                        errors.append(ValidationError(
                            error_type="G.L2.04",
                            message=f"出版年份({publish_year})可能从标题中错误提取，而非从出版信息中提取。",
                            severity="info",
                            suggestion="请核对出版年份是否来自正确的位置（应从出版信息而非标题中提取）。"
                        ))
        
        # 🔍 检测3: 标题包含期刊名
        journal = parsed_ref.get("journal", "")
        if title and journal:
            # 检查标题是否包含期刊名（忽略大小写）
            if journal.lower() in title.lower():
                errors.append(ValidationError(
                    error_type="G.L2.03",
                    message=f"标题字段可能错误包含了期刊名: {journal}",
                    severity="info",
                    suggestion="标题应在期刊名之前结束，请核对标题是否被正确分割。"
                ))
        
        # 🔍 检测4: 期刊文献的年份、卷期、页码一致性
        doc_type = parsed_ref.get("document_type", "")
        if doc_type == "J":
            volume = parsed_ref.get("volume")
            issue = parsed_ref.get("issue")
            pages = parsed_ref.get("pages")
            
            # 如果有卷期但无页码，或有页码但无年份，可能存在问题
            if (volume or issue) and not pages:
                errors.append(ValidationError(
                    error_type="J.L3.01",
                    message="期刊文献有卷期信息但缺少页码，可能提取不完整。",
                    severity="info",
                    suggestion="请检查是否应该包含页码信息。"
                ))
            
            if pages and not publish_year:
                errors.append(ValidationError(
                    error_type="G.L2.04",
                    message="期刊文献有页码但缺少出版年份，信息不完整。",
                    severity="error",
                    suggestion="期刊文献应包含出版年份信息。"
                ))
        
        # 🔍 检测5: 析出文献必须有host_title和pages
        if doc_type == "A":
            host_title = parsed_ref.get("host_title")
            pages = parsed_ref.get("pages")
            
            if not host_title:
                errors.append(ValidationError(
                    error_type="A.L2.01",
                    message="析出文献缺少出处文献题名(host_title)。",
                    severity="error",
                    suggestion="析出文献必须标明其出处（如所在专著的书名）。"
                ))
            
            if not pages:
                errors.append(ValidationError(
                    error_type="A.L2.01",
                    message="析出文献缺少页码信息。",
                    severity="error",
                    suggestion="析出文献应标明在出处文献中的页码范围。"
                ))
        
        return errors

    # === 新增验证调度方法占位符 ===
    def validate_l2_rules(self, parsed_ref: Dict, reference: str) -> List[ValidationError]:
        """L2级规则验证调度：完整性检查（必备字段验证）"""
        errors = []
        doc_type = parsed_ref.get("document_type", "")
        
        # === 通用L2规则（所有文献类型共有的检查）===
        errors.extend(self.validate_g_l2_01(parsed_ref, reference))  # LLM解析完整性
        errors.extend(self.validate_g_l2_02(parsed_ref, reference))  # 主要责任者
        errors.extend(self.validate_g_l2_03(parsed_ref, reference))  # 题名  
        errors.extend(self.validate_g_l2_04(parsed_ref, reference))  # 出版年
        
        # === 特定文献类型L2规则（检查类型独有的必备字段）===
        
        # 专著(M)：出版地、出版者
        if doc_type == "M":
            errors.extend(self.validate_m_l2_01(parsed_ref, reference))  # 出版者
            errors.extend(self.validate_m_l2_02(parsed_ref, reference))  # 出版地
        
        # 期刊文章(J)：期刊名
        elif doc_type == "J":
            errors.extend(self.validate_j_l2_01(parsed_ref, reference))
        
        # 会议论文集(C)：出版者、出版地、出版年
        elif doc_type == "C":
            errors.extend(self.validate_c_l2_01(parsed_ref, reference))  # 出版者
            errors.extend(self.validate_c_l2_02(parsed_ref, reference))  # 出版地
            errors.extend(self.validate_c_l2_03(parsed_ref, reference))  # 出版年
        
        # 学位论文(D)：保存单位(学校)、出版地
        elif doc_type == "D":
            errors.extend(self.validate_d_l2_01(parsed_ref, reference))  # 保存单位
            errors.extend(self.validate_d_l2_02(parsed_ref, reference))  # 出版地
        
        # 报告(R)：出版者、出版地
        elif doc_type == "R":
            errors.extend(self.validate_r_l2_01(parsed_ref, reference))  # 出版者
            errors.extend(self.validate_r_l2_02(parsed_ref, reference))  # 出版地
        
        # 标准(S)：标准编号、出版地、出版者
        elif doc_type == "S":
            errors.extend(self.validate_s_l2_01(parsed_ref, reference))  # 标准编号
            errors.extend(self.validate_s_l2_02(parsed_ref, reference))  # 出版地
            errors.extend(self.validate_s_l2_03(parsed_ref, reference))  # 出版者
        
        # 专利(P)：专利号、公告日期
        elif doc_type == "P":
            errors.extend(self.validate_p_l2_01(parsed_ref, reference))  # 专利号
            errors.extend(self.validate_p_l2_02(parsed_ref, reference))  # 公告日期
        
        # 报纸(N)：报纸名
        elif doc_type == "N": 
            errors.extend(self.validate_n_l2_01(parsed_ref, reference))
        
        # 档案(Archive)：档案保存地、档案馆名
        elif doc_type == "Archive":
            errors.extend(self.validate_archive_l2_01(parsed_ref, reference))  # 档案保存地
            errors.extend(self.validate_archive_l2_02(parsed_ref, reference))  # 档案馆名称
        
        # === 跨类型L2规则（适用于多种文献类型）===
        
        # 析出文献(A)：出处文献题名、出版地、出版者、页码
        if self._is_analytical_document(parsed_ref):
            errors.extend(self.validate_a_l2_01(parsed_ref, reference))  # 出处文献题名
            errors.extend(self.validate_a_l2_02(parsed_ref, reference))  # 出版地
            errors.extend(self.validate_a_l2_03(parsed_ref, reference))  # 出版者
            errors.extend(self.validate_a_l2_04(parsed_ref, reference))  # 页码
        
        # 电子资源(/OL)：URL、引用日期
        if self._is_electronic_resource(reference):
            errors.extend(self.validate_e_l2_01(parsed_ref, reference))  # URL
            errors.extend(self.validate_e_l2_02(parsed_ref, reference))  # 引用日期
            
        return errors

    def validate_l3_rules(self, parsed_ref: Dict, reference: str) -> List[ValidationError]:
        """L3级规则验证调度"""
        errors = []
        doc_type = parsed_ref.get("document_type", "")
        
        # 通用L3规则 (G.L3.x)
        errors.extend(self.validate_g_l3_01(parsed_ref, reference))  # 作者超过3个未使用"等"
        errors.extend(self.validate_g_l3_02(parsed_ref, reference))  # 作者不足3个使用"等"
        errors.extend(self.validate_g_l3_03(parsed_ref, reference))  # 作者拼音格式
        errors.extend(self.validate_g_l3_04(parsed_ref, reference))  # 其他责任者格式
        errors.extend(self.validate_g_l3_05(parsed_ref, reference))  # 副标题格式
        errors.extend(self.validate_g_l3_06(parsed_ref, reference))  # 引文页码格式
        errors.extend(self.validate_g_l3_07(parsed_ref, reference))  # 标点符号格式
        
        # 专著L3规则 (M.L3.x)
        if doc_type == "M" or "专著" in reference:
            errors.extend(self.validate_m_l3_01(parsed_ref, reference))  # 版本信息格式
            errors.extend(self.validate_m_l3_02(parsed_ref, reference))  # 出版社格式
        
        # 学位论文L3规则 (D.L3.x)
        if doc_type == "D":
            errors.extend(self.validate_d_l3_01(parsed_ref, reference))  # 保存地与保存单位格式
        
        # 会议论文L3规则 (C.L3.x)
        if doc_type == "C":
            errors.extend(self.validate_c_l3_01(parsed_ref, reference))  # 会议论文格式
            errors.extend(self.validate_c_l3_03(parsed_ref, reference))  # 会议日期格式
            errors.extend(self.validate_c_l3_04(parsed_ref, reference))  # 会议名称建议
            errors.extend(self.validate_c_l3_05(parsed_ref, reference))  # 会议地点格式
            errors.extend(self.validate_c_l3_06(parsed_ref, reference))  # 页码建议
        
        # 会议论文析出文献L3规则 (C.L3.02)
        if doc_type == "A":
            errors.extend(self.validate_c_l3_02(parsed_ref, reference))  # 会议编者检查
            # 如果是会议论文析出，也检查会议地点和日期
            if parsed_ref.get("conference_name") or parsed_ref.get("host_title"):
                errors.extend(self.validate_c_l3_03(parsed_ref, reference))  # 会议日期格式
                errors.extend(self.validate_c_l3_05(parsed_ref, reference))  # 会议地点格式
        
        # 报告文献L3规则 (R.L3.x)
        if doc_type == "R":
            errors.extend(self.validate_r_l3_01(parsed_ref, reference))  # 报告编号格式
        
        # 析出文献L3规则 (A.L3.x)
        if doc_type in ["J", "M"] and "//" in reference:
            errors.extend(self.validate_a_l3_01(parsed_ref, reference))  # 析出文献分隔符
            errors.extend(self.validate_a_l3_02(parsed_ref, reference))  # 析出文献页码格式
        
        # 期刊L3规则 (J.L3.x)  
        if doc_type == "J":
            errors.extend(self.validate_j_l3_01(parsed_ref, reference))  # 期刊年卷期格式
            errors.extend(self.validate_j_l3_02(parsed_ref, reference))  # 期刊题名缩写
        
        # 报纸L3规则 (N.L3.x)
        if doc_type == "N":
            errors.extend(self.validate_n_l3_01(parsed_ref, reference))  # 报纸日期格式
            errors.extend(self.validate_n_l3_02(parsed_ref, reference))  # 报纸版次格式
        
        # 专利L3规则 (P.L3.x)
        if doc_type == "P" or "专利" in reference:
            errors.extend(self.validate_p_l3_01(parsed_ref, reference))  # 申请人题名分隔符
            errors.extend(self.validate_p_l3_02(parsed_ref, reference))  # 专利号题名分隔符
        
        # 标准文献L3规则 (S.L3.x)
        if doc_type == "S":
            errors.extend(self.validate_s_l3_01(parsed_ref, reference))  # 标准编号格式
        
        # 档案文献L3规则 (Archive.L3.x)
        if doc_type == "Archive":
            errors.extend(self.validate_archive_l3_01(parsed_ref, reference))  # 档案标识符
            errors.extend(self.validate_archive_l3_02(parsed_ref, reference))  # 档案号格式
        
        # 电子资源L3规则 (E.L3.x)
        if "/OL" in doc_type or "/OL" in reference:
            errors.extend(self.validate_e_l3_01(parsed_ref, reference))  # 电子资源引用日期格式
            errors.extend(self.validate_e_l3_02(parsed_ref, reference))  # 电子载体类型标识
        
        return errors

    # === 新增L1级验证方法占位符 ===
    def validate_g_l1_01(self, reference: str) -> List[ValidationError]:
        """G.L1.01: 文献类型标识检查 - 所有文献必备"""
        if not re.search(r'\[[A-Z/]+\]', reference):
            return [ValidationError(
                error_type="G.L1.01",
                message="参考文献缺少文献类型标识（如[M], [J]等）。",
                suggestion="请为参考文献添加正确的文献类型标识，例如：[M]代表专著，[J]代表期刊文章。"
            )]
        return []

    def validate_g_l1_02(self, reference: str) -> List[ValidationError]:
        """G.L1.02: DOI检查 - L1级规则，所有文献强制要求
        
        ⚠️ 这是L1级规则（最严格级别），所有参考文献都必须提供DOI！
        
        DOI检测支持多种格式：
        1. URL形式: https://doi.org/10.xxxx 或 https://dx.doi.org/10.xxxx
        2. 字段形式: DOI: 10.xxxx 或 doi: 10.xxxx
        3. 直接形式: 10.xxxx/xxx（嵌入在文献中）
        
        注意：本系统要求所有文献提供DOI以确保可追溯性和学术规范性。
        """
        # 检查URL中是否包含DOI（多种形式）
        url_contains_doi = re.search(r'https?://.*doi\.org', reference) or \
                          re.search(r'https?://dx\.doi\.org', reference)
        
        # 检查是否存在独立的DOI字段（多种格式）
        has_doi_field = re.search(r'DOI\s*[:\.]?\s*10\.\d+', reference, re.IGNORECASE) or \
                       re.search(r'\bdoi\s*[:\.]?\s*10\.\d+', reference, re.IGNORECASE)
        
        # 检查是否存在10.开头的DOI标识符（更宽松的检测）
        has_doi_pattern = re.search(r'10\.\d{4,}[/\.][\w\.\-]+', reference)
        
        if not url_contains_doi and not has_doi_field and not has_doi_pattern:
            return [ValidationError(
                error_type="G.L1.02",
                message="参考文献缺少必要的数字对象唯一标识符（DOI）。",
                suggestion="所有参考文献都应提供DOI。请添加DOI信息，格式如：DOI: 10.xxxx/xxxx 或在URL中包含doi.org链接。",
                severity="error"  # ⚠️ L1级规则，必须为error级别！
            )]
        return []

    def validate_e_l1_01(self, reference: str) -> List[ValidationError]:
        """E.L1.01: URL检查 - 仅电子资源必备"""
        if not re.search(r'https?://', reference):
            return [ValidationError(
                error_type="E.L1.01",
                message="电子资源缺少必要的获取和访问路径（URL）。",
                suggestion="对于联机网络资源（标识含/OL），必须提供URL。"
            )]
        return []

    def validate_e_l3_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """E.L3.01: 电子资源的引用日期格式不正确或未使用方括号"""
        errors = []
        
        doc_type = parsed_ref.get("document_type", "")
        # 检查是否为电子资源
        if "/OL" in doc_type or "[EB/OL]" in original_ref or "[DB/OL]" in original_ref or "[J/OL]" in original_ref:
            # 查找所有可能的日期结构
            potential_dates = re.findall(r'\[?(\d{4}-\d{1,2}-\d{1,2})\]?', original_ref)
            
            if not potential_dates:
                # 缺少日期的错误由其他规则处理，这里不报错
                return errors
            
            # 放宽检查：允许方括号前后有空格，接受YYYY-M-D或YYYY-MM-DD
            # 检查找到的日期是否被方括号括起（允许月日为1位或2位数字）
            if not re.search(r'\[\s*\d{4}-\d{1,2}-\d{1,2}\s*\]', original_ref):
                errors.append(ValidationError(
                    error_type="E.L3.01",
                    severity="info",
                    message="电子资源的引用日期格式不正确或未使用方括号。",
                    suggestion="请使用严格的[YYYY-MM-DD]格式，例如[2023-12-01]。"
                ))
        
        return errors

    def validate_e_l3_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """E.L3.02: 电子资源的载体类型标识不规范"""
        errors = []
        
        doc_type = parsed_ref.get("document_type", "")
        
        # 检查是否为电子资源
        if "/OL" not in doc_type and not re.search(r'\[([A-Z]+)/OL\]', original_ref):
            return errors
        
        # 常见的电子载体类型标识
        valid_carriers = [
            r'\[M/OL\]',     # 在线专著
            r'\[J/OL\]',     # 在线期刊文章
            r'\[EB/OL\]',    # 电子公告板
            r'\[DB/OL\]',    # 在线数据库
            r'\[CP/OL\]',    # 在线会议论文
            r'\[N/OL\]',     # 在线报纸
            r'\[S/OL\]',     # 在线标准
            r'\[P/OL\]',     # 在线专利
            r'\[A/OL\]',     # 在线档案
            r'\[G/OL\]',     # 在线汇编
            r'\[R/OL\]',     # 在线报告
            r'\[D/OL\]',     # 在线学位论文
            r'\[CD\]',       # 光盘
            r'\[MT\]',       # 磁带
            r'\[DK\]',       # 磁盘
        ]
        
        # 检查是否使用了有效的载体类型标识
        has_valid_carrier = any(re.search(pattern, original_ref) for pattern in valid_carriers)
        
        if not has_valid_carrier:
            # 检查是否有奇怪的格式
            strange_format = re.search(r'\[([A-Z]+)/([A-Z]+)\]', original_ref)
            if strange_format:
                carrier_type = strange_format.group(2)
                if carrier_type not in ['OL', 'CD', 'MT', 'DK']:
                    errors.append(ValidationError(
                        error_type="E.L3.02",
                        severity="info",
                        message=f"电子资源的载体类型标识\"{strange_format.group(0)}\"不规范。",
                        suggestion="请使用规范的载体类型标识，如[OL]（在线）、[CD]（光盘）、[MT]（磁带）、[DK]（磁盘）等。常见组合如[M/OL]、[J/OL]、[EB/OL]、[DB/OL]等。"
                    ))
        
        return errors

    # === P3规则：档案文献验证方法 ===
    def validate_archive_l2_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """Archive.L2.01: 档案文献必备字段检查（档案保存地）"""
        if not self._check_doc_type(parsed_ref, "Archive"):
            return []
        
        archive_location = parsed_ref.get("archive_location")
        
        if not archive_location:
            return [ValidationError(
                error_type="Archive.L2.01",
                message="档案文献缺少档案保存地。",
                suggestion="请补充档案保存地信息，如\"北京\"、\"南京\"等。"
            )]
        
        return []
    
    def validate_archive_l2_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """Archive.L2.02: 档案文献必备字段检查（档案馆名称）"""
        if not self._check_doc_type(parsed_ref, "Archive"):
            return []
        
        archive_holder = parsed_ref.get("archive_holder")
        
        if not archive_holder:
            return [ValidationError(
                error_type="Archive.L2.02",
                message="档案文献缺少档案馆名称。",
                suggestion="请补充档案馆名称，如\"中国第二历史档案馆\"、\"国家图书馆\"等。"
            )]
        
        return []

    def validate_archive_l3_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """Archive.L3.01: 档案文献标识符\"[A]\"缺失或位置不正确"""
        if not self._check_doc_type(parsed_ref, "Archive"):
            return []
        
        errors = []
        if not re.search(r'\[A\]', original_ref):
            errors.append(ValidationError(
                error_type="Archive.L3.01",
                severity="info",
                message="档案文献标识符\"[A]\"缺失。",
                suggestion="请在题名后添加档案文献标识符[A]。"
            ))
        else:
            # 检查位置是否正确（应该在题名之后，出版地之前）
            a_position = original_ref.find('[A]')
            if a_position > len(original_ref) * 0.8:  # 如果在后80%位置
                errors.append(ValidationError(
                    error_type="Archive.L3.01",
                    severity="info",
                    message="档案文献标识符\"[A]\"位置不正确。",
                    suggestion="[A]标识符应该紧跟在题名之后，而不是在参考文献末尾。"
                ))
        
        return errors

    def validate_archive_l3_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """Archive.L3.02: 档案文献的档案号格式不规范"""
        if not self._check_doc_type(parsed_ref, "Archive"):
            return []
        
        errors = []
        archive_number = parsed_ref.get("archive_number")
        
        if archive_number:
            # 档案号格式：数字-数字-数字 或 字母数字组合
            # 示例：3-2-317、1011-011-0019-002、A123-B456
            # 🔧 修复：确保archive_number是字符串类型
            archive_number_str = str(archive_number)
            if not re.match(r'^[A-Z0-9]+-[A-Z0-9]+-[A-Z0-9]+(-[A-Z0-9]+)*$', archive_number_str, re.IGNORECASE):
                errors.append(ValidationError(
                    error_type="Archive.L3.02",
                    severity="info",
                    message=f"档案号\"{archive_number}\"格式不规范。",
                    suggestion="档案号通常格式为\"数字-数字-数字\"或\"字母数字-数字-数字\"，如\"3-2-317\"、\"1011-011-0019-002\"。"
                ))
        
        return errors

    def validate_m_l2_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """M.L2.01: 专著必备字段检查（出版者）"""
        if not self._check_doc_type(parsed_ref, "M"):
            return []
        
        error = self._check_required_field(parsed_ref, "publisher", "M.L2.01", 
                                           "出版者", "请补充出版者信息，如：科学出版社、人民出版社等。")
        if error:
            return [error]
        return []
    
    def validate_m_l2_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """M.L2.02: 专著必备字段检查（出版地）"""
        if not self._check_doc_type(parsed_ref, "M"):
            return []
        
        error = self._check_required_field(parsed_ref, "publish_place", "M.L2.02",
                                           "出版地", "请补充出版地信息，如：北京、上海等。")
        if error:
            return [error]
        return []

    def validate_n_l2_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """N.L2.01: 报纸必备字段检查（报纸名）"""
        if not self._check_doc_type(parsed_ref, "N"):
            return []
        
        error = self._check_required_field(parsed_ref, "journal", "N.L2.01",
                                           "报纸名", "请补充报纸名信息。")
        return [error] if error else []

    def validate_p_l2_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """P.L2.01: 专利必备字段检查（专利号）"""
        if not self._check_doc_type(parsed_ref, "P"):
            return []
        
        error = self._check_required_field(parsed_ref, "patent_number", "P.L2.01",
                                           "专利号", "请补充专利号信息。")
        if error:
            return [error]
        return []
    
    def validate_p_l2_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """P.L2.02: 专利必备字段检查（公告日期）"""
        if not self._check_doc_type(parsed_ref, "P"):
            return []
        
        # 检查公告日期（可能在publish_year或publish_date字段）
        pub_date = parsed_ref.get("publish_year") or parsed_ref.get("publish_date")
        if not pub_date:
            return [ValidationError(
                error_type="P.L2.02",
                message="专利文献缺少公告日期。",
                suggestion="请补充专利公告日期。"
            )]
        
        return []

    # === 析出文献和电子资源L2检查（跨类型） ===
    
    def validate_a_l2_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """A.L2.01: 析出文献必备字段检查（出处文献题名）
        
        根据GB/T 7714-2015标准4.2.1，析出文献必须著录出处文献题名。
        """
        # 检查是否为析出文献
        if not self._is_analytical_document(parsed_ref):
            return []
        
        doc_type = parsed_ref.get("document_type", "")
        if doc_type != "A":
            return []
        
        error = self._check_required_field(parsed_ref, "host_title", "A.L2.01", 
                                           "出处文献题名", 
                                           "根据GB/T 7714-2015标准4.2.1，析出文献必须著录出处文献题名（专著名或会议论文集名）。")
        if error:
            return [error]
        return []
    
    def validate_a_l2_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """A.L2.02: 析出文献必备字段检查（出版地）
        
        根据GB/T 7714-2015标准4.2.1，析出文献必须著录出版地。
        """
        if not self._is_analytical_document(parsed_ref):
            return []
        
        doc_type = parsed_ref.get("document_type", "")
        if doc_type != "A":
            return []
        
        error = self._check_required_field(parsed_ref, "publish_place", "A.L2.02",
                                           "出版地", 
                                           "根据GB/T 7714-2015标准4.2.1，析出文献必须著录出版地。请补充出版地信息，如：北京、上海等。")
        if error:
            return [error]
        return []
    
    def validate_a_l2_03(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """A.L2.03: 析出文献必备字段检查（出版者）
        
        根据GB/T 7714-2015标准4.2.1，析出文献必须著录出版者。
        """
        if not self._is_analytical_document(parsed_ref):
            return []
        
        doc_type = parsed_ref.get("document_type", "")
        if doc_type != "A":
            return []
        
        error = self._check_required_field(parsed_ref, "publisher", "A.L2.03",
                                           "出版者", 
                                           "根据GB/T 7714-2015标准4.2.1，析出文献必须著录出版者。请补充出版者信息，如：科学出版社、人民出版社等。")
        if error:
            return [error]
        return []
    
    def validate_a_l2_04(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """A.L2.04: 析出文献必备字段检查（页码）
        
        根据GB/T 7714-2015标准4.2.1，析出文献必须著录页码。
        """
        if not self._is_analytical_document(parsed_ref):
            return []
        
        doc_type = parsed_ref.get("document_type", "")
        if doc_type != "A":
            return []
        
        error = self._check_required_field(parsed_ref, "pages", "A.L2.04",
                                           "页码", 
                                           "根据GB/T 7714-2015标准4.2.1，析出文献必须著录页码。请补充页码范围（如：32-36）或起始页（如：112）。")
        if error:
            return [error]
        return []
    
    def validate_j_l2_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """J.L2.01: 期刊文章类型独有必备字段检查
        
        根据GB/T 7714-2015标准4.4，期刊文章必须包含：
        - 主要责任者 (authors) - 由G.L2.02通用检查
        - 题名 (title) - 由G.L2.03通用检查
        - 出版年 (publish_year) - 由G.L2.04通用检查
        - 期刊名 (journal) - **期刊文章独有**
        
        此函数只检查期刊文章独有的必备字段（加粗部分）。
        """
        if not self._check_doc_type(parsed_ref, "J"):
            return []
        
        error = self._check_required_field(parsed_ref, "journal", "J.L2.01",
                                           "期刊名", "请补充期刊名信息。")
        return [error] if error else []
    
    def validate_e_l2_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """E.L2.01: 电子资源必备字段检查（URL）"""
        if not self._is_electronic_resource(original_ref):
            return []
        
        error = self._check_required_field(parsed_ref, "url", "E.L2.01",
                                           "获取和访问路径（URL）", 
                                           "根据GB/T 7714-2015标准4.6，电子资源必须提供URL。请补充完整的网址。")
        if error:
            return [error]
        return []
    
    def validate_e_l2_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """E.L2.02: 电子资源必备字段检查（引用日期）"""
        if not self._is_electronic_resource(original_ref):
            return []
        
        # 检查引用日期（需要特殊处理格式）
        if not parsed_ref.get("access_date"):
            if not re.search(r'\[\d{4}-\d{1,2}-\d{1,2}\]', original_ref):
                return [ValidationError(
                    error_type="E.L2.02",
                    message="电子资源缺少引用日期。",
                    suggestion="根据GB/T 7714-2015标准4.6，电子资源必须著录引用日期。请添加引用日期，格式为[YYYY-MM-DD]，如[2023-12-01]。"
                )]
        
        return []
    
    def validate_d_l2_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """D.L2.01: 学位论文必备字段检查（保存单位/学校）"""
        if not self._check_doc_type(parsed_ref, "D"):
            return []
        
        error = self._check_required_field(parsed_ref, "school", "D.L2.01", 
                                           "保存单位（学校）", "请补充学位论文所在学校，如：清华大学、北京大学等。")
        if error:
            return [error]
        return []
    
    def validate_d_l2_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """D.L2.02: 学位论文必备字段检查（出版地）"""
        if not self._check_doc_type(parsed_ref, "D"):
            return []
        
        error = self._check_required_field(parsed_ref, "publish_place", "D.L2.02",
                                           "出版地", "请补充出版地信息，通常与学校所在地一致。")
        if error:
            return [error]
        return []
    
    def validate_s_l2_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """S.L2.01: 标准文献必备字段检查（标准编号）"""
        if not self._check_doc_type(parsed_ref, "S"):
            return []
        
        error = self._check_required_field(parsed_ref, "standard_number", "S.L2.01", 
                                           "标准编号", "请补充标准编号，如：GB/T 7714-2015。")
        if error:
            return [error]
        return []
    
    def validate_s_l2_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """S.L2.02: 标准文献必备字段检查（出版地）"""
        if not self._check_doc_type(parsed_ref, "S"):
            return []
        
        error = self._check_required_field(parsed_ref, "publish_place", "S.L2.02",
                                           "出版地", "请补充出版地信息，如：北京。")
        if error:
            return [error]
        return []
    
    def validate_s_l2_03(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """S.L2.03: 标准文献必备字段检查（出版者）"""
        if not self._check_doc_type(parsed_ref, "S"):
            return []
        
        error = self._check_required_field(parsed_ref, "publisher", "S.L2.03",
                                           "出版者", "请补充出版者信息，如：中国标准出版社。")
        if error:
            return [error]
        return []
    
    def validate_a_l3_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """A.L3.02: 析出文献的页码格式不规范"""
        errors = []
        
        # 检查是否为析出文献
        if self._is_analytical_document(parsed_ref):
            pages = parsed_ref.get("pages")
            
            if pages:
                # 放宽页码格式检查：允许常见变体
                # 正确格式：32-36, 112, 1-10, 32—36（长短横线都接受）
                # 允许格式：数字后可能有空格，连字符可以是-或—或–
                # 去除首尾空格后检查
                pages_clean = str(pages).strip()
                
                # 放宽检查：接受短横线(-)、长横线(—)、连接号(–)
                valid_page_pattern = r'^\d+\s*[-—–]\s*\d+$|^\d+$'
                
                if not re.match(valid_page_pattern, pages_clean):
                    errors.append(ValidationError(
                        error_type="A.L3.02",
                        severity="info",
                        message="析出文献的页码格式不规范。",
                        suggestion=f"页码格式应为纯数字或数字范围（如32-36或112），当前为：{pages}。不要使用p.、pp.、第等前缀。"
                    ))
                # 已放宽：接受不同类型的连字符和空格
        
        return errors
    
    def validate_g_l3_06(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """G.L3.06: 引文页码格式不规范
        
        根据GB/T 7714-2015标准8.5：
        - 阅读型参考文献：著录起讫页或起始页
        - 引文参考文献：著录引用信息所在页
        - 页码前使用":"分隔
        """
        errors = []
        
        pages = parsed_ref.get("pages")
        
        if pages:
            # 放宽检查：允许冒号前后有任意空格
            # 查找页码在原文中的位置及其前面的符号
            pages_str = str(pages).replace('-', r'[-\-—]')  # 兼容不同的连字符
            # 修改正则：允许冒号前后有0个或多个空格
            page_context = re.search(rf'([:.：])\s*{pages_str}', original_ref)
            
            if page_context:
                separator = page_context.group(1)
                # 只检查是否使用了冒号，不检查空格数量
                if separator not in [':', '：']:
                    errors.append(ValidationError(
                        error_type="G.L3.06",
                        severity="info",
                        message="引文页码格式不规范。",
                        suggestion=f"根据GB/T 7714-2015标准，页码前应使用\":\"分隔，当前使用了\"{separator}\"。"
                    ))
                # 删除对空格数量的检查
        
        return errors
    
    def validate_s_l3_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """S.L3.01: 标准编号格式不规范或位置不正确
        
        根据GB/T 7714-2015附录A.6：
        - 格式：GB/T 7714-2015 或 ISO 690:2010
        - 位置：在题名之后，用":"分隔
        """
        if not self._check_doc_type(parsed_ref, "S"):
            return []
        
        standard_number = parsed_ref.get("standard_number")
        if not standard_number:
            return []
        
        errors = []
        
        # 🔧 修复：确保standard_number是字符串类型
        standard_number_str = str(standard_number)
        
        # 检查标准编号格式
        # 常见格式：GB/T XXXXX-YYYY, ISO XXX:YYYY, GB XXXXX-YYYY
        valid_patterns = [
            r'^GB/T\s+\d+[.\d]*[-—]\d{4}$',  # GB/T 7714-2015
            r'^GB\s+\d+[.\d]*[-—]\d{4}$',     # GB 7714-2015
            r'^ISO\s+\d+:\d{4}$',              # ISO 690:2010
            r'^[A-Z]+/[A-Z]+\s+\d+[.\d]*[-—]\d{4}$'  # 其他标准
        ]
        
        is_valid_format = any(re.match(pattern, standard_number_str.strip(), re.IGNORECASE) 
                            for pattern in valid_patterns)
        
        if not is_valid_format:
            errors.append(ValidationError(
                error_type="S.L3.01",
                severity="info",
                message="标准编号格式不规范。",
                suggestion=f"标准编号格式应为：GB/T XXXXX-YYYY 或 ISO XXX:YYYY，当前为：{standard_number_str}。"
            ))
        
        # 检查标准编号在原文中的位置（应在题名之后）
        title = parsed_ref.get("title")
        if title:
            # 查找题名和标准编号在原文中的位置
            title_pos = original_ref.find(str(title))
            std_pos = original_ref.find(standard_number_str)
            
            if title_pos >= 0 and std_pos >= 0 and std_pos < title_pos:
                errors.append(ValidationError(
                    error_type="S.L3.01",
                    severity="info",
                            message="标准编号位置不正确。",
                            suggestion="标准编号应放在题名之后，用\":\"分隔。"
                        ))
        
        return errors

    def validate_d_l3_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """D.L3.01: 学位论文的保存地与保存单位格式不规范
        
        根据GB/T 7714-2015附录A.4：
        - 格式：[D]. 保存地：保存单位, 年份
        - 示例：北京：清华大学, 2020
        """
        if not self._check_doc_type(parsed_ref, "D"):
            return []
        
        school = parsed_ref.get("school")
        publish_place = parsed_ref.get("publish_place")
        
        if not (school and publish_place):
            return []
        
        # 🔧 修复：确保字段是字符串类型
        school_str = str(school)
        publish_place_str = str(publish_place)
        
        # 放宽检查：允许冒号前后有0个或多个空格（已经有\s*）
        # 检查原文中保存地和保存单位的分隔符
        # 应该是：保存地：保存单位（允许空格灵活）
        pattern = rf'{re.escape(publish_place_str)}\s*[:：]\s*{re.escape(school_str)}'
        
        if not re.search(pattern, original_ref):
            return [ValidationError(
                error_type="D.L3.01",
                severity="info",
                message="学位论文的保存地与保存单位格式不规范。",
                suggestion=f"格式应为：{publish_place}：{school}。保存地与保存单位之间应使用冒号分隔。"
            )]
        # 已放宽：允许冒号前后任意空格
        
        return []
    
    def validate_g_l3_04(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """G.L3.04: 其他责任者著录不规范
        
        根据GB/T 7714-2015标准4.1.1：
        - 其他责任者（任选）：译者、编者、注释者、校对者等
        - 格式：", 译" 或 "edited by" 等
        - 示例：谢远涛, 译 / 张三, 李四, 译 / translated by John Smith
        
        注意：
        1. 此字段由LLM解析，如果LLM未正确提取，可能漏检。
        2. 会议论文集的编者（conference_editors）不应该在这里检查。
        """
        errors = []
        
        other_contributors = parsed_ref.get("other_contributors")
        doc_type = parsed_ref.get("document_type", "")
        
        # 🔧 优化：如果是会议论文且有conference_editors字段，跳过检查
        # 因为会议论文集的编者不属于"其他责任者"
        conference_editors = parsed_ref.get("conference_editors")
        if doc_type == "A" and conference_editors and not other_contributors:
            # 这是正常情况：会议论文析出文献有编者但没有其他责任者
            return errors
        
        if other_contributors:
            # 🔧 优化：排除误将会议编者放入other_contributors的情况
            # 如果格式像"Burstein J, Doran C, Solorio T."（纯姓名列表，无角色标识），
            # 且是会议论文，则判定为LLM误解析，给出提示性错误而非严重错误
            if doc_type == "A" and conference_editors is None:
                # 检查是否为纯姓名列表（无"译"、"编"等角色标识）
                role_keywords = ['译', '编', '注', '校', 'translated', 'edited', 'annotated', 'trans.', 'ed.']
                has_role = any(keyword in other_contributors for keyword in role_keywords)
                
                if not has_role:
                    errors.append(ValidationError(
                        error_type="G.L3.04",
                        message="疑似将会议论文集编者误标记为其他责任者。",
                        severity="info",
                        suggestion=f"当前other_contributors为：{other_contributors}，看起来像是会议论文集的编者而非译者/注释者。如果是会议编者，应放入conference_editors字段。"
                    ))
                    return errors
            
            # 检查其他责任者的格式
            # 中文格式：姓名, 译 / 姓名, 编 / 姓名1, 姓名2, 译
            # 英文格式：translated by XXX / edited by XXX
            
            valid_patterns = [
                # 中文格式 - 支持多个责任者
                r'^[一-龥]{2,4}(,\s*[一-龥]{2,4})*,\s*[译编注校]$',  # 纯中文姓名
                r'^[A-Z][a-z]+\s+[A-Z]\.(,\s*[A-Z][a-z]+\s+[A-Z]\.)*,\s*[译编注校]$',  # 拼音格式
                r'^[A-Z]+\s+[A-Z]\.(,\s*[A-Z]+\s+[A-Z]\.)*,\s*[译编注校]$',  # 全大写姓氏拼音
                r'.+,\s*[译编注校]',  # 宽松匹配 - 任意姓名 + 角色
                
                # 英文格式
                r'^translated by\s+[A-Z][a-z]+(\s+[A-Z]\.)?(\s+[A-Z][a-z]+)?$',  # translated by
                r'^edited by\s+[A-Z][a-z]+(\s+[A-Z]\.)?(\s+[A-Z][a-z]+)?$',      # edited by
                r'^annotated by\s+[A-Z][a-z]+(\s+[A-Z]\.)?(\s+[A-Z][a-z]+)?$',   # annotated by
                
                # 缩写形式
                r'^.+,\s+trans\.$',    # 译者缩写
                r'^.+,\s+ed\.$',       # 编者缩写
                r'^.+,\s+annot\.$'     # 注释者缩写
            ]
            
            is_valid = False
            for pattern in valid_patterns:
                if re.search(pattern, other_contributors.strip(), re.IGNORECASE):
                    is_valid = True
                    break
            
            if not is_valid:
                # 检查是否至少包含角色关键词
                role_keywords = ['译', '编', '注', '校', 'translated', 'edited', 'annotated', 'trans.', 'ed.']
                has_role = any(keyword in other_contributors for keyword in role_keywords)
                
                if has_role:
                    # 包含角色但格式可能不规范
                    errors.append(ValidationError(
                        error_type="G.L3.04",
                        message="其他责任者著录格式可能不规范。",
                        severity="info",  # 降级为info
                        suggestion=f"其他责任者格式应为：\"姓名, 译\"或\"translated by 姓名\"等。当前为：{other_contributors}。请人工核对。"
                    ))
                else:
                    # 完全不符合格式
                    errors.append(ValidationError(
                        error_type="G.L3.04",
                        severity="info",
                        message="其他责任者著录不规范，缺少角色标识。",
                        suggestion=f"其他责任者应包含角色标识（如：译、编、注、校、translated by等）。当前为：{other_contributors}。"
                    ))
        
        return errors
    
    def validate_g_l3_05(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """G.L3.05: 题名中的其他题名信息（副标题）格式不规范
        
        根据GB/T 7714-2015标准4.1.1和第7章：
        - 其他题名信息（副标题）
        - 分隔符：": "（英文冒号+空格）
        - 示例：国史旧闻：第1卷
        """
        errors = []
        
        title = parsed_ref.get("title")
        
        if title and ("：" in title or ":" in title):
            # 检查副标题的分隔符格式
            # 应该是": "（冒号后有空格）或"："（中文冒号）
            
            # 检查是否使用了不规范的格式
            # 错误格式：:（无空格）、 : （前后都有空格）
            if re.search(r'[^：]:(?!\s)', title):  # 英文冒号后没有空格
                errors.append(ValidationError(
                    error_type="G.L3.05",
                    severity="info",
                    message="题名中的其他题名信息（副标题）格式不规范。",
                    suggestion="副标题前应使用\": \"（英文冒号+空格）或\"：\"（中文冒号）分隔。当前题名冒号后缺少空格。"
                ))
        
        return errors
    
    def validate_j_l3_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """J.L3.02: 期刊题名缩写不符合ISO 4规范
        
        根据GB/T 7714-2015标准引用ISO 4：
        - 期刊题名可使用标准缩写
        - 但需符合ISO 4规范
        - 常见错误：不规范的缩写、缺少缩写点等
        
        注意：这是一个启发式检查，不能完全验证ISO 4符合性
        """
        if not self._check_doc_type(parsed_ref, "J"):
            return []
        
        journal = parsed_ref.get("journal")
        if not journal:
            return []
        
        # 启发式检查：如果期刊名看起来是缩写但格式不规范
        # 缩写特征：含有大写字母缩写、较短
        
        # 检查是否包含明显的缩写词（连续大写字母）
        has_abbreviation = re.search(r'\b[A-Z]{2,}\b', journal)
        
        if not has_abbreviation:
            return []
        
        # 检查缩写词后是否有缩写点
        # ISO 4规范：缩写词通常应该有点（但也有例外，如IEEE）
        abbrev_words = re.findall(r'\b[A-Z]{2,}\b', journal)
        
        for abbrev in abbrev_words:
            # 检查这个缩写词在原文中是否后跟点号
            if abbrev not in ['IEEE', 'ACM', 'USA', 'UK', 'DNA', 'RNA']:  # 常见的不需要点的缩写
                # 在原文中查找这个缩写
                abbrev_pattern = rf'{re.escape(abbrev)}(?!\.|[A-Z])'
                if re.search(abbrev_pattern, original_ref):
                    # 找到了没有点号的缩写，给出建议性提示
                    return [ValidationError(
                        error_type="J.L3.02",
                        message="期刊题名缩写可能不符合ISO 4规范。",
                        severity="info",  # 这是一个提示性信息
                        suggestion=f"期刊题名中的缩写\"{abbrev}\"可能需要添加缩写点。请参考ISO 4标准确认期刊题名的正确缩写格式。常见期刊缩写可在PubMed或Web of Science查询。"
                    )]
        
        return []

    def validate_c_l2_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """C.L2.01: 会议论文集缺少出版者信息
        
        根据GB/T 7714-2015标准4.1，会议论文集[C]按专著著录，出版者是必备字段。
        """
        if not self._check_doc_type(parsed_ref, "C"):
            return []
        
        error = self._check_required_field(parsed_ref, "publisher", "C.L2.01",
                                           "出版者", "请补充出版者信息，如：科学出版社、Springer等。")
        if error:
            return [error]
        return []
    
    def validate_c_l2_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """C.L2.02: 会议论文集缺少出版地信息
        
        根据GB/T 7714-2015标准4.1，会议论文集[C]按专著著录，出版地是必备字段。
        """
        if not self._check_doc_type(parsed_ref, "C"):
            return []
        
        error = self._check_required_field(parsed_ref, "publish_place", "C.L2.02",
                                           "出版地", "请补充出版地信息，如：北京、上海、New York等。")
        if error:
            return [error]
        return []
    
    def validate_c_l2_03(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """C.L2.03: 会议论文集缺少年份信息
        
        根据GB/T 7714-2015标准4.1，会议论文集[C]按专著著录，出版年是必备字段。
        """
        if not self._check_doc_type(parsed_ref, "C"):
            return []
        
        has_year = parsed_ref.get("publish_year") or parsed_ref.get("conference_date")
        if not has_year:
            return [ValidationError(
                error_type="C.L2.03",
                message="会议论文缺少年份信息。",
                suggestion="请补充会议召开年份或论文发表年份。"
            )]
        return []
        
        return errors
    
    def validate_c_l3_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """C.L3.01: 会议论文格式不规范
        
        根据GB/T 7714-2015标准，会议论文有两种格式：
        1. 纯会议论文: [C]//会议名称  (需要"//"分隔符)
        2. 会议析出文献: [A]...会议论文集[C]  (不需要"//"分隔符)
        """
        if not self._check_doc_type(parsed_ref, "C"):
            return []
        
        errors = []
        
        # 检查是否是会议析出文献格式 [A]...[C]
        has_a_tag = "[A]" in original_ref or "[a]" in original_ref
        has_c_tag = "[C]" in original_ref or "[c]" in original_ref
        
        # 如果没有[A]标识,说明是纯会议论文,需要检查"//"分隔符
        if not has_a_tag and has_c_tag:
            if "//" not in original_ref:
                errors.append(ValidationError(
                    error_type="C.L3.01",
                    severity="info",
                    message="会议论文格式不规范，缺少\"//\"分隔符。",
                    suggestion="会议论文应使用\"//\"将析出文献题名与会议名称分隔，格式如：题名[C]//会议名称。"
                ))
        
        # 检查页码格式（放宽空格检查）
        pages = parsed_ref.get("pages")
        if pages:
                # 放宽检查：允许冒号前后有0个或多个空格
                pages_pattern = rf':\s*{re.escape(str(pages))}'
                if not re.search(pages_pattern, original_ref):
                    errors.append(ValidationError(
                        error_type="C.L3.01",
                        severity="info",
                        message="会议论文页码格式不规范。",
                        suggestion="页码前应使用冒号分隔，格式如：2021: 32-36。"
                    ))
                # 已放宽：允许冒号前后任意空格
        
        return errors
    
    def validate_c_l3_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """C.L3.02: 会议论文集编者信息可能缺失或位置不正确
        
        根据GB/T 7714-2015标准：
        - 会议论文析出文献格式：主要责任者. 析出文献题名[A]. 编者. 会议论文集题名[C]. 出版地: 出版者, 年: 页码
        - 编者位置应在析出文献题名[A]之后，会议论文集题名[C]之前
        - 格式如：Burstein J, Doran C, Solorio T. 或 Burstein J, Doran C, Solorio T, eds.
        
        注意：这是一个信息性检查，帮助识别会议论文集编者是否正确提取
        """
        errors = []
        
        doc_type = parsed_ref.get("document_type", "")
        
        # 仅对会议论文析出文献（标记为A但有会议信息）进行检查
        if doc_type == "A":
            conference_name = parsed_ref.get("conference_name")
            conference_editors = parsed_ref.get("conference_editors")
            other_contributors = parsed_ref.get("other_contributors")
            
            if conference_name:  # 这是一篇会议论文
                if not conference_editors:
                    # 检查是否误放在other_contributors中
                    if other_contributors:
                        # 检查格式是否像编者列表（无"译"等角色标识）
                        role_keywords = ['译', '编', '注', '校', 'translated', 'edited', 'annotated', 'trans.', 'ed.']
                        has_role = any(keyword in other_contributors for keyword in role_keywords)
                        
                        if not has_role:
                            errors.append(ValidationError(
                                error_type="C.L3.02",
                                message="会议论文集编者可能未正确提取。",
                                severity="info",
                                suggestion=f"检测到other_contributors字段为\"{other_contributors}\"，但缺少角色标识。如果这是会议论文集的编者，应放入conference_editors字段。"
                            ))
                    # else: 可能是没有编者信息，这是允许的（任选项）
        
        return errors
    
    def validate_c_l3_03(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """C.L3.03: 会议日期格式不规范
        
        根据GB/T 7714-2015附录A.2，会议日期应使用标准格式。
        示例：February 1-4, 2000 或 2000-02-01至2000-02-04
        """
        errors = []
        
        doc_type = parsed_ref.get("document_type", "")
        if doc_type not in ["C", "A"]:
            return []
        
        conference_date = parsed_ref.get("conference_date", "")
        
        # 检查会议日期格式
        if conference_date:
            # LLM可能返回整数类型的年份，需要转换为字符串
            conference_date = str(conference_date)
            
            # 常见日期格式：
            # - "February 1-4, 2000"
            # - "2000-02-01至2000-02-04"
            # - "2000年2月1-4日"
            date_patterns = [
                r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
                r'[A-Z][a-z]+\s+\d{1,2}-?\d{0,2},?\s+\d{4}',  # Month Day-Day, Year
                r'\d{4}年\d{1,2}月\d{1,2}[-~至]\d{1,2}日',  # 中文日期范围
            ]
            
            has_valid_format = any(re.search(pattern, conference_date) for pattern in date_patterns)
            
            if not has_valid_format and len(conference_date) < 4:
                errors.append(ValidationError(
                    error_type="C.L3.03",
                    severity="info",
                    message="会议日期格式不规范。",
                    suggestion=f"会议日期应使用标准格式，如\"February 1-4, 2000\"或\"2000-02-01至2000-02-04\"。当前为：{conference_date}"
                ))
        
        return errors
    
    def validate_c_l3_05(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """C.L3.05: 会议地点格式不规范
        
        根据GB/T 7714-2015附录A.2，会议地点应包含城市和国家信息。
        示例：Moscow, Russia
        """
        errors = []
        
        doc_type = parsed_ref.get("document_type", "")
        if doc_type not in ["C", "A"]:
            return []
        
        conference_location = parsed_ref.get("conference_location", "")
        
        # 会议地点格式检查（信息性，不强制）
        if conference_location:
            # LLM可能返回非字符串类型，需要转换
            conference_location = str(conference_location)
            # 地点通常为"城市, 国家"格式
            if len(conference_location.strip()) < 2:
                errors.append(ValidationError(
                    error_type="C.L3.05",
                    message="会议地点信息过短。",
                    severity="info",
                    suggestion=f"会议地点应包含城市和国家信息，如\"Moscow, Russia\"。当前为：{conference_location}"
                ))
        
        return errors
    
    def validate_c_l3_04(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """C.L3.04: 会议论文建议包含会议名称（info级别）"""
        if not self._check_doc_type(parsed_ref, "C"):
            return []
        
        errors = []
        host_title = parsed_ref.get("host_title") or parsed_ref.get("conference_name")
        if not host_title:
            errors.append(ValidationError(
                error_type="C.L3.04",
                severity="info",
                message="会议论文建议包含会议名称。",
                suggestion="建议补充会议名称信息，如：第XX届国际XX会议论文集、ICML 2020等。"
            ))
        
        return errors
    
    def validate_c_l3_06(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """C.L3.06: 会议论文建议包含页码（info级别）"""
        if not self._check_doc_type(parsed_ref, "C"):
            return []
        
        errors = []
        if not parsed_ref.get("pages"):
            errors.append(ValidationError(
                error_type="C.L3.06",
                severity="info",
                message="会议论文建议包含页码信息。",
                suggestion="会议论文通常应包含页码信息。如果是仅发表摘要，可忽略此提示。"
            ))
        
        return errors
    
    def validate_r_l2_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """R.L2.01: 报告文献缺少出版者信息"""
        if not self._check_doc_type(parsed_ref, "R"):
            return []
        
        error = self._check_required_field(parsed_ref, "publisher", "R.L2.01", 
                                           "出版者（报告发布机构）", "请补充出版者（报告发布机构）信息。")
        if error:
            return [error]
        return []
    
    def validate_r_l2_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """R.L2.02: 报告文献缺少出版地信息"""
        if not self._check_doc_type(parsed_ref, "R"):
            return []
        
        error = self._check_required_field(parsed_ref, "publish_place", "R.L2.02", 
                                           "出版地", "请补充出版地信息。")
        if error:
            return [error]
        return []
    
    def validate_r_l3_01(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """R.L3.01: 报告编号格式不规范或位置不正确
        
        根据GB/T 7714-2015附录A.3，报告格式：
        [序号] 主要责任者. 题名: 报告编号[R]. 出版地: 出版者, 出版年.
        
        示例：[18] 世界卫生组织. WHO/EHA emergency health training programme for Africa: 
        report on a WHO meeting, Geneva, 24-26 February 1997: WHO/EHA/97.3[R]. 
        Geneva: WHO, 1997.
        """
        if not self._check_doc_type(parsed_ref, "R"):
            return []
        
        errors = []
        report_number = parsed_ref.get("report_number", "")
        
        # 检查报告编号格式
        if report_number:
            # 报告编号通常格式：XXX/XXX/YY.Z 或类似格式
            # 示例：WHO/EHA/97.3, NASA-TP-1234
            if len(report_number.strip()) < 3:
                errors.append(ValidationError(
                    error_type="R.L3.01",
                    message="报告编号格式不规范。",
                    severity="info",
                    suggestion=f"报告编号通常包含机构代码和编号，如\"WHO/EHA/97.3\"。当前为：{report_number}"
                ))
            
            # 检查在原文中的位置（应在题名后、[R]前，用冒号分隔）
            title = parsed_ref.get("title", "")
            # 🔧 修复：确保字段是字符串类型以进行 in 操作
            report_number_str = str(report_number) if report_number else ""
            if title and report_number_str and report_number_str in original_ref:
                # 🔧 修复：确保字段是字符串类型
                title_str = str(title)
                report_number_str = str(report_number)
                # 查找报告编号是否在题名和[R]之间
                title_pos = original_ref.find(title_str)
                report_pos = original_ref.find(report_number_str)
                r_marker_pos = original_ref.find("[R]")
                
                if title_pos >= 0 and report_pos >= 0 and r_marker_pos >= 0:
                    if not (title_pos < report_pos < r_marker_pos):
                        errors.append(ValidationError(
                            error_type="R.L3.01",
                            severity="info",
                            message="报告编号位置不正确。",
                            suggestion=f"报告编号应位于题名之后、[R]之前，用冒号分隔。格式：题名: {report_number}[R]"
                        ))
        
        return errors
    
    def validate_n_l3_02(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """N.L3.02: 报纸版次著录格式不正确"""
        if not self._check_doc_type(parsed_ref, "N"):
            return []
        
        errors = []
        newspaper_date = parsed_ref.get("newspaper_date", "")
        newspaper_edition = parsed_ref.get("newspaper_edition", "")
        
        # 检查newspaper_edition字段格式（应为"2"或"2版"）
        if newspaper_edition:
            # 版次应为数字或"数字版"格式
            if not re.match(r'^\d+版?$', newspaper_edition.strip()):
                errors.append(ValidationError(
                    error_type="N.L3.02",
                    severity="info",
                    message="报纸版次格式不规范。",
                    suggestion=f"版次应为纯数字（如\"2\"）或带版字（如\"2版\"），当前为：{newspaper_edition}"
                ))
        
        # 检查原文献中的日期和版次格式
        # 正确格式：YYYY-MM-DD(版次) 如：2012-01-10(2)
        date_edition_pattern = r'\d{4}-\d{1,2}-\d{1,2}\s*\(\d+\)'
        if re.search(date_edition_pattern, original_ref):
            return errors  # 格式正确
        
        # 检查是否有日期但格式不对
        has_date = re.search(r'\d{4}[-/]\d{1,2}[-/]\d{1,2}', original_ref)
        has_edition_in_text = re.search(r'[版第]\s*\d+|edition\s+\d+|\(\d+\)', original_ref, re.IGNORECASE)
        
        if newspaper_date and newspaper_edition and not re.search(date_edition_pattern, original_ref):
            errors.append(ValidationError(
                error_type="N.L3.02",
                severity="info",
                message="报纸的出版日期和版次著录格式不正确。",
                suggestion=f"报纸的出版日期和版次应使用格式：YYYY-MM-DD(版次)，如：2012-01-10(2)。当前日期：{newspaper_date}，版次：{newspaper_edition}"
            ))
        elif has_date and has_edition_in_text:
            errors.append(ValidationError(
                error_type="N.L3.02",
                severity="info",
                message="报纸版次著录格式不正确。",
                suggestion="报纸的出版日期和版次应使用格式：YYYY-MM-DD(版次)，如：2012-01-10(2)。版次数字应使用圆括号括起。"
            ))
        
        return errors
    
    def validate_g_l3_07(self, parsed_ref: Dict, original_ref: str) -> List[ValidationError]:
        """
        根据GB/T 7714-2015第7章：
        - . 句号：用于分隔著录项目
        - : 冒号：用于副标题、出版地与出版者之间、页码前
        - , 逗号：用于同一著录项目内部
        - ; 分号：用于多个出版地、出版者
        - // 双斜线：析出文献与出处文献之间
        - ( ) 圆括号：用于卷期号等
        - [ ] 方括号：文献类型标识、补充信息、引用日期
        """
        errors = []
        
        doc_type = parsed_ref.get("document_type", "")
        
        # 检查常见的标点符号错误
        
        # 1. 检查作者与题名之间的分隔（应该是". "）
        authors = parsed_ref.get("authors")
        title = parsed_ref.get("title")
        
        if authors and title:
            # 获取作者列表的最后一个元素
            if isinstance(authors, list) and authors:
                last_element = str(authors[-1])
                
                # 在原文中查找该元素的位置
                last_element_escaped = re.escape(last_element)
                match = re.search(last_element_escaped, original_ref)
                
                if match:
                    # 找到最后一个作者元素的结束位置
                    end_pos = match.end()
                    
                    # 从该位置开始，查找距离最近的空格（放宽检查：允许1个或多个空格）
                    remaining_text = original_ref[end_pos:]
                    space_match = re.search(r'\s+', remaining_text)
                    
                    if space_match:
                        # 检查空格前是否有句号（放宽检查：允许空格数量不定）
                        text_before_space = remaining_text[:space_match.start()].strip()
                        
                        # 只检查是否有句号，不检查句号数量（放宽对多余句号的检查）
                        if not text_before_space.endswith('.'):
                            # 判断使用了什么符号
                            if text_before_space.endswith(','):
                                desc = '使用了逗号而非句号'
                            elif text_before_space.endswith(':'):
                                desc = '使用了冒号而非句号'
                            elif text_before_space.endswith(';'):
                                desc = '使用了分号而非句号'
                            elif text_before_space == '':
                                # 没有任何符号
                                desc = '缺少句号'
                            else:
                                desc = '使用了不正确的分隔符'
                            
                            errors.append(ValidationError(
                                error_type="G.L3.07",
                                message=f"标点符号使用不规范：作者与题名之间{desc}。",
                                severity="info",
                                suggestion="作者与题名之间应使用\". \"（句号+空格）分隔。"
                            ))
                        # 删除对多余句号的检查，减少误报
                    else:
                        # 找不到空格，检查是否直接连接（没有空格）
                        if remaining_text and not remaining_text.strip().startswith('.'):
                            errors.append(ValidationError(
                                error_type="G.L3.07",
                                message=f"标点符号使用不规范：作者后缺少句号。",
                                severity="info",
                                suggestion="作者与题名之间应使用\". \"（句号+空格）分隔。"
                            ))
        
        # 2. 检查出版地与出版者之间的分隔（放宽检查：允许多个空格）
        publish_place = parsed_ref.get("publish_place")
        publisher = parsed_ref.get("publisher")
        
        if publish_place and publisher and doc_type not in ["J", "N"]:  # 期刊和报纸通常不需要出版地
            # 🔧 修复：确保字段是字符串类型
            publish_place_str = str(publish_place)
            publisher_str = str(publisher)
            # 放宽检查：允许冒号前后有0个或多个空格
            place_publisher_pattern = rf'{re.escape(publish_place_str)}\s*:\s*{re.escape(publisher_str)}'
            if not re.search(place_publisher_pattern, original_ref):
                # 只检查是否使用了明显错误的分隔符（逗号、分号、句号）
                if re.search(rf'{re.escape(publish_place_str)}\s*[,;.]\s*{re.escape(publisher_str)}', original_ref):
                    errors.append(ValidationError(
                        error_type="G.L3.07",
                        message="标点符号使用不规范：出版地与出版者之间应使用\":\"分隔。",
                        severity="info",
                        suggestion=f"格式应为：{publish_place}：{publisher}。"
                    ))
                # 删除对空格数量的严格检查
        
        # 3. 检查多个作者之间的分隔（放宽检查：允许空格数量灵活）
        if authors and isinstance(authors, list) and len(authors) > 1:
            # 在原文中查找作者
            for i in range(len(authors) - 1):
                if authors[i] and authors[i+1]:
                    # 放宽检查：允许逗号前后有0个或多个空格
                    author_sep_pattern = rf'{re.escape(str(authors[i]))}\s*,\s*{re.escape(str(authors[i+1]))}'
                    if not re.search(author_sep_pattern, original_ref):
                        # 只检查是否使用了明显错误的分隔符（分号、句号、顿号）
                        if re.search(rf'{re.escape(str(authors[i]))}\s*[;.、]\s*{re.escape(str(authors[i+1]))}', original_ref):
                            errors.append(ValidationError(
                                error_type="G.L3.07",
                                message="标点符号使用不规范：多个作者之间应使用\",\"分隔。",
                                severity="info",
                                suggestion="作者之间应使用逗号分隔，最后一个作者后使用句号。"
                            ))
                            break
                        # 删除对空格数量的严格检查
        
        return errors


# 包装函数，用于向后兼容
def detect_citation_system_in_text(text: str) -> str:
    """
    检测文本中的引用系统类型（向后兼容函数）
    
    Args:
        text: 要检测的文本
        
    Returns:
        引用系统类型字符串 ('numeric', 'author_year', 'unknown')
    """
    validator = GBT7714Validator()
    citation_system = validator.detect_citation_system(text)
    return citation_system.value


if __name__ == "__main__":
    try:
        # Comprehensive test cases for L1 and L2 rules
        test_references_comprehensive = [
            # --- L1级规则违规 ---
            # E.L1.01: 电子资源缺少URL
            "[1] Chen Y, et al. A review of deep learning in medical imaging [J/OL]. (2023-01-15).",
            # G.L1.02: 电子资源缺少DOI
            "[2] Zhang L, Wang H. Artificial intelligence in drug discovery [J/OL]. https://example.com/article, (2022-11-20).",
            # G.L1.01: 缺少文献类型标识
            "[3] Li J, Zhao Q. The application of machine learning in finance. Beijing: Science Press, 2021.",

            # --- L2级规则违规 (需要LLM解析) ---
            # G.L2.02: 缺少作者
            "[4] . A comprehensive survey on graph neural networks [J]. IEEE Transactions on Neural Networks and Learning Systems, 2021, 32(2): 4-24.",
            # G.L2.03: 缺少题名
            "[5] Krizhevsky A, Sutskever I, Hinton G E. [J]. Communications of the ACM, 2017, 60(6): 84-90.",
            # G.L2.04: 缺少出版年
            "[6] Goodfellow I, Bengio Y, Courville A. Deep learning [M]. Cambridge: MIT Press.",
            # M.L2.01: 专著缺少出版者
            "[7] LeCun Y, Bengio Y, Hinton G. Deep learning [J]. Nature, 2015, 521(7553): 436-444.", # 注意: 这是期刊，M.L2.01不应触发
            "[8] Hastie T, Tibshirani R, Friedman J. The elements of statistical learning [M]. New York, 2009.", # 缺少出版者

            # --- 格式正确的参考文献 ---
            "[9] Vaswani A, Shazeer N, Parmar N, et al. Attention is all you need [C]//Advances in neural information processing systems. Long Beach, CA: Curran Associates, Inc., 2017: 5998-6008.",
            "[10] He K, Zhang X, Ren S, et al. Deep residual learning for image recognition [J]. IEEE, 2016, 12(2): 10-24. DOI:10.1109/CVPR.2016.90.",
            "[11] Sutton R S, Barto A G. Reinforcement learning: An introduction [M]. Cambridge: MIT Press, 2018.",
            "[12] OpenAI. GPT-4 technical report [R/OL]. (2023-03-15) [2023-10-26]. https://arxiv.org/abs/2303.08774. DOI:10.48550/arXiv.2303.08774."
        ]

        validator = GBT7714Validator()

        print("=== 参考文献格式验证器测试 ===")
        print("测试 L1（必需项检查）、L2（LLM解析）、L3（格式规范）规则\n")
        
        # 先测试L1规则（本地验证，无需API）
        print("🔍 第一阶段：L1规则验证（本地检查）")
        print("-" * 50)
        l1_report = validator.generate_validation_report(test_references_comprehensive, user_id=None)
        print(l1_report)
        
        print("\n" + "="*60)
        print("🤖 第二阶段：L1+L2+L3规则验证（包含LLM解析）")
        print("注意：需要有效的SiliconFlow API密钥才能进行L2、L3验证")
        print("-" * 50)
        # 测试完整验证（包含L2、L3规则）
        # 使用测试用户ID = 1
        full_report = validator.generate_validation_report(test_references_comprehensive, user_id=1)
        print(full_report)

    except Exception as e:
        import traceback
        print(f"An error occurred during script execution: {e}")
        print(traceback.format_exc())