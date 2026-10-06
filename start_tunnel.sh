#!/bin/bash
LOG_FILE="/home/vale/cloudflared.log"
URL_FILE="/home/vale/tunnel_url.txt"

rm -f "$URL_FILE"

cloudflared tunnel --url http://127.0.0.1:5000 --logfile "$LOG_FILE" &
CPID=$!

for i in $(seq 1 30); do
    if [ -f "$LOG_FILE" ]; then
        URL=$(grep -o 'https://[-a-z0-9]*\.trycloudflare\.com' "$LOG_FILE" | head -n 1)
        if [ -n "$URL" ]; then
            echo "$URL" > "$URL_FILE"
            echo "Tunnel online: $URL"
            break
        fi
    fi
    sleep 1
done

wait $CPID
