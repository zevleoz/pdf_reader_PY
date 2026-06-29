"""重写内驱力页面：顶部gauge + 三个donut图"""

with open("/Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/report.html", "r", encoding="utf-8") as f:
    content = f.read()

# 找到并替换自驱力页面
old_page_start = "<!-- 1-4 自驱力 -->"
old_page_end = "<!-- 1-5 人格 -->"

start_idx = content.find(old_page_start)
end_idx = content.find(old_page_end)

print(f"替换范围: {start_idx} - {end_idx}")

new_page = """<!-- 1-4 内驱力 -->
<div class="page">
    <div class="page-header">
        <div class="left"><span class="accent-dot"></span>INNER DRIVE</div>
        <div class="right">{{ student.name }} · {{ student.date }}</div>
    </div>
    <div class="report-title">内驱力</div>
    <div class="report-en">Inner Drive Dimensions</div>

    <!-- 顶部：思维模式 gauge -->
    <div class="sd-gauge-wrap">
        <div style="text-align: center; font-size: 10.5pt; font-weight: 600; color: #2A9D8F; margin-bottom: 4mm; letter-spacing: 2px;">思 维 模 式</div>
        <svg class="sd-gauge-svg" viewBox="0 0 280 150" style="overflow: visible; display: block; margin: 0 auto;">
            <defs>
                <linearGradient id="mindGrad" x1="0%" y1="0%" x2="100%" y2="0%">
                    <stop offset="0%" stop-color="#B87333" />
                    <stop offset="50%" stop-color="#F2B84B" />
                    <stop offset="100%" stop-color="#2A9D8F" />
                </linearGradient>
            </defs>
            <!-- 背景弧 -->
            <path d="M 30 120 A 120 120 0 0 1 250 120" fill="none" stroke="#E5E7EB" stroke-width="22" stroke-linecap="round" />
            <path d="M 30 120 A 120 120 0 0 1 250 120" fill="none" stroke="url(#mindGrad)" stroke-width="16" stroke-linecap="round" />
            <circle cx="30" cy="120" r="5" fill="#FFFFFF" stroke="#E5E7EB" stroke-width="2"/>
            <circle cx="250" cy="120" r="5" fill="#FFFFFF" stroke="#E5E7EB" stroke-width="2"/>
            <!-- 指针 -->
            <g transform="translate(140 120)">
                <g transform="rotate({{ mindset.gauge_rotation }})">
                    <line x1="0" y1="0" x2="110" y2="0" stroke="#2D3748" stroke-width="6" stroke-linecap="round" />
                </g>
                <circle cx="0" cy="0" r="12" fill="#2D3748" stroke="#FFFFFF" stroke-width="4"/>
                <circle cx="0" cy="0" r="4" fill="#FFFFFF"/>
            </g>
        </svg>
        <div class="sd-gauge-value">{{ mindset.mindset_score }}<span class="sd-gauge-denom"> / 100</span></div>
        <div class="sd-gauge-text">{{ mindset.mindset_text }}</div>
        <div class="sd-gauge-labels">
            <span class="label-left">固定型思维模式<br/><span class="label-sub">Fixed Mindset</span></span>
            <span class="label-right" style="text-align:right;">成长型思维模式<br/><span class="label-sub">Growth Mindset</span></span>
        </div>
    </div>

    <!-- 下方：三个 donut 图 -->
    <div style="margin: 8mm 0 3mm; text-align: center; font-size: 10.5pt; font-weight: 600; color: #2A9D8F; letter-spacing: 2px;">— 三 个 核 心 维 度 —</div>
    <div class="sd-donut-row">
        {% for item in mindset['items'] %}
        <div class="sd-donut-item">
            <div class="sd-donut">
                <svg viewBox="0 0 120 120">
                    <!-- 背景圆 -->
                    <circle cx="60" cy="60" r="48" fill="none" stroke="#E5E7EB" stroke-width="14" />
                    <!-- 填充弧 -->
                    <circle cx="60" cy="60" r="48" fill="none" stroke="#2A9D8F" stroke-width="14"
                            transform="rotate(-90 60 60)"
                            stroke-dasharray="{{ item.pct * 3.016 }}, 1000"
                            stroke-linecap="round" />
                    <!-- 平均得分标记：浅色弧 -->
                    <circle cx="60" cy="60" r="48" fill="none" stroke="#B87333" stroke-width="3"
                            transform="rotate(-90 60 60)"
                            stroke-dasharray="4, 1000"
                            stroke-dashoffset="{{ item.avg_pct * 3.016 - 2 }}" />
                </svg>
                <div class="sd-donut-center">
                    <div class="sd-donut-value">{{ item.value }}</div>
                    <div class="sd-donut-max">/ {{ item.max }}</div>
                </div>
            </div>
            <div class="sd-donut-label">{{ item.label }}</div>
            <div class="sd-donut-en">{{ item.en }}</div>
            <div class="sd-donut-avg">平均 {{ item.avg }}</div>
        </div>
        {% endfor %}
    </div>
</div>

"""

new_content = content[:start_idx] + new_page + "\n" + content[end_idx:]

with open("/Users/jefflau/projects/pdf_report_converter/PDF_converter/templates/report.html", "w", encoding="utf-8") as f:
    f.write(new_content)

print("✓ 内驱力页面已重写")
