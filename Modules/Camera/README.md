# Camera frame ownership

`gs_camera_pool` is a C99 metadata module, not an OV2640 or HAL driver. Two
caller-owned image buffers remain separate from LCD framebuffers. No large image
array, allocator, RTOS dependency or assumed SDRAM address is hidden here.

Only CameraTask modifies the pool. ISR callbacks send bounded messages containing
the capture ticket, event bits, total DMA bytes and errors. VisionTask obtains a
lease and releases it by request to CameraTask; it must not call pool methods from
another task concurrently. A critical section around a callback alone does not
make an entire begin/report/finish operation atomic.

## Adapter sequence

1. Initialize two nonoverlapping DMA-accessible buffers after SDRAM validation.
   Planned 320 x 240 RGB565 frames need 153,600 bytes each, aligned to four bytes.
   DCMI's intended 32-bit transfer uses 38,400 DMA items. The BSP must verify its
   actual HAL transfer units and convert the final count into bytes. CCM cannot
   hold these buffers.
2. `gs_camera_begin()` reserves a FREE slot and returns a capture ticket plus the
   DMA destination. BUSY means skip this capture; do not reuse a PROCESSING slot.
   Bind the ticket to this hardware transaction before enabling capture.
3. `gs_camera_report()` accumulates FRAME_END, DMA_DONE, received byte count and
   errors. Either callback can arrive first. Each DMA_DONE must describe the
   complete transfer, not a half-transfer or an individual DMA segment. Reporting
   both completion events still leaves the slot CAPTURING.
4. After both events, the BSP checks snapshot/DMA stopped writing, handles pending
   IRQs, drains this ticket's reports and samples final DCMI/DMA error flags. Only
   then call `gs_camera_finish_quiesced()` with the actual frame-end timestamp and
   final errors. It publishes READY only for exact length and no errors. The
   timestamp must use the same millisecond clock as gesture freshness checks.
5. `gs_camera_acquire_latest()` returns the newest READY lease, frees older READY
   slots and leaves PROCESSING slots untouched. Perform preprocessing and any
   preview copy before `gs_camera_release()`. A GUI cannot retain the raw pointer
   after release. Inference should retain only its copied small input tensor.

On start failure, timeout, queue overflow, DCMI overrun or DMA error, stop both
engines, wait for DMA disable/idle, clear pending interrupts and drain messages;
then call `gs_camera_abort_quiesced()`. Never free a destination while hardware
can write it. Finalization of a failed quiesced frame also reclaims it safely.
An error event with no completion flags is allowed; `error_flags != 0` poisons the
capture. Error recovery and counters belong to the BSP/HealthTask.

The ticket must be captured at event creation. Do not relabel an old IRQ using the
currently active ticket. Queue overflow needs an independently observable fault
latch or an equivalent reliable recovery signal, since the error queue may itself
be full. After recovery, refuse old-ticket messages; the pool performs this check
again. A release also checks the ticket to protect a reused slot from a late
consumer message.

Tokens increase without reuse. Once all uint32 tokens have been used, new begin
returns TOKEN_EXHAUSTED. Controlled reinitialization then requires hardware and
consumers stopped, no outstanding leases, and all old messages discarded. This is
intentional protection against a very late event matching a wrapped token.

Fields are public for fixed allocation and inspection, but callers must not
mutate them outside the API. `Tests/test_buffers.c` checks ownership, event order,
incomplete/error rejection, late messages, slow consumers and token exhaustion.
Hardware quiescence and DMA accessibility require board validation; host tests do
not establish them.
