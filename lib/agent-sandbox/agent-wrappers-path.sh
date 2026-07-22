case ":$PATH:" in
  *:/lib/agent-wrappers:*) ;;
  *) PATH=/lib/agent-wrappers:$PATH ;;
esac
export PATH
