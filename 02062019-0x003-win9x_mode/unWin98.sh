#!/bin/bash

real_root="SET YOUR MOUNT POINT"

find / -mount | while read "fname" # '-mount' will prevet find from looking at mounted disks (e.g. won't look into $real_root)
do
    perms=`stat "$fname" -c "%a"`
    owner=`stat "$fname" -c "%u:%g"`

    fix_file="${real_root}${fname}"

    ee=0
    if [ -e "$fix_file ]; then # if the file found in / also exists in $real_root, then set the one in $real_root to match the one in /
        chown $owner "$fix_file"
        let ee=$ee+$?
        chmod $perms "$fix_file"
        let ee=$ee+$?

        if [ $ee -eq 0 ]; then
            echo "Success (-: $fix_file"
        else
            echo "PERMISSION FAILURE: $fix_file" >&2
        fi
    else
        echo "FOUR OH FOUR'D: $fix_file"
    fi
done
