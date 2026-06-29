"""替换 思维模式/自驱力 两页为现代布局"""
import re

# 读取当前文件
with open("/Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/report.html", "r", encoding="utf-8") as f:
    content = f.read()

# 找到要替换的区域：从 "<!-- 1-6 思维模式" 到 "</div>\n\n<!-- ==================== 第三板块"
start_tag = "<!-- 1-6 思维模式"
end_tag = "<!-- ==================== 第三板块"

start_idx = content.find(start_tag)
end_idx = content.find(end_tag)

if start_idx == -1 or end_idx == -1:
    print(f"ERROR: Cannot find boundaries (start={start_idx}, end={end_idx})")
    exit(1)

print(f"替换范围: {start_idx} 到 {end_idx}")
print(f"原内容长度: {end_idx - start_idx}")

# 新的两页内容
new_pages = '''<!-- 1-6 思维模式 -->
<div class="page">
    <div class="page-header">
        <div class="left"><span class="accent-dot"></span>MINDSET</div>
        <div class="right">{{ student.name }} · {{ student.date }}</div>
    </div>
    <div class="report-title">思维模式</div>
    <div class="report-en">Growth Mindset vs Fixed Mindset</div>

    <div class="ms-intro">{{ mindset.intro_mindset }}</div>

    <div class="ms-your-type">
        <div class="ms-label">你的思维模式</div>
        <div class="ms-type">{{ mindset.your_mindset }}</div>
        <div class="ms-desc">{{ mindset.mindset_intro }}</div>
    </div>

    <div class="ms-compare">
        <div class="ms-col ms-fixed">
            <h3>固定型思维模式</h3>
            <div class="ms-compare-row"><span class="ms-tag">挑战</span> 后退放弃</div>
            <div class="ms-compare-row"><span class="ms-tag">错误</span> 气馁，避免犯错</div>
            <div class="ms-compare-row"><span class="ms-tag">障碍</span> 轻易放弃</div>
            <div class="ms-compare-row"><span class="ms-tag">批评</span> 这人怎么总针对我</div>
            <div class="ms-compare-row"><span class="ms-tag">结果</span> 停滞不前，不能发挥自己的潜力</div>
        </div>
        <div class="ms-col ms-growth">
            <h3>成长型思维模式</h3>
            <div class="ms-compare-row"><span class="ms-tag">挑战</span> 拥抱挑战，努力坚持</div>
            <div class="ms-compare-row"><span class="ms-tag">错误</span> 是学习的机会和提高的途径</div>
            <div class="ms-compare-row"><span class="ms-tag">障碍</span> 坚持不懈</div>
            <div class="ms-compare-row"><span class="ms-tag">批评</span> 感激引导和指正，从中学习和成长</div>
            <div class="ms-compare-row"><span class="ms-tag">结果</span> 提高了能力，取得了更高的成就</div>
        </div>
    </div>
</div>

<!-- 1-7 自驱力 -->
<div class="page">
    <div class="page-header">
        <div class="left"><span class="accent-dot"></span>SELF DRIVING FORCE</div>
        <div class="right">{{ student.name }} · {{ student.date }}</div>
    </div>
    <div class="report-title">自驱力</div>
    <div class="report-en">Self-Driving Force Dimensions</div>

    <div class="sd-intro">{{ mindset.intro_selfdrive }}</div>

    <div class="sd-compare">
        <div class="sd-col sd-high">
            <h4>高分表现</h4>
            <ul>
                {% for item in mindset.high_low.high %}
                <li>{{ item }}</li>
                {% endfor %}
            </ul>
        </div>
        <div class="sd-col sd-low">
            <h4>低分表现</h4>
            <ul>
                {% for item in mindset.high_low.low %}
                <li>{{ item }}</li>
                {% endfor %}
            </ul>
        </div>
    </div>

    <div class="sd-legend">
        <div class="sd-legend-item">
            <span class="sd-legend-dot user"></span>
            <span>我的得分</span>
        </div>
        <div class="sd-legend-item">
            <span class="sd-legend-dot avg"></span>
            <span>平均得分</span>
        </div>
    </div>

    {% for item in mindset['items'] %}
    <div class="sd-item">
        <div class="sd-item-label">
            <span>{{ item.label }} <span class="sd-en">· {{ item.en }}</span></span>
            <span class="sd-score">{{ item.value }}<span class="sd-denom">/{{ item.max }}</span></span>
        </div>
        <div class="sd-bar-wrap">
            <div class="sd-bar-track">
                <div class="sd-bar-marker avg" style="left: {{ (item.avg / item.max * 100) }}%;">
                    <span>{{ item.avg }}</span>
                </div>
                <div class="sd-bar-marker user" style="left: {{ (item.value / item.max * 100) }}%;">
                    <span>{{ item.value }}</span>
                </div>
            </div>
        </div>
    </div>
    {% endfor %}
</div>

'''

# 拼接新内容
new_content = content[:start_idx] + new_pages + content[end_idx:]

with open("/Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/report.html", "w", encoding="utf-8") as f:
    f.write(new_content)

print(f"✓ 已替换思维模式/自驱力两页")
print(f"新内容长度: {len(new_pages)}")
print(f"文件总长度: {len(new_content)}")
