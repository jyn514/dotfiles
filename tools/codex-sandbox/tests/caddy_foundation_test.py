from __future__ import annotations
import contextlib, http.client, importlib.util, io, json, os
from pathlib import Path
import socket, subprocess, sys, tempfile, threading, time, unittest
from unittest.mock import patch
ROOT=Path(__file__).parents[1]
DOCKER="/libexec/sandbox-wrappers/docker" if Path("/libexec/sandbox-wrappers/docker").is_file() else "docker"
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path); module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module
caddy=load("caddy_foundation",ROOT/"caddy_foundation.py"); helper=load("profile_helper",ROOT/"auth-proxy/profile_helper.py")

def native_caddy_image():
 # Query the daemon, not the client host: DOCKER_HOST may be remote. Foreign
 # manifests are admitted policy, but executing them requires optional emulation.
 result=subprocess.run([DOCKER,"info","--format","{{.OSType}}/{{.Architecture}}"],capture_output=True,text=True)
 if result.returncode: raise unittest.SkipTest("Docker unavailable: "+result.stderr.strip())
 platform=result.stdout.strip()
 platform={"linux/x86_64":"linux/amd64","linux/aarch64":"linux/arm64/v8","linux/arm64":"linux/arm64/v8"}.get(platform,platform)
 if platform not in caddy.PLATFORMS: raise AssertionError("Unsupported Docker engine platform: "+platform)
 return platform,"caddy@"+caddy.PLATFORMS[platform][0]

class RuntimeContract:
 def __init__(self,bad=False,platform="linux/amd64"): self.bad=bad; self.platform=platform
 def build_platform(self): return self.platform
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
  digest=caddy.configuration_digest(caddy.generate_caddy_config("zulip","chat.example.com")); self.assertRegex(identity.implementation_identity(digest),r"^sha256:[0-9a-f]{64}$")
 def test_resolves_both_admitted_platforms_without_foreign_execution(self):
  for platform in ("linux/amd64","linux/arm64"):
   with self.subTest(platform=platform):
    identity=caddy.resolve_caddy_image(RuntimeContract(platform=platform))
    self.assertEqual(identity.platform,"linux/arm64/v8" if platform == "linux/arm64" else platform)
    self.assertEqual((identity.manifest_digest,identity.configuration_digest),caddy.PLATFORMS[identity.platform])
 def test_rejects_inspection_mismatch(self):
  with self.assertRaises(caddy.CaddyIdentityError): caddy.resolve_caddy_image(RuntimeContract(True))
 def test_captured_dependency_descriptors_match_installed_policy(self):
  evidence=json.loads((ROOT/"tests/fixtures/caddy-2.11.4-alpine-index.json").read_text())
  self.assertEqual(evidence["digest"],caddy.INDEX)
  observed={m["platform"]["os"]+"/"+m["platform"]["architecture"]+("/"+m["platform"]["variant"] if "variant" in m["platform"] else ""):(m["digest"],m["config"]) for m in evidence["manifests"]}
  self.assertEqual(observed,caddy.PLATFORMS)

class NativeImageTest(unittest.TestCase):
 def test_daemon_architecture_selects_its_pinned_manifest(self):
  for architecture,platform in (("amd64","linux/amd64"),("x86_64","linux/amd64"),("arm64","linux/arm64/v8"),("aarch64","linux/arm64/v8")):
   with self.subTest(architecture=architecture),patch.object(subprocess,"run",return_value=subprocess.CompletedProcess([],0,"linux/"+architecture+"\n","")) as info:
    self.assertEqual(native_caddy_image(),(platform,"caddy@"+caddy.PLATFORMS[platform][0]))
    self.assertEqual(info.call_args.args[0],[DOCKER,"info","--format","{{.OSType}}/{{.Architecture}}"])
 def test_present_engine_validation_failure_is_not_skipped(self):
  with patch(__name__+".native_caddy_image",return_value=("linux/amd64","caddy@"+caddy.PLATFORMS["linux/amd64"][0])),patch.object(subprocess,"run",return_value=subprocess.CompletedProcess([],1,b"",b"exec format error")):
   with self.assertRaisesRegex(AssertionError,"exec format error"):
    ConfigTest("test_real_pinned_native_caddy_validates_zulip_profile").test_real_pinned_native_caddy_validates_zulip_profile()
 def test_native_validation_does_not_require_a_cached_image(self):
  image="caddy@"+caddy.PLATFORMS["linux/amd64"][0]
  def runtime(arguments,**keywords):
   if arguments[1:3]==["image","inspect"]:
    return subprocess.CompletedProcess(arguments,1,b"",b"No such image")
   return subprocess.CompletedProcess(arguments,0,b"",b"")
  with patch(__name__+".native_caddy_image",return_value=("linux/amd64",image)),patch.object(subprocess,"run",side_effect=runtime) as commands:
   try: ConfigTest("test_real_pinned_native_caddy_validates_zulip_profile").test_real_pinned_native_caddy_validates_zulip_profile()
   except unittest.SkipTest as error: self.fail("Native validation skipped instead of allowing an image pull: "+str(error))
  runs=[call.args[0] for call in commands.call_args_list if call.args[0][1]=="run"]
  self.assertEqual(len(runs),1)
  for arguments in runs:
   self.assertIn(image,arguments); self.assertNotIn("--pull=never",arguments)

 def test_present_unsupported_engine_fails_instead_of_skipping(self):
  with patch.object(subprocess,"run",return_value=subprocess.CompletedProcess([],0,"linux/riscv64\n","")):
   with self.assertRaisesRegex(AssertionError,"Unsupported Docker engine platform"): native_caddy_image()

class ConfigTest(unittest.TestCase):
 def test_real_pinned_native_caddy_validates_zulip_profile(self):
  platform,image=native_caddy_image()
  for profile,upstream in (("zulip","chat.example.com"),):
   with self.subTest(platform=platform,profile=profile):
    config=caddy.generate_caddy_config(profile,upstream)
    result=subprocess.run([DOCKER,"run","--rm","-i","--platform",platform,image,"caddy","validate","--config","-"],input=config,capture_output=True,timeout=120)
    self.assertEqual(result.returncode,0,result.stderr.decode())
 def test_retired_codex_profile_cannot_generate_a_configuration(self):
  with self.assertRaisesRegex(ValueError,"invalid Caddy profile"):
   caddy.generate_caddy_config("codex","chatgpt.com")
 def test_security_semantics_are_in_generated_json(self):
  config=json.loads(caddy.generate_caddy_config("zulip","chat.example.com")); server=config["apps"]["http"]["servers"]["egress"]
  self.assertNotIn("read_body_timeout",server); self.assertNotIn("logs",server); self.assertEqual(server["idle_timeout"],300_000_000_000)
  self.assertEqual(config["logging"]["logs"]["default"]["exclude"],["http.handlers.reverse_proxy"])
  route=server["routes"][1]; self.assertEqual(route["handle"][0]["handler"],"reverse_proxy")
  gate=route["handle"][0]; self.assertEqual(gate["rewrite"],{"method":"GET","uri":"/admit?"})
  self.assertEqual(gate["headers"]["request"]["set"]["X-Original-Method"],["{http.request.method}"])
  self.assertEqual(gate["headers"]["request"]["set"]["X-Original-Uri"],["{http.request.uri}"])
  success=gate["handle_response"][0]["routes"][0]["match"][0]
  self.assertEqual(success["not"][0]["vars"],{"{http.reverse_proxy.header.Authorization}":[""]})
  self.assertEqual(gate["handle_response"][1]["match"],{"status_code":[401]})
  proxy=route["handle"][-1]
  self.assertEqual(len(proxy["upstreams"]),1)
  self.assertNotIn("lb_retries",proxy); self.assertNotIn("lb_try_duration",proxy)
  self.assertNotIn("lb_retries",proxy["upstreams"][0]); self.assertNotIn("lb_try_duration",proxy["upstreams"][0])
  self.assertEqual(server["routes"][0]["handle"][0]["rewrite"]["uri"],"/ready?")
  self.assertEqual(server["errors"]["routes"][0]["handle"][0]["status_code"],503)
 def test_live_gate_mutates_original_request_and_strips_forwarding(self):
  platform,image=native_caddy_image()
  config=json.loads(caddy.generate_caddy_config("zulip","localhost","/tmp/helper.sock")); servers=config["apps"]["http"]["servers"]
  app=servers["egress"]; proxy=app["routes"][1]["handle"][-1]; proxy["upstreams"]=[{"dial":"localhost:9999"}]; proxy["transport"]={"protocol":"http"}
  servers["helper"]={"listen":["unix//tmp/helper.sock"],"routes":[{"handle":[{"handler":"static_response","status_code":204,"headers":{"Authorization":["Basic trusted"]}}]}]}
  body='auth={{.Req.Header.Get "Authorization"}} acct={{.Req.Header.Get "Chatgpt-Account-Id"}} xff={{.Req.Header.Get "X-Forwarded-For"}} safe={{.Req.Header.Get "X-Safe"}} path={{.Req.URL.Path}}'
  servers["upstream"]={"listen":[":9999"],"routes":[{"handle":[{"handler":"templates"},{"handler":"static_response","body":body}]}]}
  container=subprocess.check_output([DOCKER,"create","--platform",platform,image,"sh","-c","sleep 3600"],text=True).strip()
  try:
   subprocess.run([DOCKER,"start",container],check=True,stdout=subprocess.DEVNULL)
   with tempfile.NamedTemporaryFile("w") as stream:
    json.dump(config,stream); stream.flush(); subprocess.run([DOCKER,"cp",stream.name,container+":/tmp/config.json"],check=True)
   subprocess.run([DOCKER,"exec","-d",container,"caddy","run","--config","/tmp/config.json"],check=True)
   deadline=time.monotonic()+10
   while True:
    ready=subprocess.run([DOCKER,"exec",container,"wget","-qO-","--header=Authorization: Bearer session","http://127.0.0.1:8787/ready"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    if ready.returncode == 0: break
    if time.monotonic() >= deadline: self.fail("Caddy did not become ready within 10 seconds")
    time.sleep(.1)
   output=subprocess.check_output([DOCKER,"exec",container,"wget","-qO-","--header=Authorization: Bearer session","--header=X-Forwarded-For: evil","--header=X-Safe: yes","http://127.0.0.1:8787/api/v1/messages"],text=True)
   self.assertEqual(output,"auth=Basic trusted acct= xff= safe=yes path=/api/v1/messages")
  finally: subprocess.run([DOCKER,"rm","-f",container],stdout=subprocess.DEVNULL)

class UnixConnection(http.client.HTTPConnection):
 def __init__(self,path): super().__init__("localhost"); self.path=path
 def connect(self): self.sock=socket.socket(socket.AF_UNIX); self.sock.connect(self.path)
class HelperTest(unittest.TestCase):
 def setUp(self):
  @contextlib.contextmanager
  def deadline(): yield time.monotonic()+30
  deadline_patch=patch.object(helper,"operation_deadline",deadline)
  deadline_patch.start(); self.addCleanup(deadline_patch.stop)
  self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.path=str(Path(self.tmp.name)/"s")
  self.log=io.StringIO(); self.server=helper.UnixHTTPServer(self.path,"secret",lambda d:(("Authorization","Basic abc"),),lambda d:(("Authorization","Basic ready"),),self.log)
  self.addCleanup(self.server.server_close)
  self.thread=threading.Thread(target=self.server.serve_forever); self.thread.start()
  self.addCleanup(self.thread.join); self.addCleanup(self.server.shutdown)
 def request(self,path="/admit",token="secret",original_uri=None):
  headers={"Authorization":"Bearer "+token}
  if original_uri is not None: headers["X-Original-Uri"]=original_uri
  client=UnixConnection(self.path); client.request("GET",path,headers=headers); response=client.getresponse(); result=(response.status,dict(response.getheaders()),response.read()); client.close(); return result
 def test_admission_logs_original_path_without_query_or_credentials(self):
  self.assertEqual(self.request(original_uri="/api/v1/streams?include_can_access_content=true")[0],204)
  self.assertEqual(self.request("/ready")[0],204)
  status,headers,body=self.request(token="bad",original_uri="/api/v1/messages?anchor=private")
  self.assertEqual((status,headers,body),(401,{"Content-Length":"0"},b""))
  self.assertEqual(self.request("/unsupported",original_uri="/api/v1/private?token=hidden")[0],401)
  self.assertEqual(self.request("/admit?retained=yes",original_uri="/api/v1/streams?anchor=private")[0],401)
  output=self.log.getvalue()
  self.assertIn('decision=allow method="GET" path="/api/v1/streams" result=admitted',output)
  self.assertIn('decision=deny method="GET" path="/api/v1/messages" result=unauthorized reason=session-token-mismatch',output)
  self.assertIn('decision=deny method="GET" path="/api/v1/private" result=rejected reason=helper-path-not-allowed helper_path="/unsupported"',output)
  self.assertIn('decision=deny method="GET" path="/api/v1/streams" result=rejected reason=helper-query-not-allowed helper_path="/admit"',output)
  for sensitive in ("secret","include_can_access_content","anchor=private","token=hidden","retained=yes"):
   self.assertNotIn(sensitive,output)
 def test_generated_precheck_preserves_caller_admission_for_zulip_profile(self):
  # Deterministic producer-to-helper check, not an emulation of Caddy routing.
  # LiveCaddyAcceptanceTest below verifies the same matrix in the real engine.
  for profile,token in (("zulip","other-instance-token"),):
   self.server.session_token=token
   calls=[]
   trusted=(("Authorization","Basic trusted"),)
   def credentials(deadline): calls.append("application"); return trusted
   def readiness(deadline): calls.append("ready"); return trusted
   self.server.credentials=credentials; self.server.readiness=readiness
   routes=json.loads(caddy.generate_caddy_config(profile,"example.invalid",token=token))["apps"]["http"]["servers"]["egress"]["routes"]
   for operation,route in (("ready",routes[0]),("application",routes[1])):
    precheck=next(handler for handler in route["handle"] if handler.get("rewrite",{}).get("method")=="GET")
    policy=precheck["headers"]["request"]
    for authorization,status in ((None,401),("Bearer wrong",401),("Bearer "+"x"*4090,401),("Bearer "+token,204)):
     with self.subTest(profile=profile,operation=operation,authorization_class="absent" if authorization is None else "valid" if status==204 else "invalid"):
      calls.clear(); headers={} if authorization is None else {"Authorization":authorization}
      # Apply the generated request-header mutations at their HTTP boundary.
      for name in policy["delete"]:
       if name in headers: del headers[name]
      for name,values in policy["set"].items():
       if name=="Authorization": headers[name]=values[0]
      client=UnixConnection(self.path); client.request("GET",precheck["rewrite"]["uri"].removesuffix("?"),headers=headers)
      response=client.getresponse(); body=response.read(); returned=dict(response.getheaders()); client.close()
      self.assertEqual(response.status,status); self.assertEqual(body,b"")
      self.assertEqual(returned.get("Content-Length"),"0")
      self.assertEqual(calls,[operation] if status==204 else [])
      if status==401: self.assertEqual(returned,{"Content-Length":"0"})
      else:
       for name,value in trusted: self.assertEqual(returned[name],value)

 def test_profile_schema_is_exact(self):
  self.server.credentials=lambda d:(("Authorization","bearer wrong"),)
  self.assertEqual(self.request(),(503,{"Content-Length":"0"},b""))
class SetupCleanupTest(unittest.TestCase):
 def test_failed_server_setup_restores_deadline_for_later_tests(self):
  original=helper.operation_deadline
  case=HelperTest("test_profile_schema_is_exact"); result=unittest.TestResult()
  try:
   with patch.object(helper,"UnixHTTPServer",side_effect=PermissionError("socket denied")):
    case.run(result)
   self.assertEqual(len(result.errors),1)
   self.assertIn("socket denied",result.errors[0][1])
   self.assertIs(helper.operation_deadline,original)
   self.assertFalse(Path(case.tmp.name).exists())
  finally:
   helper.operation_deadline=original; case.tmp.cleanup()
# Register the live suite through pytest.ini's normal *_test.py discovery.
# Missing unchanged local images are skips, never implicit pulls.
LiveCaddyAcceptanceTest=load("caddy_acceptance_integration",Path(__file__).with_name("caddy_acceptance_integration.py")).LiveCaddy
if __name__=="__main__": unittest.main()
