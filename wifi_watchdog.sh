#!/bin/bash
fails=0
while true; do
    # Usar un nombre de dominio (google.com) en lugar de una IP (8.8.8.8)
    # Esto garantiza que probamos TANTO la conexión a internet COMO el servicio DNS.
    if ! ping -c 3 -W 5 google.com > /dev/null 2>&1; then
        fails=$((fails+1))
        echo "$(date) - Ping/DNS fallido. Contador: $fails/12" >> /home/vale/swing-trading-bots/wifi_watchdog.log
    else
        if [ $fails -gt 0 ]; then
            echo "$(date) - Conexión y DNS recuperados. Reiniciando contador." >> /home/vale/swing-trading-bots/wifi_watchdog.log
        fi
        fails=0
    fi
    
    if [ $fails -ge 12 ]; then
        echo "$(date) - Red o DNS caídos por 60 min. Ejecutando reinicio de NetworkManager..." >> /home/vale/swing-trading-bots/wifi_watchdog.log
        systemctl restart NetworkManager
        fails=0
        sleep 60
    fi
    
    sleep 300
done
