"""Bind every diagnostic address/size to the exact ELF32 AXF symbol table.

Read-only: does not touch a target, change a layout, or reinterpret old captures.
"""
from pathlib import Path
import argparse,hashlib,json,struct
def symbols(path):
    data=Path(path).read_bytes()
    if data[:6]!=b'\x7fELF\x01\x01':raise ValueError('Expected little-endian ELF32 AXF')
    off=struct.unpack_from('<I',data,32)[0];entry,count=struct.unpack_from('<HH',data,46)
    if entry!=40:raise ValueError('Unsupported section table entry size')
    sections=[struct.unpack_from('<10I',data,off+i*entry) for i in range(count)]
    result={}
    for sh in sections:
        if sh[1]!=2:continue
        strings=sections[sh[6]];table=data[strings[4]:strings[4]+strings[5]]
        if sh[9]!=16:raise ValueError('Unsupported symbol entry size')
        for pos in range(sh[4],sh[4]+sh[5],16):
            name,value,size,info,other,index=struct.unpack_from('<IIIBBH',data,pos)
            if not name or not index:continue
            end=table.index(0,name);name=table[name:end].decode('utf-8')
            result.setdefault(name,[]).append({'address':f'0x{value:08x}','size':size,'type':info&15})
    return result
def check(axf,layout):
    spec=json.loads(Path(layout).read_text(encoding='utf-8-sig'));actual=symbols(axf)
    digest=hashlib.sha256(Path(axf).read_bytes()).hexdigest();errors=[];resolved={}
    binding=spec.get('binding',spec)
    if binding.get('axf_sha256','').lower()!=digest:errors.append('AXF SHA mismatch')
    for name,expected in spec['symbols'].items():
        candidates=[v for v in actual.get(name,[]) if v['type'] in (1,2)]
        if len(candidates)!=1:errors.append(f'{name}: expected one ELF object/function, found {len(candidates)}');continue
        value=candidates[0];resolved[name]=value
        normalized=int(value['address'],0)&(~1 if value['type']==2 else -1)
        if int(str(expected['address']),0)!=normalized:errors.append(f'{name}: address {expected["address"]} != AXF {value["address"]}')
        if 'thumb_map_address' in expected and int(expected['thumb_map_address'],0)!=int(value['address'],0):errors.append(f'{name}: Thumb symbol mismatch')
        if expected['size']!=value['size']:errors.append(f'{name}: size {expected["size"]} != AXF {value["size"]}')
    return {'axf_sha256':digest,'layout_sha256':hashlib.sha256(Path(layout).read_bytes()).hexdigest(),'passed':not errors,'errors':errors,'elf_symbols':resolved}
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--axf',required=True,type=Path);a.add_argument('--layout',required=True,type=Path);a.add_argument('--output',type=Path);args=a.parse_args()
    result=check(args.axf,args.layout)
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2));raise SystemExit(0 if result['passed'] else 1)
