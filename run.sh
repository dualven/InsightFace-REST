docker run  -p 18080:18080\
    -e PYTHONUNBUFFERED=0\
    -e PORT=18080\
    -e MAX_SIZE=640\
    --name insight-face\
     $IMAGE:$TAG
