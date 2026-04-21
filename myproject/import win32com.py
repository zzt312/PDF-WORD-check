import win32com.client
import tkinter as tk
from tkinter import filedialog
import os
from PIL import ImageGrab
import time
from reference_validator import GBT7714Validator, quick_validate_references, detect_citation_system_in_text
import json

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

# 打开 Word 应用
word = win32com.client.Dispatch("Word.Application")
word.Visible = False
word_path = os.path.abspath(word_path)
word_path = word_path.replace("/", "\\")  # 强制用反斜杠
doc = word.Documents.Open(word_path, ReadOnly=True)

# 创建 images 文件夹
images_dir = os.path.join(os.path.dirname(md_path), "images")
os.makedirs(images_dir, exist_ok=True)

markdown_lines = []
image_count = 1

# 提取图片（InlineShapes 和 Shapes）
def save_shape_as_image(shape, image_path):
    shape.Range.CopyAsPicture()
    time.sleep(0.5)  # 等待剪贴板刷新
    img = ImageGrab.grabclipboard()
    if img:
        img.save(image_path, 'PNG')
        return True
    return False

# 先处理图片，按文档顺序插入图片引用
for i in range(1, doc.InlineShapes.Count + 1):
    shape = doc.InlineShapes(i)
    image_name = f"image{image_count}.png"
    image_path = os.path.join(images_dir, image_name)
    if save_shape_as_image(shape, image_path):
        markdown_lines.append(f"![](images/{image_name})")
        image_count += 1

for i in range(1, doc.Shapes.Count + 1):
    shape = doc.Shapes(i)
    if shape.Type == 13:  # msoPicture
        image_name = f"image{image_count}.png"
        image_path = os.path.join(images_dir, image_name)
        shape.Copy()
        time.sleep(0.5)
        img = ImageGrab.grabclipboard()
        if img:
            img.save(image_path, 'PNG')
            markdown_lines.append(f"![](images/{image_name})")
            image_count += 1

# 处理段落文本
for para in doc.Paragraphs:
    text = para.Range.Text.strip()
    style = para.Range.Style
    if not text:
        continue
    style_name = style.NameLocal if style is not None else ""
    if "标题 1" in style_name or "Heading 1" in style_name:
        markdown_lines.append(f"# {text}")
    elif "标题 2" in style_name or "Heading 2" in style_name:
        markdown_lines.append(f"## {text}")
    else:
        markdown_lines.append(text)

doc.Close(SaveChanges=0)  # 不保存更改
word.Quit()

with open(md_path, "w", encoding="utf-8") as f:
    f.write("\n\n".join(markdown_lines))

# 提取参考文献功能（简化版）
def extract_references(md_file_path):
    """从markdown文件中提取参考文献部分并进行格式验证（仅生成独立部分报告）"""
    
    # 定义文件名映射
    def get_ref_name(idx):
        if idx == 0:
            return "report_ref"
        elif idx == 1:
            return "overview_ref"
        else:
            return f"ref_{idx + 1}"
    
    try:
        with open(md_file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        lines = content.split('\n')
        
        # 检测全文的引用体系
        citation_system = detect_citation_system_in_text(content)
        print(f"检测到的引用体系: {citation_system}")
        
        # 查找所有"参考文献"标题的位置
        ref_positions = []
        for i, line in enumerate(lines):
            if line.strip() == "参考文献":
                ref_positions.append(i)
        
        if len(ref_positions) == 0:
            print("未找到'参考文献'标题")
            return
        
        print(f"找到 {len(ref_positions)} 个参考文献部分")
        
        # 提取每个参考文献部分
        for idx, ref_start_idx in enumerate(ref_positions):
            ref_name = get_ref_name(idx)
            part_name = "报告" if idx == 0 else "综述" if idx == 1 else f"第{idx + 1}部分"
            
            print(f"\n处理{part_name}参考文献部分...")
            
            # 找到这个参考文献部分的结束位置
            ref_end_idx = len(lines)
            
            # 查找下一个参考文献或致谢作为结束标记
            for i in range(ref_start_idx + 1, len(lines)):
                line = lines[i].strip()
                if (line == "参考文献" or 
                    ("致" in line and "谢" in line) or
                    line.startswith("综") or
                    line.startswith("#") and "参考文献" not in line):
                    ref_end_idx = i
                    break
            
            # 提取这一部分的参考文献内容
            ref_lines = []
            for i in range(ref_start_idx, ref_end_idx):
                line = lines[i].strip()
                if line:  # 非空行
                    ref_lines.append(line)
            
            # 筛选包含[数字]格式的引用条目
            filtered_refs = []
            for line in ref_lines:
                if line.startswith("[") and "]" in line and line[1:line.find("]")].isdigit():
                    filtered_refs.append(line)
            
            if filtered_refs:
                # 进行GB/T 7714-2015格式验证
                print(f"正在验证{part_name}的{len(filtered_refs)}条参考文献...")
                validation_report = quick_validate_references(filtered_refs)
                
                # 生成JSON格式验证报告
                validator = GBT7714Validator()
                validation_results = validator.validate_references_list(filtered_refs)
                json_report = generate_json_validation_report(validation_results, filtered_refs, citation_system)
                
                # 生成参考文献内容文件
                ref_file_path = os.path.join(os.path.dirname(md_file_path), f"{ref_name}.md")
                with open(ref_file_path, "w", encoding="utf-8") as f:
                    f.write(f"# 参考文献 - {part_name}\n\n")
                    for ref in filtered_refs:
                        f.write(ref + "\n\n")
                
                # 生成Markdown格式详细验证报告
                validation_md_file_path = os.path.join(os.path.dirname(md_file_path), f"{ref_name}_validation_detail.md")
                with open(validation_md_file_path, "w", encoding="utf-8") as f:
                    f.write(f"# {part_name}参考文献详细验证报告\n\n")
                    f.write(f"**检测到的引用体系**: {citation_system}\n\n")
                    f.write("## 说明\n")
                    f.write("本报告包含每条参考文献的详细格式验证结果，包括具体错误和修改建议。\n\n")
                    f.write("---\n\n")
                    f.write(validation_report)
                
                # 生成JSON格式详细验证报告
                validation_json_file_path = os.path.join(os.path.dirname(md_file_path), f"{ref_name}_validation_detail.json")
                with open(validation_json_file_path, "w", encoding="utf-8") as f:
                    json.dump(json_report, f, ensure_ascii=False, indent=2)
                
                print(f"{part_name}参考文献已保存为：{ref_file_path}")
                print(f"{part_name}Markdown验证报告已保存为：{validation_md_file_path}")
                print(f"{part_name}JSON验证报告已保存为：{validation_json_file_path}")
                print(f"{part_name}共 {len(filtered_refs)} 条参考文献")
            else:
                print(f"{part_name}未找到符合[数字]格式的参考文献条目")
    
    except Exception as e:
        print(f"提取参考文献时出错：{str(e)}")

def generate_json_validation_report(validation_results, references, citation_system):
    """生成JSON格式的验证报告"""
    # 统计信息
    total_refs = len(references)
    valid_count = sum(1 for r in validation_results.values() if r.is_valid)
    error_rate = ((total_refs - valid_count) / total_refs * 100) if total_refs > 0 else 0
    
    # 错误统计
    error_stats = {}
    warning_stats = {}
    
    all_errors = []
    all_warnings = []
    
    for result in validation_results.values():
        all_errors.extend(result.errors)
        all_warnings.extend(result.warnings)
    
    # 统计错误类型
    for error in all_errors:
        error_stats[error.error_type] = error_stats.get(error.error_type, 0) + 1
    
    for warning in all_warnings:
        warning_stats[warning.error_type] = warning_stats.get(warning.error_type, 0) + 1
    
    # 构建详细的参考文献验证结果
    detailed_results = []
    for i, (ref_id, result) in enumerate(validation_results.items()):
        ref_data = {
            "id": ref_id,
            "index": i + 1,
            "content": references[i] if i < len(references) else "",
            "is_valid": result.is_valid,
            "confidence": round(result.confidence, 2),
            "errors": [
                {
                    "type": error.error_type,
                    "message": error.message,
                    "severity": error.severity,
                    "suggestion": error.suggestion,
                    "position": error.position,
                    "correct_format": getattr(error, 'correct_format', None),
                    "corrected_reference": getattr(error, 'corrected_reference', None)
                } for error in result.errors
            ],
            "warnings": [
                {
                    "type": warning.error_type,
                    "message": warning.message,
                    "severity": warning.severity,
                    "suggestion": warning.suggestion,
                    "position": warning.position,
                    "correct_format": getattr(warning, 'correct_format', None),
                    "corrected_reference": getattr(warning, 'corrected_reference', None)
                } for warning in result.warnings
            ]
        }
        detailed_results.append(ref_data)
    
    # 生成完整的JSON报告
    json_report = {
        "meta": {
            "report_type": "reference_validation",
            "citation_system": citation_system,
            "total_references": total_refs,
            "validation_date": "2025-09-12",
            "validator_version": "1.0.0"
        },
        "summary": {
            "total_references": total_refs,
            "valid_count": valid_count,
            "invalid_count": total_refs - valid_count,
            "error_rate": round(error_rate, 1),
            "success_rate": round(100 - error_rate, 1)
        },
        "statistics": {
            "error_types": {
                error_type: {
                    "count": count,
                    "percentage": round((count / len(all_errors) * 100), 1) if all_errors else 0
                } for error_type, count in sorted(error_stats.items(), key=lambda x: x[1], reverse=True)
            },
            "warning_types": {
                warning_type: {
                    "count": count,
                    "percentage": round((count / len(all_warnings) * 100), 1) if all_warnings else 0
                } for warning_type, count in sorted(warning_stats.items(), key=lambda x: x[1], reverse=True)
            },
            "total_errors": len(all_errors),
            "total_warnings": len(all_warnings)
        },
        "references": detailed_results
    }
    
    return json_report

# 在转换完成后提取参考文献
if os.path.exists(md_path):
    print("\n" + "="*50)
    print("开始提取和验证参考文献...")
    print("="*50)
    extract_references(md_path)
    print("\n" + "="*50)
    print("参考文献处理完成！")
    print("="*50)
    print("\n生成的文件说明：")
    print(" 参考文献内容：")
    print("  - ref_X.md: 各部分的参考文献内容")
    print("🔍 详细验证报告：")
    print("  - ref_X_validation_detail.md: 各部分的Markdown格式详细验证报告")
    print("  - ref_X_validation_detail.json: 各部分的JSON格式详细验证报告")
    print("\n💡 使用建议：")
    print("  1. 查看 ref_X_validation_detail.md 了解详细验证结果")
    print("  2. 使用 ref_X_validation_detail.json 进行网站展示或程序处理")
    print("  3. 根据验证报告修正参考文献格式问题")

print(f"转换完成，已保存为：{md_path}")

# 使用说明
"""
简化版功能说明：

1. 引用体系检测：
   - 自动检测文档使用的是顺序编码制还是著者-出版年制

2. 独立部分处理：
   - 仅生成各部分的独立文件，不生成合并文件
   - 每个部分生成3个文件：内容文件、MD验证报告、JSON验证报告

3. 双格式验证报告：
   - Markdown格式：适合人类阅读
   - JSON格式：适合网站展示和程序处理

生成文件：
- report_ref.md, overview_ref.md: 参考文献内容
- report_ref_validation_detail.md, overview_ref_validation_detail.md: Markdown验证报告
- report_ref_validation_detail.json, overview_ref_validation_detail.json: JSON验证报告
"""