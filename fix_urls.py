"""Remove duplicate imports from urls.py"""
import re

filepath = r'C:\Users\Christian R\OneDrive\Desktop\Capstone---Updated-14\app\urls.py'

with open(filepath, 'r', encoding='utf-8') as f:
    content = f.read()

# Find the import block
lines = content.split('\n')
in_import_block = False
import_lines = []
other_lines = []
import_block_start = None
import_block_end = None

for i, line in enumerate(lines):
    if 'from .views import (' in line:
        in_import_block = True
        import_block_start = i
        import_lines.append(line)
        continue
    if in_import_block:
        import_lines.append(line)
        if ')' in line and 'import' not in line.split(')')[0]:
            import_block_end = i
            in_import_block = False
            continue
    else:
        other_lines.append((i, line))

# Remove duplicates from import lines
seen = set()
unique_imports = []
for line in import_lines:
    stripped = line.strip().rstrip(',')
    if stripped in ('from .views import (', ')', ''):
        unique_imports.append(line)
    elif stripped not in seen:
        seen.add(stripped)
        unique_imports.append(line)

# Reconstruct the file
result_lines = []
import_done = False
for i, line in enumerate(lines):
    if i == import_block_start:
        result_lines.extend(unique_imports)
        import_done = True
        continue
    if import_block_start is not None and import_block_end is not None:
        if i > import_block_start and i <= import_block_end:
            continue
    result_lines.append(line)

with open(filepath, 'w', encoding='utf-8') as f:
    f.write('\n'.join(result_lines))

print("Fixed duplicate imports in urls.py")
