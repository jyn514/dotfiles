case ":$PATH:" in
  *:/libexec/agent-wrappers:*) ;;
  *) PATH=/libexec/agent-wrappers:$PATH ;;
esac
export PATH
