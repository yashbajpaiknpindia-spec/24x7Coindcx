from pathlib import Path
p=Path('/app/collector.py')
print('COLLECTOR_INSPECTION_START')
if p.exists():
 lines=p.read_text(errors='replace').splitlines()
 for i,line in enumerate(lines):
  if 'spot' in line.lower() or 'history' in line.lower(): print(str(i+1)+': '+line[:250])
print('COLLECTOR_INSPECTION_END')
