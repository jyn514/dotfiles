for directory in /libexec/agent-wrappers /libexec/sandbox-wrappers; do
  case ":$PATH:" in
    *:$directory:*) ;;
    *) PATH=$directory:$PATH ;;
  esac
done
unset directory
export PATH
