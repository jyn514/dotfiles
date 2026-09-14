#!/usr/bin/env python3
"""Network fixture for live Caddy acceptance tests (stdlib only)."""
from __future__ import annotations
import http.client, json, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

lock=threading.Lock(); release=threading.Event()
state={"mode":"valid","helper":[],"application":[],"clients":[],"release":False}

def snapshot():
 with lock: return json.dumps(state,separators=(",",":"),sort_keys=True).encode()
def record(kind, **value):
 with lock: state[kind].append({"at":time.monotonic(),**value})

class Handler(BaseHTTPRequestHandler):
 protocol_version="HTTP/1.1"
 def log_message(self,*args): pass
 def reply(self,status,body=b"",headers=()):
  self.send_response_only(status)
  for k,v in headers:self.send_header(k,v)
  self.send_header("Content-Length",str(len(body))); self.end_headers()
  if body:self.wfile.write(body)
 def do_GET(self):
  if self.server.server_port==8080:
   if self.path=="/state": return self.reply(200,snapshot(),(("Content-Type","application/json"),))
   if self.path.startswith("/mode/"):
    mode=self.path.removeprefix("/mode/")
    with lock: state["mode"]=mode
    if mode=="release": release.set()
    return self.reply(204)
   if self.path=="/reset":
    with lock:
     state.update(mode="valid",helper=[],application=[],clients=[],release=False)
    release.clear(); return self.reply(204)
  if self.server.server_port==8081:
   length=int(self.headers.get("Content-Length","0")); body=self.rfile.read(length)
   with lock: mode=state["mode"]
   record("helper",path=self.path,body=len(body),authorization=self.headers.get("Authorization",""))
   if mode in ("delay","timeout"): release.wait(5)
   if mode=="unauthorized": return self.reply(401)
   if mode=="malformed": return self.reply(204,headers=(("X-Helper-Secret","helper-header-secret"),("Set-Cookie","helper-cookie-secret=1")))
   return self.reply(204,headers=(("Authorization","Bearer fixture-secret"),("Chatgpt-Account-Id","fixture-account")))
  self.reply(404)
 def do_POST(self):
  if self.server.server_port==8080 and self.path=="/client":
   length=int(self.headers.get("Content-Length","0")); spec=json.loads(self.rfile.read(length))
   def run():
    data=spec.get("body","fixture-request-secret").encode()
    headers={"Authorization":spec.get("authorization","Bearer caller-secret"),"Content-Type":"application/json",**spec.get("headers",{})}
    client=http.client.HTTPConnection("caddy",8787,timeout=8); response=None
    try:
     client.request("POST",spec.get("path","/codex/responses"),body=data,headers=headers)
     response=client.getresponse(); body=response.read()
     result={"status":response.status,"body":body.decode(errors="replace"),"headers":dict(response.getheaders())}
    except http.client.IncompleteRead as error:
     result={"status":response.status,"body":error.partial.decode(errors="replace"),"headers":dict(response.getheaders()),"error":"IncompleteRead"}
    except Exception as error:
     result={"status":getattr(response,"status",0),"body":"","headers":dict(response.getheaders()) if response else {},"error":type(error).__name__}
    finally: client.close()
    record("clients",**result)
   threading.Thread(target=run,daemon=True).start(); return self.reply(202)
  if self.server.server_port==8082:
   length=int(self.headers.get("Content-Length","0")); body=self.rfile.read(length)
   record("application",body=body.decode(errors="replace"),authorization=self.headers.get("Authorization",""),account=self.headers.get("Chatgpt-Account-Id",""))
   with lock: mode=state["mode"]
   if mode=="upstream-close": self.connection.shutdown(2); self.connection.close(); return
   if mode=="premature-framing":
    self.send_response_only(200); self.send_header("Content-Type","text/event-stream"); self.send_header("Content-Length","100"); self.end_headers(); self.wfile.write(b"short"); self.wfile.flush()
    time.sleep(.2); self.connection.shutdown(2); self.connection.close(); return
   return self.reply(200,b"fixture-ok")
  self.reply(404)

for port in (8080,8081,8082): threading.Thread(target=ThreadingHTTPServer(("0.0.0.0",port),Handler).serve_forever,daemon=True).start()
threading.Event().wait()
