from gauge_processor import extract_mindset_gauge

image_path = '/Users/jefflau/projects/pdf_report_converter/PDF_converter/pages/report_B4/page_11.png'

score = extract_mindset_gauge(image_path)
print(f"\n最终识别分数: {score}")