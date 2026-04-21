"""Debug script to check why 研究期限 and 主要研究领域 are not found."""
import pymysql
import re

conn = pymysql.connect(host='localhost', user='root', password='', database='pdf_md_system', charset='utf8mb4')
cursor = conn.cursor(pymysql.cursors.DictCursor)

# Get the latest file with original_md_content
cursor.execute("""SELECT file_id, original_name, 
    LENGTH(md_content) as md_len, LENGTH(original_md_content) as orig_len
FROM user_files WHERE original_md_content IS NOT NULL ORDER BY id DESC LIMIT 1""")
file_info = cursor.fetchone()
print(f"=== File: {file_info['original_name']} ===")
print(f"  md_content: {file_info['md_len']} bytes")
print(f"  original_md_content: {file_info['orig_len']} bytes")

file_id = file_info['file_id']

# Get both contents
cursor.execute("SELECT md_content, original_md_content FROM user_files WHERE file_id = %s", (file_id,))
row = cursor.fetchone()
md = row['md_content']
orig = row['original_md_content']

print(f"\n=== 研究期限 搜索 ===")
# Check in md_content
if '研究期限' in md:
    idx = md.index('研究期限')
    print(f"md_content: FOUND at pos {idx}")
    print(f"  Context: ...{md[max(0,idx-50):idx+100]}...")
else:
    print("md_content: NOT FOUND")

if '研究期限' in orig:
    idx = orig.index('研究期限')
    print(f"original_md_content: FOUND at pos {idx}")
    print(f"  Context: ...{orig[max(0,idx-50):idx+100]}...")
else:
    print("original_md_content: NOT FOUND")

# Check HTML <td> patterns
td_pattern = r'<td[^>]*>[^<]*研究期限[^<]*</td>'
md_td = re.search(td_pattern, md, re.IGNORECASE)
orig_td = re.search(td_pattern, orig, re.IGNORECASE)
print(f"  md_content  <td>研究期限</td>: {'FOUND' if md_td else 'NOT FOUND'} {md_td.group()[:80] if md_td else ''}")
print(f"  orig_content <td>研究期限</td>: {'FOUND' if orig_td else 'NOT FOUND'} {orig_td.group()[:80] if orig_td else ''}")

# Test _find_html_cell_value
from regex_preliminary_check import _find_html_cell_value
val_md = _find_html_cell_value(md, '研究期限')
val_orig = _find_html_cell_value(orig, '研究期限')
val_both = _find_html_cell_value([orig, md], '研究期限')
print(f"  _find_html_cell_value(md): {val_md}")
print(f"  _find_html_cell_value(orig): {val_orig}")
print(f"  _find_html_cell_value([orig, md]): {val_both}")

# Check regex patterns for duration
duration_patterns = [
    r'(?:研究期限|执行期限|项目周期|起止年月)[^\d]*(\d{4})年(\d{1,2})月\d{1,2}日\s*[-—~至]{1,3}\s*(\d{4})年(\d{1,2})月\d{1,2}日',
    r'(?:研究期限|执行期限|项目周期|起止年月)[：:]\s*(\d{4})[.年](\d{1,2})[月]?\s*[-~至]\s*(\d{4})[.年](\d{1,2})',
    r'\|\s*(?:研究期限|执行期限)\s*\|\s*(\d{4})[.年](\d{1,2})[月]?\s*[-~至]\s*(\d{4})[.年](\d{1,2})',
    r'选择(\d{4})年(\d{1,2})月至(\d{4})年(\d{1,2})月',
    r'(\d{4})年(\d{1,2})月\d{1,2}日\s*[-—~至]{1,3}\s*(\d{4})年(\d{1,2})月\d{1,2}日',
    r'(\d{4})年(\d{1,2})月至(\d{4})年(\d{1,2})月',
]

print(f"\n=== Regex patterns for duration ===")
for content_name, content in [('md', md), ('orig', orig)]:
    for i, pat in enumerate(duration_patterns):
        m = re.search(pat, content)
        if m:
            print(f"  {content_name}: Pattern {i} matched: {m.group()[:80]}")
            break
    else:
        print(f"  {content_name}: No regex match")

print(f"\n=== 主要研究领域 搜索 ===")
if '主要研究领域' in md:
    idx = md.index('主要研究领域')
    print(f"md_content: FOUND at pos {idx}")
    print(f"  Context: ...{md[max(0,idx-50):idx+100]}...")
else:
    print("md_content: NOT FOUND")

if '主要研究领域' in orig:
    idx = orig.index('主要研究领域')
    print(f"original_md_content: FOUND at pos {idx}")
    print(f"  Context: ...{orig[max(0,idx-50):idx+100]}...")
else:
    print("original_md_content: NOT FOUND")

# Check HTML <td> for 主要研究领域
td_pattern2 = r'<td[^>]*>[^<]*主要研究领域[^<]*</td>'
md_td2 = re.search(td_pattern2, md, re.IGNORECASE)
orig_td2 = re.search(td_pattern2, orig, re.IGNORECASE)
print(f"  md_content  <td>主要研究领域</td>: {'FOUND' if md_td2 else 'NOT FOUND'}")
print(f"  orig_content <td>主要研究领域</td>: {'FOUND' if orig_td2 else 'NOT FOUND'}")

val_field_md = _find_html_cell_value(md, '主要研究领域')
val_field_orig = _find_html_cell_value(orig, '主要研究领域')
val_field_both = _find_html_cell_value([orig, md], '主要研究领域')
print(f"  _find_html_cell_value(md): {val_field_md}")
print(f"  _find_html_cell_value(orig): {val_field_orig}")
print(f"  _find_html_cell_value([orig, md]): {val_field_both}")

# Now test the actual check function
print(f"\n=== Running actual check functions ===")
from regex_preliminary_check import check_annual_plan_from_md, check_required_fields_from_md

v1 = check_annual_plan_from_md(orig, vlm_content=md)
print(f"check_annual_plan_from_md: {len(v1)} violations")
for v in v1:
    print(f"  - {v['rule_name']}: {v['error_text'][:80]}")

v2 = check_required_fields_from_md(orig, vlm_content=md)
print(f"check_required_fields_from_md: {len(v2)} violations")
for v in v2:
    print(f"  - {v['rule_name']}: {v['error_text'][:80]}")

conn.close()
