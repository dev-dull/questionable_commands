FROM devdull/jonah:latest

ARG DIND_DEPTH=0
ENV DIND_DEPTH=${DIND_DEPTH}

WORKDIR /dind
COPY Dockerfile Dockerfile
COPY jonah.tar jonah.tar
COPY runme.sh runme.sh

ENTRYPOINT ["./runme.sh"]
CMD ["dockerd-entrypoint.sh"]
