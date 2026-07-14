#!/bin/sh

# Invoke `dockerd-entrypoint.sh` as passed by the dind container
exec "$@" > /dev/null 2>&1 &

echo "DIND_DEPTH: $DIND_DEPTH"
let DIND_DEPTH=$DIND_DEPTH+1

# Waiting for docker to start
dockerUp=""
while [ -z "$dockerUp" ]
do
  sleep 1
  dockerUp=$(netstat -nlp 2>/dev/null | grep LISTEN | grep -o 'dockerd$')
done

# Load devdull/jonah:latest from the `.tar` file.
docker load -i jonah.tar > /dev/null 2>&1

# Build the docker image that's identical to the docker image that we are currently in.
DOCKER_BUILDKIT=0 docker build --build-arg DIND_DEPTH=$DIND_DEPTH . -t fishy > /tmp/build 2>&1 || { cat /tmp/build; exit 1; }

# complete the recursion by running the new docker image.
docker run --privileged --pid=host fishy
