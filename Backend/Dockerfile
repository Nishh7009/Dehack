FROM python:3.12

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    gcc g++ \
    libgomp1 libglib2.0-0 libsm6 libxext6 libxrender-dev \
    binutils libproj-dev gdal-bin libgdal-dev && \
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

RUN chown -R app:app $APP_HOME && \
    sed -i 's/\r$//g' $APP_HOME/entrypoint.sh && \
    chmod +x $APP_HOME/entrypoint.sh

USER app

ENTRYPOINT ["/home/app/web/entrypoint.sh"]
