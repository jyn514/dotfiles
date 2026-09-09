"""Historical iptables baseline from 6dec364f, retained for differential tests."""

PUBLIC = 'cs-public'
LINK = 'csl+'
EGRESS = 'cse+'


def rules(policy, ipv6=False):
    incoming = [['-i', bridge, '-j', 'REJECT'] for bridge in (PUBLIC, LINK)]
    if ipv6:
        return incoming + [['-i', EGRESS, '-j', 'REJECT']], [
            ['-i', bridge, '-j', 'REJECT'] for bridge in (PUBLIC, LINK, EGRESS)]
    # Internal relay traffic is allowed only while bridged, never routed to
    # another link. Interface identity also survives forged source addresses.
    forwarding = [
        ['-i', LINK, '-m', 'physdev', '--physdev-is-bridged', '-j', 'RETURN'],
        ['-i', LINK, '-j', 'REJECT'],
        ['-i', PUBLIC, '-o', PUBLIC, '-j', 'RETURN'],
        ['-i', EGRESS, '-o', PUBLIC, '-j', 'REJECT'],
        ['-i', EGRESS, '-o', LINK, '-j', 'REJECT'],
        ['-i', EGRESS, '-o', EGRESS, '-m', 'physdev', '--physdev-is-bridged', '-j', 'RETURN'],
        ['-i', EGRESS, '-o', EGRESS, '-j', 'REJECT'],
    ]
    for protocol in ('tcp', 'udp'):
        forwarding.append(['-i', PUBLIC, '-d', policy['dns'] + '/32',
                           '-p', protocol, '-m', protocol, '--dport', '53', '-j', 'RETURN'])
    forwarding += [['-i', PUBLIC, '-d', destination, '-j', 'REJECT']
                   for destination in policy['prohibited']]
    return incoming, forwarding
