#!/usr/bin/env python
"""Extract chat-related sections from views.py for inspection."""
import sys

filepath = r'C:\Users\Christian R\OneDrive\Desktop\Capstone---Updated-14\app\views.py'

with open(filepath, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Extract lines 4056-4900 (0-indexed: 4055-4899)
start = 4055
end = min(4900, len(lines))

with open(r'C:\Users\Christian R\OneDrive\Desktop\Capstone---Updated-14\app\chat_section.txt', 'w', encoding='utf-8') as out:
    for i in range(start, end):
        out.write(f"{i+1}: {lines[i]}")

print(f"Extracted lines {start+1}-{end} to chat_section.txt")
print(f"Total file length: {len(lines)} lines")
