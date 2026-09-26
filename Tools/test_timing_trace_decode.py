import struct
import unittest
import timing_trace_decode as trace


def fixture(sequence=1, capture=100):
    raw = bytearray(trace.RING_BYTES)
    struct.pack_into('<13I', raw, 0, 1, trace.PAYLOAD_BYTES, 32, sequence, 1, 0, 0, 0, 0, 0, 1, 1, 0)
    row = dict.fromkeys(trace.FIELDS, 0)
    row.update(sequence=sequence, frame_id=42, stage_valid=127,
               capture_end_ms=capture, camera_publish_ms=(capture+20)&trace.MASK,
               vision_dequeue_ms=(capture+30)&trace.MASK, preprocess_done_ms=(capture+40)&trace.MASK,
               inference_begin_ms=(capture+41)&trace.MASK, inference_end_ms=(capture+181)&trace.MASK,
               gesture_consume_ms=(capture+183)&trace.MASK, terminal_age_ms=181,
               consume_age_ms=183, inference_scheduled_cycles=17136000)
    slot = (sequence-1) % 32
    struct.pack_into('<'+'I'*(len(trace.FIELDS)+2), raw, 52+slot*trace.SLOT_BYTES,
                     sequence, *(row[name] for name in trace.FIELDS), sequence)
    guard = bytearray(128)
    struct.pack_into('<I', guard, slot*4, sequence)
    return raw, guard, bytearray(guard), slot


class DecodeTest(unittest.TestCase):
    def test_complete(self):
        raw, left, right, _ = fixture()
        result = trace.decode(raw,left,right)
        self.assertEqual(len(result['records']),1)
        row = result['records'][0]
        self.assertEqual(row['durations']['inference_wall_ms'],140)
        self.assertEqual(row['inference_accounted_ms'],102)

    def test_tick_wrap_and_zero_valid(self):
        for capture in (0,0xfffffff0):
            raw,left,right,_ = fixture(capture=capture)
            self.assertEqual(trace.decode(raw,left,right)['records'][0]['durations']['capture_to_consume_ms'],183)

    def test_sequence_wrap_endpoints(self):
        for seq in (0xffffffff,1,33,64):
            raw,left,right,_ = fixture(sequence=seq)
            self.assertEqual(len(trace.decode(raw,left,right)['records']),1)

    def test_changed_guard(self):
        raw,left,right,slot = fixture()
        struct.pack_into('<I',right,slot*4,33)
        self.assertFalse(trace.decode(raw,left,right)['records'])

    def test_writing_slot(self):
        raw,left,right,slot = fixture()
        struct.pack_into('<I',raw,52+slot*trace.SLOT_BYTES+trace.SLOT_BYTES-4,0)
        self.assertFalse(trace.decode(raw,left,right)['records'])

    def test_wrong_slot(self):
        raw,left,right,_ = fixture()
        values = raw[52:52+trace.SLOT_BYTES]
        raw[52:52+trace.SLOT_BYTES] = bytes(trace.SLOT_BYTES)
        raw[52+trace.SLOT_BYTES:52+2*trace.SLOT_BYTES] = values
        left = right = struct.pack('<32I',0,1,*([0]*30))
        self.assertFalse(trace.decode(raw,left,right)['records'])

    def test_schema_and_size(self):
        raw,left,right,_ = fixture()
        with self.assertRaises(ValueError): trace.decode(raw[:-1],left,right)
        struct.pack_into('<I',raw,0,2)
        with self.assertRaises(ValueError): trace.decode(raw,left,right)

    def test_incomplete_stages_do_not_fabricate_metrics(self):
        raw,left,right,slot = fixture()
        struct.pack_into('<I',raw,52+slot*trace.SLOT_BYTES+4+2*4,7)
        row = trace.decode(raw,left,right)['records'][0]
        self.assertNotIn('inference_wall_ms',row['durations'])
        self.assertFalse(row['complete_inference'])

    def test_reversed_stage_is_not_normal_wrap(self):
        raw,left,right,slot = fixture()
        offset = 52+slot*trace.SLOT_BYTES+4+trace.FIELDS.index('inference_end_ms')*4
        struct.pack_into('<I',raw,offset,140)  # begin is 141
        row = trace.decode(raw,left,right)['records'][0]
        self.assertIn('inference_wall_ms',row['invalid_duration_fields'])
        self.assertFalse(row['complete_inference'])

    def test_frozen_header_field_order(self):
        from pathlib import Path
        header = Path(__file__).resolve().parents[1]/'App/Inc/gs_timing_trace.h'
        self.assertEqual(len(trace.verify_header(header)),64)

    def test_gap_excludes_missing_and_handles_wrap(self):
        rows = [{'sequence':0xffffffff, 'capture_end_ms':0xfffffff0, 'gesture_consume_ms':100},
                {'sequence':1, 'capture_end_ms':124, 'gesture_consume_ms':240},
                {'sequence':3, 'capture_end_ms':404, 'gesture_consume_ms':520}]
        result = trace.consecutive_gaps(rows,0xfffffffe)
        self.assertEqual(result['capture_gap_ms']['count'],1)
        self.assertEqual(result['capture_gap_ms']['max'],140)
        self.assertEqual(result['consume_gap_ms']['max'],140)
        self.assertEqual(result['missing_sequence_pairs'],1)


if __name__ == '__main__':
    unittest.main()
