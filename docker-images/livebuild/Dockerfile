FROM debian:bullseye-slim

COPY do-make.sh patch /
RUN apt-get update &&\
	DEBIAN_FRONTEND=noninteractive apt-get install -y git live-build vim live-manual procps debootstrap

# https://salsa.debian.org/installer-team/debootstrap/-/merge_requests/26
RUN patch -p 0 < /patch

# https://www.mail-archive.com/debian-live@lists.debian.org/msg17513.html
RUN sed -i '1161s%umount%#umount%' /usr/share/debootstrap/functions

WORKDIR /live

ENTRYPOINT ["/do-make.sh"]
CMD ["build"]
