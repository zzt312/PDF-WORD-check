"""Debug 面上测试1.pdf to find project duration format."""
import pymysql
import re

conn = pymysql.connect(host='localhost', user='root', password='', database='pdf_md_system', charset='utf8mb4')
cursor = conn.cursor(pymysql.cursors.DictCursor)

cursor.execute("SELECT md_content FROM user_files WHERE file_id = '23291733-956c-4e7a-b2aa-7054518a58d6'")
row = cursor.fetchone()
md = row['md_content']

# Search for any year patterns like 2025, 2026, 2027, etc.
print("=== Year patterns in content ===")
year_patterns = re.findall(r'20[2-3]\d年?\d{0,2}月?', md)
print(f"Found {len(year_patterns)} year-like patterns")
for y in set(year_patterns):
    # Find context
    idx = md.index(y)
    ctx = md[max(0,idx-30):idx+50].replace('\n', '\\n')
    print(f"  {y}: ...{ctx}...")

# Search for any date-like patterns
print("\n=== Date range patterns ===")
date_ranges = re.findall(r'20\d{2}.*?20\d{2}', md[:5000])
for d in date_ranges:
    if len(d) < 60:
        print(f"  {d}")

# Search for 执行期限, 起止年月, etc.
print("\n=== Duration-related keywords ===")
kws = ['执行期限', '起止', '研究期限', '项目周期', '期限', '选择.*月至', '起始日期', '结束日期']
for kw in kws:
    m = re.search(kw, md)
    if m:
        idx = m.start()
        print(f"  '{kw}' found at {idx}: ...{md[max(0,idx-20):idx+80].replace(chr(10), '\\n')}...")
    else:
        print(f"  '{kw}' NOT FOUND")

# Also look for 主要研究领域
print("\n=== 主要研究领域 search ===")
if '主要研究领域' in md:
    idx = md.index('主要研究领域')
    print(f"  Found at {idx}: ...{md[max(0,idx-50):idx+100].replace(chr(10), '\\n')}...")
else:
    print("  NOT FOUND")
    # Search for similar keywords
    for kw in ['研究领域', '主要领域', '领域']:
        m = re.search(kw, md)
        if m:
            idx = m.start()
            print(f"  BUT '{kw}' found at {idx}: ...{md[max(0,idx-30):idx+80].replace(chr(10), '\\n')}...")

# Show first 3000 chars to understand the document structure
print("\n=== First 3000 chars of document ===")
print(md[:3000])

conn.close()
