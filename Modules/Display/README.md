# LCD buffer ownership

`gs_display_swap` manages two external framebuffers without touching LTDC or
DMA2D. GuiTask serializes every API call; IRQs queue messages. Initialize with
buffer0 already selected for LTDC scanout, or with LTDC stopped and configured to
start at buffer0. Both buffers must have valid initial content and reside in
verified LTDC/DMA2D-accessible storage, not CCM. Camera storage must not overlap.

Each update follows one sequence:

1. `gs_display_begin()` reserves the back buffer and returns immutable front,
   writable back, full byte length, and a submission token.
2. For partial updates, copy the **entire front frame** into back once, then wait for the copy/DMA2D to
   finish. Call `gs_display_copy_complete()` before drawing. This explicit step
   protects unchanged screen regions from alternating stale contents. The module
   checks the step order; it cannot inspect whether the physical copy occurred.
   For a full repaint, copying may be skipped: call `copy_complete`, then overwrite
   the entire back canvas before submit. The current BSP uses this path and skips
   unchanged UI/preview redraws, while still repainting an expired preview.
3. Draw all dirty areas/stripes into back. Wait for every drawing operation and
   DMA2D job to finish. `gs_display_submit()` makes back immutable and returns the
   address to request as the next LTDC framebuffer at vertical blanking.
4. Capture a completion report for that specific LTDC reload, including the token
   and confirmed active address. Call `gs_display_reload_confirm()` only after
   actual reload completion. A VSYNC interrupt alone, a shadow-register write,
   or a call that requests reload does not prove that the address became active.
5. Only successful confirmation releases old front as the next writable back.
   Starting another composition or cancelling while pending is rejected.

If the hardware reload request fails or its event is lost, remain PENDING and
reconcile/retry the hardware request in the BSP. Do not guess completion or reuse
old front. A full recovery/reinitialization requires stopped LTDC/DMA2D and drained
old completion messages. Cancellation before submit is allowed only after copy
and drawing engines become idle. The next update must preserve unchanged regions
by copying or repaint the entire canvas.

Tokens never wrap into reuse. After uint32 token exhaustion, stop and drain all
hardware/messages before reinitializing. Callers may inspect metadata but must not
change it. The header documents ownership preconditions; host tests cover state
transitions and preservation of unchanged regions, not LTDC timing or hardware
bus bandwidth.
