import os
a = ['<html><body style="background:#e2e8f0; display:flex; flex-wrap:wrap; gap:20px; padding:20px;">']
for f in os.listdir('.'):
    if f.endswith('.svg'):
        a.append(f'<div style="background:white; padding:10px; border-radius:8px; text-align:center;"><img src="{f}" width="100" height="100"><br><small>{f}</small></div>')
a.append('</body></html>')
open('index.html', 'w', encoding='utf-8').write('\n'.join(a))
