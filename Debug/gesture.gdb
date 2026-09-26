# Open server first with Tools/firedap.ps1 -Action Server. From MDK-ARM:
# arm-none-eabi-gdb -x ../Debug/gesture.gdb Objects/GestureScreen.axf
set pagination off
target extended-remote 127.0.0.1:3333
monitor reset halt
break main
break gs_app_fatal
break Error_Handler
break HardFault_Handler
# Continue manually after wiring/boot settings have been checked.
