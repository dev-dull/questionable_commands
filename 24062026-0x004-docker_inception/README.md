## Questionable Commands - Ep. 0x004 - Docker Inception
This uses Docker in Docker (`dind`) to run Docker in Docker inside of it. It keeps recursing all the way down until the system chokes.

[![Questionable Commands - Ep. 0x004 - Docker Inception](https://img.youtube.com/vi/fle7hfKgSnE/maxresdefault.jpg)](https://www.youtube.com/watch?v=fle7hfKgSnE)

### Setup:
You'll need to save the `dind` image as a tarball called `jonah.tar`. To help address the very serious matter of being silly, I republished the `dind` container image as `devdull/jonah:latest`. Below is an example command to save jonah as a tar file, but the upstream `dind` should work the same.

```bash
docker save devdull/jonah:latest -o jonah.tar
```

### Run:
```bash
docker build -t fishy . && docker run --privileged --pid=host fishy
```
