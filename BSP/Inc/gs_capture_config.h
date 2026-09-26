#ifndef GS_CAPTURE_CONFIG_H
#define GS_CAPTURE_CONFIG_H
/* USB和以太网采集功能均完整保留，目前默认使用USB。
 * 使用以太网时改为USB=0、Ethernet=1并重新编译。
 * 两种上传方式共用SDRAM槽，一次选择一种。 */
#ifndef GS_ENABLE_USB_CAPTURE
#define GS_ENABLE_USB_CAPTURE 1
#endif
#ifndef GS_ENABLE_ETHERNET
#define GS_ENABLE_ETHERNET 0
#endif
#if GS_ENABLE_USB_CAPTURE && GS_ENABLE_ETHERNET
#error "Choose one capture transport: USB and Ethernet share the upload slots"
#endif
#endif
