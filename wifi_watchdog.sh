#!/bin/bash
# WiFi & LAN Keep-Alive Watchdog for Intel Centrino Wireless-N 105
fails=0

while true; do
    # 1. Keep LAN presence and ARP table actively refreshed (prevents router/PC from dropping netbook)
    arping -U -c 1 -I wlp1s0 192.168.120.28 > /dev/null 2>&1
    ping -c 1 -W 2 192.168.120.1 > /dev/null 2>&1

    # 2. Test Internet and DNS connectivity
    if ! ping -c 2 -W 3 google.com > /dev/null 2>&1; then
        fails=$((fails+1))
        echo "$(date) - Ping/DNS fallido. Contador: $fails/10" >> /home/vale/swing-trading-bots/wifi_watchdog.log
    else
        if [ $fails -gt 0 ]; then
            echo "$(date) - Conexi?n y DNS recuperados. Reiniciando contador." >> /home/vale/swing-trading-bots/wifi_watchdog.log
        fi
        fails=0
    fi

    # 3. If disconnected from internet for 10 min, self-heal connection
    if [ $fails -ge 10 ]; then
        echo "$(date) - Red ca?da por 10 minutos. Reiniciando NetworkManager..." >> /home/vale/swing-trading-bots/wifi_watchdog.log
        systemctl restart NetworkManager
        fails=0
        sleep 30
    fi

    sleep 60
done
