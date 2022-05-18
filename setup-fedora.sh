#!/bin/bash

# This file is part of INSECA.
#
#    Copyright (C) 2022 INSECA authors
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

echo -e "\n### Install INSECA ###"
echo -e "\nThis script uses sudo to obtain root privileges when required"

echo -e "\n### Checks for the latest updates ###"
sudo dnf update -y
sudo dnf upgrade -y
sudo dnf clean packages

echo -e "\n### Installation of rclone ###"
sudo dnf install -y rclone

echo -e "\n### Installation of python3 and related ###"
sudo dnf install -y python3 python3-inotify

echo -e "\n### Installation of GTK libraries ###"
sudo dnf install -y gtk3

echo -e "\n### Installation of borgbackup ###"
sudo dnf install -y borgbackup

echo -e "\n### Installation of dbus ###"
sudo dnf install -y dbus

echo -e "\n### Installation of make ###"
sudo dnf install -y make

echo -e "\n### Installation of Docker ###"
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io

echo -e "\n### Installation of INSECA ###"
sudo dnf install -y wget curl openssl
sudo systemctl unmask docker
sudo systemctl start docker
pushd docker-images/grub-bios > /dev/null && sudo make && popd > /dev/null
pushd docker-images/livebuild > /dev/null && sudo make && popd > /dev/null

echo -e "\n### Downloading Veracrypt ###"
pushd components/veracrypt/packages.deb > /dev/null
github_latest_release() {
    basename $(curl -fs -o/dev/null -w %{redirect_url} $1/releases/latest)
}
base="https://github.com/veracrypt/VeraCrypt"
release=$(github_latest_release "$base")
version=${release#VeraCrypt_}
url="$base/releases/download/$release/veracrypt-$version-Debian-11-amd64.deb"
wget "$url"
wget "$url.sig"
gpg --import ../VeraCrypt_PGP_public_key.asc
gpg --verify vera*.sig
rm -f vera*.sig
popd > /dev/null

echo -e "\n### Installation succeed ###"
instdir=$(realpath "$(pwd)")
echo -e "\nSet the local environment variables (only if you are using bash): cd $instdir/tools && source ./set-env.sh"