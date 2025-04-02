#!/bin/sh

# Invoke what was passed by CMD in the Dockerfile, dockerd-entrypoint.sh
exec "$@" &

# Wait for Docker daemon (dockerd-entrypoint.sh) to start
dd=''
while [ -z "$dd" ]
do
  echo "...wait for it..."
  sleep 1
  dd=$(netstat -nlp | grep LISTEN | grep -o dockerd$)
done

# Build the docker image (identical to the current docker image)
docker build . -t ddd

# Run the docker image (identical to the current docker image)
docker run --privileged ddd
