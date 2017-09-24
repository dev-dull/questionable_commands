#!/bin/bash

SVG_FILE='aa.svg'
if [ ! -f "$SVG_FILE" ]; then
  echo "Missing expected SVG file: $SVG_FILE" >&2
  exit -1
fi

# find all (f)iles, don't touch system directories, leave fonts alone, ignore the image we're using
find / -type f -mount | grep -Ev "$SVG_FILE|^(/boot|/sys|/proc)|\.(ttf|otf)$" | while read "fname"
do
  is_emtpy=$(file "$fname" | grep -Eio 'empty$')
  if [ -z "$is_empty" ]; then
    img_info=$(identify -format "%wx%h\n" "$fname" 2> /dev/null)
    is_img=$?
    if [ $is_img -eq 0 ]; then
      let width=$(echo "$img_info" | awk -Fx '{print $1}')
      let height=$(echo "$img_info" | awk -Fx '{print $2}')

      if [ $width -gt 0 -a $height -gt 0 ]; then
        # get the file owner/group
        og=$(ls -l aa.svg | awk '{print $3":"$4}')

        # replace the original file.
        convert -density 1200 -geometry $img_info\! $SVG_FILE "$fname"
        chown $og "$fname"
        echo "$(date) $density $img_info $SVG_FILE -> $fname"
      fi
    fi
  fi
done
