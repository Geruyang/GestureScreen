"""Copy the exact installed ST QVGA register table and its license; no HAL code changes."""
from pathlib import Path
import re, hashlib, shutil
root = Path(__file__).resolve().parents[1]
src = Path('D:/STM32CubeMX/Repository/STM32Cube_FW_F4_V1.28.3/Drivers/BSP/Components/ov2640')
raw = (src/'ov2640.c').read_bytes()
body = re.search(r'const unsigned char OV2640_QVGA\[\]\[2\]\s*=\s*(\{.*?\n\});', raw.decode(), re.S).group(1)
dst = root/'BSP/Inc/gs_ov2640_regs.h'
dst.write_text('/* QVGA register table from STMicroelectronics ov2640.c V1.0.2, 2014.\n'
               ' * Copyright (c) 2014 STMicroelectronics. All rights reserved.\n'
               ' * License: BSP/ThirdParty/ov2640-LICENSE.txt\n'
               f' * Source SHA256: {hashlib.sha256(raw).hexdigest()}\n */\n'
               'static const uint8_t gs_ov2640_qvga[][2] = '+body+';\n',encoding='utf-8')
(root/'BSP/ThirdParty').mkdir(exist_ok=True)
shutil.copy2(src/'LICENSE.txt',root/'BSP/ThirdParty/ov2640-LICENSE.txt')
print(dst)
