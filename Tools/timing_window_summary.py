"""Decode before/after diagnostics using the matching frozen C field order."""
import argparse
import json
import re
import struct
from pathlib import Path

GROUPS = {
    'g_gs_diag': ('App/Inc/gs_app.h', 'gs_app_diagnostics_t'),
    'g_gs_preview_diag': ('Modules/Preview/Inc/gs_preview.h', 'gs_preview_diagnostics_t'),
    'g_gs_board_diag': ('BSP/Inc/gs_board.h', 'gs_board_diag_t'),
    'g_gs_usb_diag': ('BSP/Inc/gs_usb_capture.h', 'gs_usb_diag_t'),
}


def fields(path, typename):
    text = re.sub(r'/\*.*?\*/', '', path.read_text(encoding='utf-8-sig'), flags=re.S)
    types = {name:body for body,name in re.findall(r'typedef\s+struct\s*\{([^}]+)\}\s*(\w+)\s*;',text)}
    result = []
    for line in types[typename].split(';'):
        if not line.strip(): continue
        match = re.fullmatch(r'\s*uint32_t\s+(.+)\s*',line,flags=re.S)
        if not match: raise ValueError('Unsupported diagnostic declaration: '+line)
        for decl in match[1].split(','):
            match = re.fullmatch(r'\s*(\w+)(?:\[(\w+)\])?\s*',decl)
            if not match: raise ValueError('Unsupported diagnostic field: '+decl)
            name,count = match.groups()
            if count:
                n = 6 if count == 'GS_TASK_COUNT' else int(count)
                result.extend(f'{name}[{i}]' for i in range(n))
            else: result.append(name)
    return result


def summary(session, source):
    groups = {}
    for group,(header,typename) in GROUPS.items():
        names = fields(source/header,typename)
        pair = {}
        for phase in ('before','after'):
            raw = (session/f'diagnostics-{phase}-{group}.bin').read_bytes()
            pair[phase] = dict(zip(names,struct.unpack('<'+'I'*len(names),raw)))
        pair['delta'] = {name:(pair['after'][name]-pair['before'][name])&0xffffffff for name in names}
        groups[group] = pair
    for admission in ('g_gs_deadline_admission_drops','g_gs_preprocess_admission_drops'):
        paths = [session/f'diagnostics-{phase}-{admission}.bin' for phase in ('before','after')]
        if any(path.exists() for path in paths):
            values = [struct.unpack('<I', path.read_bytes())[0] for path in paths]
            groups[admission] = {'before':values[0], 'after':values[1],
                                 'delta':(values[1]-values[0])&0xffffffff}
    ticks = [struct.unpack('<I',(session/f'diagnostics-{p}-uwTick.bin').read_bytes())[0] for p in ('before','after')]
    elapsed = (ticks[1]-ticks[0])&0xffffffff
    if not 0 < elapsed < 300000: raise ValueError('Invalid window or reset/wrap ambiguity')
    return {'scope':'Sequential diagnostic reads; approximate window rates, not atomic per-frame measurements',
            'elapsed_ms':elapsed, 'preview_confirmed_fps':groups['g_gs_preview_diag']['delta']['confirmed_unique']*1000/elapsed,
            'vision_frames_fps':groups['g_gs_diag']['delta']['vision_frames']*1000/elapsed,
            'camera_frames_fps':groups['g_gs_diag']['delta']['camera_frames']*1000/elapsed,
            'groups':groups}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('session',type=Path);p.add_argument('--source',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a = p.parse_args();r = summary(a.session,a.source)
    a.output.write_text(json.dumps(r,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in r.items() if k!='groups'},indent=2))
