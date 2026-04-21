"""Simulate the full re-check flow for each file."""
import pymysql
import json

conn = pymysql.connect(host='localhost', user='root', password='', database='pdf_md_system', charset='utf8mb4')
cursor = conn.cursor(pymysql.cursors.DictCursor)

# Get all files with content
cursor.execute("""SELECT file_id, original_name, md_content, original_md_content
FROM user_files WHERE md_content IS NOT NULL AND LENGTH(md_content) > 1000
ORDER BY id DESC LIMIT 5""")

from regex_preliminary_check import check_annual_plan_from_md, check_required_fields_from_md, check_project_duration_from_md

for row in cursor.fetchall():
    fid = row['file_id'][:8]
    name = row['original_name'][:30]
    md = row['md_content']
    orig = row['original_md_content']
    
    # Simulate what the re-check route does:
    # original_md_content = file_info.get('original_md_content') or md_content
    primary = orig or md
    vlm = md  # VLM content is always md_content
    
    print(f"\n{'='*60}")
    print(f"File: {fid} | {name}")
    print(f"  Primary (orig or md): {len(primary)} chars | VLM (md): {len(vlm)} chars")
    print(f"  Has orig_md_content: {orig is not None}")
    
    # Test annual plan check
    v1 = check_annual_plan_from_md(primary, vlm_content=vlm)
    if v1:
        for v in v1:
            print(f"  [annual_plan] {v['error_text'][:80]}")
    else:
        print(f"  [annual_plan] No violations (good or not found)")
    
    # Test project duration check  
    v2 = check_project_duration_from_md(primary, vlm_content=vlm)
    if v2:
        for v in v2:
            print(f"  [duration] {v['error_text'][:80]}")
    else:
        print(f"  [duration] No violations")
    
    # Test required fields check
    v3 = check_required_fields_from_md(primary, vlm_content=vlm)
    if v3:
        for v in v3:
            print(f"  [required] {v['error_text'][:80]}")
    else:
        print(f"  [required] No violations (field filled or not found)")

conn.close()
