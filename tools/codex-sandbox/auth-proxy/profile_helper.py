#!/usr/bin/env python3
"""Single-threaded private Unix-socket Caddy credential helper."""
from __future__ import annotations
import argparse, base64, configparser, contextlib, hmac, importlib.util, json, os, signal, sys, time
from pathlib import Path
import socketserver
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import Callable
from urllib.parse import urlsplit

MAX_AUTHORIZATION=4096; MAX_REQUEST_LINE=8192; MAX_HEADERS=65536; MAX_LOG_METHOD=64; MAX_LOG_PATH=2048; WORK_TIMEOUT=30.0
class CredentialFailure(Exception): pass

@contextlib.contextmanager
def operation_deadline(seconds=WORK_TIMEOUT):
    def expired(signum, frame): raise TimeoutError("credential operation deadline exceeded")
    started=time.monotonic(); previous=signal.signal(signal.SIGALRM, expired)
    old=signal.setitimer(signal.ITIMER_REAL, seconds)
    try: yield started+seconds
    finally:
        # Block delivery while replacing both timer and handler. An inherited
        # one-shot timer resumes with only its unelapsed portion.
        signal.pthread_sigmask(signal.SIG_BLOCK,{signal.SIGALRM})
        try:
            signal.setitimer(signal.ITIMER_REAL,0)
            elapsed=time.monotonic()-started
            if not old[0]: restored=0
            elif elapsed < old[0]: restored=old[0]-elapsed
            elif old[1]: restored=old[1]-((elapsed-old[0]) % old[1])
            else: restored=0
            # Discard a just-expired alarm owned by this context before putting
            # the caller's handler back; otherwise it can hit the wrong handler.
            if signal.SIGALRM in signal.sigpending(): signal.sigwait({signal.SIGALRM})
            signal.signal(signal.SIGALRM,previous)
            signal.setitimer(signal.ITIMER_REAL,restored,old[1])
        finally: signal.pthread_sigmask(signal.SIG_UNBLOCK,{signal.SIGALRM})

def _codex_module():
    path=Path(__file__).with_name("codex_profile.py")
    spec=importlib.util.spec_from_file_location("caddy_codex_profile",path)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module

def codex_credentials(deadline):
    access,account=_codex_module().credentials(deadline=deadline)
    return (("Authorization","Bearer "+access),("Chatgpt-Account-Id",account))
def codex_ready(deadline):
    module=_codex_module(); data=module.read_auth(); tokens=data["tokens"]
    access=tokens["access_token"]; claims=module.jwt_payload(access)
    account=tokens.get("account_id")
    auth=claims.get("https://api.openai.com/auth")
    account=account or (auth.get("chatgpt_account_id") if isinstance(auth,dict) else None)
    if not isinstance(claims.get("exp"),(int,float)) or not isinstance(account,str) or not account:
        raise CredentialFailure("invalid Codex credential structure")
    return (("Authorization","Bearer ready"),("Chatgpt-Account-Id","ready"))
def _zulip(path=None):
    parser=configparser.ConfigParser(interpolation=None)
    with (path or Path(os.environ.get("ZULIPRC","/var/lib/zulip/zuliprc"))).open(encoding="utf-8") as stream: parser.read_file(stream)
    email=parser.get("api","email",fallback=""); key=parser.get("api","key",fallback="")
    if not email or not key or any(c in email+key for c in "\r\n"): raise CredentialFailure("invalid Zulip credential")
    return email,key
def zulip_credentials(deadline,path=None):
    email,key=_zulip(path); value=base64.b64encode((email+":"+key).encode()).decode("ascii")
    return (("Authorization","Basic "+value),)
def zulip_ready(deadline):
    _zulip(); return (("Authorization","Basic ready"),)

class UnixHTTPServer(socketserver.UnixStreamServer):
    allow_reuse_address=False
    def __init__(self,path,token,credentials,readiness=None,log=sys.stderr):
        if not token or len(("Bearer "+token).encode())>MAX_AUTHORIZATION: raise ValueError("session token is empty or too long")
        self.session_token=token; self.credentials=credentials; self.readiness=readiness or credentials; self.result_log=log
        super().__init__(path,HelperHandler)
    def result(self,decision,method,path,result,reason=None,helper_path=None):
        line=("profile_helper decision="+decision+" method="+json.dumps(method)+
              " path="+json.dumps(path)+" result="+result)
        if reason is not None: line+=" reason="+reason
        if helper_path is not None: line+=" helper_path="+json.dumps(helper_path)
        print(line,file=self.result_log,flush=True)

class HelperHandler(BaseHTTPRequestHandler):
    protocol_version="HTTP/1.1"; server_version="profile-helper"; sys_version=""
    def log_message(self,*args): return
    def _log_result(self,result,reason=None,helper_path=None):
        uri=self.headers.get("X-Original-Uri",self.path)
        try: path=urlsplit(uri).path or "/"
        except ValueError: path="<invalid>"
        if len(path)>MAX_LOG_PATH: path=path[:MAX_LOG_PATH]+"…"
        method=self.headers.get("X-Original-Method",self.command)
        if len(method)>MAX_LOG_METHOD: method=method[:MAX_LOG_METHOD]+"…"
        decision="allow" if result in ("ready","admitted") else "error" if result=="credential-failure" else "deny"
        self.server.result(decision,method,path,result,reason,helper_path)
    def _failure(self,status,result,reason=None,helper_path=None):
        self._log_result(result,reason,helper_path); self.send_response_only(status); self.send_header("Content-Length","0"); self.end_headers(); self.close_connection=True
    def do_GET(self):
        header_bytes=sum(len(key.encode())+len(value.encode())+4 for key,value in self.headers.items())
        if header_bytes>MAX_HEADERS:
            return self._failure(HTTPStatus.UNAUTHORIZED,"rejected","request-headers-too-large")
        if "?" in self.path:
            return self._failure(HTTPStatus.UNAUTHORIZED,"rejected","helper-query-not-allowed",urlsplit(self.path).path)
        if self.path not in ("/admit","/ready"):
            return self._failure(HTTPStatus.UNAUTHORIZED,"rejected","helper-path-not-allowed",urlsplit(self.path).path)
        if self.headers.get("Transfer-Encoding") is not None:
            return self._failure(HTTPStatus.UNAUTHORIZED,"rejected","transfer-encoding-not-allowed")
        try: length=int(self.headers.get("Content-Length","0"))
        except ValueError: return self._failure(HTTPStatus.UNAUTHORIZED,"rejected","invalid-content-length")
        authorization=self.headers.get("Authorization","")
        expected="Bearer "+self.server.session_token
        if length != 0:
            return self._failure(HTTPStatus.UNAUTHORIZED,"unauthorized","request-body-not-empty")
        if len(authorization.encode())>MAX_AUTHORIZATION:
            return self._failure(HTTPStatus.UNAUTHORIZED,"unauthorized","authorization-too-large")
        if not hmac.compare_digest(authorization.encode(),expected.encode()):
            return self._failure(HTTPStatus.UNAUTHORIZED,"unauthorized","session-token-mismatch")
        try:
            with operation_deadline() as deadline:
                callback=self.server.readiness if self.path=="/ready" else self.server.credentials
                headers=callback(deadline)
            expected_names=("Authorization","Chatgpt-Account-Id") if len(headers)==2 else ("Authorization",)
            if tuple(k for k,v in headers)!=expected_names or any(not v or any(c in v for c in "\r\n") for k,v in headers): raise CredentialFailure()
            auth=dict(headers)["Authorization"]
            if not auth.startswith("Bearer ") if len(headers)==2 else not auth.startswith("Basic "): raise CredentialFailure()
        except Exception: return self._failure(HTTPStatus.SERVICE_UNAVAILABLE,"credential-failure")
        self._log_result("ready" if self.path=="/ready" else "admitted")
        self.send_response_only(HTTPStatus.NO_CONTENT)
        for key,value in headers: self.send_header(key,value)
        self.send_header("Content-Length","0"); self.end_headers(); self.close_connection=True
    def unsupported(self): self._failure(HTTPStatus.UNAUTHORIZED,"rejected","unsupported-method",urlsplit(self.path).path)
    do_HEAD=do_POST=do_PUT=do_DELETE=do_OPTIONS=do_PATCH=unsupported

def serve(profile,socket_path,token):
    credentials,ready=(codex_credentials,codex_ready) if profile=="codex" else (zulip_credentials,zulip_ready)
    path=Path(socket_path); path.unlink(missing_ok=True); path.parent.mkdir(parents=True,exist_ok=True)
    server=UnixHTTPServer(str(path),token,credentials,ready); os.chmod(path,0o600)
    try: server.serve_forever()
    finally: server.server_close(); path.unlink(missing_ok=True)
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--profile",required=True,choices=("codex","zulip")); parser.add_argument("--socket",default="/run/profile-helper/socket")
    args=parser.parse_args(); serve(args.profile,args.socket,os.environ.get("CADDY_PROFILE_TOKEN",""))
if __name__=="__main__": main()
