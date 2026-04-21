import win32com.client
import tkinter as tk
from tkinter import filedialog
import os

# 创建文件选择对话框
root = tk.Tk()
root.withdraw()
word_path = filedialog.askopenfilename(
    title="选择Word文件",
    filetypes=[("Word 文件", "*.docx;*.doc")]
)
if not word_path:
    print("未选择文件，程序退出。")
    exit()

# 默认输出路径
default_md = os.path.splitext(word_path)[0] + ".md"
md_path = filedialog.asksaveasfilename(
    title="保存为Markdown",
    defaultextension=".md",
    initialfile=os.path.basename(default_md),
    initialdir=os.path.dirname(word_path),
    filetypes=[("Markdown 文件", "*.md")]
)
if not md_path:
    print("未选择输出路径，程序退出。")
    exit()

print(f"正在转换: {os.path.basename(word_path)}")
print(f"输出文件: {md_path}")

# 打开 Word 应用
word = win32com.client.Dispatch("Word.Application")
word.Visible = False
word_path = os.path.abspath(word_path)
word_path = word_path.replace("/", "\\")
doc = word.Documents.Open(word_path, ReadOnly=True)

markdown_lines = []

# 遍历段落
total_paras = len(doc.Paragraphs)
print(f"开始处理 {total_paras} 个段落...")

for i, para in enumerate(doc.Paragraphs, 1):
    if i % 100 == 0:
        print(f"进度: {i}/{total_paras}")
    
    text = para.Range.Text.strip()
    if not text:
        continue
    
    # 识别标题样式
    try:
        style = para.Range.Style
        style_name = style.NameLocal if style is not None else ""
        if "标题 1" in style_name or "Heading 1" in style_name:
            markdown_lines.append(f"# {text}")
        elif "标题 2" in style_name or "Heading 2" in style_name:
            markdown_lines.append(f"## {text}")
        elif "标题 3" in style_name or "Heading 3" in style_name:
            markdown_lines.append(f"### {text}")
        else:
            markdown_lines.append(text)
    except:
        markdown_lines.append(text)

# 关闭文档
doc.Close(False)
word.Quit()

# 生成完整的Markdown内容
md_content = "\n\n".join(markdown_lines)

# 保存文件
with open(md_path, "w", encoding="utf-8") as f:
    f.write(md_content)

print(f"\n✅ 转换完成！")
print(f"Markdown文件: {md_path}")
print(f"总段落数: {total_paras}")
print(f"有效段落数: {len(markdown_lines)}")

# 显示参考文献部分预览
lines = md_content.split('\n')
for i, line in enumerate(lines):
    if line.strip() == "参考文献":
        print(f"\n找到参考文献部分（第{i+1}行）:")
        # 显示参考文献标题后的10行
        preview_lines = lines[i:min(i+11, len(lines))]
        for j, pline in enumerate(preview_lines):
            print(f"  {i+j+1}: {pline[:80]}")
        break
