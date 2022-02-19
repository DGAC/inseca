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

# define environment variables
cwd=$(pwd)
if [ -f "$cwd/inseca-admin" ] && [ -f "$cwd/inseca" ]
then
    export PATH="$PATH:$cwd"
    export PYTHONPATH="$(realpath $cwd/../lib):$(dirname $(realpath inseca-admin))"

    [ "$INSECA_ROOT" == "" ] && {
        echo "WARNING: the INSECA_ROOT environment variable should also be defined"
    }
else
    echo "This file must be sourced from the tools/ directory"
fi
