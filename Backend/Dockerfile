FROM python:3.11.4-slim-buster

RUN sed -i 's/deb.debian.org/archive.debian.org/g' /etc/apt/sources.list && \
    sed -i 's/security.debian.org/archive.debian.org/g' /etc/apt/sources.list && \
    sed -i '/stretch-updates/d' /etc/apt/sources.list

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc g++ netcat \
    libgomp1 libglib2.0-0 libsm6 libxext6 libxrender-dev libgl1-mesa-glx && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

RUN mkdir -p /home/app && \
    addgroup --system app && \
    adduser --system --group app


ENV HOME=/home/app
ENV APP_HOME=/home/app/web
ENV PIP_NO_CACHE_DIR=1

RUN mkdir $APP_HOME
WORKDIR $APP_HOME

COPY ./requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . $APP_HOME

RUN sed -i 's/\r$//g' $APP_HOME/entrypoint.sh && \
    chmod +x $APP_HOME/entrypoint.sh && \
    chown -R app:app $APP_HOME

USER app

ENTRYPOINT ["/home/app/web/entrypoint.sh"]