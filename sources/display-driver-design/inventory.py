import hashlib,json,re
from pathlib import Path
LAB=Path(__file__).resolve().parents[2]
ROOT=LAB/'sources/wine-pin-adea/pristine/wine-adea6cbac9d00bb22910145354d00c463fcf3afc/dlls/winemac.drv'
files=[p for p in sorted(ROOT.iterdir()) if p.suffix in ['.c','.m','.h']]
metrics={'scope':str(ROOT),'method':'lexical source inventory; lines include comments/blank; regex names not ABI or reachable-call proof',
 'files':[{'path':str(p.relative_to(LAB)),'lines':len(p.read_text().splitlines()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in files]}
metrics['implementation_files']={ext:{'count':sum(p.suffix==ext for p in files),'lines':sum(len(p.read_text().splitlines()) for p in files if p.suffix==ext)} for ext in ['.c','.m','.h']}
make=(ROOT/'Makefile.in').read_text();metrics['frameworks']=re.findall(r'-framework (\w+)',make)
text='\n'.join(p.read_text() for p in files)
metrics['host_c_api_lexical_distinct_names']={name:sorted(set(re.findall(r'\b('+prefix+r'\w+)\s*\(',text))) for name,prefix in [('CoreGraphics','CG'),('CoreFoundation','CF'),('CoreVideo','CV'),('IOKit','IO'),('dispatch','dispatch_')]}
metrics['NS_named_types']=sorted(set(re.findall(r'\b(NS[A-Z]\w+)\b',text)))
header=(ROOT/'macdrv_cocoa.h').read_text();metrics['cocoa_boundary_extern_function_names']=sorted(set(re.findall(r'extern\s+[^;{}]*?\b(macdrv_\w+)\s*\(',header,re.S)))
metrics['cocoa_boundary_extern_function_count']=len(metrics['cocoa_boundary_extern_function_names'])
out=LAB/'logs/display-driver-design/source-inventory.json';out.write_text(json.dumps(metrics,indent=2)+'\n')
print(json.dumps({'implementation_files':metrics['implementation_files'],'frameworks':metrics['frameworks'],
 'host_c_api_distinct_counts':{k:len(v) for k,v in metrics['host_c_api_lexical_distinct_names'].items()},
 'NS_named_types':len(metrics['NS_named_types']),'cocoa_boundary_extern_function_count':metrics['cocoa_boundary_extern_function_count']},indent=2))
