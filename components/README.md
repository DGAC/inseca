This directory contains all the live Linux components.

# Concepts
Each directory corresponds to a **component** which can be part of the live Linux.

# Components' files
Each component's files are:

- **README.md**: description of the component
- **prepare.sh** or **prepare.py**: script executed before building the live Linux, with the following environment variables defined:
  - `COMPONENT_DIR`: directory where all the component's files are
  - `CONF_DIR`: directory containing the configuration file
  - `BUILD_DIR`: build directory (where all the Debian live build files are)
  - `BUILD_DATA_FILE`: file to append build data (if any, like for example the admin password) to
  - `LIVE_DIR`: directory containing the filesystem of the future Live Linux
  - `PRIVDATA_DIR`: directory where each component can put some PRIVDATA which will be encrypted in the live Linux image
    and decrypted once the user has authenticated on the system (to protect data in the live Linux image).
    BE CAREFULL of the actual privileges of files and directories
  - `LIBS_DIR`: directory containing the Python libraries
  - `CONF_DATA_FILE`: the name of the file containing the component's configuration, in a JSON format
- **packages.deb/**: directory containing DEB packages
  - use `dpkg-name` to rename the DEB file (usage: `dpkg-name <file.deb>`, will rename the file)
  -  _must_ end in `_amd64.deb` for binary packages
- **_ATTIC/**: ignored directory
- **live-config/**: place to store scripts to integrate the component in the live system:
  - via the **configure0.py** and **configure1.py** upon INSECA's device startup, after the "private" and "data" partitions have been unlocked and mounted,
    where the environment contains the following variables:
    - `PRIVDATA_DIR`: directory containing the PRIVDATA resources specific to the component (defined in the `prepare.*` scripts)
    - `USERDATA_DIR`: directory containing the USERDATA resources specific to the component (defined when an install is created)
    the **configure0.py** script is executed _before_ the user's default (hard coded) profile and config backups (bookmarks, UI settings, etc.), while the **configure1.py** is executed _after_ that.
  - via the **infos.py** script, to give informations about the status of the component (the end of validity of a certificate for example), the `USERDATA_DIR` is
    defined when executed. This script needs to print:
    - 1st line: the component "user friendly" name
    - other lines: the component's status
    the exit status must be:
    - 0: success
    - 255: nothing to report (component not available, etc.)
    - something else: script failed (write error to stderr)
  - via the **shutdown.py** script, when the system is about to shut down, the `USERDATA_DIR` is defined when executed. The output of this script
    is not used, only the stderr if it fails (to report in the logs)
- **packages.list**: list of DEB packages to add
- directories starting with a `_`: livebuild's configuration files, copied **AS IS** to the top of the build environment
- other directories: included **AS IS** in the live Linux's filesystem
- other files: ignored

# References

- https://dquinton.github.io/debian-install/netinstall/live-build.html
