#include "gs_usb_protocol.h"
#include <string.h>
static uint32_t read32(const uint8_t *p)
{
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static void write32(uint8_t *p, uint32_t v)
{
    p[0]=(uint8_t)v; p[1]=(uint8_t)(v>>8); p[2]=(uint8_t)(v>>16); p[3]=(uint8_t)(v>>24);
}
uint32_t gs_usb_crc32_update(uint32_t state, const void *data, size_t bytes)
{
    static const uint32_t table[16] = {
        0x00000000U,0x1DB71064U,0x3B6E20C8U,0x26D930ACU,
        0x76DC4190U,0x6B6B51F4U,0x4DB26158U,0x5005713CU,
        0xEDB88320U,0xF00F9344U,0xD6D6A3E8U,0xCB61B38CU,
        0x9B64C2B0U,0x86D3D2D4U,0xA00AE278U,0xBDBDF21CU
    };
    const uint8_t *p=data;
    while (bytes-- != 0U) {
        state ^= *p++;
        state = (state >> 4) ^ table[state & 15U];
        state = (state >> 4) ^ table[state & 15U];
    }
    return state;
}
uint32_t gs_usb_crc32_finish(uint32_t state)
{
    return state ^ UINT32_MAX;
}
uint32_t gs_usb_crc32(const void *data, size_t bytes)
{
    return gs_usb_crc32_finish(gs_usb_crc32_update(
        GS_USB_CRC32_INITIAL, data, bytes));
}
bool gs_usb_decode_control(const uint8_t *p, gs_usb_control_t *c)
{
    if (memcmp(p,"GSCT",4)!=0 || read32(p+20)!=gs_usb_crc32(p,20)) return false;
    c->enabled=read32(p+4); c->interval_ms=read32(p+8);
    c->epoch=read32(p+12); c->cookie=read32(p+16);
    return c->enabled<=1U && c->interval_ms>=200U && c->interval_ms<=5000U;
}
void gs_usb_frame_header(uint8_t *p, uint32_t id, uint32_t ms,
                         uint32_t epoch, uint32_t crc, const uint32_t uid[3])
{
    memset(p,0,GS_USB_HEADER_BYTES); memcpy(p,"GSFR",4);
    p[4]=1; p[6]=GS_USB_HEADER_BYTES;
    write32(p+8,GS_USB_FRAME_BYTES); write32(p+12,id);
    write32(p+16,ms); write32(p+20,epoch);
    p[24]=0x40; p[25]=1; p[26]=0xf0; /* 320 x 240 */
    write32(p+28,1); write32(p+32,crc);
    write32(p+36,uid[0]); write32(p+40,uid[1]); write32(p+44,uid[2]);
}
