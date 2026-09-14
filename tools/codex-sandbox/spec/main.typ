#set document(title: "Sandbox design specification")
#set page(margin: 1in)
#set text(size: 10.5pt)
#set par(justify: true)
#set heading(numbering: "1.")

= Sandbox design specification

This aggregate specification covers the sandbox launcher, trusted command
proxies, selected host-Pi/guest-tool execution, image resolution, host coordination,
credential relays, and resource lifecycle. Each included file is authoritative for one subsystem; this file
owns their presentation and order.

#outline(title: "Contents", indent: auto)

#include "proxy-design.typ"

#include "trusted-service-lifecycle.typ"

#include "launcher-interface.typ"

#include "bake-resolver.typ"

#include "process-ownership.typ"

#include "reclaim-before-exhaustion.typ"

#include "r2-keychain-relay-design.typ"
