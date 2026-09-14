#!/bin/sh
# Install the privileged helper and its polkit action. Needs root.
#
# Without this the application still runs, but changing the port count falls
# back to pkexec's generic "run this program as root" prompt, or to showing
# the user the commands to paste.
set -eu
here=$(cd "$(dirname "$0")" && pwd)

install -d -m 0755 /usr/libexec/lmssdr
install -m 0755 -o root -g root \
    "$here/polkit/lmssdr-module-helper" /usr/libexec/lmssdr/lmssdr-module-helper
install -D -m 0644 -o root -g root \
    "$here/polkit/org.atmanactive.lmssdr.policy" \
    /usr/share/polkit-1/actions/org.atmanactive.lmssdr.policy

echo "Installed:"
echo "  /usr/libexec/lmssdr/lmssdr-module-helper"
echo "  /usr/share/polkit-1/actions/org.atmanactive.lmssdr.policy"
