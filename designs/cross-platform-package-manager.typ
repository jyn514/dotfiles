#set page(paper: "us-letter", margin: 1in)
#set text(size: 10.5pt)
#set par(justify: true, leading: 0.65em)
#set heading(numbering: "1.")

= Cross-platform package management for the dotfiles repository

== Decision

Replace package selection and package-manager invocation in
`libexec/setup/setup_sudo.sh` with:

- one Clojure policy at `install/packages.clj`;
- a small Babashka planner under `tools/package-plan/`; and
- mise's package-manager backends as the package executor.

The policy keeps all target mappings and omissions visible together. The
planner validates and expands it before mutation. mise invokes apt, dnf, apk,
pacman, and Homebrew with explicit package arguments.

This design covers only behavior implemented by `setup.sh` today. It does not
define a general package-management framework.

== Required behavior

The replacement must preserve:

- the common package list and target-specific renames and omissions;
- Debian/Ubuntu, Fedora, Arch, Alpine, Chimera, and Apple Silicon macOS;
- Alpine's base packages plus `cargo-audit` and `difftastic`, Arch's `bacon`,
  and WSL's `keychain`;
- Brew installation of `bacon` where the native manager does not provide it and
  Homebrew supports the host;
- Ubuntu universe, Microsoft's PowerShell repository, the VS Code Debian
  package, the Git PPA used for old Git, 1Password's Fedora repository, and
  RPM Fusion codecs;
- a complete plan before package or repository mutation; and
- separate setup paths for packages, security policy, global files, device
  setup, encryption, and services.

Keymapp installation is device setup, not package policy. `install_security`,
`copy_globals`, encryption, and `remove_unwanted` also remain outside this
planner.

== Policy model

=== Targets and host facts

The closed target set is:

```text
debian
ubuntu
fedora
arch
alpine
chimera
macos-arm64
```

Detection produces a target, normalized distribution release, architecture,
libc, WSL status, installed-command facts needed by current conditions, and the
installed Git version. Unknown derivatives and Intel macOS fail explicitly.
Release is data for repository URLs; package targets are not release-qualified.

The planner owns one tested mapping from each target to its native mise manager:

```text
debian, ubuntu  -> apt
fedora          -> dnf
arch            -> pacman
alpine, chimera -> apk
macos-arm64     -> brew
```

=== Logical packages and dispositions

A logical package is a stable intent from the common package list or a current
platform addition. Every logical package has exactly one disposition for every
target:

/ Native: One or more package names for the target's native manager.

/ Fallback: Package names for Brew on a supported non-native target, with a
  reason. This is initially used only for `bacon`.

/ Skip: Do not install the package on this target, with a reason such as
  supplied by Xcode Command Line Tools, included in another package, irrelevant
  to the platform, or unavailable.

There is no missing or empty disposition. Package names are vectors, never
whitespace-separated shell strings.

The policy declares one common selection set and additions selected by current
host facts:

- `bash`, GNU `less`, `libgcc`, and `shadow` on Alpine; the common
  `python3-pip` and `zsh` intents map to Alpine's `py3-pip` and `zsh`, avoiding
  the duplicate requests in the current shell;
- `cargo-audit` and `difftastic` on Alpine;
- `bacon` on Arch;
- `bacon` through Brew on Debian, Ubuntu, Fedora, and macOS;
- `keychain` under WSL.

Chimera and Alpine do not receive the Brew fallback because they use musl.

=== Repository and conditional package operations

The planner supports only the prerequisite operations current setup needs:

- enable Ubuntu universe if absent;
- install Microsoft's release package and then `powershell` when `pwsh` is
  absent on Debian or Ubuntu;
- download and install the VS Code Debian package when `code` is absent and the
  host is not WSL;
- enable the Git PPA and reinstall `git` when Ubuntu's Git is older than 2.35;
- install the pinned 1Password repository key and repository definition before
  `1password` on Fedora; and
- install the Fedora-versioned RPM Fusion release packages, then the current
  codec package set with `--allow-erasing`.

These are typed constructors implemented by the planner, not command strings.
Each constructor accepts only the fields its adapter needs: validated URLs,
release interpolation, owned destination paths, package vectors, and pinned
digests where the upstream supplies a stable artifact. The policy cannot embed
shell or arbitrary argv.

Repository operations precede dependent package operations. Retry inspects
current state and repeats safely. There is no prune operation or transaction
claim; a successfully installed repository remains if a later package fails.

== Manifest

`install/packages.clj` is one Clojure expression returning a policy value built
with planner-provided constructors. It may use literals, `let`, collection
operations, and small local functions to remove repetition. It may not inspect
the host or perform effects.

A representative fragment is:

```clojure
(let [linux #{:debian :ubuntu :fedora :arch :alpine :chimera}
      glibc-linux #{:debian :ubuntu :fedora}]
  (policy
    {:schema 1
     :targets #{:debian :ubuntu :fedora :arch
                :alpine :chimera :macos-arm64}
     :common #{:valgrind :python3-pylsp}
     :additions [(on-target :alpine
                   #{:bash :less :libgcc :shadow :cargo-audit :difftastic})
                 (on-targets (conj glibc-linux :arch :macos-arm64) #{:bacon})
                 (on-wsl #{:keychain})]
     :resources [(ubuntu-universe)
                 (powershell-repository :targets #{:debian :ubuntu})
                 (vscode-deb :targets #{:debian :ubuntu})
                 (git-ppa :target :ubuntu :below "2.35")
                 (onepassword-fedora)
                 (rpmfusion-codecs)]}

    [(package :valgrind
       (native-same-name (disj linux :chimera))
       (skip #{:chimera} "Not packaged by the supported repositories")
       (skip #{:macos-arm64} "Unsupported on current macOS"))

     (package :bacon
       (native {:arch ["bacon"]})
       (fallback glibc-linux :brew ["bacon"]
         :reason "No suitable native package")
       (native {:macos-arm64 ["bacon"]})
       (skip #{:alpine :chimera} "Homebrew bottles require glibc"))

     (package :python3-pylsp
       (native {:debian ["python3-pylsp"]
                :ubuntu ["python3-pylsp"]
                :fedora ["python3-lsp-server"]
                :arch ["python-lsp-server"]
                :alpine ["py3-python-lsp-server"]
                :chimera ["python-lsp-server"]
                :macos-arm64 ["python-lsp-server"]}))]))
```

The real manifest transcribes `install/packages.txt`, every `queue_install`
branch, and the current platform additions. A generated matrix shows the fully
expanded result, so concision cannot hide a missing target or omission.

== Policy evaluation

The Babashka planner is trusted; the policy expression is evaluated in a fresh
SCI context with an explicit, versioned allowlist. The context contains only:

- the policy constructors;
- literals, local bindings, functions, conditionals, and collection operations
  needed by the manifest; and
- a small explicit subset of `clojure.string` if transcription needs it.

It contains no filesystem, environment, process, network, Java interop,
namespace loading, clocks, randomness, or host facts. Tests cover every allowed
constructor and representative denied effects. This boundary prevents
accidental effects; it is not a sandbox for an untrusted checkout.

Constructors return opaque values. One conversion boundary parses the result
into the planner's domain model and attaches source locations to diagnostics.

== Planning and execution

`dev/package-plan` exposes:

```text
dev/package-plan validate
dev/package-plan show
dev/package-plan matrix
dev/package-plan explain PACKAGE
dev/package-plan apply [--dry-run] [--yes]
```

`validate` checks the complete policy without reading installed state. `show`
and `apply` detect the host and installed-state conditions. `matrix` shows every
logical package against every target, including skips. `explain` shows one
package's declarations and expansion.

Planning performs no mutation:

+ Evaluate and parse the policy.
+ Detect host facts and inspect current repository state.
+ Require one disposition for every package/target pair.
+ Validate package names, fallback compatibility, resource fields, URLs, and
  digests.
+ Select common packages and current platform or WSL additions.
+ Add conditional repository and package operations.
+ Order repositories before their dependents and group packages by provider.
+ Return the complete plan, including skipped decisions and reasons.

`apply` displays that plan, asks once unless `--yes` was given, applies typed
repository operations, and invokes mise with explicit requests:

```text
mise bootstrap packages apply --update --yes apt:bat apt:jq ...
mise bootstrap packages apply --yes brew:bacon
```

`--update` is used only when the current native-manager path requires it.
Commands are argv vectors: the executor never builds shell text, uses `eval`,
or splits package names. It stops on the first failed operation. Dry run performs
all reads and planning but no mutation.

An Arch setup run must retain the current
`pacman --sync --refresh --sysupgrade --needed` semantics: refresh package
metadata, perform one full system upgrade, and avoid reinstalling satisfied
packages. If the planned sudo prerequisite performs that upgrade, package
application omits another update. Otherwise, Arch does not switch to the planner
unless mise's `--update` path is proven to provide all three behaviors.

`setup.sh install-global` calls `package-plan apply`. The planner, not the whole
setup subprocess, prefixes typed repository operations with the elevation
command selected by the plan. The pinned mise process remains unprivileged and
receives the target's `sudo` interface. Only the fixed elevation prerequisite
may use `su -c`; no policy-derived package or repository operation does. This
keeps user-owned bootstrap files out of a root-owned home.

== Bootstrap

=== Runtime bootstrap

`package-plan` must run before global packages, so it cannot depend on Python,
Node, Cargo, or a system Babashka package. A small POSIX shell shim downloads a
pinned standalone Babashka archive for the detected architecture, operating
system, and libc. It requires only `uname`, `tar`, one TLS downloader, and one
SHA-256 implementation. A missing prerequisite is an explicit unsupported-host
error.

`install/bootstrap.edn` pins Babashka and mise release URLs and SHA-256 digests
for every supported binary target. A development generator emits the minimal
shell lookup table used before Babashka exists. Tests reject stale generated
data. The shim downloads to a unique sibling temporary path, verifies the
digest and expected executable, then atomically renames it into a versioned
user cache.

Once running, the planner reads the same EDN file with a strict single-value
reader, validates its primitive data schema, and installs the pinned standalone
mise binary in the same manner. Ambient Babashka and mise are ignored during
bootstrap; all later calls use the pinned absolute paths. Updating either pin is
an explicit development command that regenerates the shell table and displays
the complete pin diff.

Runtime bootstrap mutates only the invoking user's versioned cache. It does not
install a system package or request root. The planner can therefore construct
and display the complete system-mutation plan before privilege setup.

=== Planned privilege setup

The planner selects elevation while building the plan:

+ If setup already runs as UID 0, use direct execution.
+ On Debian, Ubuntu, Arch, Fedora, and macOS, use an installed real `sudo`.
  When it is absent on Debian, Ubuntu, or Arch, plan installation and
  configuration of `sudo`; its fixed helper runs through an installed `doas`,
  or through `su` if doas is also absent. Fedora and macOS fail planning when
  sudo is absent.
+ On Alpine, accept an installed real sudo. Otherwise require the packaged
  `doas-sudo-shim` sudo interface. When neither is present, plan installation
  of `doas` and `doas-sudo-shim` plus doas configuration; run the fixed helper
  through an installed doas, or through `su` if doas is absent.
+ On Chimera, use an installed doas. If it is absent and `su` is present, plan
  installation of `opendoas` and doas configuration through the fixed helper;
  if both are absent, fail planning. Prepend the repository's vendored
  `doas-sudo-shim` directory only to the pinned mise process's `PATH`; typed
  repository operations continue to invoke doas directly. Do not install or
  expose that shim system-wide.

Authorization is checked by the first real privileged operation; failure stops
with that exact diagnostic rather than falling through after possible mutation.
The plan displays any prerequisite, its fixed package-manager action, the
resolved configuration destination, and the exact permanent sudoers or doas
rule before confirmation. If the plan contains that prerequisite, apply invokes
the checked-in `libexec/setup/bootstrap_elevation.sh` through the selected
launcher and verifies the resulting interface. Otherwise it does not invoke the
helper. Apply then continues with the planned elevation behavior.

The only dynamic value placed in the `su -c` command is the invoking numeric
UID, obtained from `id -u` and accepted only if it contains ASCII digits and is
not zero. The remainder is a fixed target-specific launcher for the checked-in
helper. No policy value, package name, URL, repository field, environment
value, or user-supplied path enters the command string.

The helper redetects the target and maps it to one compiled-in installation:

```text
debian, ubuntu -> apt-get update; apt-get install -y sudo
alpine         -> apk add doas doas-sudo-shim
arch           -> pacman --sync --refresh --sysupgrade --needed sudo
chimera         -> apk add opendoas
```

Automatic elevation-package installation is limited to these mappings. Fedora
and macOS fail planning when sudo is absent rather than gaining a general
package-install escape hatch. Chimera fails planning when neither doas nor su is
available.

After installation, the helper resolves the validated UID through the system
password database and rejects root, no match, multiple matches, or an invalid
login name. On Debian, Ubuntu, and Arch it adds one marked
`USER ALL=(ALL:ALL) ALL` rule under `/etc/sudoers.d`, validates the complete
candidate with `visudo`, and installs it mode 0440. On Alpine and Chimera it adds
one marked `permit persist USER as root` rule at the target's supported OpenDoas
location and validates the complete candidate with OpenDoas. Both paths preserve
existing configuration, refuse an unmanaged conflicting rule, and replace the
owned file atomically. Failure leaves the previous configuration unchanged.

The exact released upstream `doas-sudo-shim` script, its license, version, and
source digest are committed under `vendor/doas-sudo-shim/`. Chimera executes
that file in place through an absolute private `PATH` entry for mise only; the
runtime bootstrap performs no download. Updating the vendored release is an
explicit development action that verifies its digest and displays the complete
vendor diff.

The helper contains no general package or command interface. Changing its
package names, package-manager argv, supported targets, or privilege rule
requires a source change and exact-argv test. On Arch its planned operation performs the
one full system upgrade required by package setup; later package operations omit
another update in that run.

== Validation

Repository tests reject:

- unknown constructors, targets, providers, fields, or disposition kinds;
- missing or overlapping package/target dispositions;
- empty native or fallback package vectors;
- fallback on a target unsupported by that provider;
- skips without reasons;
- invalid conditional resources or unpinned stable artifacts;
- duplicate physical requests with conflicting logical owners; and
- stale bootstrap data.

Privilege-setup tests cover root, each target's required interface, authorization
failure at the first privileged operation, absent commands, failed `su`, invalid
UIDs, password-database mismatches, conflicting sudoers and doas rules, atomic
replacement, and exact package-manager argv on Debian, Ubuntu, Alpine, Arch, and
Chimera.
They prove that manifest strings and environment values cannot reach `su -c` or
the helper's package selection. Golden plans show the resolved rule and
destination, accept real sudo on Alpine, invoke the helper only for a planned
prerequisite, reject automatic installation on Fedora and macOS, and reject a
Chimera host lacking both doas and su.
Chimera tests prove that mise alone receives the vendored shim path, that the
shim translates the exact sudo argv emitted by the pinned mise release, and that
the vendored files match their recorded digest. A test against the official
minimal Chimera image records `sh`, `awk`, and `cat` as stage-zero facilities and
exercises root-direct planning without assuming doas, sudo, or su is installed.

Golden tests cover the complete matrix and these current host scenarios:

- Debian and Ubuntu, including WSL;
- Fedora;
- Arch;
- Alpine and Chimera; and
- Apple Silicon macOS.

Scenario tests cover present and absent `pwsh` and `code`, old and current Git,
Ubuntu universe state, repository ordering, RPM Fusion's special arguments, the
Alpine baseline, and Arch's full-upgrade behavior. Debian scenarios prove that
Ubuntu universe and the Git PPA are not selected and that PowerShell uses
Microsoft's Debian repository rather than an Ubuntu release path.
Executor tests record NUL-delimited argv and check provider grouping, dry run,
partial failure, retry, and that Brew fallback never installs unrelated Brew
packages. JSON tests compare parsed values; human matrices use stable target and
package order for reviewable diffs.

The cross-manifest test continues to reject duplicate ownership between this
policy, mise `[tools]`, Cargo, pipx, and other package manifests.

== Migration

+ Transcribe the current package list, mappings, omissions, platform additions,
  and repository operations, preserving the effective installed package set.
+ Add the matrix, host scenarios, adapter tests, and clean-host bootstrap tests.
+ Run the new path behind an explicit opt-in command on every supported target.
+ Switch `setup.sh install-global` after its plans match the characterized
  current requests.
+ Remove `install/packages.txt`, `queue_install`, manager command construction,
  and the duplicate Bacon declaration from `config/mise.toml`.

Do not migrate unrelated setup behavior into the planner. In particular, leave
Keymapp, security configuration, global files, encryption, services, Python
packages, mise user tools, and platform bundles with their current owners.

The migration deliberately repairs three overbroad or duplicated `IS_DEB` and
Alpine behaviors: Ubuntu universe and the Git PPA run only on Ubuntu; Debian
PowerShell uses Microsoft's Debian repository; and Alpine's unconditional
`py3-pip` and `zsh` collapse into their existing logical package requests.

== Rejected larger systems

Nix/Home Manager would replace native package ownership with a separate store.
Ansible and chezmoi would still require repository-owned name mappings. asdf
does not install system dependencies. mise executes all required managers but
does not model logical names, omissions, or native-versus-fallback policy.

Those tools solve broader problems. This design adds only the missing policy
layer around mise.
