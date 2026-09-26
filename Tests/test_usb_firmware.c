/* Exercise the production sender with a manually completed asynchronous USB
 * transfer. Mocks replace only hardware calls, not ownership/timeout logic. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "../BSP/Src/gs_usb_capture.c"
uint32_t mock_frames[2][153600/4];
USBD_HandleTypeDef hUsbDeviceHS;
static uint32_t clock_ms, irq_mask;
static uint8_t pending[4096], wire[153600+48], pixels[153600];
static uint32_t pending_bytes, wire_bytes, submit_status;
uint32_t HAL_GetTick(void) { return clock_ms; }
uint32_t HAL_GetUIDw0(void) { return 1; }
uint32_t HAL_GetUIDw1(void) { return 2; }
uint32_t HAL_GetUIDw2(void) { return 3; }
uint32_t __get_PRIMASK(void) { return irq_mask; }
void __disable_irq(void) { irq_mask=1; }
void __set_PRIMASK(uint32_t value) { irq_mask=value; }
void MX_USB_DEVICE_Init(void) { hUsbDeviceHS.dev_state=3; hUsbDeviceHS.pClassData=&hUsbDeviceHS; }
uint8_t CDC_Transmit_HS(uint8_t *data,uint16_t bytes)
{
    assert(irq_mask==1);
    if (submit_status!=USBD_OK) return (uint8_t)submit_status;
    assert(pending_bytes==0); assert(bytes<=sizeof(pending));
    memcpy(pending,data,bytes); pending_bytes=bytes; return 0;
}
static void complete(void)
{
    assert(pending_bytes>0); assert(memcmp(pending,tx,pending_bytes)==0);
    assert(wire_bytes+pending_bytes<=sizeof(wire));
    memcpy(wire+wire_bytes,pending,pending_bytes); wire_bytes+=pending_bytes;
    pending_bytes=0; gs_usb_capture_tx_complete();
}
static void control(uint32_t on,uint32_t e,uint32_t c)
{
    uint8_t p[24]={0}; memcpy(p,"GSCT",4);
    /* LE MSVC test host, same explicit little-endian wire contract. */
    memcpy(p+4,&on,4); uint32_t period=200; memcpy(p+8,&period,4);
    memcpy(p+12,&e,4); memcpy(p+16,&c,4);
    uint32_t crc=gs_usb_crc32(p,20); memcpy(p+20,&crc,4);
    gs_usb_capture_receive(p,7); gs_usb_capture_receive(p+7,17);
    gs_usb_capture_step(clock_ms);
}
static void reset(void)
{
    memset(slots,0,sizeof(slots)); memset((void *)&g_gs_usb_diag,0,sizeof(g_gs_usb_diag));
    rx_write=rx_read=link_generation=tx_busy=0; enabled=epoch=cookie=control_ms=0;
    seen_generation=command_bytes=last_offer_ms=offer_seen=0;
    last_offer_epoch=last_offer_cookie=offset=start_ms=header_sent=offer_sequence=0; active=-1;
    pending_bytes=wire_bytes=submit_status=irq_mask=0; clock_ms=100;
    memset(pixels,0xa5,sizeof(pixels)); gs_usb_capture_init();
}
static void prepare_active_crc(void)
{
    unsigned budget=(GS_USB_FRAME_BYTES+CRC_STEP_BYTES-1U)/CRC_STEP_BYTES+1U;
    while ((active<0 || !slots[active].crc_ready) && budget--) {
        uint32_t before=active>=0 ? slots[active].crc_bytes : 0U;
        gs_usb_capture_step(clock_ms);
        assert(active>=0 && pending_bytes==0U);
        assert(slots[active].crc_bytes>=before &&
            slots[active].crc_bytes-before<=CRC_STEP_BYTES);
    }
    assert(active>=0 && slots[active].crc_ready);
    assert(slots[active].crc_bytes==GS_USB_FRAME_BYTES);
    assert(slots[active].crc_value==gs_usb_crc32(slots[active].data,GS_USB_FRAME_BYTES));
}
static void submit_header(void)
{
    prepare_active_crc();
    gs_usb_capture_step(clock_ms);
    assert(pending_bytes==GS_USB_HEADER_BYTES && header_sent);
}
static void finish_frame(uint32_t count,uint32_t expected_id)
{
    unsigned budget=100;
    while(g_gs_usb_diag.sent<count && budget--) {
        gs_usb_capture_step(clock_ms); if(pending_bytes) complete(); ++clock_ms;
    }
    assert(g_gs_usb_diag.sent==count && g_gs_usb_diag.last_frame_id==expected_id);
    assert(pending_bytes==0 && wire_bytes==sizeof wire);
    uint32_t header_id; memcpy(&header_id,wire+12,4); assert(header_id==expected_id);
    wire_bytes=0;
}
int main(int argc,char **argv)
{
    assert(gs_usb_crc32("123456789",9)==0xcbf43926U);
    {
        const char vector[]="123456789";
        uint32_t state=GS_USB_CRC32_INITIAL;
        state=gs_usb_crc32_update(state,vector,1U);
        state=gs_usb_crc32_update(state,vector+1,3U);
        state=gs_usb_crc32_update(state,vector+4,5U);
        assert(gs_usb_crc32_finish(state)==gs_usb_crc32(vector,9U));
    }
    reset(); control(1,UINT32_MAX,7);
    assert(gs_usb_capture_offer(pixels,sizeof(pixels),42,clock_ms));
    memset(pixels,0,sizeof(pixels)); /* camera immediately reuses its lease */
    for (unsigned i=0;i<100;++i) {
        gs_usb_capture_step(clock_ms); if (pending_bytes) complete(); clock_ms+=2;
    }
    assert(g_gs_usb_diag.sent==1 && wire_bytes==sizeof(wire));
    assert(memcmp(wire,"GSFR",4)==0 && wire[12]==42 && wire[20]==255);
    uint32_t crc; memcpy(&crc,wire+32,4);
    assert(crc==gs_usb_crc32(wire+48,153600) && wire[48]==0xa5);
    if (argc==2) { FILE *f=NULL; assert(fopen_s(&f,argv[1],"wb")==0); assert(fwrite(wire,1,wire_bytes,f)==wire_bytes); fclose(f); }

    reset(); control(1,1,1);
    assert(gs_usb_capture_offer(pixels,sizeof(pixels),1,100));
    assert(!gs_usb_capture_offer(pixels,sizeof(pixels),2,101));
    assert(gs_usb_capture_offer(pixels,sizeof(pixels),2,300));
    assert(!gs_usb_capture_offer(pixels,sizeof(pixels),3,500));
    assert(!gs_usb_capture_offer(pixels,1,4,600));
    submit_header();
    gs_usb_capture_step(clock_ms); assert(pending_bytes==48); /* no overwrite */
    control(0,2,1); assert(active==-1 && g_gs_usb_diag.dropped==2);
    complete(); /* in-flight staging remains immutable despite slot release */
    assert(slots[0].state==FREE && slots[1].state==FREE);

    reset(); control(1,1,1); assert(gs_usb_capture_offer(pixels,sizeof(pixels),1,100));
    submit_header(); complete();
    control(1,1,2); /* host connection cookie changes while epoch is identical */
    assert(g_gs_usb_diag.dropped==1 && active==-1);
    assert(gs_usb_capture_offer(pixels,sizeof(pixels),2,101));

    reset(); control(1,1,1); assert(gs_usb_capture_offer(pixels,sizeof(pixels),1,100));
    submit_header();
    clock_ms+=1501; gs_usb_capture_step(clock_ms);
    assert(active==-1 && !g_gs_usb_diag.capture_enabled); complete();
    assert(!gs_usb_capture_offer(pixels,sizeof(pixels),2,clock_ms));

    reset(); control(1,1,1); assert(gs_usb_capture_offer(pixels,sizeof(pixels),1,100));
    submit_header(); pending_bytes=0; gs_usb_capture_link_reset();
    gs_usb_capture_step(clock_ms); assert(!enabled && active==-1 && !tx_busy);
    control(1,2,2); assert(gs_usb_capture_offer(pixels,sizeof(pixels),2,101));

    reset(); clock_ms=UINT32_MAX-10; control(1,1,1); clock_ms=30;
    assert(gs_usb_capture_offer(pixels,sizeof(pixels),1,clock_ms));
    prepare_active_crc();
    { uint32_t cached=slots[active].crc_value, bytes=slots[active].crc_bytes;
      submit_status=USBD_BUSY; gs_usb_capture_step(clock_ms); assert(!tx_busy && !header_sent);
      assert(slots[active].crc_value==cached && slots[active].crc_bytes==bytes);
      submit_status=USBD_FAIL; gs_usb_capture_step(clock_ms); assert(g_gs_usb_diag.tx_errors==1);
      assert(slots[active].crc_value==cached && slots[active].crc_bytes==bytes); }
    submit_status=USBD_OK; gs_usb_capture_step(clock_ms); assert(tx_busy); complete();

    reset(); uint8_t junk[256]={0}; gs_usb_capture_receive(junk,256);
    gs_usb_capture_receive(junk,1); assert(g_gs_usb_diag.rx_overflow==1);
    gs_usb_capture_step(clock_ms); control(1,1,1); assert(enabled && g_gs_usb_diag.bad_controls>0);

    /* Producer refills slot0 between its completion and the next consumer step.
       The waiting slot1 must precede that newer publication. Test rollover too. */
    for(unsigned wrapping=0;wrapping<2;++wrapping) {
        reset(); control(1,77,99); if(wrapping) offer_sequence=UINT32_MAX;
        assert(gs_usb_capture_offer(pixels,sizeof pixels,1,100));
        submit_header(); assert(active==0); complete();
        clock_ms=300; assert(gs_usb_capture_offer(pixels,sizeof pixels,2,300));
        assert(slots[1].state==READY);
        finish_frame(1,1); assert(active==-1 && slots[0].state==FREE);
        clock_ms=500; assert(gs_usb_capture_offer(pixels,sizeof pixels,3,500));
        submit_header(); assert(active==1); complete();
        finish_frame(2,2); finish_frame(3,3);
        assert(slots[0].state==FREE && slots[1].state==FREE);
        assert(offer_sequence==(wrapping?2U:3U));
    }
    /* Two READY publications spanning serial rollover, before either starts. */
    reset(); control(1,1,1); offer_sequence=UINT32_MAX;
    assert(gs_usb_capture_offer(pixels,sizeof pixels,17,100));
    clock_ms=300; assert(gs_usb_capture_offer(pixels,sizeof pixels,18,300));
    submit_header(); assert(active==0); complete();
    finish_frame(1,17); finish_frame(2,18);

    /* Epoch/cookie replacement discards both old READY slots before FIFO choice.
       Publication serial is not reset, so sessions do not invent a new order. */
    reset(); control(1,1,1);
    assert(gs_usb_capture_offer(pixels,sizeof pixels,31,100));
    gs_usb_capture_step(clock_ms);
    assert(active==0 && slots[0].crc_bytes==CRC_STEP_BYTES && !slots[0].crc_ready);
    control(0,1,1);
    assert(active==-1 && slots[0].state==FREE && pending_bytes==0);
    clock_ms=300; control(1,2,2);
    assert(gs_usb_capture_offer(pixels,sizeof pixels,32,300));
    gs_usb_capture_step(clock_ms);
    assert(active==0 && slots[0].crc_bytes==CRC_STEP_BYTES && !slots[0].crc_ready);
    control(1,3,3);
    assert(active==-1 && slots[0].state==FREE && pending_bytes==0);

    reset(); control(1,1,1);
    assert(gs_usb_capture_offer(pixels,sizeof pixels,1,100)); clock_ms=300;
    assert(gs_usb_capture_offer(pixels,sizeof pixels,2,300)); clock_ms=400;
    control(1,2,3); assert(g_gs_usb_diag.dropped==2 && offer_sequence==2);
    assert(slots[0].state==FREE && slots[1].state==FREE);
    assert(gs_usb_capture_offer(pixels,sizeof pixels,21,400)); clock_ms=600;
    assert(gs_usb_capture_offer(pixels,sizeof pixels,22,600));
    finish_frame(1,21); finish_frame(2,22);

    reset(); control(1,1,1);
    assert(gs_usb_capture_offer(pixels,sizeof pixels,1,100)); clock_ms=300;
    assert(gs_usb_capture_offer(pixels,sizeof pixels,2,300));
    control(0,1,1); assert(g_gs_usb_diag.dropped==2 && pending_bytes==0 && active==-1);
    assert(!gs_usb_capture_offer(pixels,sizeof pixels,3,500));
    clock_ms=600; control(1,1,1);
    assert(gs_usb_capture_offer(pixels,sizeof pixels,3,600)); finish_frame(1,3);
    puts("PASS: USB production sender ownership, CRC, controls, pause, cookie, timeout, reset, overflow, busy/failure and tick wrap.");
    puts("PASS: actual USB FIFO slot0 refill, uint32 publication rollover, epoch/cookie cleanup and STOP.");
    return 0;
}
