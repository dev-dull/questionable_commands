#!/bin/bash
cd `dirname $0`

TEMPLATE_FILE="tinyproxy.template"
TMP_FILE="/tmp/tinyproxy.conf"
CONF_FILE="/etc/tinyproxy/tinyproxy.conf"

# TODO: sed replace instead of last 'grep' command.
tun_ip=`ifconfig | tr '\n' '~' | sed 's/~~/\n/g' | grep tun0 | grep -Eio 'inet ([0-9]{1,3}\.?){4}' | grep -Eio '([0-9]{1,3}\.?){4}'`

if [ "$tun_ip" ]; then
    if [ -f "$TEMPLATE_FILE" ]; then
        cat "$TEMPLATE_FILE" | sed "s/BIND_IP_GLYPH/$tun_ip/g" > "$TMP_FILE"
    else
        echo "Missing tempalte. Can't complete autoconfig"  # to-do: send an alert email.
    fi

    if [ -f "$CONF_FILE" ]; then
        current_md5=`md5sum "$CONF_FILE" | awk '{print $1}'`
        new_md5=`md5sum "$TMP_FILE" | awk '{print $1}'`

        if [ "$current_md5" != "$new_md5" ]; then
            cp "$TMP_FILE" "$CONF_FILE"
            systemctl restart tinyproxy
        fi
    else
        echo "Did not find configuration file for TinyProxy in the expected location."
    fi
else
    echo "Uh oh. We've disconnected."  # to-do: send an alert email.
fi
