"""Check the production C sender's byte stream against the Python decoder."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'HostTools'))
from usb_capture import FrameDecoder

def main():
    wire = Path(sys.argv[1]).read_bytes()
    frames = FrameDecoder().feed(wire)
    assert len(frames) == 1 and frames[0].raw == b'\xa5' * 153600
    assert frames[0].metadata == dict(device_id='usb-000000010000000200000003',
                                     frame_id=42, capture_ms=100, epoch=0xffffffff)
    print('PASS: actual C sender wire decoded by Python, including frame bytes, metadata and CRC.')

if __name__ == '__main__':
    main()
