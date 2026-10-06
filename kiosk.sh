#!/bin/bash
# Desactivar protector de pantalla y apagado de monitor
xset -dpms 2>/dev/null || true
xset s off 2>/dev/null || true
xset s noblank 2>/dev/null || true

# Ocultar cursor del mouse tras 2s inactivo
unclutter -idle 2 -root &

# Gestor de ventanas minimo
openbox &

# Esperar inicializacion
sleep 1

# Lanzar navegador ultra liviano en pantalla completa
exec nice -n 10 surf -F http://127.0.0.1:5000
