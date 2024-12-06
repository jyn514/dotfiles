check() {
    require_binaries sshd || return 1
    # 0 enables by default, 255 only on request
    return 0
}

depends() {
    echo network
    return 0
}

install() {
    if [ -e /etc/dracut-dropbear/authorized_keys ]; then
        authorized_keys=/etc/dracut-sshd/authorized_keys
    elif [ -e /root/.ssh/dracut_authorized_keys ]; then
        authorized_keys=/root/.ssh/dracut_authorized_keys
    else
        # TODO: this isn't great lol, fix this in setup.sh
        authorized_keys=/home/jyn/.ssh/authorized_keys
    fi
    if [ ! -r "$authorized_keys" ]; then
        dfatal "No authorized_keys for root user found!"
        return 1
    fi
    mkdir -p -m 0700 "$initdir/etc/dropbear"
    /usr/bin/install -m 600 -D "$authorized_keys" "$initdir/root/.ssh/authorized_keys"

  inst_binary /usr/sbin/dropbear
  inst_simple "${moddir}/dropbear.service" "$systemdsystemunitdir/dropbear.service"

  systemctl -q --root "$initdir" enable dropbear

  # mkdir -p -m 0755 "$initdir/var/log"
  # -E -R -c systemd-tty-ask-password-agent
  # echo systemd-tty-ask-password-agent >> "$initdir/root/.bash_history"
}
