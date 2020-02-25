#!/usr/bin/env sh

export PATH=${PATH}:/usr/local/bin:/usr/sbin

pip3 install youtube-dl
crond
exec python3 main.py
