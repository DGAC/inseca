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


# check that deb package has been downloaded
dirs=(${COMPONENT_BLOBS_DIR//|/ })
for dir in "${dirs[@]}"
do
    debfiles=$(ls -1 "$dir/"*.deb 2>/dev/null)
    [ $? == 0 ] && exit 0
done

>&2 echo ""
>&2 echo "VeraCrypt needs to be downloaded from https://www.veracrypt.fr/en/Downloads.html or https://github.com/veracrypt/VeraCrypt"
>&2 echo "into one of the following directories:"
for dir in "${dirs[@]}"
do
    >&2 echo "  $dir"
done
exit 1
