FROM python:3-alpine

EXPOSE 8080

WORKDIR /root/YtbDownBot

COPY src ./
COPY requirements.txt ./
COPY start.sh ./

ADD youtubedl-autoupdate /etc/periodic/hourly/youtubedl

RUN apk update && \
    apk add --no-cache git curl ffmpeg gcc musl-dev libffi-dev && \
    pip3 install --no-cache-dir -r requirements.txt  && \
    apk del gcc musl-dev libffi-dev git && \
    chmod +x ./start.sh && \
    chmod +x /etc/periodic/hourly/youtubedl && \
    touch /var/log/cron.log && \
    rm -rf /var/cache/apk/*

CMD ["./start.sh"]
