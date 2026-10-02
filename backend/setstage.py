"""python setstage.py <stage> <backend|frontend> <done|building|next|soon>  (updates live progress page)"""
import re, sys
p = "app/stages.py"
s = open(p).read()
stage, key, val = int(sys.argv[1]), sys.argv[2], sys.argv[3]
lines = s.split("\n")
for i, l in enumerate(lines):
    if l.strip().startswith(f'{{"id": {stage},'):
        lines[i] = re.sub(rf'"{key}": "\w+"', f'"{key}": "{val}"', l)
open(p, "w").write("\n".join(lines))
