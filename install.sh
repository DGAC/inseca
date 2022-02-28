#!/bin/bash

# This script must be started with root privileges
if [ "$USER" != "root" ]
then 
    echo "Start the script with root privileges"
    exit
fi

echo "### Install INSECA ###"

echo "### Checks for the latest updates ###"
apt update -y
apt full-upgrade -y
apt clean

echo "### Installation of rclone ###"
apt install curl -y 
apt install sudo -y
curl https://rclone.org/install.sh | sudo bash

echo "### Installation of python3 with pacparser ###"
apt install python3 python3-pacparser -y

echo "### Installation of GTK libraries ###"
apt install libgtk-3-dev -y

echo "### Installation of git ###"
apt install git -y

echo "### Installation of dbus ###"
apt install dbus -y

echo "### Installation of make ###"
apt install make -y

echo "### Installation of Docker ###"
apt install \
    ca-certificates \
    gnupg \
    lsb-release -y
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian \
  $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
apt update -y
apt install docker-ce docker-ce-cli containerd.io -y

echo "### Installation of INSECA ###"
apt install wget -y
git clone https://github.com/DGAC/inseca
cd inseca/docker-images/grub-bios/ && make
cd ../livebuild && make

echo "### Installation of Veracrypt ###"
cd ../../components/veracrypt/packages.deb/
wget https://launchpad.net/veracrypt/trunk/1.25.9/+download/veracrypt-console-1.25.9-Debian-11-amd64.deb
cd ../../../../../

echo "### Installation succeed ###"
cwd=$(pwd)
echo "Use this command to set the local environment variables (only if you are using bash) : cd $cwd/tools && source ./set-env.sh"