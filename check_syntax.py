import py_compile
import sys

files = ["app/views.py", "app/urls.py", "app/models.py"]
ok = True
for f in files:
    try:
        py_compile.compile(f, doraise=True)
        print(f"{f}: OK")
    except py_compile.PyCompileError as e:
        print(f"{f}: ERROR - {e}")
        ok = False

sys.exit(0 if ok else 1)
