#!/usr/bin/env sh

export PATH=${PATH}:/usr/local/bin:/usr/sbin

pip3 install youtube-dl
crond
# to wait until old connection will be reseted 
sleep 60
exec python3 main.py
