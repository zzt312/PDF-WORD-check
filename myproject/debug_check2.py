"""Debug: check which file user is testing with."""
import pymysql

conn = pymysql.connect(host='localhost', user='root', password='', database='pdf_md_system', charset='utf8mb4')
cursor = conn.cursor(pymysql.cursors.DictCursor)

# All files: check if they have the fields and original_md_content
cursor.execute("""SELECT file_id, original_name, 
    LENGTH(md_content) as md_len,
    LENGTH(original_md_content) as orig_len,
    md_content LIKE '%研究期限%' as md_has_qx,
    COALESCE(original_md_content LIKE '%研究期限%', 0) as orig_has_qx,
    md_content LIKE '%主要研究领域%' as md_has_ly,
    COALESCE(original_md_content LIKE '%主要研究领域%', 0) as orig_has_ly,
    table_preliminary_check IS NOT NULL as has_cache
FROM user_files ORDER BY id DESC LIMIT 10""")

for row in cursor.fetchall():
    orig_str = str(row['orig_len']) if row['orig_len'] else 'NULL'
    print(f"  {row['file_id'][:8]} | {str(row['original_name'])[:30]:30s} | md={row['md_len']:6d} | orig={orig_str:>6s} | md_qx={row['md_has_qx']} orig_qx={row['orig_has_qx']} | md_ly={row['md_has_ly']} orig_ly={row['orig_has_ly']} | cache={row['has_cache']}")

conn.close()
