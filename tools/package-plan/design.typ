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
- mise's package-manager backends as the package executor, except for one typed
  Arch adapter required to preserve full-system upgrades.

The policy keeps all target mappings and omissions visible together. The
planner validates and expands it before mutation. Mise invokes apt, dnf, apk,
and Homebrew with explicit package arguments; the typed Arch adapter invokes
pacman.

This design covers only behavior implemented by `setup` today. It does not
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

The planner owns one tested mapping from each target to its native executor:

```text
debian, ubuntu  -> mise apt
fedora          -> mise dnf
arch            -> direct pacman adapter
alpine, chimera -> mise apk
macos-arm64     -> mise brew
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

These are fixed operations implemented by the planner, not command strings in
the policy. Their URLs, release interpolation, destination paths, package
vectors, and stable digests live in trusted planner code. The policy can select
an operation, but cannot embed shell or arbitrary argv.

Repository operations precede dependent package operations. Retry inspects
current state and repeats safely. There is no prune operation or transaction
claim; a successfully installed repository remains if a later package fails.

== Manifest

`install/packages.clj` is one Clojure expression returning a policy map. It may
use literals, `let`, collection operations, and small local functions to remove
repetition. It may not inspect the host or perform effects.

A representative fragment is:

```clojure
{:schema 1
 :targets [:debian :ubuntu :fedora :arch :alpine :chimera :macos-arm64]
 :common [:valgrind :python3-pylsp]
 :additions {:alpine [:bash :less :libgcc :shadow
                      :cargo-audit :difftastic]
             :arch [:bacon]
             :wsl [:keychain]
             :brew-fallback [:bacon]}
 :targets-policy
 {:debian {:manager :apt}
  :fedora {:manager :dnf
           :rename {:python3-pylsp [:python3-lsp-server]}}
  :arch {:manager :pacman}
  :alpine {:manager :apk
           :skip {:python3-pylsp "Unavailable"
                  :bacon "Homebrew bottles require glibc"}}
  :chimera {:manager :apk}
  :macos-arm64 {:manager :brew
                :skip {:valgrind "Unsupported on current macOS"}}}
 :resources [:ubuntu-universe :powershell-repository :vscode-deb
             :git-ppa :onepassword-fedora :rpmfusion-codecs]}
```

The real manifest transcribes `install/packages.txt`, every `queue_install`
branch, and the current platform additions. A generated matrix shows the fully
expanded result, so concision cannot hide a missing target or omission.

== Policy evaluation

The Babashka planner is trusted; the policy expression is evaluated in a fresh
SCI context with an explicit allowlist. The context contains only:

- literals, local bindings, functions, conditionals, and collection operations
  needed by the manifest; and
- a small explicit subset of `clojure.string` if transcription needs it.

It contains no filesystem, environment, process, network, Java interop,
namespace loading, clocks, randomness, or host facts. Tests cover representative
allowed expressions and denied effects. The planner validates the returned map
before using it. This boundary prevents accidental effects; it is not a sandbox
for an untrusted checkout.

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

`apply` displays that plan, validates the required elevation interface, asks
once unless `--yes` was given, applies typed repository operations, and invokes
the selected executors with explicit requests:

```text
mise bootstrap packages apply --update --yes apt:bat apt:jq ...
mise bootstrap packages apply --yes brew:bacon
sudo pacman --sync --refresh --sysupgrade --needed -- bat jq ...
```

`--update` is used only when the current native-manager path requires it.
Commands are argv vectors: the executor never builds shell text, uses `eval`,
or splits package names. It stops on the first failed operation. Dry run performs
all reads and planning and may populate the pinned Babashka or mise versioned
user cache required to run the planner, but performs no package-manager,
repository, privilege-policy, or other system mutation.

Mise 2026.8.0's pacman backend uses `pacman -Sy` followed by
`pacman -S --needed` for named packages. That is a partial upgrade and does not
preserve the current setup contract. The Arch adapter therefore emits one typed
privileged pacman operation. Its non-root argv is
`sudo pacman --sync --refresh --sysupgrade --needed -- PACKAGES...`; root
execution omits sudo. It refreshes metadata, performs one full system upgrade,
avoids reinstalling satisfied packages, and protects package operands with `--`.
The policy still supplies logical names and mappings; only execution differs.

Both package entrypoints call `package-plan apply` as the invoking user. This
includes the package-only `setup_install_global_packages` path and the package
phase of the full `setup_install_global` path. The latter runs the planner before
it invokes the remaining root-owned setup phases; `setup_sudo.sh main` no longer
calls `install_features`. The planner, not the whole setup subprocess, prefixes
typed repository operations with the elevation command selected by the plan.
The pinned mise process remains unprivileged and receives the target's `sudo`
interface. This keeps user-owned bootstrap files out of a root-owned home.

== Bootstrap

=== Runtime bootstrap

`package-plan` must run before global packages, so it cannot depend on Python,
Node, Cargo, or a system Babashka package. A small POSIX shell shim downloads a
pinned standalone Babashka archive for the detected architecture, operating
system, and libc. Its declared bootstrap floor is a POSIX shell, `uname`, `tar`,
either `curl` or `wget` with TLS and certificate validation, and either
`sha256sum` or `shasum`. The planner does not install this floor. A missing
command produces a target-specific prerequisite error naming the packages to
install, without constructing or executing an installation command.

Linux x64, Linux ARM64, and Apple Silicon macOS are supported binary targets.
Babashka's official ARM64 Linux artifact requires the glibc loader despite its
`static` filename, so ARM64 Alpine and Chimera additionally require their native
`gcompat` package. A missing loader is reported with the other bootstrap-floor
prerequisites; the planner does not install it.

Official minimal container images are not the support boundary. Observed base
images currently divide as follows:

```text
debian, ubuntu -> tar and sha256sum; no TLS downloader
fedora, arch    -> tar, curl, and sha256sum
alpine          -> tar, wget, and sha256sum
chimera         -> sha256sum; no tar or TLS downloader
```

The corresponding tested floor packages are `ca-certificates` and `curl` on
Debian and Ubuntu, and `curl` plus `libarchive-progs` on Chimera. ARM64 Alpine
and Chimera additionally require `gcompat`. A TLS failure caused by a missing
trust store additionally names `ca-certificates`. Fedora, Arch, and x64 Alpine
require no added floor package in their current official base images.

Apple Silicon macOS supplies the bootstrap floor through the base system. These
facts are test fixtures, not permanent distribution promises; runtime command
detection remains authoritative.

`install/bootstrap.edn` pins Babashka and mise release URLs and SHA-256 digests
for every supported binary target. A development generator emits the minimal
shell lookup table used before Babashka exists. Tests reject stale generated
data. The shim downloads to a unique sibling temporary path, verifies the
digest and expected executable, then atomically renames it into a versioned
user cache.

Once running, the planner reads the same EDN file with a strict single-value
reader, validates its primitive data schema, and installs the pinned standalone
mise binary in the same manner. Ambient Babashka and mise are ignored during
bootstrap; all later calls use the pinned absolute paths. After a pin is edited,
an explicit development command regenerates the shell table; version control
displays the complete pin diff.

Runtime bootstrap mutates only the invoking user's versioned cache. It does not
install a system package or request root. The planner can therefore construct
and display the complete system-mutation plan before checking privilege access.

=== Privilege prerequisite

The planner does not install or configure an elevation tool:

+ If setup already runs as UID 0, use direct execution.
+ On Chimera, require doas in the ambient `PATH`, then prepend the repository's
  vendored `doas-sudo-shim` directory to the private package-execution `PATH`.
  Do not install or expose that shim system-wide.
+ On every non-root target, require a `sudo` executable already present in that
  package-execution `PATH`. Alpine may satisfy this with its packaged
  `doas-sudo-shim` or with real sudo; Chimera satisfies it with the vendored
  shim.

Planning, `show`, and dry run do not require an elevation command. Real apply
checks for the target's required interface after displaying the complete plan
but before confirmation or mutation. Authorization is checked by the first real
privileged operation; failure stops with that exact diagnostic rather than
trying another tool after possible mutation. The planner never invokes `su`,
changes sudoers or doas policy, or installs sudo or doas.
The error names the manual prerequisite for the detected target: the native
`sudo` package on Debian, Ubuntu, Fedora, and Arch; `sudo` or
`doas-sudo-shim` on Alpine; `opendoas` on Chimera; or the base-system sudo on
macOS. These are instructions for the operator, not executable plan operations.

The exact released upstream `doas-sudo-shim` script, its license, version, and
source digest are committed under `vendor/doas-sudo-shim/`. Chimera executes
that file in place through an absolute private `PATH` entry used for package
execution; the runtime bootstrap performs no download. Updating the vendored
release is an explicit development action that verifies its digest and displays
the complete vendor diff.

== Validation

Repository tests reject:

- unknown targets, providers, logical packages, resources, or disposition kinds;
- missing or overlapping package/target dispositions;
- empty native or fallback package vectors;
- fallback on a target unsupported by that provider;
- skips without reasons;
- invalid conditional resources or unpinned stable artifacts;
- duplicate physical requests with conflicting logical owners; and
- stale bootstrap data.

Privilege tests cover root, each target's required command, missing commands,
authorization failure at the first privileged operation, and exact elevated
argv. They prove that the planner never invokes `su`, installs an elevation
package, or changes privilege policy. Golden plans accept real sudo or Alpine's
packaged shim and reject a non-root host without its required interface, with
the target-specific manual prerequisite in the diagnostic. Setup integration
tests exercise both package-only and full setup entrypoints and prove that each
invokes the planner with the original user identity before any root-only phase.
They reject any path that calls the planner from `setup_sudo.sh`.
Chimera tests prove that only package execution receives the vendored shim path,
that the shim translates the exact sudo argv emitted by the pinned mise release,
and that the vendored files match their recorded digest. A test against the
official minimal Chimera image records `sh`, `awk`, and `cat` as stage-zero
facilities, records `id` for the vendored shim, and exercises root-direct
planning without assuming doas, sudo, or su is installed.

Container bootstrap tests record the observed minimal-image matrix above. A
missing floor command must produce the exact prerequisite diagnostic without
mutation. After the test fixture installs only the named floor packages, the
same image must bootstrap the pinned Babashka and mise artifacts successfully.
Fedora, Arch, and Alpine must succeed without adding floor packages. Equivalent
Apple Silicon macOS tests use a clean user cache rather than a container.

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
Executor tests record argv and check provider grouping, dry run, partial failure,
retry, and that Brew fallback never installs unrelated Brew packages. Human
matrices use stable target and package order for reviewable diffs.

Separate conformance tests run the pinned mise binary, rather than a mock, in
the disposable platform environments. They record its dry-run manager argv and
sudo forms. The Arch test bypasses mise and requires the direct adapter's single
exact `--sync --refresh --sysupgrade --needed --` argv with sudo as non-root and
without it as root. The Chimera test passes the observed `sudo COMMAND...`,
`sudo env KEY=VALUE COMMAND...`, and noninteractive `sudo -n true` forms through
the vendored shim to a recording fake doas. A pinned mise update cannot land
until these tests pass.

The cross-manifest test continues to reject duplicate ownership between this
policy, mise `[tools]`, Cargo, pipx, and other package manifests.

== Migration

+ Transcribe the current package list, mappings, omissions, platform additions,
  and repository operations, preserving the effective installed package set.
+ Add `install/bootstrap.edn`, pin Babashka and mise artifacts for every supported
  binary target, and generate the stage-zero shell table.
+ Vendor the reviewed Chimera `doas-sudo-shim` release, license, version, and
  digest, together with its explicit update command.
+ Add the matrix, host scenarios, adapter tests, and clean-host bootstrap tests.
+ Run the new path behind an explicit opt-in command on every supported target.
+ Split `install_features` out of `setup_sudo.sh main`; make both full setup and
  package-only setup invoke the planner as the original user before root-owned
  phases.
+ Switch both setup entrypoints after their plans match the characterized
  current requests and their integration tests prove the planner is not
  elevated.
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
does not install system dependencies. Mise covers the required managers except
for Arch's full-upgrade contract, but does not model logical names, omissions,
or native-versus-fallback policy.

Those tools solve broader problems. This design adds only the missing policy
layer around mise.
