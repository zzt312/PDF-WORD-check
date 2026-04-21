"""Check if extracted_json_data has the missing fields."""
import pymysql, json

conn = pymysql.connect(host='localhost', user='root', password='', database='pdf_md_system', charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)
cursor = conn.cursor()

# Check all recent files
cursor.execute("""SELECT file_id, original_name, extracted_json_data 
FROM user_files WHERE md_content IS NOT NULL AND LENGTH(md_content) > 1000
ORDER BY id DESC LIMIT 5""")

for row in cursor.fetchall():
    fid = row['file_id'][:8]
    name = row['original_name'][:35]
    print(f"\n=== {fid} | {name} ===")
    if row['extracted_json_data']:
        try:
            jd = json.loads(row['extracted_json_data'])
            if isinstance(jd, dict):
                for key in ['研究期限', '执行期限', '项目周期', '起止年月', '主要研究领域', '研究领域', '申请代码']:
                    if key in jd:
                        print(f"  JSON['{key}'] = {str(jd[key])[:80]}")
                # Also check nested
                for key, val in jd.items():
                    if isinstance(val, str) and ('研究期限' in val or '主要研究领域' in val):
                        print(f"  JSON['{key}'] contains target text = {val[:80]}")
        except Exception as e:
            print(f"  Error parsing JSON: {e}")
    else:
        print(f"  No extracted_json_data")

conn.close()
