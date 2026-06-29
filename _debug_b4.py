import fitz
doc = fitz.open('input/report_B4.pdf')
b4 = '\n'.join(p.get_text() for p in doc)
doc.close()

idx = b4.find('思维模式')
print('思维模式 context:', repr(b4[max(0,idx-100):idx+1200]))
print('---')
print("'成长型思维模式' in:", '成长型思维模式' in b4, "'固定型思维模式' in:", '固定型思维模式' in b4)
print("'提高' in:", '提高' in b4, "'努力' in:", '努力' in b4)
