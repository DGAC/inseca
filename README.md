# INSECA

INSECA is a set of tools to build and manage very secure live Linux based endpoint systems.

It builds on top of Debian's livebuild technology and adds many security oriented features to ensure a high level of security while keeping the overall usage as simple as any system.

Main features of the resulting systems include:
- possibility to be installed on any mass storage device (which will be made bootable), internal PC hard disk or VM's disk
- all non yet public data (i.e. what is not already present on the Internet) is encrypted, data is most of the time digitally signed as well
- encrypted partitions dedicated to store system and end-user data, which access is only possible after the end user authenticated _and_ if the device has not been altered
- and more

For more infos, refer the documentation in the `doc/` directory.


## Introdution
INSECA operates from several configuration files, all grouped in one single global configuration directory, pointed by the `$INSECA_ROOT` environment variable or using the `--root` command line argument of the `inseca` tool.

These configuration files define sets of objects which main ones are:
- **build configurations** describing the contents of a live Linux to be built, ranging from packages, configuration scripts and the like to cryptographic keys used to protect data;
- **install configurations** describing how a live Linux build will be installed (cryptographic keys and secrets and various other parameters)
- **domain configurations** listing a coherent set of install configurations all bubdled in a **domain** which can be seen as a business need

The global settings are described in the `$INSECA_ROOT/inseca.json` file.

**WARNING**
This program is useable but still _rough_, at least regarding areas such as:
- language: most is in English, with some strings still in French (gettext has started to be used)
- the documentation, which is only on French
- error reporting, especially in the configuration files handling where one is prone to make mistakes
- installation: there is no installation procedure, just download and run
- some components are not yet complete, some features don't yet work as expected


## Quick start
What follows should work out of the box on any Linux distribution but has only been tested using Debian. YMMV.

### Preparation steps
1. install the dependencies:
  - rclone, python 3 with the pacparser, gi, dbus, requests, sqlite3 modules
  - GTK3 libraries
  - the Docker engine
1. create the required Docker images: run `make` from the `$SRCDIR/docker-images/grub-bios/` and the `$SRCDIR/docker-images/livebuild/` directories
1. download INSECA in dedicated directory (refered to as `$SRCDIR` afterwards)
1. set the local environment variables: `cd $SRCDIR/tools && source ./set-env.sh` if you are using bash
1. download VeraCrypt as a DEB file from https://www.veracrypt.fr/en/Downloads.html in the `$SRCDIR/components/veracrypt/packages.deb/` directory
1. check that the `inseca` program can be run: `inseca -h` should display the help.

### First configuration
To create a global configuration:
1. create a dedicated directory and define the `$INSECA_ROOT` environment variable to point to it
1. initialize the configuration's structure, run: `inseca init`
1. create a default build configuration: `inseca config-create build "My first INSECA build"`
1. build the associated live Linux: `inseca build "My first INSECA build"`

These steps, if sucessfull, ensure that INSECA is operational, from that point, refer to the documentation and build your own ecosystem.