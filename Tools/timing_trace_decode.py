"""Decode bounded, running-target trace snapshots with independent guard reads.

Each sample requires trace.bin plus trace-guards-before.bin/after.bin. These
guard arrays must bracket the entire ring read. A ring dump alone is rejected.
"""
import argparse
import hashlib
import json
import re
import statistics
import struct
from pathlib import Path

HEADER = 'version record_bytes capacity published_sequence total_published overwrite_count observation_queue_drops stale_before_inference gesture_tick_faults input_fault_signals observations_enqueued observations_consumed reset_discarded'.split()
FIELDS = ('sequence frame_id stage_valid capture_end_ms camera_publish_ms vision_dequeue_ms '
          'preprocess_done_ms inference_begin_ms inference_end_ms gesture_consume_ms '
          'terminal_age_ms consume_age_ms preprocess_status inference_status static_status '
          'outcome_flags gesture_state_before gesture_state_after fault_count_before '
          'fault_count_after command_sequence command_action inference_scheduled_cycles').split()
CAPACITY = 32
PAYLOAD_BYTES = 4 * len(FIELDS)
SLOT_BYTES = PAYLOAD_BYTES + 8
RING_BYTES = 4 * len(HEADER) + CAPACITY * SLOT_BYTES
MASK = 0xffffffff
OUTCOMES = 'observation_valid command fault fault_age fault_invalid fault_scores fault_order fault_gap duplicate recovery_cutoff disabled fault_unknown'.split()


def elapsed(end, start):
    return (end - start) & MASK


def verify_header(path):
    source = path.read_text(encoding='utf-8-sig')
    structures = dict((name, body) for body, name in re.findall(r'typedef\s+struct\s*\{([^}]+)\}\s*(\w+)\s*;', source))
    payload = re.findall(r'uint32_t\s+(\w+)\s*;', structures['gs_timing_trace_payload_t'])
    ring = re.findall(r'uint32_t\s+(\w+)\s*;', structures['gs_timing_trace_ring_t'])
    if payload != FIELDS or ring != HEADER:
        raise ValueError('Decoder field order differs from frozen C header')
    for name, expected in [('GS_TIMING_TRACE_VERSION', 1), ('GS_TIMING_TRACE_CAPACITY', CAPACITY)]:
        match = re.search(r'#define\s+' + name + r'\s+(\d+)U', source)
        if not match or int(match[1]) != expected:
            raise ValueError('Trace macro mismatch: ' + name)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def decode(raw, before, after):
    if len(raw) != RING_BYTES or len(before) != CAPACITY * 4 or len(after) != CAPACITY * 4:
        raise ValueError('Trace/guard byte size mismatch')
    header = dict(zip(HEADER, struct.unpack_from('<13I', raw)))
    if (header['version'], header['record_bytes'], header['capacity']) != (1, PAYLOAD_BYTES, CAPACITY):
        raise ValueError('Unsupported trace schema')
    left = struct.unpack('<32I', before)
    right = struct.unpack('<32I', after)
    accepted, rejected = [], []
    for slot in range(CAPACITY):
        values = struct.unpack_from('<' + 'I' * (len(FIELDS) + 2), raw, 4 * len(HEADER) + slot * SLOT_BYTES)
        row = dict(zip(FIELDS, values[1:-1]))
        seq = row['sequence']
        if not any((left[slot], right[slot], values[0], seq, values[-1])):
            continue
        if not seq or not left[slot] == right[slot] == values[0] == seq == values[-1]:
            rejected.append({'slot': slot, 'reason': 'in-progress, changed or torn sequence'})
            continue
        if (seq - 1) % CAPACITY != slot:
            rejected.append({'slot': slot, 'reason': 'sequence in wrong slot'})
            continue
        row['slot'] = slot
        row['fault_delta'] = elapsed(row['fault_count_after'], row['fault_count_before'])
        durations = {}
        stages = [('capture_to_publish_ms', 'camera_publish_ms', 'capture_end_ms', 3),
                  ('mailbox_wait_ms', 'vision_dequeue_ms', 'camera_publish_ms', 6),
                  ('preprocess_wall_ms', 'preprocess_done_ms', 'vision_dequeue_ms', 12),
                  ('inference_wall_ms', 'inference_end_ms', 'inference_begin_ms', 48),
                  ('inference_to_consume_ms', 'gesture_consume_ms', 'inference_end_ms', 96),
                  ('capture_to_consume_ms', 'gesture_consume_ms', 'capture_end_ms', 65)]
        for name, end, start, bits in stages:
            if row['stage_valid'] & bits == bits:
                durations[name] = elapsed(row[end], row[start])
        row['durations'] = durations
        row['invalid_duration_fields'] = [name for name, value in durations.items() if value >= 0x80000000]
        row['outcomes'] = [name for bit, name in enumerate(OUTCOMES) if row['outcome_flags'] & (1 << bit)]
        row['complete_inference'] = row['stage_valid'] & 127 == 127 and not row['invalid_duration_fields']
        if row['complete_inference']:
            row['inference_accounted_ms'] = row['inference_scheduled_cycles'] / 168000.0
        accepted.append(row)
    return {'header': header, 'records': accepted, 'rejected': rejected}


def describe(values):
    ordered = sorted(values)
    if not ordered:
        return None
    return {'count': len(ordered), 'min': ordered[0], 'median': statistics.median(ordered),
            'p95_nearest_rank': ordered[(95 * len(ordered) + 99) // 100 - 1], 'max': ordered[-1]}


def consecutive_gaps(rows, reference):
    ordered = sorted(rows, key=lambda row: elapsed(row['sequence'],reference))
    capture, consume = [], []
    missing = 0
    for previous, current in zip(ordered, ordered[1:]):
        following = (previous['sequence'] + 1) & MASK or 1
        if current['sequence'] != following:
            missing += 1
            continue
        capture.append(elapsed(current['capture_end_ms'],previous['capture_end_ms']))
        consume.append(elapsed(current['gesture_consume_ms'],previous['gesture_consume_ms']))
    return {'scope':'Adjacent committed records only; missing sequences are excluded, not treated as a measured receive gap',
            'capture_gap_ms':describe(capture), 'consume_gap_ms':describe(consume),
            'missing_sequence_pairs':missing}


def session(path):
    samples, distinct = [], {}
    for file in sorted(path.glob('sample-*-trace.bin')):
        stem = file.name[:-4]
        left = file.with_name(stem + '-guards-before.bin')
        right = file.with_name(stem + '-guards-after.bin')
        result = decode(file.read_bytes(), left.read_bytes(), right.read_bytes())
        result['file'] = file.name
        result['sha256'] = hashlib.sha256(file.read_bytes()).hexdigest()
        for row in result['records']:
            key = (row['sequence'], row['frame_id'], row['capture_end_ms'])
            if key in distinct and distinct[key] != row:
                raise ValueError('A committed record changed between samples')
            distinct[key] = row
        samples.append(result)
    if not samples:
        raise ValueError('No trace samples found')
    rows = list(distinct.values())
    complete = [r for r in rows if r['complete_inference']]
    initial_seq = samples[0]['header']['published_sequence']
    new_rows = [r for r in rows if 0 < elapsed(r['sequence'], initial_seq) < 0x80000000]
    new_complete = [r for r in new_rows if r['complete_inference']]
    metrics = {name: describe([r['durations'][name] for r in complete if name in r['durations']])
               for name in ('capture_to_publish_ms', 'mailbox_wait_ms', 'preprocess_wall_ms',
                            'inference_wall_ms', 'inference_to_consume_ms', 'capture_to_consume_ms')}
    metrics['inference_accounted_ms'] = describe([r['inference_accounted_ms'] for r in complete])
    return {'scope': 'Guard-validated, deduplicated frame trace; counters are non-atomic snapshots, no implied classification acceptance',
            'unique_records': len(rows), 'complete_inference_records': len(complete),
            'consume_age_over_300': sum(r['consume_age_ms'] > 300 for r in complete),
            'record_fault_delta_sum': sum(r['fault_delta'] for r in rows),
            'outcome_record_counts': {name: sum(name in r['outcomes'] for r in rows) for name in OUTCOMES},
            'invalid_duration_records': sum(bool(r['invalid_duration_fields']) for r in rows),
            'after_first_snapshot': {
                'scope': 'Excludes records already present in the initial ring snapshot; not identical to sequential diagnostic endpoint times',
                'initial_published_sequence': initial_seq,
                'new_unique_records': len(new_rows),
                'complete_inference_records': len(new_complete),
                'consume_age_over_300': sum(r['consume_age_ms'] > 300 for r in new_complete),
                'record_fault_delta_sum': sum(r['fault_delta'] for r in new_rows),
                'consecutive_gaps':consecutive_gaps(new_complete,initial_seq)},
            'metrics': metrics, 'samples': samples}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('session', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--header', required=True, type=Path, help='Exact frozen gs_timing_trace.h')
    args = parser.parse_args()
    header_sha = verify_header(args.header)
    result = session(args.session)
    result['frozen_header_sha256'] = header_sha
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in result.items() if k != 'samples'}, indent=2))
