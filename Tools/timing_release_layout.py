"""Bind a frozen timing candidate's diagnostic layout to its ELF symbols."""
import argparse
import hashlib
import json
from pathlib import Path
from deploy_v5_layout_check import symbols, check
from timing_trace_decode import verify_header, RING_BYTES

SIZES = {'s_ai_input': 9216, 'g_gs_usb_diag': 64, 'g_gs_preview_diag': 48,
         'g_gs_board_diag': 80, 'g_gs_diag': 172, 'g_gs_static_diag': 368,
         'uwTick': 4, 'g_gs_debug_action': 4,
         'g_gs_bootstrap_stack_free_bytes': 4, 's_gesture': 80,
         'g_gs_timing_trace': RING_BYTES}


def generate(release):
    def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
    axf = release/'GestureScreen.axf'
    found = symbols(axf)
    layout = {'version': release.name, 'hex_sha256': sha(release/'GestureScreen.hex'),
              'axf_sha256': sha(axf), 'map_sha256': sha(release/'GestureScreen.map'),
              'trace_header_sha256': verify_header(release/'source/App/Inc/gs_timing_trace.h'),
              'symbols': {}, 'status': 'offline_candidate_not_yet_flashed'}
    sizes = dict(SIZES)
    for optional in ('g_gs_deadline_admission_drops','g_gs_preprocess_admission_drops'):
        if optional in found:
            sizes[optional] = 4
    for name, size in sizes.items():
        matches = [s for s in found.get(name,[]) if s['type'] == 1]
        if len(matches) != 1 or matches[0]['size'] != size:
            raise ValueError(f'Unexpected ELF symbol/size: {name}: {matches}')
        layout['symbols'][name] = {k: matches[0][k] for k in ('address','size')}
    out = release/'validation/timing-layout.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(layout, indent=2), encoding='utf-8')
    result = check(axf,out)
    (out.parent/'timing-layout-check.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    if not result['passed']: raise ValueError(result['errors'])
    return out, layout


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('release', type=Path)
    args = parser.parse_args()
    out, spec = generate(args.release)
    print(json.dumps({'layout':str(out.resolve()),'symbols':len(spec['symbols']),
                      'hex_sha256':spec['hex_sha256']},indent=2))
