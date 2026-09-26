"""校验源码和工程配置；--with-build 额外核对实际链接 map 与构建产物。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import xml.etree.ElementTree as ET

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument('--with-build', action='store_true')
args = parser.parse_args()

def require(condition, description):
    if not condition:
        raise SystemExit('FAIL: ' + description)

def elf32_sections_and_symbols(path):
    """Minimal ELF32-LE reader for load/NOBITS safety checks; stdlib only."""
    data = path.read_bytes()
    require(data[:6] == b'\x7fELF\x01\x01', 'AXF is ELF32 little-endian')
    phoff, shoff = struct.unpack_from('<II', data, 28)
    phentsize, phnum, shentsize, shnum, shstrndx = struct.unpack_from('<HHHHH', data, 42)
    require(shentsize == 40 and shnum > 0 and shstrndx < shnum, 'AXF section table')
    raw = [struct.unpack_from('<IIIIIIIIII', data, shoff + i * shentsize) for i in range(shnum)]
    shstr = raw[shstrndx]
    names = data[shstr[4]:shstr[4] + shstr[5]]
    def cstring(blob, offset):
        end = blob.find(b'\0', offset)
        return blob[offset:end].decode('ascii', errors='strict')
    sections = []
    for item in raw:
        sections.append({'name': cstring(names, item[0]), 'type': item[1],
                         'flags': item[2], 'addr': item[3], 'offset': item[4],
                         'size': item[5], 'link': item[6], 'entsize': item[9]})
    symbols = {}
    for section in sections:
        if section['type'] != 2:  # SHT_SYMTAB
            continue
        strings = sections[section['link']]
        strtab = data[strings['offset']:strings['offset'] + strings['size']]
        require(section['entsize'] == 16, 'AXF symbol entry size')
        for offset in range(section['offset'], section['offset'] + section['size'], 16):
            name, value, size = struct.unpack_from('<III', data, offset)
            if name < len(strtab): symbols[cstring(strtab, name)] = (value, size)
    segments = []
    for index in range(phnum):
        item = struct.unpack_from('<IIIIIIII', data, phoff + index * phentsize)
        segments.append({'type': item[0], 'vaddr': item[2], 'filesz': item[4], 'memsz': item[5]})
    def virtual_bytes(address, size):
        for section in sections:
            if section['type'] == 1 and section['addr'] <= address and \
                    address + size <= section['addr'] + section['size']:
                start = section['offset'] + address - section['addr']
                return data[start:start + size]
        return None
    return sections, symbols, segments, virtual_bytes

ioc_text = (root / 'GestureScreen.ioc').read_text(encoding='utf-8')
ioc = dict(line.split('=', 1) for line in ioc_text.splitlines() if '=' in line)
require(ioc['Mcu.CPN'] == 'STM32F429IGT6', 'exact MCU')
require(ioc['Mcu.Package'] == 'LQFP176', 'package')
require(ioc['RCC.SYSCLKFreq_VALUE'] == '168000000', 'V1 168 MHz profile')
require(ioc['RCC.HSE_VALUE'] == '25000000' and ioc['RCC.PLLM'] == '25' and
        ioc['RCC.PLLN'] == '336' and ioc['RCC.PLLQ'] == '7', 'HSE25 PLL168 / 48 MHz')
for key, expected in {'PB14.Signal':'USB_OTG_HS_DM', 'PB15.Signal':'USB_OTG_HS_DP',
                      'PB14.Mode':'Device_Only_FS', 'PB15.Mode':'Device_Only_FS',
                      'USB_DEVICE.CLASS_NAME_HS':'CDC',
                      'USB_OTG_HS.VirtualMode':'Device_Only_FS',
                      'USB_OTG_HS.DeviceSpeed':'PCD_SPEED_FULL',
                      'USB_OTG_HS.phy_itface':'USB_OTG_EMBEDDED_PHY',
                      'USB_OTG_HS.dma_enable':'DISABLE',
                      'USB_OTG_HS.vbus_sensing_enable':'DISABLE'}.items():
    require(ioc.get(key) == expected, 'V1 USB ' + key)
usb_irq = ioc['NVIC.OTG_HS_IRQn'].split('\\:')
require(usb_irq[0] == 'true' and 5 <= int(usb_irq[1]) <= 15, 'USB IRQ priority')
require(ioc['FMC.WriteRecoveryTime1'] == '3', 'FMC write recovery meets TRC-TRCD-TRP constraint')
require(ioc['FMC.SDBank1'] == 'FMC_SDRAM_BANK2' and
        ioc['FMC.ColumnBitsNumber1'] == 'FMC_SDRAM_COLUMN_BITS_NUM_8' and
        ioc['FMC.RowBitsNumber1'] == 'FMC_SDRAM_ROW_BITS_NUM_12',
        'Challenger V1 8 MiB SDRAM geometry')
require(ioc['LTDC.Layers'] == '0', 'one LCD layer (CubeMX zero-based enum)')
require(ioc['Dma.DCMI.0.Mode'] == 'DMA_NORMAL', 'snapshot DMA must not wrap')
require(ioc['Dma.DCMI.0.Instance'] == 'DMA2_Stream1', 'camera DMA resource')
require('PA8.Signal' not in ioc, 'module oscillator: no camera MCO without rework')
for pin, expected in {
        'PH9':'DCMI_D0', 'PH10':'DCMI_D1', 'PH11':'DCMI_D2', 'PH12':'DCMI_D3',
        'PH14':'DCMI_D4', 'PD3':'DCMI_D5', 'PI6':'DCMI_D6', 'PI7':'DCMI_D7',
        'PA4':'DCMI_HSYNC', 'PI5':'DCMI_VSYNC', 'PB8':'LTDC_B6', 'PB9':'LTDC_B7',
        'PF7':'SPI5_SCK', 'PF8':'SPI5_MISO', 'PF9':'SPI5_MOSI',
        'PA1':'ETH_REF_CLK', 'PA2':'ETH_MDIO', 'PA7':'ETH_CRS_DV', 'PC1':'ETH_MDC',
        'PC4':'ETH_RXD0', 'PC5':'ETH_RXD1', 'PB11':'ETH_TX_EN',
        'PG13':'ETH_TXD0', 'PG14':'ETH_TXD1'}.items():
    require(ioc.get(pin + '.Signal') == expected, 'V1 pin ' + pin + '=' + expected)
for pin, label in {'PG2':'CAM_RESET', 'PG3':'CAM_PWDN', 'PF6':'FLASH_CS', 'PI1':'ETH_PHY_RESET'}.items():
    require(ioc.get(pin + '.Signal') == 'GPIO_Output' and ioc.get(pin + '.GPIO_Label') == label,
            'V1 control pin ' + pin + '=' + label)
require(not any(value in ('CAN1', 'FMC_NAND') for key, value in ioc.items() if key.startswith('Mcu.IP')),
        'no Challenger V2 NAND or CAN/LTDC conflict enabled')
require(ioc['NVIC.TimeBase'] == 'TIM6_DAC_IRQn', 'HAL timebase IRQ')
require(ioc['FREERTOS.configTOTAL_HEAP_SIZE'] == '24576', 'RTOS heap budget')
for file in [p for base in ('Core', 'USB_DEVICE') for p in (root / base).rglob('*')]:
    if file.suffix not in ('.c', '.h'):
        continue
    text = file.read_text(encoding='utf-8')
    begins = re.findall(r'/\* USER CODE BEGIN ([^*]+) \*/', text)
    ends = re.findall(r'/\* USER CODE END ([^*]+) \*/', text)
    require(sorted(begins) == sorted(ends), 'USER CODE markers ' + file.name)
freertos = (root / 'Core/Src/freertos.c').read_text(encoding='utf-8')
require('gs_app_init();' in freertos and 'osThreadExit();' in freertos, 'app hooks survive generation')
require('gs_app_fatal(0x21U)' in freertos and 'gs_app_fatal(0x22U)' in freertos, 'RTOS failure hooks')
irq = (root / 'Core/Src/stm32f4xx_it.c').read_text(encoding='utf-8')
require(irq.count('HAL_TIM_IRQHandler(&htim6);') == 1, 'TIM6 dispatch exactly once')
require(irq.count('HAL_PCD_IRQHandler(&hpcd_USB_OTG_HS);') == 1, 'USB device IRQ exactly once')
require('void SysTick_Handler' not in irq, 'no duplicate SysTick owner')
timebase = (root / 'Core/Src/stm32f4xx_hal_timebase_tim.c').read_text(encoding='utf-8')
require('HAL_NVIC_EnableIRQ(TIM6_DAC_IRQn)' in timebase, 'TIM6 NVIC')
main = (root / 'Core/Src/main.c').read_text(encoding='utf-8')
require('HAL_IncTick();' in main and 'htim->Instance == TIM6' in main, 'HAL tick callback')
require('RCC_PLLSOURCE_HSE' in main and 'RCC_PLL_ON' in main, 'HSE PLL generated clock')
fmc = (root / 'Core/Src/fmc.c').read_text(encoding='utf-8')
require('gs_board_sdram_init();' in fmc and 'FMC_SDRAM_BANK2' in fmc, 'SDRAM boot hook and bank')
require('FMC_SDRAM_MEM_BUS_WIDTH_16' in fmc and 'FMC_SDRAM_INTERN_BANKS_NUM_4' in fmc,
        'V1 SDRAM width and internal banks')
eth = (root / 'Core/Src/eth.c').read_text(encoding='utf-8')
require('gs_board_early_init();' in eth and 'heth.Init.RxBuffLen = 1536;' in eth, 'PHY reset and RX capacity')
require('gs_board_dma_irq();' in irq, 'camera DMA evidence hook')
iwdg = (root / 'Core/Src/iwdg.c').read_text(encoding='utf-8')
require('if (!g_gs_board_diag.watchdog_started) { return; }' in iwdg,
        'IWDG startup deferred until BSP requests it')
usb_conf = (root / 'USB_DEVICE/Target/usbd_conf.c').read_text(encoding='utf-8')
cdc = (root / 'USB_DEVICE/App/usbd_cdc_if.c').read_text(encoding='utf-8')
usb_init = (root / 'USB_DEVICE/App/usb_device.c').read_text(encoding='utf-8')
usb_capture = (root / 'BSP/Src/gs_usb_capture.c').read_text(encoding='utf-8')
usb_protocol = (root / 'Modules/UsbCapture/Src/gs_usb_protocol.c').read_text(encoding='utf-8')
require('Init.phy_itface = USB_OTG_EMBEDDED_PHY;' in usb_conf and
        'Init.speed = PCD_SPEED_FULL;' in usb_conf and
        'Init.vbus_sensing_enable = DISABLE;' in usb_conf, 'generated device FS PHY')
require('HAL_PCDEx_SetTxFiFo(&hpcd_USB_OTG_HS, 2, 0x10);' in cdc and
        'gs_usb_capture_receive(Buf, *Len);' in cdc and
        'gs_usb_capture_tx_complete();' in cdc, 'CDC notification FIFO and async hooks')
require('!g_gs_usb_diag.initialized || started' in usb_init, 'USB startup has a single owner')
require('#define CRC_STEP_BYTES 4096U' in usb_capture and
        'gs_usb_crc32_update(s->crc_state,s->data+s->crc_bytes,n)' in usb_capture and
        'At most one 4 KiB CRC slice per StorageTask service' in usb_capture and
        'gs_usb_frame_header(tx,s->id,s->ms,s->epoch,s->crc_value,uid)' in usb_capture and
        'gs_usb_crc32(s->data,GS_USB_FRAME_BYTES)' not in usb_capture and
        'uint32_t gs_usb_crc32_update' in usb_protocol and
        'uint32_t gs_usb_crc32_finish' in usb_protocol,
        'USB frame CRC is bounded to one 4 KiB slice per Storage service and cached for header retries')
require('#if !GS_ENABLE_ETHERNET' in eth, 'disabled Ethernet skips PHY initialization')
board_header = (root / 'BSP/Inc/gs_board.h').read_text(encoding='utf-8')
memory_map = (root / 'BSP/Inc/gs_memory_map.h').read_text(encoding='utf-8')
board_source = (root / 'BSP/Src/gs_port_board.c').read_text(encoding='utf-8')
require('GS_BOARD_PROFILE_EMBEDFIRE_F429_CHALLENGER_V1' in board_header and
        'GS_BOARD_W25Q128_JEDEC' in board_header and '0x00800000UL' in memory_map,
        'explicit Challenger V1 board identity, W25Q128 and 8 MiB capacity')
require('flash_profile_match' in board_source and 'expected_sdram_bytes' in board_source,
        'debugger-visible V1 diagnostics')
for handle in ['hdcmi', 'heth', 'hltdc']:
    require(('(&' + handle + ');') in irq, 'peripheral IRQ dispatch ' + handle)

project = root / 'MDK-ARM/GestureScreen.uvprojx'
tree = ET.parse(project)
require(tree.findtext('./Targets/Target/uAC6') == '1', 'AC6 selected')
paths = []
for node in tree.findall('.//FilePath'):
    file = (project.parent / node.text.replace('\\', '/')).resolve()
    require(file.is_file(), 'Keil source exists: ' + str(file))
    paths.append(file)
require(len(paths) == len(set(paths)), 'no duplicate translation units')
require(sum(p.name == 'port.c' for p in paths) == 1, 'exactly one RTOS port')
require(any('GCC/ARM_CM4F/port.c' in p.as_posix() for p in paths), 'AC6-compatible RTOS port')
for base in ['App', 'BSP', 'Modules']:
    for file in (root / base).rglob('*.c'):
        if file.name == 'gs_static_weights.c':
            require(file.resolve() not in paths, 'reference weights excluded from Cube.AI firmware')
            continue
        require(file.resolve() in paths, 'user source in Keil: ' + str(file))
require('GS_STATIC_USE_CUBEAI=1' in tree.findtext('.//Cads/VariousControls/Define'), 'Cube.AI deployment enabled')
require(any(p.name == 'gs_network.c' for p in paths), 'Cube.AI generated network linked')
require(any(p.name == 'NetworkRuntime1201_CM4_Keil.lib' for p in paths), 'official Cortex-M4 runtime linked')
generated_header = (root / 'Middlewares/ST/AI/Generated/gs_network.h').read_text(encoding='utf-8')
require('#define STAI_GS_NETWORK_ORIGIN_MODEL_NAME         "gesture_v12_int8"' in generated_header,
        'selected six-class origin model name')
require('#define STAI_GS_NETWORK_ORIGIN_MODEL_SIGNATURE    "0xd296874353b574cf6412d26f8fecd5cb"' in generated_header,
        'selected six-class origin model signature')
require('#define STAI_GS_NETWORK_MODEL_SIGNATURE           (0xddc721ed9c76cc82)' in generated_header,
        'approved generated network signature')
require(tree.findtext('.//LDads/ScatterFile') == '.\\GestureScreen.sct', 'explicit scatter selected')
scatter = (root / 'MDK-ARM/GestureScreen.sct').read_text(encoding='utf-8')
require('0x08000000 0x00100000' in scatter and '0x20000000 0x00030000' in scatter, 'linker capacities')
require('0xD0000000' not in scatter, 'no uninitialized SDRAM ZI')
require('RW_CCM_AI 0x10000000 UNINIT 0x00010000' in scatter and
        '*(.bss.ccm.ai_arena)' in scatter, 'explicit UNINIT CPU-only CCM arena region')
board_source = (root / 'BSP/Src/gs_port_board.c').read_text(encoding='utf-8')
backend_source = (root / 'Modules/StaticRecognition/Src/gs_cubeai_backend.c').read_text(encoding='utf-8')
require('__HAL_RCC_CCMDATARAMEN_CLK_ENABLE()' in board_source and
        '__HAL_RCC_CCMDATARAMEN_IS_CLK_ENABLED()' in board_source,
        'CCM clock explicitly enabled and verified before tasks')
require('section(".bss.ccm.ai_arena")' in backend_source and
        'if (!arena_initialized)' in backend_source and 'memset(arena, 0, sizeof(arena))' in backend_source,
        'Cube.AI arena has explicit CCM placement and first-use initialization')

app_source = (root / 'App/Src/gs_app.c').read_text(encoding='utf-8')
trace_header = (root / 'App/Inc/gs_timing_trace.h').read_text(encoding='utf-8')
trace_source = (root / 'App/Src/gs_timing_trace.c').read_text(encoding='utf-8')
ui_render = (root / 'Modules/Ui/Src/gs_ui_render.c').read_text(encoding='utf-8')
require('GS_TIMING_TRACE_CAPACITY 32U' in trace_header and
        'inference_scheduled_cycles' in trace_header and
        'observations_enqueued' in trace_header and 'observations_consumed' in trace_header and
        'reset_discarded' in trace_header, 'fixed frame timing trace ABI and queue accounting')
require('slot->end_sequence = 0U;' in trace_source and
        'slot->begin_sequence = sequence;' in trace_source and
        'g_gs_timing_trace.published_sequence = sequence;' in trace_source,
        'guarded trace publication with published sequence last')
require('gs_gesture_envelope_t' in app_source and
        'sizeof(gs_gesture_envelope_t)' in app_source and
        'GS_VISION_START_INTERVAL_MS' not in app_source and
        'gs_keys' not in app_source, 'trace envelope without rejected budget or Keys candidate')
require('GS_VISION_DEQUEUE_REMAINING_BUDGET_MS 200U' in app_source and
        'GS_VISION_PREPROCESS_REMAINING_BUDGET_MS 220U' in app_source and
        'GS_VISION_ADMISSION_MAX_AGE_MS' in app_source and
        'GS_VISION_PREPROCESS_ADMISSION_MAX_AGE_MS' in app_source and
        'g_gs_deadline_admission_drops' in app_source and
        'g_gs_preprocess_admission_drops' in app_source and
        'dequeue_age_ms > GS_VISION_TERMINAL_MAX_AGE_MS' in app_source and
        '!vision_deadline_admit(frame.capture_ms, dequeue_ms)' in app_source and
        'vision_preprocess_deadline_expired(frame->capture_ms' in app_source,
        'two-stage deadline admission rejects doomed work before model start')
require('GS_GUI_INCREMENTAL_BEGIN' in board_source and
        'gs_display_buffer_history_t display_buffer_history[2]' in board_source and
        'history->valid = false;' in board_source and
        '*history = staged_history;' in board_source,
        'per-physical-buffer incremental history invalidated on paint and committed after arm')
require('gs_display_recognition_key_t' in board_source and
        'gs_display_result_age_key_t' in board_source and
        'gs_display_preview_age_key_t' in board_source and
        'gs_display_detail_key_t' in board_source and
        'gs_display_gesture_key_t' in board_source and
        'dirty_region_count != 0U' in board_source and
        'preview_visible = false;' in board_source,
        'reader screen uses incremental updates without camera overlay')
require('gs_ui_render_dashboard_regions_rgb565' in ui_render and
        'canvas->region_count' in ui_render, 'reader partial path reuses clipped full composition')

content_manifest = json.loads((root / 'Modules/Content/Src/gs_content_builtin.json').read_text(encoding='utf-8'))
require(content_manifest.get('source_sha256') ==
        hashlib.sha256((root / 'Assets/content/package.json').read_bytes()).hexdigest(),
        'content source manifest regenerated from current package.json')
require(content_manifest.get('generated_sha256') ==
        hashlib.sha256((root / 'Modules/Content/Src/gs_content_builtin.c').read_bytes()).hexdigest(),
        'content C package matches generator manifest')
glyph_text = (root / 'Modules/Ui/Inc/gs_ui_font_aa_subset.h').read_text(encoding='utf-8')
glyphs = {int(value, 16) for value in re.findall(r'\{0x([0-9A-F]{4})U,\d+U,\{', glyph_text)}
package = json.loads((root / 'Assets/content/package.json').read_text(encoding='utf-8'))
required_glyphs = set(content_manifest.get('non_ascii_requires_font_check', []))
for collection in package['collections']:
    for value in (collection['title'], collection.get('author', '')):
        required_glyphs.update(ch for ch in value if ord(ch) >= 0x80 and ch.isprintable())
    for page in collection['pages']:
        for value in (page['title'], page['body']):
            required_glyphs.update(ch for ch in value if ord(ch) >= 0x80 and ch.isprintable())
for relative in ('Modules/Ui/Src/gs_ui_render.c', 'App/Src/gs_app.c'):
    source = (root / relative).read_text(encoding='utf-8-sig')
    for literal in re.findall(r'"([^"\n]*)"', source):
        required_glyphs.update(ch for ch in literal if ord(ch) >= 0x80 and ch.isprintable())
require(all(ord(ch) in glyphs for ch in required_glyphs),
        'all reader content and UI non-ASCII glyphs are present in the generated font')
heading_chars = set()
for collection in package['collections']:
    for value in (collection['title'], collection.get('author', '')):
        heading_chars.update(ch for ch in value if ord(ch) >= 0x80 and ch.isprintable())
    for page in collection['pages']:
        heading_chars.update(ch for ch in page['title'] if ord(ch) >= 0x80 and ch.isprintable())
for literal in re.findall(r'"([^"\n]*)"',
        (root / 'Modules/Ui/Src/gs_ui_render.c').read_text(encoding='utf-8-sig')):
    heading_chars.update(ch for ch in literal if ord(ch) >= 0x80 and ch.isprintable())
font32_section = glyph_text.split('static const gs_aa_glyph_32_t gs_font32[] = {', 1)[1]
glyphs32 = {int(value, 16) for value in re.findall(r'\{0x([0-9A-F]{4})U,\d+U,\{', font32_section)}
require(all(ord(ch) in glyphs32 for ch in heading_chars),
        'native 32px headings and UI labels have complete font coverage')

sdk = Path(ioc['ProjectManager.CustomerFirmwarePackage'].replace('\\:', ':').replace('\\\\', '\\'))
for name in ['port.c', 'portmacro.h']:
    relative = Path('Middlewares/Third_Party/FreeRTOS/Source/portable/GCC/ARM_CM4F') / name
    if sdk.exists():
        require(hashlib.sha256((sdk / relative).read_bytes()).digest() ==
                hashlib.sha256((root / relative).read_bytes()).digest(), 'unmodified SDK port ' + name)

if args.with_build:
    map_text = (root / 'MDK-ARM/Objects/GestureScreen.map').read_text(encoding='utf-8')
    require('Load Region LR_IROM1 (Base: 0x08000000' in map_text, 'actual ROM region')
    require(re.search(r'Execution Region RW_IRAM1 .*Exec base: 0x20000000.*Max: 0x00030000', map_text), 'actual SRAM region')
    require(re.search(r'Execution Region RW_CCM_AI .*Exec base: 0x10000000.*Size: 0x0000e500.*Max: 0x00010000.*UNINIT', map_text),
            'actual CCM region contains the 58624-byte UNINIT arena')
    require(re.search(r'arena\s+0x10000000\s+Data\s+58624\s+gs_cubeai_backend\.o\(\.bss\.ccm\.ai_arena\)', map_text),
            'Cube.AI arena symbol is the sole expected CCM payload')
    require(map_text.count('gs_cubeai_backend.o(.bss.ccm.ai_arena)') >= 1 and
            map_text.count('.bss.ccm.ai_arena') < 8, 'CCM arena section is singular')
    sections, symbols, segments, virtual_bytes = elf32_sections_and_symbols(
        root / 'MDK-ARM/Objects/GestureScreen.axf')
    ccm = [section for section in sections if section['name'] == 'RW_CCM_AI']
    require(len(ccm) == 1 and ccm[0]['type'] == 8 and ccm[0]['addr'] == 0x10000000 and
            ccm[0]['size'] == 58624, 'AXF CCM section is exactly one SHT_NOBITS arena')
    require(not any(segment['type'] == 1 and segment['vaddr'] <= 0x10000000 <
                    segment['vaddr'] + segment['memsz'] for segment in segments),
            'AXF has no PT_LOAD segment targeting CCM')
    require('Region$$Table$$Base' in symbols and 'Region$$Table$$Limit' in symbols,
            'AXF Region Table symbols')
    region_base = symbols['Region$$Table$$Base'][0]
    region_limit = symbols['Region$$Table$$Limit'][0]
    region_table = virtual_bytes(region_base, region_limit - region_base)
    require(region_table is not None and struct.pack('<I', 0x10000000) not in region_table,
            'AXF Region Table has no startup copy/decompress/zero descriptor targeting CCM')
    rom = re.search(r'Total ROM Size .*?([0-9]+) \(', map_text).group(1)
    ram = re.search(r'Total RW  Size .*?([0-9]+) \(', map_text).group(1)
    require(int(rom) <= 928 * 1024 and int(ram) <= 168 * 1024, 'current map within project budgets')
    require('cmsis_os2.o(.text.SysTick_Handler)' in map_text, 'linked RTOS tick')
    require('stm32f4xx_it.o(.text.TIM6_DAC_IRQHandler) refers to stm32f4xx_hal_tim.o' in map_text, 'linked HAL tick dispatch')
    require('gs_usb_capture.o' in map_text and 'usbd_cdc.o' in map_text, 'USB sender and class linked')
    for suffix in ['axf', 'hex']:
        require((root / ('MDK-ARM/Objects/GestureScreen.' + suffix)).stat().st_size > 0, 'build artifact ' + suffix)
    print(f'Actual map: ROM {rom} bytes; RW+ZI {ram} bytes. Hardware not tested.')
print('PASS: source, CubeMX, IRQ, Keil and memory ownership structure.')
