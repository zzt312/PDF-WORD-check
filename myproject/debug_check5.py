"""Simulate EXACT re-check flow for the GRAMD1B file."""
import pymysql
import sys
sys.path.insert(0, '.')

conn = pymysql.connect(host='localhost', user='root', password='', database='pdf_md_system', charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)
cursor = conn.cursor()

# Get the file exactly as the route does
cursor.execute("""
    SELECT original_name, md_content, original_md_content, table_preliminary_check, text_preliminary_check, status, extracted_json_data, nsfc_json_data
    FROM user_files
    WHERE file_id = 'a6ad6e65-4e15-41fa-b818-5aaa7f2dee53'
""")
file_info = cursor.fetchone()

print(f"File: {file_info['original_name']}")
print(f"md_content: {len(file_info['md_content'])} chars")
print(f"original_md_content: {len(file_info['original_md_content']) if file_info['original_md_content'] else 'NULL'}")
print(f"type of file_info: {type(file_info)}")

md_content = file_info.get('md_content')
original_md_content = file_info.get('original_md_content') or md_content
print(f"original_md_content used: {len(original_md_content)} chars")
print(f"'研究期限' in original_md_content: {'研究期限' in original_md_content}")
print(f"'主要研究领域' in original_md_content: {'主要研究领域' in original_md_content}")

# Now call the function exactly as the route does
from regex_preliminary_check import run_regex_preliminary_check
import json

json_data = None
if file_info.get('extracted_json_data'):
    try:
        json_data = json.loads(file_info['extracted_json_data'])
    except:
        pass

print(f"\n=== Calling run_regex_preliminary_check ===")
print(f"  md_content (primary) = original_md_content: {len(original_md_content)} chars")
print(f"  vlm_md_content = md_content: {len(md_content)} chars")

violations = run_regex_preliminary_check(
    md_content=original_md_content,
    vlm_md_content=md_content,
    api_key='test'
)

print(f"\n=== Results: {len(violations)} violations ===")
for v in violations:
    print(f"  [{v.get('severity','?')}] {v.get('rule_name','?')}: {v.get('error_text','?')[:80]}")

# Specifically check for the two rules
has_annual = any('年度' in str(v.get('rule_name','')) or '年度' in str(v.get('error_text','')) for v in violations)
has_field = any('主要研究领域' in str(v.get('error_text','')) for v in violations)
print(f"\n年度计划违规检出: {has_annual}")
print(f"主要研究领域违规检出: {has_field}")

conn.close()
