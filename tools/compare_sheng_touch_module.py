#!/usr/bin/env python3
"""Read-only section comparison of the installed touch module and original dump."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

p=argparse.ArgumentParser()
p.add_argument('live',type=Path)
p.add_argument('stock',type=Path)
p.add_argument('output',type=Path)
args=p.parse_args()
def read(path):
    data=path.read_bytes()
    if data[:6]!=b'\x7fELF\x02\x01':raise SystemExit('Expected ELF64 little-endian module')
    offset=struct.unpack_from('<Q',data,40)[0]
    size,count,names=struct.unpack_from('<HHH',data,58)
    headers=[struct.unpack_from('<IIQQQQIIQQ',data,offset+i*size) for i in range(count)]
    strings=headers[names]
    table=data[strings[4]:strings[4]+strings[5]]
    sections={}; chunks={}
    for h in headers:
        name=table[h[0]:].split(b'\0',1)[0].decode()
        if name and h[1]!=8:
            chunks[name]=data[h[4]:h[4]+h[5]]
            sections[name]={'bytes':h[5],'sha256':hashlib.sha256(data[h[4]:h[4]+h[5]]).hexdigest()}
    return {'file':str(path),'sha256':hashlib.sha256(data).hexdigest(),'sections':sections},chunks
(live,live_bytes),(stock,stock_bytes)=read(args.live),read(args.stock)
changes=[]
if len(live_bytes.get('.text',b''))==len(stock_bytes.get('.text',b'')):
    for i in range(0,len(live_bytes.get('.text',b'')),4):
        a,b=live_bytes['.text'][i:i+4],stock_bytes['.text'][i:i+4]
        if a!=b:changes.append({'address':hex(i),'live':a.hex(),'stock':b.hex()})
result={'live':live,'stock':stock,'changed_sections':[
    name for name in sorted(set(live['sections'])|set(stock['sections']))
    if live['sections'].get(name)!=stock['sections'].get(name)],
    'text_instruction_differences':changes,
    'sources_modified':False,'module_installed':False}
args.output.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'changed_sections':result['changed_sections'],
                  'text_equal':live['sections'].get('.text')==stock['sections'].get('.text'),
                  'text_instruction_differences':changes[:32],'instruction_count':len(changes)},indent=2))
