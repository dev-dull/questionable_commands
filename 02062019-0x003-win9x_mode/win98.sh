#!/bin/bash

u="SET YOUR USERNAME" # Username
g=`groups $u | awk '{print $1}'` # primary group

#find all files/dirs on disk
find / | grep -Ev '^(/proc|dev)' | while read "fname"
do
    # double check that the file isn't a special type
    if [ -d "$fname" -o -f "$fname" ]; then
        # skip files where special permissions are set (e.g. the sticky bit)
        is_sticky=`stat -c "%a" "$fname" | grep -Eio '[0-9]{4,}'` # If the octal permissions are 4 digits long, then a special bit is set.
        if [ -z "$is_sticky" ]; then # only apply changes if file does not have special permissions.
            chmod 777 "$fname"
            chown $u:$g "$fname"
        fi
    fi
done
