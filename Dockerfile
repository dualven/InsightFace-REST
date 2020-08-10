FROM tensorflow-opencv:preconf
#RUN  apt-get update && apt-get install -y --no-install-recommends libnvinfer6=6.0.1-1+cuda10.1 libnvinfer-dev=6.0.1-1+cuda10.1 libnvinfer-plugin6=6.0.1-1+cuda10.1
WORKDIR /app

COPY ./src /app/src

ENTRYPOINT [ "python" ]

CMD [ "src/api/app.py" ]
