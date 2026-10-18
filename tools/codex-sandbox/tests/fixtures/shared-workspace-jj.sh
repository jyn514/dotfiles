#!/trusted/bin/sh
# Test-only trusted shim: every operation still executes the pinned real JJ.
set -eu
case " $* " in
	*' user.name=Pi-B '*)
		case " $* " in
			*' commit '*|*' new '*) /trusted/bin/busybox touch /run/sandbox-proxy/entered-b ;;
		esac
		;;
esac
/trusted/bin/jj-real "$@"
case " $* " in
	*' user.name=Pi-A '*)
		case " $* " in
			*' metaedit --update-author '*) ;;
			*) exit 0 ;;
		esac
		if [ ! -e /run/sandbox-proxy/pause-complete ]; then
			/trusted/bin/busybox touch /run/sandbox-proxy/paused-a
			while [ ! -e /run/sandbox-proxy/release-a ]; do
				/trusted/bin/busybox sleep 0.02
			done
			/trusted/bin/busybox touch /run/sandbox-proxy/pause-complete
		fi
		;;
esac
