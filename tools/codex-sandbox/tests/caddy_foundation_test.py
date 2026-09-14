from __future__ import annotations
import contextlib, http.client, importlib.util, io, json, os
from pathlib import Path
import socket, subprocess, sys, tempfile, threading, time, unittest
ROOT=Path(__file__).parents[1]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path); module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module
caddy=load("caddy_foundation",ROOT/"caddy_foundation.py"); helper=load("profile_helper",ROOT/"auth-proxy/profile_helper.py")

class RuntimeContract:
 def __init__(self,bad=False): self.bad=bad
 def build_platform(self): return "linux/amd64"
 def verify_external_image(self,repository,manifest,configuration,platform):
  from types import SimpleNamespace
  return SimpleNamespace(reference=repository+"@"+manifest,content=manifest,config=("sha256:"+"0"*64 if self.bad else configuration))
 def inspect_runtime_image_id(self,reference): return caddy.PLATFORMS["linux/amd64"][1]
class ImmutableConfigurationTest(unittest.TestCase):
 def test_atomic_read_only_publication_rejects_changed_authority(self):
  with tempfile.TemporaryDirectory() as directory:
   path=Path(directory)/"caddy.json"; digest=caddy.publish_configuration(path,b"{}\n")
   self.assertEqual(digest,caddy.configuration_digest(b"{}\n")); self.assertEqual(path.stat().st_mode & 0o222,0)
   self.assertEqual(caddy.publish_configuration(path,b"{}\n"),digest)
   with self.assertRaises(caddy.CaddyIdentityError): caddy.publish_configuration(path,b"changed\n")

class IdentityTest(unittest.TestCase):
 def test_exact_chain_and_configuration_binding(self):
  identity=caddy.resolve_caddy_image(RuntimeContract()); self.assertEqual(identity.configuration_digest,"sha256:af555904a0961945f16bb323a501457b13a4f7e9bde969b145b97da80b38ecbe")
  digest=caddy.configuration_digest(caddy.generate_caddy_config("codex","chatgpt.com")); self.assertRegex(identity.implementation_identity(digest),r"^sha256:[0-9a-f]{64}$")
 def test_rejects_inspection_mismatch(self):
  with self.assertRaises(caddy.CaddyIdentityError): caddy.resolve_caddy_image(RuntimeContract(True))
 def test_captured_dependency_descriptors_match_installed_policy(self):
  evidence=json.loads((ROOT/"tests/fixtures/caddy-2.11.4-alpine-index.json").read_text())
  self.assertEqual(evidence["digest"],caddy.INDEX)
  observed={m["platform"]["os"]+"/"+m["platform"]["architecture"]+("/"+m["platform"]["variant"] if "variant" in m["platform"] else ""):(m["digest"],m["config"]) for m in evidence["manifests"]}
  self.assertEqual(observed,caddy.PLATFORMS)

class ConfigTest(unittest.TestCase):
 def test_real_pinned_caddy_validates_both_platforms(self):
  if subprocess.run(["docker","info"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode: self.skipTest("Docker unavailable")
  for profile,upstream in (("codex","chatgpt.com"),("zulip","chat.example.com")):
   config=caddy.generate_caddy_config(profile,upstream)
   for platform,digest in (("linux/amd64",caddy.PLATFORMS["linux/amd64"][0]),("linux/arm64",caddy.PLATFORMS["linux/arm64/v8"][0])):
    result=subprocess.run(["docker","run","--rm","-i","--platform",platform,"caddy@"+digest,"caddy","validate","--config","-"],input=config,capture_output=True,timeout=120)
    self.assertEqual(result.returncode,0,result.stderr.decode())
 def test_security_semantics_are_in_generated_json(self):
  server=json.loads(caddy.generate_caddy_config("codex","chatgpt.com"))["apps"]["http"]["servers"]["egress"]
  self.assertNotIn("read_body_timeout",server); self.assertNotIn("logs",server); self.assertEqual(server["idle_timeout"],300_000_000_000)
  route=server["routes"][1]; self.assertEqual(route["handle"][0]["handler"],"request_body")
  gate=route["handle"][1]; self.assertEqual(gate["rewrite"],{"method":"GET","uri":"/admit"})
  success=gate["handle_response"][0]["routes"][0]["match"][0]
  self.assertEqual(success["not"][0]["vars"],{"{http.reverse_proxy.header.Authorization}":[""]})
  self.assertEqual(gate["handle_response"][1]["match"],{"status_code":[401]})
  self.assertEqual(server["routes"][0]["handle"][0]["rewrite"]["uri"],"/ready")
  self.assertEqual(server["errors"]["routes"][0]["handle"][0]["status_code"],503)
 def test_live_gate_mutates_original_request_and_strips_forwarding(self):
  if subprocess.run(["docker","info"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode: self.skipTest("Docker unavailable")
  config=json.loads(caddy.generate_caddy_config("codex","localhost","/tmp/helper.sock")); servers=config["apps"]["http"]["servers"]
  app=servers["egress"]; proxy=app["routes"][1]["handle"][-1]; proxy["upstreams"]=[{"dial":"localhost:9999"}]; proxy["transport"]={"protocol":"http"}
  servers["helper"]={"listen":["unix//tmp/helper.sock"],"routes":[{"handle":[{"handler":"static_response","status_code":204,"headers":{"Authorization":["Bearer trusted"],"Chatgpt-Account-Id":["acct"]}}]}]}
  body='auth={{.Req.Header.Get "Authorization"}} acct={{.Req.Header.Get "Chatgpt-Account-Id"}} xff={{.Req.Header.Get "X-Forwarded-For"}} safe={{.Req.Header.Get "X-Safe"}} path={{.Req.URL.Path}}'
  servers["upstream"]={"listen":[":9999"],"routes":[{"handle":[{"handler":"templates"},{"handler":"static_response","body":body}]}]}
  image="caddy@"+caddy.PLATFORMS["linux/arm64/v8"][0]; container=subprocess.check_output(["docker","create",image,"sh","-c","sleep 3600"],text=True).strip()
  try:
   subprocess.run(["docker","start",container],check=True,stdout=subprocess.DEVNULL)
   with tempfile.NamedTemporaryFile("w") as stream:
    json.dump(config,stream); stream.flush(); subprocess.run(["docker","cp",stream.name,container+":/tmp/config.json"],check=True)
   subprocess.run(["docker","exec","-d",container,"caddy","run","--config","/tmp/config.json"],check=True); time.sleep(1)
   output=subprocess.check_output(["docker","exec",container,"wget","-qO-","--header=Authorization: Bearer session","--header=X-Forwarded-For: evil","--header=X-Safe: yes","--post-data={}","http://127.0.0.1:8787/codex/responses"],text=True)
   self.assertEqual(output,"auth=Bearer trusted acct=acct xff= safe=yes path=/backend-api/codex/responses")
  finally: subprocess.run(["docker","rm","-f",container],stdout=subprocess.DEVNULL)

class UnixConnection(http.client.HTTPConnection):
 def __init__(self,path): super().__init__("localhost"); self.path=path
 def connect(self): self.sock=socket.socket(socket.AF_UNIX); self.sock.connect(self.path)
class HelperTest(unittest.TestCase):
 def setUp(self):
  self.old=helper.operation_deadline
  @contextlib.contextmanager
  def deadline(): yield time.monotonic()+30
  helper.operation_deadline=deadline; self.tmp=tempfile.TemporaryDirectory(); self.path=str(Path(self.tmp.name)/"s")
  self.log=io.StringIO(); self.server=helper.UnixHTTPServer(self.path,"secret",lambda d:(("Authorization","Basic abc"),),lambda d:(("Authorization","Basic ready"),),self.log)
  self.thread=threading.Thread(target=self.server.serve_forever); self.thread.start()
 def tearDown(self): self.server.shutdown(); self.server.server_close(); self.thread.join(); self.tmp.cleanup(); helper.operation_deadline=self.old
 def request(self,path="/admit",token="secret"):
  client=UnixConnection(self.path); client.request("GET",path,headers={"Authorization":"Bearer "+token}); response=client.getresponse(); result=(response.status,dict(response.getheaders()),response.read()); client.close(); return result
 def test_admit_ready_and_failures_are_bodyless_and_logs_are_class_only(self):
  self.assertEqual(self.request()[0],204); self.assertEqual(self.request("/ready")[0],204)
  status,headers,body=self.request(token="bad"); self.assertEqual((status,headers,body),(401,{"Content-Length":"0"},b""))
  self.assertNotIn("secret",self.log.getvalue()); self.assertNotIn("/admit",self.log.getvalue())
 def test_profile_schema_is_exact(self):
  self.server.credentials=lambda d:(("Authorization","bearer wrong"),)
  self.assertEqual(self.request(),(503,{"Content-Length":"0"},b""))
if __name__=="__main__": unittest.main()
