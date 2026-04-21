"""Check ALL files to see if 面上测试1 or others have hidden format issues."""
import pymysql
import re

conn = pymysql.connect(host='localhost', user='root', password='', database='pdf_md_system', charset='utf8mb4', cursorclass=pymysql.cursors.DictCursor)
cursor = conn.cursor()

# Check 面上测试1 specifically - it has md_has_qx=0, md_has_ly=0
cursor.execute("SELECT md_content FROM user_files WHERE file_id = '23291733-956c-4e7a-b2aa-7054518a58d6'")
row = cursor.fetchone()
md = row['md_content']

print("=== 面上测试1.pdf ===")
# Search for any mention of duration-like fields
for kw in ['研究期限', '执行期限', '起止年月', '项目周期', '选择', '月至', '月——', '月--', '月-']:
    if kw in md:
        idx = md.index(kw)
        ctx = md[max(0,idx-40):idx+80].replace('\n', '\\n')
        print(f"  '{kw}' FOUND at {idx}: ...{ctx}...")
    else:
        print(f"  '{kw}' NOT FOUND")

# Check if there's any basic info table with fields
print("\nSearching for basic_info table patterns...")
# Check for 资助类别, 申请代码, etc. in HTML tables
for kw2 in ['资助类别', '申请代码', '研究方向', '依托单位', '主要研究领域', '研究领域']:
    # Check both HTML and plain text
    if kw2 in md:
        idx = md.index(kw2)
        ctx = md[max(0,idx-40):idx+100].replace('\n', '\\n')
        print(f"  '{kw2}': ...{ctx}...")
    else:
        print(f"  '{kw2}' NOT FOUND")

# Check for HTML table near the beginning (basic info table usually is first)
print("\nHTML tables in first 5000 chars:")
tables = list(re.finditer(r'<table[^>]*>(.*?)</table>', md[:5000], re.DOTALL))
for i, t in enumerate(tables):
    table_text = re.sub(r'<[^>]+>', ' ', t.group(0))[:200]
    print(f"  Table {i}: ...{table_text}...")

conn.close()
