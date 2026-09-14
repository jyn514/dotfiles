#!/usr/bin/env python3
"""Codex HTTP adapter for the generic authenticated egress broker."""
from __future__ import annotations
import hmac, importlib.util, json, os, select, socket, sys, threading, time, uuid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Imports also work when tests load this file directly rather than as a package.
def _load(name):
    path = Path(__file__).with_name(name + '.py')
    spec = importlib.util.spec_from_file_location(name, path); module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, module); spec.loader.exec_module(module); return module
broker = _load('broker'); profile = _load('codex_profile')

AUTH = profile.AUTH; HTTPSConnection = profile.HTTPSConnection
jwt_payload = profile.jwt_payload; read_auth = profile.read_auth; atomic_auth = profile.atomic_auth
UPSTREAM_HOST='chatgpt.com'; UPSTREAM_PATH='/backend-api/codex/responses'; MAX_BODY=32*1024*1024
FORWARDED_REQUEST_HEADERS=frozenset({'accept','content-encoding','content-type','openai-beta','session-id','x-client-request-id'})
FORWARDED_RESPONSE_HEADERS=frozenset({'content-encoding','content-type','openai-processing-ms','request-id','retry-after','retry-after-ms','x-request-id'})
ROUTE = broker.Route('codex', UPSTREAM_HOST, UPSTREAM_PATH, '/codex/responses', frozenset({'POST'}), FORWARDED_REQUEST_HEADERS, FORWARDED_RESPONSE_HEADERS, max_request_body=MAX_BODY)
SESSION_KEY=os.environ['CODEX_SIDECAR_KEY']
if not SESSION_KEY: raise RuntimeError('CODEX_SIDECAR_KEY must not be empty')

def credentials():
    profile.AUTH=AUTH; profile.HTTPSConnection=HTTPSConnection
    return profile.credentials()

def upstream_headers(request_headers, access, account, body_length):
    supplied = broker.filter_request_headers(request_headers, ROUTE)
    supplied.update({'Authorization':f'Bearer {access}','chatgpt-account-id':account,'originator':'pi','User-Agent':'codex-sandbox-sidecar','Content-Length':str(body_length),'Host':UPSTREAM_HOST})
    return supplied

def connection_diagnostic(connection):
    sock=getattr(connection,'sock',None); details={}
    if sock is None: return details
    try:
        version=sock.version()
        if isinstance(version,str): details['tls_version']=version
    except Exception: pass
    try:
        cipher=sock.cipher()
        if cipher and isinstance(cipher[0], str): details['tls_cipher']=cipher[0]
    except Exception: pass
    return details

def log_failure(request_id, phase, body_length, error, connection=None):
    event={'event':'upstream_failure','request_id':request_id,'phase':phase,'body_bytes':body_length,'error_type':type(error).__name__}
    if connection is not None: event.update(connection_diagnostic(connection))
    print(json.dumps(event,separators=(',',':'),sort_keys=True),file=sys.stderr,flush=True)

class UpstreamRequestError(Exception):
    def __init__(self,error): super().__init__('upstream request failed'); self.error=error


def cancel_upstream(connection):
    sock = getattr(connection, 'sock', None)
    if sock is not None:
        try: sock.shutdown(socket.SHUT_RDWR)
        except OSError: pass
    connection.close()


def request_upstream(source, headers, request_id, length=None, deadline=None, uploaded=None,
                     downstream_socket=None):
    # Compatibility accepts bytes, but the handler always supplies its bounded stream.
    if isinstance(source,(bytes,bytearray)):
        import io; length=len(source); source=io.BytesIO(source)
    upstream=broker.open_upstream(ROUTE); sent=0
    try:
        upstream.connect()
        sent=broker.stream_request(upstream,'POST',UPSTREAM_PATH,headers,source,length,MAX_BODY,
                                   deadline,downstream_socket)
        if uploaded is not None: uploaded(upstream)
        if deadline is not None:
            remaining=deadline-time.monotonic()
            if remaining <= 0: raise TimeoutError('total request deadline exceeded')
            upstream.sock.settimeout(min(ROUTE.timeout,remaining))
        return upstream,upstream.getresponse()
    except Exception as error:
        log_failure(request_id,'request_upload' if sent < (length or 0) else 'response_headers',sent,error,upstream)
        upstream.close(); raise UpstreamRequestError(error) from error

class Handler(BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'; server_version='codex-auth-proxy'; timeout=ROUTE.timeout
    def setup(self):
        super().setup(); self.connection.settimeout(ROUTE.timeout)
    def finish(self):
        self.close_connection=True
        try: super().finish()
        except (BrokenPipeError,ConnectionResetError): pass
    def log_message(self,*args): return
    def send_error(self, code, message=None, explain=None):
        # BaseHTTPRequestHandler diagnostics can contain attacker-controlled syntax.
        if code == HTTPStatus.NOT_IMPLEMENTED: code = HTTPStatus.METHOD_NOT_ALLOWED
        self.error(HTTPStatus(code), 'malformed request' if code != HTTPStatus.METHOD_NOT_ALLOWED else 'method not permitted')
    def error(self,status,message):
        body=(message+'\n').encode(); self.send_response(status); self.send_header('Content-Type','text/plain; charset=utf-8'); self.send_header('Content-Length',str(len(body))); self.send_header('Connection','close'); self.end_headers()
        try: self.wfile.write(body)
        except (BrokenPipeError,ConnectionResetError): pass
    def health(self, body: bool):
        if self.path!='/health': return self.error(HTTPStatus.NOT_FOUND,'not found')
        payload=b'ok\n'; self.send_response(HTTPStatus.OK); self.send_header('Content-Length',str(len(payload))); self.send_header('Connection','close'); self.end_headers()
        if body: self.wfile.write(payload)
    def do_GET(self): self.health(True)
    def do_HEAD(self): self.health(False)
    def unsupported(self): self.error(HTTPStatus.METHOD_NOT_ALLOWED,'method not permitted')
    do_CONNECT=do_PUT=do_PATCH=do_DELETE=do_OPTIONS=do_TRACE=unsupported
    def do_POST(self):
        request_id=uuid.uuid4().hex; request_deadline=time.monotonic()+ROUTE.request_timeout
        try:
            broker.validate_method(self.command,ROUTE); broker.parse_target(self.path,ROUTE)
            authorization=broker.single_header(self.headers,'Authorization',required=True)
            broker.single_header(self.headers,'Host',required=True)
            length=broker.request_length(self.headers,MAX_BODY)
        except broker.LimitError: return self.error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE,'request limit exceeded')
        except broker.PolicyError: return self.error(HTTPStatus.BAD_REQUEST,'policy rejection')
        supplied = authorization.removeprefix('Bearer ') if authorization.startswith('Bearer ') else ''
        if not hmac.compare_digest(supplied,SESSION_KEY): return self.error(HTTPStatus.UNAUTHORIZED,'unauthorized')
        try:
            broker.filter_request_headers(self.headers,ROUTE)
            access,account=credentials(); headers=upstream_headers(self.headers,access,account,length)
        except broker.PolicyError: return self.error(HTTPStatus.BAD_REQUEST,'policy rejection')
        except broker.LimitError: return self.error(HTTPStatus.REQUEST_HEADER_FIELDS_TOO_LARGE,'header limit exceeded')
        except Exception as error:
            log_failure(request_id,'credentials',0,error); return self.error(HTTPStatus.BAD_GATEWAY,'credential failure')
        upstream=None; cancelled=threading.Event(); monitor_stop=threading.Event()
        def uploaded(connection):
            def monitor():
                while not monitor_stop.wait(.05):
                    try:
                        readable,_,_=select.select([self.connection],[],[],0)
                        if readable:
                            self.connection.recv(1,socket.MSG_PEEK) # EOF or pipeline bytes both cancel
                            cancelled.set(); cancel_upstream(connection); return
                    except OSError:
                        cancelled.set(); cancel_upstream(connection); return
            threading.Thread(target=monitor,daemon=True).start()
        try:
            upstream,response=request_upstream(self.rfile,headers,request_id,length,request_deadline,
                                               uploaded,self.connection)
            if cancelled.is_set(): raise UpstreamRequestError(ConnectionError('downstream disconnected'))
        except UpstreamRequestError:
            monitor_stop.set()
            if cancelled.is_set(): return
            return self.error(HTTPStatus.BAD_GATEWAY,'upstream transport failure')
        try:
            response_headers=response.getheaders(); total=sum(len(k)+len(v)+4 for k,v in response_headers)
            if total>ROUTE.max_headers: raise broker.LimitError('response headers too large')
            expected,no_body=broker.response_framing(response.status,response_headers,ROUTE)
            if 300 <= response.status < 400 and response.status != 304: raise broker.PolicyError('redirect rejected')
        except Exception as error:
            upstream.close(); log_failure(request_id,'response_headers',length,error); return self.error(HTTPStatus.BAD_GATEWAY,'upstream response rejected')
        self.send_response(response.status,response.reason)
        for key,value in response_headers:
            if key.lower() in ROUTE.response_headers: self.send_header(key,value)
        if no_body:
            self.send_header('Content-Length','0')
        else:
            self.send_header('Transfer-Encoding','chunked')
        self.end_headers()
        if no_body:
            monitor_stop.set(); upstream.close(); self.close_connection=True; return
        received=0; complete=False; response_deadline=time.monotonic()+ROUTE.response_timeout
        try:
            while True:
                remaining=response_deadline-time.monotonic()
                if remaining<=0: raise TimeoutError('total response deadline exceeded')
                if upstream.sock is not None: upstream.sock.settimeout(min(ROUTE.timeout,remaining))
                chunk=response.read(min(broker.CHUNK,ROUTE.max_response_body-received+1))
                if not chunk: break
                received+=len(chunk)
                if received>ROUTE.max_response_body: raise broker.LimitError('response body too large')
                self.wfile.write(f'{len(chunk):x}\r\n'.encode()+chunk+b'\r\n'); self.wfile.flush()
            if expected is not None and received != expected: raise EOFError('premature upstream body EOF')
            if cancelled.is_set(): raise ConnectionError('downstream disconnected')
            complete=True; self.wfile.write(b'0\r\n\r\n'); self.wfile.flush()
        except Exception as error: log_failure(request_id,'response_stream',length,error,upstream)
        finally:
            monitor_stop.set(); upstream.close(); self.close_connection=True

if __name__=='__main__':
    server=ThreadingHTTPServer(('0.0.0.0',8787),Handler); server.daemon_threads=True; server.serve_forever()
