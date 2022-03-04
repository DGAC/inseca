#!/bin/bash

set -e

echo -e "\n### Install INSECA ###"
echo -e "\nThis script uses sudo to obtain root privileges when required"

echo -e "\n### Checks for the latest updates ###"
sudo yum update -y
sudo yum upgrade -y
sudo yum clean packages

echo -e "\n### Installation of rclone ###"
sudo yum install rclone -y

echo -e "\n### Installation of python3 with pacparser ###"
sudo yum install python3 python3-pycparser -y

echo -e "\n### Installation of GTK libraries ###"
sudo yum install gtk3 -y

echo -e "\n### Installation of borgbackup ###"
sudo yum install borgbackup -y

echo -e "\n### Installation of git ###"
sudo yum install git -y

echo -e "\n### Installation of dbus ###"
sudo yum install dbus -y

echo -e "\n### Installation of make ###"
sudo yum install make -y

echo -e "\n### Installation of Docker ###"
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/fedora/docker-ce.repo
sudo dnf install docker-ce docker-ce-cli containerd.io

echo -e "\n### Installation of INSECA ###"
sudo yum install wget openssl -y
git clone https://github.com/DGAC/inseca
sudo systemctl unmask docker
sudo systemctl start docker
pushd inseca/docker-images/grub-bios > /dev/null && sudo make && popd > /dev/null
pushd inseca/docker-images/livebuild > /dev/null && sudo make && popd > /dev/null

echo -e "\n### Installation of Veracrypt ###"
sudo yum install dpkg-dev -y
pushd inseca/components/veracrypt/packages.deb > /dev/null
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
dpkg-name vera*.deb > /dev/null
popd > /dev/null

echo -e "\n### Installation succeed ###"
instdir=$(realpath "$(pwd)/inseca")
echo -e "\nSet the local environment variables (only if you are using bash): cd $instdir/tools && source ./set-env.sh"