set pagination off
set confirm off
set print thread-events off
set sysroot /home/marius/ext_proj/touch10/development/perrier-qt/runtime
set solib-search-path /home/marius/ext_proj/touch10/development/perrier-qt/qt-arm/lib:/home/marius/ext_proj/touch10/development/perrier-qt/runtime/lib
file /home/marius/ext_proj/touch10/development/perrier-qt/build-arm-a9-local/perrier-touch-grid
target remote | ssh -F /home/marius/ext_proj/touch10/access/ssh_config touch10-ram 'PERRIER_QT_DURATION_MS=3000 PERRIER_QT_APP=/qt/bin/perrier-touch-grid /usr/bin/qt-run --gdb'
continue
bt 20
thread apply all bt 10
