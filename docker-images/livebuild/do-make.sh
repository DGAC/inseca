#!/bin/bash

# This file is part of INSECA.
#
#    Copyright (C) 2020-2022 INSECA authors
#
#    INSECA is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    INSECA is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with INSECA.  If not, see <https://www.gnu.org/licenses/>

set -e

case "$1" in
    "build")
	lb clean --purge
	# configure HTTP/HTTPS proxies for the programs executed in the chroot environment
	# See /usr/share/live/build/functions/chroot.sh
	[ -n "$http_proxy" ] && echo "http_proxy=$http_proxy" >> /live/config/environment.chroot
	[ -n "$https_proxy" ] && echo "https_proxy=$https_proxy" >> /live/config/environment.chroot
	lb config
	lb build
	;;
    "clean")
	lb clean --purge
	;;
    "shred")
	rm -rf /live/* /live/.[a-z]*
	;;
    *)
	echo "Nothing to do!"
	;;
esac
