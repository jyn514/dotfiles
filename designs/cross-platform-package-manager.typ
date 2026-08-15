#set page(paper: "us-letter", margin: 1in)
#set text(size: 10.5pt)
#set par(justify: true, leading: 0.65em)
#set heading(numbering: "1.")

= Cross-platform package management for the dotfiles repository

== Status and decision

This document proposes replacing package-selection logic in
`libexec/setup/setup_sudo.sh` with a typed policy and a small Clojure planner
running on Babashka.
The planner chooses packages; mise applies the resulting package-manager
requests. Shell remains only at the bootstrap boundary and where setup must
mutate a running shell.

The design deliberately retains native system package managers. It does not
replace apt, dnf, apk, pacman, or Homebrew with a universal package store. A
package should come from the platform's native manager when that manager has a
suitable package. A declared fallback such as mise's built-in Homebrew manager
may be used when the native manager does not.

The source of truth is one cross-platform policy manifest. Separate package
lists per manager are generated views, never independent declarations.

== Problem

The current design has one useful property: `install/packages.txt` establishes
a common package set, while the `queue_install` case statement makes platform
differences visible. A reviewer can see that macOS omits `strace` and
`valgrind`, that Arch renames `build-essential` to `base-devel`, and that
Alpine cannot supply several desktop packages.

It also has structural defects:

- Package identity, platform detection, package-name translation, fallback
  policy, and subprocess execution are mixed in one shell function.
- Omission is represented by `return`. The representation cannot distinguish
  unavailable software, software supplied by the operating system, deliberate
  policy, and an accidentally forgotten mapping.
- Multiple package names can be stored in one shell string. The boundary
  between one package and several packages is therefore implicit shell syntax.
- Platform coverage is tested by reconstructing the shell mapping in Python,
  rather than testing a shared domain model.
- Adding a second provider such as Homebrew on Linux makes manager detection an
  insufficient model. The planner must choose among providers, not merely find
  the first executable package manager.
- Moving one platform into a standalone mise manifest preserves installation
  behavior but destroys the easy comparison with other platforms. Positive
  declarations alone do not record negative decisions.

== Goals

- Give every logical package an explicit disposition on every supported target,
  independent of whether a host profile selects it.
- Make translations, omissions, and fallbacks readable in one place.
- Prefer native system packages unless policy explicitly selects a fallback.
- Use mise's package-manager implementations rather than maintaining subprocess
  syntax for every manager.
- Produce a complete, deterministic plan before changing the machine.
- Make invalid or incomplete policy fail during repository tests.
- Preserve bootstrap safety on a machine that has neither mise nor Babashka from
  this repository.
- Keep repository configuration, security setup, and package installation as
  separate operations with separate authority.

== Non-goals

- Reproduce dependency solving. The selected package manager owns dependency
  resolution.
- Create a public universal package-name registry.
- Make every package available on every target.
- Support Intel macOS. The macOS target is Apple Silicon only because mise's
  built-in Homebrew manager does not support Intel macOS.
- Pin native package versions across distributions.
- Replace mise's existing `[tools]` declarations for versioned user tools.
- Treat all executables as system packages. A tool may remain owned by mise,
  Cargo, pipx, or another scoped backend when that is the better boundary.
- Remove Homebrew itself where shell integration or `brew-command-not-found`
  still intentionally depends on the Homebrew CLI.

== Alternatives considered

=== Nix and Home Manager

Nix is the closest existing complete solution. Home Manager provides a largely
uniform package namespace on Linux and macOS, declarative convergence, and
platform conditionals. Adopting it would avoid most native-name translation.

It would also change the policy. The repository currently prefers packages
owned by apt, dnf, apk, pacman, or Homebrew, including native libraries and
desktop integration. Nix would replace that preference with a separate store,
runtime environment, and activation model. This is a valid larger migration,
but it is not an implementation of the requirement described here.

=== Ansible

Ansible abstracts invocation of the detected package manager and supplies
facts, privilege handling, check mode, and idempotence. Its generic package
module explicitly does not translate package names between distributions.
Per-distribution variable maps would still be repository-owned, and Ansible
would add a substantial runtime around a small local-machine plan.

=== asdf

asdf normalizes installation of versioned user tools through per-tool plugins.
A plugin may report operating-system-specific dependencies through
`bin/help.deps`, but asdf does not install or reconcile those dependencies.
Plugin installation scripts also hide provider policy inside arbitrary shell.
mise already covers the useful asdf role in this repository and supports a
broader set of binary backends.

=== chezmoi

chezmoi can store package data and render platform-specific scripts. Its own
package guidance uses declarative-looking data plus imperative installation
templates. This moves the current case statement into a template without
creating a typed package model.

=== mise bootstrap packages alone

Mise supports apt, dnf, apk, pacman, Brew formulae, and Brew casks. It can
inspect installed state, elevate when needed, and apply explicit
`manager:package` requests. It does not model equivalence between names, native
preference, reasons for omission, or the requirement that every logical package
have a disposition on every supported target.

Mise is therefore the package executor in this design, not the policy database.

=== Flower's Clojure extension model

Flower uses a useful intermediate design: extension files contain real Clojure,
run inside SCI, and return structured data that the trusted implementation can
analyze. Power comes from constructing data rather than performing effects
during evaluation. This design adopts that boundary without adopting Flower's
custom GraalVM native binary, incremental graph, or site-generation machinery.

Babashka already embeds SCI. The trusted planner is an ordinary Babashka
program; only the policy file is evaluated in a fresh restricted SCI context.

== Domain model

=== Logical packages

A logical package is the user intent independent of provider spelling. Examples
are `neovim`, `build-toolchain`, `python-lsp-server`, and `valgrind`. Its name
must be stable, unique, and meaningful to a reader. It need not equal any
particular distribution's package name.

Each logical package records:

- a short purpose, when the name is not self-explanatory;
- its disposition for every supported target;
- optional ordering constraints required for repository or runtime setup.

=== Host facts and targets

Host detection produces structured facts before it selects policy. The initial
facts are operating system, distribution family, distribution identifier and
version, architecture, libc, WSL status, and whether the host has a graphical
session. Raw `/etc/os-release` strings do not flow into package lookup.

A target is the package-compatibility portion of those facts. The initial
closed set is:

```text
debian
ubuntu
fedora
arch
alpine
chimera
macos-arm64
```

Architecture and libc are part of a target only where provider availability
differs. This matters for mise's built-in Homebrew support: it supports Apple
Silicon macOS and glibc Linux, but not Intel macOS or musl Linux.

Detection returns exactly one known target plus orthogonal host facts, including
the distribution release, or fails with an unsupported-host diagnostic.
Compatibility aliases are explicit. Package dispositions are shared across
releases unless an observed name or availability difference declares a narrow
release override. Repository resources may likewise constrain supported
releases or interpolate a validated release fact into structured fields. The
planner must not silently treat an unknown derivative as Debian.

Release support is policy, not test inventory. The required `:releases` map has
exactly the target keys. Each value is either `(fixed #{RELEASE ...})`, with a
non-empty set of exact normalized releases, or `(rolling)`. Detection of a
fixed-release target whose normalized release is absent from that set fails
before package selection; the planner never silently applies an older base
mapping. A rolling target accepts the detected runtime state but makes no
repository reproducibility promise.

Host fixtures live under `tools/package-plan/tests/hosts/`, outside the policy.
Each is structured host-fact data with a stable scenario name. Tests include
every supported fixed release and representative dated snapshots for rolling
targets, but those dates do not enter package lookup or define support.

A package release override is keyed by target and exact normalized release. It
replaces that target's base disposition and must state why the base mapping does
not apply. Overrides are exceptional: validation rejects an override for an
unsupported release, and golden host scenarios exercise every override. There
is no release wildcard or inheritance hierarchy. The manifest represents one
with `(release-override TARGET RELEASE DISPOSITION :reason TEXT)`, nested in the
affected package. The constructor rejects a target/release pair that is not a
supported fixed release; it cannot introduce a new target or a partial
disposition.

=== Profiles

Profiles decide which logical packages a host wants; targets decide how those
packages can be supplied. The initial profiles are `base`, `development`,
`desktop`, `scanner`, `security`, and `wsl`. `base` is always selected. Other
profiles are selected in the machine-local
`~/.config/dotfiles/package-profiles.edn`, except that `wsl` is also enabled
from the detected WSL fact. The file contains exactly
`{:schema 1 :profiles #{...}}`; unknown keys and profiles are errors. A missing
file selects no optional profiles. The planner uses the common strict EDN data
loader: read one value, read again to require EOF, provide no tagged-literal
readers, and never evaluate the file as Clojure. Repeated `--profile` flags add
profiles for that invocation and never persist them. Selection therefore has
one order: `base`, then the local set, then detected `wsl`, then CLI additions.
Duplicate selection is harmless.

Profiles are the sole owners of package membership and necessity. Each member
is `required` or `optional`; packages do not carry a second profile list or a
global necessity flag. Profiles contain no provider names or target branches.
Thus `scanner` can require `scanner-drivers`, while the target mapping determines
whether that means `sane-airscan`, `sane-backends`, an operating-system
facility, or an unsupported capability.

If several selected profiles contain the same package, `required` dominates
`optional`. An unsupported required package is a planning error before mutation;
an unsupported optional package remains a visible warning.

Profile selection is part of the displayed plan. Desktop applications do not
silently appear because a distribution happens to package them, and a server
does not inherit workstation policy merely because it shares an operating
system.

=== Dispositions

Every logical package has exactly one disposition per target. A disposition is
required even when no current profile selects that package on the target; this
keeps availability policy independently auditable.

/ Native: Install one or more packages through the target's default native
  namespace or a named auxiliary native namespace supported by that target.

/ Fallback: Install through a named non-native provider because the native
  manager lacks a suitable package. The declaration includes a reason.

/ System: The operating system or required base tooling already supplies the
  capability. The declaration names that owner, such as Xcode Command Line
  Tools.

/ Unsupported: No supported provider can supply the capability on this
  target. The declaration includes a reason.

/ Omitted: The package exists, but repository policy intentionally does not
  install it on this target. The declaration includes a reason.

There is no implicit missing state. A missing target entry is a schema error.
An empty package list is not a synonym for unsupported or omitted.

=== Providers

A provider identifies an installation mechanism and its package namespace:

```text
apt
dnf
apk
pacman
brew
brew-cask
```

The planner has a closed, tested registry for native package namespaces: apt,
dnf, apk, pacman, Brew formulae, and Brew casks. A target declaration selects
one default namespace and thereby derives its mise manager name and privilege
requirement. The registry also makes `brew-cask` an auxiliary native namespace
on `macos-arm64`. Ordinary `(native ...)` uses the target default;
`(native-via :brew-cask ...)` names the auxiliary namespace explicitly. An
auxiliary native namespace is not a fallback and requires no fallback reason.
The manifest does not repeat registry facts.

The manifest declares only non-native fallback extensions, such as Brew
formulae on glibc Linux. `(fallback-capability PROVIDER TARGETS ...)` refers to
an existing registry provider and names only its additional targets and any
release constraints; it cannot redeclare the mise manager or native targets.
Qualification resolves operating system, architecture, libc, and release; it
cannot infer Intel macOS support from a generic `x64` entry. The planner rejects
a fallback whose provider cannot run on the selected host facts.

The initial design does not automatically fall through a preference list after
an installation failure. A missing native mapping may select Brew explicitly;
a failing native installation remains a failure. Runtime failure is not
evidence that policy should silently choose a different authority.

=== Package repositories

Third-party package repositories are first-class resources. A repository
declaration has a stable identifier, supported targets, provider, metadata URL,
signing-key source and expected file SHA-256, and an idempotent installation
adapter. A package disposition may name one repository prerequisite.

The planner includes only repositories required by selected packages. It emits
repository operations before package operations and shows their authority and
network origins in the plan. Conflicting repositories, an unpinned signing-key
artifact, or a repository unsupported on the selected distribution version are
planning errors.

Repository adapters are typed Clojure implementations for the small supported
set: apt source/keyring, dnf repository package or configuration, and pacman
repository configuration where needed. Mise's `bootstrap.repos` manages Git
checkouts, not operating-system package repositories, and is not used for this
purpose. Adapter inputs are structured fields; the manifest cannot contain an
arbitrary setup command.

`apply` converges only selected repositories owned by this manifest. For an apt
repository, that means downloading an ASCII-armored key to a sibling temporary
file, verifying its pinned SHA-256, atomically replacing the owned key file,
and atomically replacing one owned source-list file with canonical content.
Equivalent explicit contracts apply to dnf and pacman. A changed URL, suite,
component list, or accepted key digest is displayed in the plan before
replacement.

Ordinary apply never removes an unselected or obsolete repository. Removal is a
separate future prune operation because it can strand installed packages. If a
later package installation fails, an already converged repository remains; the
operation reports partial completion and a retry continues from inspected
state. Pretending repository and package-manager mutations are transactional
would be false.

== Manifest format

The policy is a pure Clojure file at `install/packages.clj`. It contains one
expression whose value is a policy object assembled through constructors
provided by the planner. It does not declare a namespace, load dependencies,
inspect the host, or perform installation.

Clojure removes the repetition pressure that made the TOML design accumulate
shorthands. Ordinary sets, maps, `let`, `into`, `merge`, `map`, `for`, and small
local functions may construct policy data. The validator still sees a complete
normalized domain model; Clojure is an authoring language, not an escape from
coverage requirements.

A representative fragment is:

```clojure
(let [linux #{:debian :ubuntu :fedora :arch :alpine :chimera}
      glibc-linux #{:debian :ubuntu :fedora :arch}]
  (policy
    {:schema 1
     :targets {:debian       (target :apt)
               :ubuntu       (target :apt)
               :fedora       (target :dnf)
               :arch         (target :pacman)
               :alpine       (target :apk)
               :chimera      (target :apk)
               :macos-arm64  (target :brew)}

     :releases
     {:debian      (fixed #{"13"})
      :ubuntu      (fixed #{"24.04"})
      :fedora      (fixed #{"42" "43"})
      :arch        (rolling)
      :alpine      (fixed #{"3.22"})
      :chimera     (rolling)
      :macos-arm64 (fixed #{"26"})}

     :profiles
     {:base        (profile :required #{:shells :version-control})
      :development (profile :required #{:python-lsp-server}
                            :optional #{:valgrind :bacon})
      :scanner     (profile :required #{:scanner-drivers})}

     :provider-extensions
     [(fallback-capability :brew glibc-linux)]

     :repositories
     {:vendor-tools
      (apt-repository
        :targets #{:debian :ubuntu}
        :releases {:debian #{"13"} :ubuntu #{"24.04"}}
        :base-url "https://packages.example.invalid/linux"
        :suite "stable"
        :components ["main"]
        :signing-key-url "https://packages.example.invalid/keys/archive.asc"
        :signing-key-sha256
        "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")}}

    [(package :valgrind
       (native-same-name (disj linux :chimera))
       (unsupported #{:chimera}
         "No maintained package in the supported repositories")
       (unsupported #{:macos-arm64}
         "Valgrind does not support current macOS"))

     (package :bacon
       (native {:arch ["bacon"] :macos-arm64 ["bacon"]})
       (fallback (disj glibc-linux :arch) :brew ["bacon"]
         :reason "No suitable native package")
       (unsupported #{:alpine :chimera}
         "Homebrew bottles require glibc"))

     (package :python-lsp-server
       (native {:debian ["python3-pylsp"]
                :ubuntu ["python3-pylsp"]
                :fedora ["python3-lsp-server"]
                :arch ["python-lsp-server"]
                :alpine ["py3-python-lsp-server"]
                :chimera ["python-lsp-server"]
                :macos-arm64 ["python-lsp-server"]})
       (release-override :fedora "43"
         (native-packages ["python-lsp-server"])
         :reason "Fedora 43 renamed the package"))]))
```

There is no unbounded default, wildcard target, inheritance chain, or negative
target list. Every package must cover every target exactly once after Clojure
evaluation. A newly added target therefore fails validation until the authored
expression covers it. The matrix renderer always shows the fully expanded
result, preserving both a concise source view and an exhaustive review view.

Do not encode multiple packages in one whitespace-separated string. Do not use
magic values such as `:none`, `:skip`, or `:system` where distinct constructors
can make states unrepresentable.

=== Policy evaluation and permissions

The Babashka planner is trusted code and runs with the invoking user's normal
authority. The policy file does not. The planner reads its bytes, creates a
fresh SCI context, evaluates the source there, and validates the returned value.

The SCI context is built with empty namespace and class maps, then populated
from a versioned allowlist owned by the planner. Policy API version 1 exposes
exactly these Clojure symbols in addition to literals:

```text
special forms: let, fn, if, do, quote
clojure.core: = not and or, + - * / < <= > >=,
  keyword symbol name str, vector hash-map hash-set,
  assoc dissoc get get-in contains? update,
  conj disj into merge select-keys,
  seq first next rest nth count empty?,
  map mapcat filter remove reduce keep,
  set vec keys vals range repeat,
  apply partial comp identity constantly,
  every? some not-any? distinct sort sort-by,
  for when when-not cond case -> ->> as->
clojure.string: join split replace lower-case upper-case starts-with? ends-with?
```

Constructors documented by the policy API are injected under their unqualified
names. Adding or removing any symbol changes the policy API version; the SCI
options do not inherit Babashka's default namespaces. Because SCI's parser may
recognize more special forms than its namespace map exposes, the loader first
walks the parsed forms and rejects every special form and qualified symbol not
listed by this API; SCI evaluation happens only after that syntactic gate. The
implementation tests the complete allowlist and gate, not merely representative
allowed expressions.

It exposes:

- pure Clojure collection, sequence, arithmetic, keyword, and local-binding
  operations needed to construct data, plus an explicitly injected subset of
  `clojure.string`;
- immutable literals and ordinary control forms;
- only the package-policy constructors documented in this section.

It exposes no filesystem functions such as `slurp` or `spit`, environment
access, process execution, networking, Java classes or interop, namespace
loading, dynamic dependency loading, clocks, randomness, or host facts. The
policy cannot `require` `babashka.process`; `System/getenv` and similar class
access are unresolved. Repository tests exercise every denied capability as
well as every allowed constructor.

This is capability restriction, not hostile-code containment. The repository
and policy file are trusted; SCI prevents accidental effects and makes the
authoring contract analyzable. The Babashka process itself retains the user's
full operating-system permissions, and an SCI or Babashka vulnerability could
violate the language boundary. Running policy supplied by an untrusted checkout
would require a separate operating-system sandbox and is outside this design.

The policy API returns opaque constructor values rather than accepting maps that
imitate internal records. After evaluation, one conversion boundary parses
those values into the planner's domain model and attributes diagnostics to SCI
source spans. A policy returning any other value is an error.

== Planner

Create a self-contained Babashka subsystem under `tools/package-plan/`. It
contains the SCI policy loader, constructor API, typed domain values, host
detection, plan construction, renderers, execution adapters, and tests. A small
entry point is exposed through `dev/package-plan` during migration and may
become a user-facing command after the interface stabilizes.

Planning is pure after host detection:

+ Read `install/packages.clj` as source bytes without evaluating it in the host
  Babashka context.
+ Evaluate it in the restricted SCI context and require one policy-constructor
  result.
+ Convert opaque constructor values into typed domain objects in one validation
  boundary.
+ Validate the closed target and provider registry plus manifest extensions.
+ Validate selected profiles and expand them to logical packages.
+ Require exactly one disposition for every package/target pair.
+ Validate provider compatibility and native-manager consistency.
+ Validate package and repository release constraints, URLs, and pinned
  signing-key digests.
+ Select the target and retain orthogonal host facts.
+ Expand every installable disposition into individual provider/package
  requests.
+ Order required repository operations before their package requests.
+ Sort observable sequences explicitly: repository operations by dependency
  then stable identifier, package requests by provider then logical package,
  and human and golden table rows by logical package in declared target order.
+ Return a plan containing both installation requests and non-installing
  decisions.

The plan retains provenance. Each requested native package points back to its
logical package and manifest location. Diagnostics can therefore say
`python-lsp-server maps to dnf:python3-lsp-server`, rather than reporting only
the provider spelling.

=== Plan output

`package-plan show` prints detected facts, selected profiles, required
repositories, and a compact table with one row per selected logical package:

```text
logical package       disposition   request or reason
python-lsp-server     native        brew:python-lsp-server
strace                unsupported   Linux-specific tracing interface
valgrind              unsupported   unsupported on current macOS
bacon                  native        brew:bacon
```

`package-plan matrix` prints the complete cross-platform matrix. This is the
primary review interface and preserves the useful property of the old case
statement: differences and absences are visible together.

`package-plan matrix --profile development` restricts rows without changing
target columns. `package-plan explain valgrind` shows the authored declarations,
expanded dispositions, profile membership, and repository prerequisites for
one logical package.

`package-plan export --format mise` emits the exact ordered argument arrays used
by the executor, encoded as versioned JSON. Generated output includes a policy
schema version and SHA-256 of the policy source bytes. It is never edited by
hand. JSON object order has no meaning and tests compare parsed values. Arrays
retain execution order. Human tables and checked-in golden matrices use their
specified stable row and column orders so review diffs remain useful.

=== Execution

`package-plan apply` first constructs and displays the complete plan. It then
applies required repository resources, refreshes only affected native-manager
metadata, groups package requests by provider, and invokes mise with argument
arrays:

```text
mise bootstrap packages apply --update --yes apt:bat apt:jq ...
mise bootstrap packages apply --yes brew:bacon ...
```

Explicit package arguments are essential. A shared mise configuration
containing macOS Brew packages must not cause bare `mise bootstrap` on Linux to
install them merely because the Brew backend is technically available there.
`--update` is present only for a native manager whose repository resources
changed or whose selected policy requires a metadata refresh. Fallback Brew
application does not refresh an unrelated native manager.

The executor never constructs shell command text, never uses `eval`, and never
splits package names on whitespace. It captures each provider result separately
and stops after the first failed provider group. A later retry replans from
installed state through mise and remains idempotent.

Dry-run mode performs full parsing, target selection, validation, repository
inspection, and rendering, but neither repository adapters nor mise mutate the
host. JSON output is available for tests and future tooling; human output is
not parsed as a protocol.

== Bootstrap boundary

The policy cannot choose the runtime needed to evaluate itself. The design
resolves this cycle with a pinned mise binary that installs pinned Babashka
before any policy evaluation. Python is not part of the planner bootstrap.

The supported-host bootstrap contract requires a POSIX shell, `uname`, `tar`,
one TLS downloader (`curl` or `wget`), and one SHA-256 implementation
(`sha256sum` or `shasum`). These are preconditions, not packages selected by the
planner. The shim checks all of them before mutation and reports the exact
missing prerequisite. Supporting a host whose base system lacks this contract
requires a separately reviewed bootstrap transport; the shim does not silently
invoke a native package manager to repair itself.

The authored source for stage zero is `install/bootstrap.edn`. It contains only
the schema version, pinned mise and Babashka versions, and a closed target map
of release URLs and SHA-256 digests. It is read by repository development tools,
never by the clean-host shim. The generator uses `clojure.edn/read` on a
pushback reader, reads again to require EOF, and supplies no tagged-literal
readers; tagged literals, trailing forms, and unknown keys are errors, and the
file is never evaluated as Clojure. `dev/package-plan bootstrap
generate` validates that value and generates a shared stage-zero mise config and
lockfile plus one mise-download metadata record per supported binary target under
`install/generated/bootstrap/`. The mise config declares exactly one tool:
pinned Babashka from a standalone binary backend. It declares no system
packages, repositories, language runtimes, hooks, or tasks. The lockfile carries
Babashka's resolved release URL and checksum for every supported target.

Each mise metadata record contains only schema version, bootstrap-lock digest,
mise version, target-specific release URL, and SHA-256. The shim parses an exact
set of `name=ASCII-value` fields; it does not source the record as shell code.
URLs, versions, digests, and field names are validated again before use.

The generated artifacts are checked in and golden-tested. Repository tests
reject stale artifacts and any stage-zero mise declaration other than
Babashka. They are compiled views of `install/bootstrap.edn`, not editable
inputs. `dev/package-plan bootstrap update --mise VERSION --babashka VERSION`
downloads upstream release metadata, verifies that every target artifact
exists, writes proposed versions, URLs, and digests to the authored source, and
regenerates all views. Review includes the complete source and generated diff;
ordinary generation never contacts the network or changes pins.

The bootstrap sequence is concrete:

+ A minimal POSIX shell entry point detects the closed target using only
  `uname`, `/etc/os-release`, and libc inspection.
+ It ignores any ambient `mise` for stage zero. If the pinned bootstrap binary
  is not already present, it acquires an atomic `mkdir` lock beside
  `~/.local/share/dotfiles-bootstrap/mise/<version>/mise` and creates a sibling
  staging directory. It downloads the target's pinned archive there, verifies
  the generated SHA-256 before extraction, validates the expected executable
  and mode, rechecks the destination under the lock, and renames the staged
  executable into place on the same filesystem. Download, hash, extraction,
  permission, or rename failure removes staging and leaves any previous binary
  unchanged.
+ The lock records PID and acquisition time. A contender waits for a bounded
  interval. It may atomically rename and remove a stale lock only when the owner
  PID is absent and the recorded age exceeds the stale threshold; malformed
  ownership data is an error requiring manual inspection. Traps remove only a
  lock whose recorded owner matches the current process.
+ It runs the pinned mise binary's `install --locked --yes` against the generated
  stage-zero config and lockfile. Every call uses the absolute pinned mise path,
  and the resulting Babashka executable is addressed through `mise exec` against
  that config rather than ambient `PATH`.
+ It invokes `package-plan validate` with that Babashka before any workstation
  package mutation.
+ The planner redetects the host independently, verifies that its target agrees
  with the stage-zero selection, and applies selected profiles.
+ Normal user-tool installation and dotfile setup follow.

Target detection exists twice by necessity, but only one copy is authored: the
Clojure detector generates POSIX case data consumed by the shim. Tests run the
same host fixtures through both interfaces and require identical results. The
shim contains no package names and cannot select arbitrary config paths.

The bootstrap matrix verifies that both pinned mise and pinned Babashka have
usable standalone artifacts on every supported target, including musl. A target
without both artifacts is unsupported until it receives a separately reviewed
bootstrap transport.

Any new stage-zero dependency requires a design revision. The generated-config
check deliberately has no general allowlist extension mechanism; this prevents
stage zero from growing into an unreviewed second package manager.

== Privilege and non-package setup

Package installation must be separated from repository enablement, security
configuration, device permissions, encryption, global file installation, and
service setup. These operations have different authority and failure modes.

The initial decomposition is:

- `package-plan apply` installs declared packages and lets mise request sudo
  for managers that require it.
- `package-plan apply` converges selected, typed package-repository prerequisites
  before invoking package providers.
- `setup security` configures unattended upgrades, PAM, encryption, or related
  host policy.
- `setup globals` installs files under system-owned paths.
- `setup devices` handles groups and device-specific software such as Keymapp.

These commands may share platform detection, but they do not share an
unstructured `install_features` function. Each command reports what authority
it needs before mutation.

During characterization, existing repository setup may remain as a named
adapter behind the typed repository resource. The caller switch cannot occur
until package selection, repository selection, and their dependency edge come
from the manifest.

== Validation

=== Schema checks

Repository tests reject:

- unknown targets, profiles, providers, repositories, fields, or disposition
  kinds;
- malformed machine-local profile configuration, including unknown keys,
  profiles, or schema versions;
- a logical package missing any supported target after shorthand expansion;
- more than one disposition for a package/target pair;
- a release map whose keys differ from the target set, an empty fixed-release
  set, or a release override without a supported fixed release, base target
  disposition, or reason;
- an empty native or fallback package list;
- fallback through a provider incompatible with the target;
- `native-via` naming a namespace that is not auxiliary-native on the target;
- a fallback extension that redeclares registry metadata, includes a native
  target, or names an unknown provider;
- unsupported, omitted, or system dispositions without a reason or owner;
- duplicate provider/package requests with conflicting logical owners;
- fallback cycles, if aliases or shared capabilities are added later;
- a selected repository unsupported by the target or distribution version;
- repository signing keys without a complete expected SHA-256;
- stale generated bootstrap configs or stage-zero detector data;
- a generated bootstrap artifact that differs from `install/bootstrap.edn`;
- stage-zero mise configs declaring anything other than pinned Babashka.

=== Golden plans

One reviewed golden matrix per target records all expanded dispositions,
including non-installing decisions. A smaller set of host-scenario goldens
records profile selection, host facts, repositories, and executable requests.
Every supported fixed release has at least one structured host scenario, and
every release override appears in one. Rolling targets use dated scenarios but
do not claim repository reproducibility. Tests also require an unlisted fixed
release to fail before package selection.
These fixtures answer both directions:

- What will this target install, and through which provider?
- Why does this logical package not install on this target?

Changing `valgrind` from unsupported to omitted, or losing its macOS row
entirely, changes the golden plan. Adding a target forces every package to
acquire a disposition before tests pass.

=== Executor tests

Mock mise with an executable that records NUL-delimited arguments. Test exact
argv, provider grouping, deterministic order, dry run, missing mise, partial
provider failure, retry, and diagnostic provenance. Tests must prove that a
Brew fallback on Debian installs only the explicitly selected fallback and not
the macOS Brew package set. Tests compare JSON structurally. Property tests vary
manifest map and set insertion order and require the same plan semantics, exact
executable argv, and stable human and golden tables.

=== End-to-end tests

Container tests cover Debian, Ubuntu, Fedora, Arch, Alpine, and Chimera where a
maintained image exists. They apply a small disposable fixture rather than the
entire workstation manifest. macOS tests use dry-run planning plus owned
formulae that are cheap to install and remove when mutation coverage is needed.

The complete repository suite remains the final gate.

== User interface

The initial command surface is deliberately small:

```text
dev/package-plan validate
dev/package-plan show [--target TARGET] [--profile PROFILE]
dev/package-plan explain PACKAGE
dev/package-plan matrix [--profile PROFILE]
dev/package-plan apply [--profile PROFILE] [--dry-run] [--yes]
```

`--target` defaults to detection for `show`; tests and reviewers can select any
target. `apply` never accepts a target override. Dry-run application against a
synthetic host uses an explicit fixture file through a development-only
subcommand, not a production override flag.

Interactive confirmation displays all providers and the count of logical and
physical packages. `--yes` is required from noninteractive setup. Unsupported
required packages make `apply` fail before mutation; unsupported optional
packages remain visible warnings.

== Migration

=== Phase 1: Characterize current policy

+ Translate `install/packages.txt` and every `queue_install` branch into the new
  manifest without changing behavior.
+ Separate current host-conditional choices into target dispositions and named
  profiles, including WSL, desktop, scanner, and security behavior.
+ Record explicit reasons for every existing `return` and every platform-only
  addition.
+ Model every selected third-party repository and pinned signing-key artifact.
+ Add golden plans and compare their install requests with existing setup
  tests.
+ Resolve accidental mappings discovered during transcription, such as names
  that Homebrew never provided, in separate commits.

Exit criterion: every current logical package has a disposition on every
supported target, representative host profiles reproduce intended current
requests, and the expanded matrix is easier to audit than the shell mapping.

=== Phase 2: Introduce mise execution

+ Add the executor behind an explicit opt-in setup command.
+ Run dry plans on every supported host and mutation tests in disposable
  environments.
+ Compare installed-state results with the existing shell path.
+ Replace third-party repository preparation with typed resources and adapters
  before enabling any package that depends on them.

Exit criterion: mise applies exact explicit requests without cross-provider or
cross-platform leakage.

=== Phase 3: Switch setup

+ Change global package setup to invoke the planner.
+ Delete `queue_install`, manager-specific package command construction, and
  hand-maintained Brew package declarations.
+ Retain only the minimal mise bootstrap adapter and non-package setup phases.
+ Update setup documentation and failure messages.

Exit criterion: there is one package policy source and one tested planner.

=== Phase 4: Tighten ownership

+ Reclassify tools that belong in mise `[tools]`, native packages, or scoped
  language backends.
+ Add a cross-manifest check preventing duplicate ownership unless an explicit
  capability relationship requires it.
+ Consider generating documentation tables from the expanded matrix.

Exit criterion: every installed tool has one declared owner per target and
selected profile.

== Rollback criteria

Do not switch setup to the planner if any of these remain true:

- Any supported clean-machine fixture cannot obtain mise and the planner runtime
  solely from its generated, closed stage-zero artifact.
- The manifest cannot explain every current omission without an escape hatch.
- Mise cannot apply an existing required native package without losing needed
  manager semantics.
- The generated plan cannot be reviewed more easily than the current case
  statement.
- Tests reconstruct policy independently instead of validating the manifest's
  domain model and expanded plans.

== Recommended first milestone

Build a vertical prototype before committing to the full API. It contains the
restricted SCI loader, policy constructors, validator, target/profile model,
matrix renderer, repository model, and stage-zero generator for a deliberately
difficult package set: `strace`,
`valgrind`, `bacon`, `cargo-audit`, Python, scanner drivers, PowerShell,
1Password, Kitty, and Signal. The set exercises native renames, unsupported
targets, Brew fallback, musl, casks, profiles, repositories, pinned keys,
and ownership of Python after the planner is already available.

The prototype must produce:

- a readable complete target matrix;
- plans for a Debian 13 WSL development host, Fedora 42 desktop, Arch rolling
  development host, Alpine 3.22 container, Chimera rolling host, and Apple
  Silicon Mac;
- typed repository prerequisites for PowerShell and 1Password;
- generated stage-zero artifacts that bootstrap Babashka in clean disposable
  environments;
- exact mise argv without installing unrelated Brew packages on Linux.

Do not migrate the remaining package set or change `setup.sh` until this
prototype passes review. It tests all four risky claims at once: the schema is
auditable, profiles are orthogonal to targets, repositories compose with
packages, and bootstrap is not circular. If any claim fails, revise the model
before adding breadth.
