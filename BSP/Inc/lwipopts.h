#ifndef GS_LWIPOPTS_H
#define GS_LWIPOPTS_H

/* One owner (StorageTask), NO ISR/raw calls. Deliberately no tcpip thread. */
#define NO_SYS                         1
#define SYS_LIGHTWEIGHT_PROT           0
#define LWIP_NETCONN                   0
#define LWIP_SOCKET                    0
#define LWIP_NETIF_API                 0
#define LWIP_IPV4                      1
#define LWIP_IPV6                      0
#define LWIP_ETHERNET                  1
#define LWIP_ARP                       1
#define LWIP_ICMP                      1
#define LWIP_RAW                       0
#define LWIP_TCP                       1
#define LWIP_UDP                       0
#define LWIP_DHCP                      0
#define LWIP_AUTOIP                    0
#define LWIP_DNS                       0
#define LWIP_IGMP                      0
#define LWIP_TIMERS                    1
#define LWIP_NETIF_HOSTNAME            0
#define LWIP_NETIF_STATUS_CALLBACK     0
#define LWIP_NETIF_LINK_CALLBACK       0
#define LWIP_SINGLE_NETIF              1
#define LWIP_SUPPORT_CUSTOM_PBUF       1
#define LWIP_NETIF_TX_SINGLE_PBUF       1
#define LWIP_TCP_TIMESTAMPS            0
#define TCP_QUEUE_OOSEQ                0
#define TCP_LISTEN_BACKLOG             0
#define IP_REASSEMBLY                  0
#define IP_FRAG                        0
#define MEM_ALIGNMENT                 4
#define MEM_SIZE                      (12 * 1024)
#define MEMP_NUM_PBUF                  12
#define MEMP_NUM_TCP_PCB               4
#define MEMP_NUM_TCP_PCB_LISTEN        1
#define MEMP_NUM_TCP_SEG               20
#define MEMP_NUM_SYS_TIMEOUT          6
#define PBUF_POOL_SIZE                 4
#define PBUF_POOL_BUFSIZE              1536
#define TCP_MSS                       1460
#define TCP_SND_BUF                    (4 * TCP_MSS)
#define TCP_SND_QUEUELEN               16
#define TCP_WND                       (4 * TCP_MSS)
#define TCP_MAXRTX                    6
#define TCP_SYNMAXRTX                 3
#define ARP_TABLE_SIZE                4
#define ARP_QUEUEING                  0
#define LWIP_STATS                    0
#define LWIP_STATS_DISPLAY            0
#define LWIP_DEBUG                    0
#define LWIP_CHECKSUM_CTRL_PER_NETIF   0
/* Keep checksums in software so protocol correctness does not depend on a
 * generated HAL checksum-offload setting. MAC still appends Ethernet CRC. */
#define CHECKSUM_GEN_IP                1
#define CHECKSUM_GEN_TCP               1
#define CHECKSUM_GEN_UDP               1
#define CHECKSUM_CHECK_IP              1
#define CHECKSUM_CHECK_TCP             1
#define CHECKSUM_CHECK_UDP             1

#endif
