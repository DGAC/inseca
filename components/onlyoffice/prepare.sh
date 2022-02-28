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


# check that the expected package has been downloaded
debfiles=$(ls -1 "$COMPONENT_DIR/packages.deb/"*.deb 2>/dev/null)
[ $? == 0 ] || {
    url="https://download.onlyoffice.com/install/desktop/editors/linux/onlyoffice-desktopeditors_amd64.deb"
    >&2 echo "OnlyOffice needs to be downloaded from"
    >&2 echo "$url"
    >&2 echo "into the $COMPONENT_DIR/packages.deb/ directory"
    exit 1
}
