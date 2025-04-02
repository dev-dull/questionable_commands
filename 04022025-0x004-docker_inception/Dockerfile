FROM devdull/jonah:latest
#docker run --privileged --name dind -d docker:stable-dind

COPY Dockerfile Dockerfile
COPY runme.sh runme.sh

#ENTRYPOINT ["dockerd-entrypoint.sh"]
#CMD ["./runme.sh"]
ENTRYPOINT ["./runme.sh"]
CMD ["dockerd-entrypoint.sh"]
