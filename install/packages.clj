;; Pure package policy. Host inspection and effects belong to tools/package-plan.
{:schema 1
 :targets [:debian :ubuntu :fedora :arch :alpine :chimera :macos-arm64]
 :common
 [:atuin :asciinema :bat :btop :build-essential :clangd :cowsay :curl
  :git-delta :direnv :fd-find :figlet :fish :fscrypt :fzy :gdu :git
  :git-absorb :glow :graphviz :ipp-usb :jq :kitty :libpam-fscrypt
  :libssl-dev :libterm-readline-gnu-perl :liburi-perl :libusb-1.0-0-dev
  :perl-file-which :manpages :manpages-dev :markdown-oxide :ninja-build
  :nmap :nvim :openjdk21 :pam-u2f :perl :pkg-config :python3-pip
  :python3-pylsp :rclone :sane :sane-airscan :shellcheck :signal-desktop
  :skanpage :strace :tcsh :traceroute :tree :tmux :unzip :valgrind
  :xdg-utils :xdot :zoxide :zsh]

 :additions
 {:alpine [:bash :less :libgcc :shadow :cargo-audit :difftastic]
  :arch [:bacon]
  :wsl [:keychain]
  :conditional [:powershell :onepassword]
  :brew-fallback [:bacon]}

 :targets-policy
 {:debian {:manager :apt
           :skip {:onepassword "Fedora repository operation"}}
  :ubuntu {:manager :apt
           :skip {:onepassword "Fedora repository operation"}}
  :fedora
  {:manager :dnf
   :rename {:openjdk21 [:java-25-openjdk]
            :onepassword ["1password"]
            :liburi-perl [:perl-URI]
            :manpages [:man-pages]
            :libssl-dev [:openssl-devel]
            :libterm-readline-gnu-perl [:perl-Term-ReadLine-Gnu]
            :python3-pylsp [:python3-lsp-server]
            :build-essential ["@development-tools"]}
   :skip {:libusb-1.0-0-dev "Unused on Fedora"
          :powershell "Debian-family repository operation"
          :manpages-dev "Included with man-pages"
          :libpam-fscrypt "Fedora setup does not use fscrypt"}}
  :arch
  {:manager :pacman
   :rename {:build-essential [:base-devel]
            :libusb-1.0-0-dev [:libusb]
            :libssl-dev [:openssl]
            :liburi-perl [:perl-uri]
            :libterm-readline-gnu-perl [:perl-term-readline-gnu]
            :ninja-build [:ninja]
            :clangd [:clang]
            :fd-find [:fd]
            :manpages [:man-pages]
            :openjdk21 [:jdk21-openjdk]
            :python3-pip [:python-pip]
            :python3-pylsp [:python-lsp-server]}
   :skip {:manpages-dev "Included with man-pages"
          :powershell "Debian-family repository operation"
          :onepassword "Fedora repository operation"
          :libpam-fscrypt "Unsupported by current setup"}}
  :alpine
  {:manager :apk
   :rename {:nvim [:neovim]
            :fd-find [:fd]
            :git-delta [:delta]
            :kitty [:kitty :kitty-kitten]
            :ninja-build [:ninja-build :ninja-is-really-ninja]
            :liburi-perl [:perl-uri]
            :libterm-readline-gnu-perl [:perl-term-readline-gnu]
            :manpages [:man-pages]
            :build-essential [:build-base]}
   :skip {:powershell "Debian-family repository operation"
          :onepassword "Fedora repository operation"
          :clangd "Unavailable"
          :cowsay "Unavailable"
          :fscrypt "Unavailable"
          :fzy "Unavailable"
          :glow "Unavailable"
          :ipp-usb "Unavailable"
          :libpam-fscrypt "Unavailable"
          :libssl-dev "Development files included by package"
          :libusb-1.0-0-dev "Development files included by package"
          :signal-desktop "Unavailable"
          :manpages-dev "Included with man-pages"
          :pkg-config "Unavailable"
          :python3-pip "Provided by Alpine baseline"
          :python3-pylsp "Unavailable"
          :skanpage "Unavailable"
          :xdot "Unavailable"
          :bacon "Homebrew bottles require glibc"}}
  :chimera
  {:manager :apk
   :rename {:clangd [:clang]
            :liburi-perl [:perl-uri]
            :pkg-config [:pkgconf]
            :python3-pip [:python-pip]
            :python3-pylsp [:python-lsp-server]
            :ninja-build [:ninja]
            :nvim [:neovim]
            :libssl-dev [:openssl3-devel]}
   :skip {:asciinema "Unavailable"
          :powershell "Debian-family repository operation"
          :onepassword "Fedora repository operation"
          :build-essential "Unavailable" :cowsay "Unavailable"
          :direnv "Unavailable" :fscrypt "Unavailable" :gdu "Unavailable"
          :git-absorb "Unavailable"
          :libpam-fscrypt "Unavailable" :libusb-1.0-0-dev "Unavailable"
          :manpages "Unavailable" :manpages-dev "Unavailable"
          :nmap "Unavailable"
          :libterm-readline-gnu-perl "Unavailable" :rclone "Unavailable"
          :shellcheck "Unavailable" :tcsh "Unavailable"
          :xdot "Provided by graphviz"
          :bacon "Homebrew bottles require glibc"}}
  :macos-arm64
  {:manager :brew
   :rename {:ninja-build [:ninja]
            :python3-pylsp [:python-lsp-server]
            :openjdk21 ["openjdk@21"]
            :fd-find [:fd]}
   :skip {:build-essential "Supplied by Xcode Command Line Tools"
          :powershell "Debian-family repository operation"
          :onepassword "Fedora repository operation"
          :fscrypt "Linux only" :libpam-fscrypt "Linux only"
          :libssl-dev "Development files included by package"
          :libterm-readline-gnu-perl "Unavailable"
          :liburi-perl "Unavailable" :libusb-1.0-0-dev "Unavailable"
          :manpages "Supplied by macOS" :manpages-dev "Supplied by macOS"
          :xdg-utils "Linux only" :strace "Linux only" :valgrind "Unsupported"
          :unzip "Supplied by Xcode Command Line Tools"
          :curl "Supplied by macOS" :clangd "Supplied by Xcode Command Line Tools"
          :python3-pip "Supplied by Xcode Command Line Tools"
          :traceroute "Supplied by macOS"}}}

 :fallbacks
 {:bacon {:targets [:debian :ubuntu :fedora]
          :manager :brew
          :packages [:bacon]
          :reason "No suitable native package"}}

 :resources
 [:ubuntu-universe :powershell-repository :vscode-deb :git-ppa
  :onepassword-fedora :rpmfusion-codecs]}
