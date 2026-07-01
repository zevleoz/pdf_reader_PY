import re

VALUE_LABELS = ["创造发明", "独立自主", "美的追求", "智力激发", "利他助人",
                "成就感", "管理权力", "工作环境", "同事关系", "上司关系",
                "多样变化", "经济报酬", "安全稳定", "声望地位", "生活方式"]

api_result = """我们来逐步分析这个图表。

已知：
- 条形图共有15个条形，从左到右位置索引为 0 到 14。
- 最高分是 8.5，对应"安全稳定"，位于位置索引 **2**（即第3个条形）。
- 最低分是 4.5，对应"多样变化"，位于位置索引 **10**（即第11个条形）。
- Y轴刻度：0, 2, 4, 6, 8, 10 —— 每格代表2单位，中间有虚线网格（如6.5、7.5等可估读）。

| 索引 | 价值观       | 估算分数 |
|------|--------------|----------|
| 0    | 经济报酬     | 7.1      |
| 1    | 声望地位     | 6.1      |
| 2    | 安全稳定     | 8.5      |
| 3    | 成就感       | 6.6      |
| 4    | 创造发明     | 5.6      |
| 5    | 美的追求     | 5.5      |
| 6    | 利他助人     | 7.8      |
| 7    | 智力激发     | 5.6      |
| 8    | 管理权力     | 6.7      |
| 9    | 上司关系     | 6.6      |
| 10   | 多样变化     | 4.5      |
| 11   | 独立自主     | 6.1      |
| 12   | 同事关系     | 6.7      |
| 13   | 工作环境     | 7.3      |
| 14   | 生活方式     | 8.2      |

验证排序前5：
1. 安全稳定 8.5
2. 生活方式 8.2
3. 利他助人 7.8
4. 工作环境 7.3
5. 经济报酬 7.1 ✅ 完全匹配底部排序！"""

def parse_api_result(api_result: str, min_score: float, max_score: float, min_label: str, max_label: str):
    results = {}
    
    lines = api_result.split('\n')
    in_table = False
    for line in lines:
        if '|' in line and ('索引' in line or '价值观' in line or '分数' in line):
            in_table = True
            continue
        
        if in_table and '|' in line:
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 2:
                label = ''
                score_str = ''
                for part in parts:
                    if any(known_label in part or part in known_label for known_label in VALUE_LABELS):
                        label = part
                    try:
                        score = float(part)
                        if min_score <= score <= max_score + 1:
                            score_str = part
                    except ValueError:
                        pass
                
                if label and score_str:
                    matched_label = None
                    for known_label in VALUE_LABELS:
                        if known_label in label or label in known_label:
                            matched_label = known_label
                            break
                    
                    if matched_label:
                        try:
                            score = float(score_str)
                            results[matched_label] = round(max(min_score, min(max_score, score)), 1)
                        except ValueError:
                            pass
        
        if in_table and not line.strip():
            if len(results) >= 10:
                break
    
    if len(results) < 10:
        pattern = re.compile(r'([^\d]+?)\s*[：:]\s*(\d+\.?\d*)')
        for match in pattern.finditer(api_result):
            label_text = match.group(1).strip()
            score_str = match.group(2)
            
            matched_label = None
            for known_label in VALUE_LABELS:
                if known_label in label_text or label_text in known_label:
                    matched_label = known_label
                    break
            
            if matched_label:
                try:
                    score = float(score_str)
                    results[matched_label] = round(max(min_score, min(max_score, score)), 1)
                except ValueError:
                    pass
    
    if max_label in VALUE_LABELS:
        results[max_label] = max_score
    if min_label in VALUE_LABELS:
        results[min_label] = min_score
    
    return results

results = parse_api_result(api_result, 4.5, 8.5, "多样变化", "安全稳定")

print(f"解析到 {len(results)} 个标签:")
for label, score in sorted(results.items(), key=lambda x: -x[1]):
    print(f"  {label}: {score}")

print(f"\n唯一标签数: {len(set(results.keys()))}/15")
