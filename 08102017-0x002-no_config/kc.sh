#!/bin/bash

# find all files, skip system paths (we still want to boot)
# skip files in /etc that are used to log a user in (not that it'll matter)
find / -type f | grep -Ev '^/(proc|sys|boot)|shadow|passwd|group|hosts' | while read "fname"
do
  # if it's a non exec text file...
  is_text=$(file "$fname" | grep -Eio 'text$')
  if [ "$is_text" ]; then
    # overwrite it with an empty file
    # this method works even if there's an open file handle to it.
    cat /dev/null > "$fname"  # good lord, this hurts and feels so wrong. Let's do it!
    #echo "/dev/null > $fname"  # test it first!
  fi
done

