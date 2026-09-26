"""Host-only PNG conversion benchmark, same RGB565 pixels and PNG output."""
import sys
from pathlib import Path
import json
import statistics
import struct
import time
import zlib
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "HostTools"))
from capture_server import rgb565_to_png


def previous(data):
    pixels = bytearray(240 * (320 * 3 + 1))
    output = 0
    for y in range(240):
        pixels[output] = 0
        output += 1
        offset = y * 320 * 2
        for x in range(320):
            value = data[offset+x*2]*256 + data[offset+x*2+1]
            r,g,b = (value>>11)&31, (value>>5)&63, value&31
            pixels[output:output+3] = bytes(((r<<3)|(r>>2), (g<<2)|(g>>4), (b<<3)|(b>>2)))
            output += 3
    def chunk(kind, body):
        return struct.pack(">I",len(body))+kind+body+struct.pack(">I",zlib.crc32(kind+body)&0xffffffff)
    return b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",320,240,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(pixels,3))+chunk(b"IEND",b"")


raw = b"".join(struct.pack(">H", i % 65536) for i in range(76800))
assert previous(raw) == rgb565_to_png(raw)
results = {"synthetic_only":True, "png_byte_exact":True, "iterations":20}
for name, function in (("previous",previous),("lookup",rgb565_to_png)):
    durations=[]
    for _ in range(20):
        start=time.perf_counter()
        function(raw)
        durations.append((time.perf_counter()-start)*1000)
    results[name+"_median_ms"] = statistics.median(durations)
results["speedup"] = results["previous_median_ms"]/results["lookup_median_ms"]
output=Path(__file__).resolve().parents[1]/"Build/reader-20260922/client/png-benchmark.json"
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(results,indent=2),encoding="utf-8")
print(json.dumps(results))
