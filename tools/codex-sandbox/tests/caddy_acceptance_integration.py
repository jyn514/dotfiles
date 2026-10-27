#!/usr/bin/env python3
"""Portable live acceptance tests for the pinned Caddy admission boundary.

No path from the test host is mounted into a container: docker cp streams the
fixture and configuration bytes through the client.  This intentionally works
when DOCKER_HOST names a remote daemon.
"""
from __future__ import annotations
import base64, importlib.util, json, subprocess, sys, time, unittest, uuid
from pathlib import Path
ROOT=Path(__file__).parents[1]
DOCKER="/libexec/sandbox-wrappers/docker" if Path("/libexec/sandbox-wrappers/docker").is_file() else "docker"
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path); module=importlib.util.module_from_spec(spec); sys.modules[name]=module; spec.loader.exec_module(module); return module
caddy=load("acceptance_caddy",ROOT/"caddy_foundation.py")
FIXTURE=Path(__file__).with_name("caddy_acceptance_fixture.py")

class LiveCaddy(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  if subprocess.run([DOCKER,"info"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
   raise unittest.SkipTest("Docker runtime unavailable")
  arch=subprocess.check_output([DOCKER,"info","--format","{{.Architecture}}"],text=True).strip()
  platform={"amd64":"linux/amd64","x86_64":"linux/amd64","arm64":"linux/arm64/v8","aarch64":"linux/arm64/v8"}.get(arch)
  if platform is None: raise AssertionError("Unsupported Docker engine architecture: "+arch)
  cls.image="caddy@"+caddy.PLATFORMS[platform][0]
  for image in (cls.image,"python:3.12-alpine"):
   if subprocess.run([DOCKER,"image","inspect",image],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode:
    raise unittest.SkipTest("Required unchanged local image unavailable: "+image)
  cls.identity="caddy-acceptance-"+uuid.uuid4().hex[:12]; cls.network=cls.identity; cls.fixture=cls.identity+"-fixture"; cls.proxy=cls.identity+"-caddy"; cls.extra_containers=[]; cls.extra_volumes=[]
  try:
   subprocess.run([DOCKER,"network","create",cls.network],check=True,stdout=subprocess.DEVNULL)
   # docker cp streams through the client, so this remains valid with a remote
   # daemon while avoiding a build and any daemon-host bind mount.
   subprocess.run([DOCKER,"create","--pull=never","--name",cls.fixture,"--network",cls.network,"--network-alias","fixture","--entrypoint","python3","python:3.12-alpine","/fixture.py"],check=True,stdout=subprocess.DEVNULL)
   subprocess.run([DOCKER,"cp",str(FIXTURE),cls.fixture+":/fixture.py"],check=True)
   subprocess.run([DOCKER,"start",cls.fixture],check=True,stdout=subprocess.DEVNULL)
   cls.start_proxy()
  except BaseException:
   cls.cleanup(); raise
 @classmethod
 def cleanup(cls):
  names=[getattr(cls,"proxy",""),getattr(cls,"fixture","")]+getattr(cls,"extra_containers",[])
  for name in names:
   if name: subprocess.run([DOCKER,"rm","-f",name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  volumes=[getattr(cls,"proxy","")+"-config"]+getattr(cls,"extra_volumes",[])
  for volume in volumes:
   if volume: subprocess.run([DOCKER,"volume","rm","-f",volume],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  network=getattr(cls,"network","")
  if network: subprocess.run([DOCKER,"network","rm",network],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 @classmethod
 def tearDownClass(cls): cls.cleanup()
 @classmethod
 def config(cls,helper="fixture:8081",timeout=2_000_000_000):
  value=json.loads(caddy.generate_caddy_config("zulip","fixture",token="acceptance-session-token"))
  server=value["apps"]["http"]["servers"]["egress"]
  for route in server["routes"][:2]:
   for handler in route["handle"]:
    if handler.get("handler")=="reverse_proxy" and handler.get("rewrite"):
     handler["upstreams"]=[{"dial":helper}]; handler["transport"]["response_header_timeout"]=timeout
  proxy=server["routes"][1]["handle"][-1]; proxy["upstreams"]=[{"dial":"fixture:8082"}]; proxy["transport"]={"protocol":"http","dial_timeout":2_000_000_000,"response_header_timeout":2_000_000_000}
  return (json.dumps(value,separators=(",",":")).encode()+b"\n")
 @classmethod
 def start_proxy(cls,helper="fixture:8081",timeout=2_000_000_000,ready_status=204):
  subprocess.run([DOCKER,"rm","-f",cls.proxy],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  image=cls.image
  # Populate a daemon-owned volume over stdin; unlike a bind mount this remains
  # valid when the Docker daemon is on another host.
  volume=cls.proxy+"-config"; subprocess.run([DOCKER,"volume","rm","-f",volume],stdout=subprocess.DEVNULL)
  subprocess.run([DOCKER,"volume","create",volume],check=True,stdout=subprocess.DEVNULL)
  subprocess.run([DOCKER,"run","--pull=never","--rm","-i","-v",volume+":/config",image,"sh","-c","cat > /config/caddy.json"],input=cls.config(helper,timeout),check=True)
  subprocess.run([DOCKER,"run","--pull=never","-d","--name",cls.proxy,"--network",cls.network,"--network-alias","caddy","-v",volume+":/config:ro",image,"caddy","run","--config","/config/caddy.json"],check=True,stdout=subprocess.DEVNULL)
  deadline=time.monotonic()+8
  while time.monotonic()<deadline:
   ready=subprocess.run([DOCKER,"exec",cls.proxy,"wget","-S","-O-","--header=Authorization: Bearer acceptance-session-token","http://127.0.0.1:8787/ready"],capture_output=True)
   reported=ready.stderr.decode(errors="replace")
   if (ready_status==204 and ready.returncode==0) or f"HTTP/1.1 {ready_status} " in reported:return
   time.sleep(.1)
  raise AssertionError(f"Caddy readiness route did not return {ready_status}: "+reported)
 def control(self,path): subprocess.run([DOCKER,"exec",self.fixture,"wget","-qO-","http://127.0.0.1:8080/"+path],check=True,stdout=subprocess.DEVNULL)
 def state(self): return json.loads(subprocess.check_output([DOCKER,"exec",self.fixture,"wget","-qO-","http://127.0.0.1:8080/state"]))
 def wait_client(self):
  deadline=time.monotonic()+10
  while time.monotonic()<deadline:
   value=self.state()
   if value["clients"]: return value
   time.sleep(.05)
  self.fail("fixture client did not finish")
 def request(self,spec=None):
  body=json.dumps(spec or {"body":"fixture-request-secret"},separators=(",",":"))
  subprocess.run([DOCKER,"exec","-i",self.fixture,"wget","-qO-","--header=Content-Type:application/json","--post-data="+body,"http://127.0.0.1:8080/client"],check=True,stdout=subprocess.DEVNULL)
 def assert_normalized(self,result,status):
  response=result["clients"][0]; self.assertEqual(response["status"],status); self.assertEqual(response["body"],"")
  headers={k.lower():v for k,v in response["headers"].items()}; self.assertEqual(headers.get("content-length"),"0")
  self.assertNotIn("x-helper-secret",headers); self.assertNotIn("set-cookie",headers)
 def assert_logs_clean(self):
  logs="\n".join(subprocess.check_output([DOCKER,"logs",name],stderr=subprocess.STDOUT,text=True) for name in (self.proxy,self.fixture))
  for secret in ("fixture-request-secret","caller-secret","fixture-secret","fixture-account","body-secret","auth-secret","acceptance-session-token","query-secret","cookie-secret","full-url-secret","account-secret","helper-header-secret","helper-cookie-secret"):
   self.assertNotIn(secret,logs)
 def test_delayed_admission_sends_no_body_or_application_then_forwards_once(self):
  self.control("reset"); self.control("mode/delay"); self.request(); time.sleep(.4); before=self.state()
  self.assertEqual(len(before["helper"]),1); self.assertEqual(before["helper"][0]["body"],0); self.assertEqual(before["application"],[])
  self.control("mode/release"); after=self.wait_client()
  self.assertEqual(after["clients"][0]["status"],200); self.assertEqual(len(after["application"]),1); self.assertEqual(after["application"][0]["body"],"fixture-request-secret")
  self.assert_logs_clean()
 def test_premature_framed_response_stays_incomplete_and_is_not_retried(self):
  self.start_proxy(); self.control("reset"); self.control("mode/premature-framing"); self.request({"body":"body-secret","authorization":"Bearer acceptance-session-token","headers":{"Cookie":"cookie-secret=1","X-Full-Url":"https://user:full-url-secret@example.invalid/","Chatgpt-Account-Id":"account-secret"}}); result=self.wait_client()
  response=result["clients"][0]; self.assertEqual(response["status"],200)
  self.assertEqual({key.lower():value for key,value in response["headers"].items()}["content-length"],"100")
  self.assertEqual(response["body"],"short"); self.assertEqual(response["error"],"IncompleteRead")
  self.assertEqual(len(result["application"]),1); self.assert_logs_clean()
 def test_helper_results_are_normalized_and_logs_exclude_secrets(self):
  for mode,status in (("malformed",503),("unauthorized",401)):
   self.control("reset"); self.control("mode/"+mode); self.request({"body":"body-secret","path":"/api/v1/messages","authorization":"Bearer acceptance-session-token","headers":{"Cookie":"cookie-secret=1","X-Full-Url":"https://user:full-url-secret@example.invalid/","Chatgpt-Account-Id":"account-secret"}}); result=self.wait_client(); self.assert_normalized(result,status); self.assertEqual(result["application"],[]); self.assert_logs_clean()
  self.control("reset"); self.request({"method":"POST","path":"/api/v1/messages?token=query-secret","body":"body-secret","headers":{"Cookie":"cookie-secret=1"}}); result=self.wait_client(); self.assert_normalized(result,404); self.assertEqual(result["helper"],[]); self.assertEqual(result["application"],[]); self.assert_logs_clean()
  self.control("reset"); self.control("mode/upstream-close"); self.request({"body":"body-secret","authorization":"Bearer acceptance-session-token","headers":{"Cookie":"cookie-secret=1","X-Full-Url":"https://user:full-url-secret@example.invalid/","Chatgpt-Account-Id":"account-secret"}}); result=self.wait_client()
  self.assertIn(result["clients"][0]["status"],(0,503)); self.assertEqual(len(result["application"]),1); self.assert_logs_clean()
  self.start_proxy("fixture:65530",ready_status=503); self.control("reset"); self.request(); self.assert_normalized(self.wait_client(),503); self.assert_logs_clean()
  self.start_proxy(timeout=250_000_000); self.control("reset"); self.control("mode/timeout"); self.request(); self.assert_normalized(self.wait_client(),503); self.assert_logs_clean(); self.control("mode/release")
 def test_ready_is_helper_only_and_production_shape_keeps_credentials_out_of_caddy(self):
  self.start_proxy(); self.control("reset")
  result=subprocess.run([DOCKER,"exec",self.proxy,"wget","-qO-","--header=Authorization: Bearer acceptance-session-token","http://127.0.0.1:8787/ready"],capture_output=True)
  self.assertEqual(result.returncode,0,result.stderr.decode()); state=self.state(); self.assertEqual([x["path"] for x in state["helper"]],["/ready"]); self.assertEqual(state["application"],[])
  inspected=json.loads(subprocess.check_output([DOCKER,"inspect",self.proxy]))[0]
  self.assertFalse(any("credential" in (m.get("Destination","")+m.get("Source","")).lower() for m in inspected["Mounts"]))
  self.assertFalse(any(k.upper() in {"OPENAI_API_KEY","CODEX_AUTH_JSON","ZULIP_API_KEY"} for k in (e.split("=",1)[0] for e in inspected["Config"]["Env"])))

 def test_actual_profile_helper_ready_is_read_only_and_isolated(self):
  self.control("reset")
  helper_name=self.identity+"-actual-helper"; proxy_name=self.identity+"-actual-caddy"
  socket_volume=self.identity+"-actual-socket"; credential_volume=self.identity+"-actual-credentials"; config_volume=self.identity+"-actual-config"
  self.extra_containers.extend((helper_name,proxy_name)); self.extra_volumes.extend((socket_volume,credential_volume,config_volume))
  for volume in (socket_volume,credential_volume,config_volume): subprocess.run([DOCKER,"volume","create",volume],check=True,stdout=subprocess.DEVNULL)
  token="actual-pair-token-secret"; email="fixture@example.invalid"; key="actual-key-secret"
  auth="[api]\nemail="+email+"\nkey="+key+"\n"
  subprocess.run([DOCKER,"create","--pull=never","--name",helper_name,"--network","none","-e","CADDY_PROFILE_TOKEN="+token,"-v",socket_volume+":/run/profile-helper","-v",credential_volume+":/var/lib/zulip","--entrypoint","python3","python:3.12-alpine","/profile_helper.py","--profile","zulip"],check=True,stdout=subprocess.DEVNULL)
  subprocess.run([DOCKER,"cp",str(ROOT/"auth-proxy/profile_helper.py"),helper_name+":/profile_helper.py"],check=True)
  subprocess.run([DOCKER,"cp","-",helper_name+":/var/lib/zulip"],input=self.tar_entry("zuliprc",auth.encode(),0o600),check=True)
  subprocess.run([DOCKER,"start",helper_name],check=True,stdout=subprocess.DEVNULL)
  before=subprocess.check_output([DOCKER,"exec",helper_name,"sh","-c","sha256sum /var/lib/zulip/zuliprc; stat -c '%a %Y' /var/lib/zulip/zuliprc"],text=True)
  value=json.loads(caddy.generate_caddy_config("zulip","fixture",token=token)); app=value["apps"]["http"]["servers"]["egress"]["routes"][1]["handle"][-1]; app["upstreams"]=[{"dial":"fixture:8082"}]; app["transport"]={"protocol":"http"}
  config=(json.dumps(value,separators=(",",":")).encode()+b"\n")
  image=self.image
  subprocess.run([DOCKER,"run","--pull=never","--rm","-i","-v",config_volume+":/config",image,"sh","-c","cat > /config/caddy.json"],input=config,check=True)
  subprocess.run([DOCKER,"run","--pull=never","-d","--name",proxy_name,"--network",self.network,"--network-alias","actual-caddy","-v",socket_volume+":/run/profile-helper:ro","-v",config_volume+":/config:ro",image,"caddy","run","--config","/config/caddy.json"],check=True,stdout=subprocess.DEVNULL)
  deadline=time.monotonic()+8
  while True:
   ready=subprocess.run([DOCKER,"exec",proxy_name,"wget","-qO-","--header=Authorization: Bearer "+token,"http://127.0.0.1:8787/ready"],capture_output=True)
   if ready.returncode==0: break
   if time.monotonic()>deadline: self.fail(ready.stderr.decode(errors="replace"))
   time.sleep(.1)
  after=subprocess.check_output([DOCKER,"exec",helper_name,"sh","-c","sha256sum /var/lib/zulip/zuliprc; stat -c '%a %Y' /var/lib/zulip/zuliprc"],text=True)
  self.assertEqual(after,before); self.assertIn("600 ",after); self.assertEqual(self.state()["application"],[])
  helper_inspect,proxy_inspect=(json.loads(subprocess.check_output([DOCKER,"inspect",name]))[0] for name in (helper_name,proxy_name))
  self.assertEqual(set(helper_inspect["NetworkSettings"]["Networks"]),{"none"})
  self.assertEqual({m["Destination"] for m in helper_inspect["Mounts"]},{"/run/profile-helper","/var/lib/zulip"})
  self.assertEqual({m["Destination"] for m in proxy_inspect["Mounts"]},{"/run/profile-helper","/config"})
  proxy_env="\n".join(proxy_inspect["Config"]["Env"]); self.assertNotIn(token,proxy_env)
  for credential_name in ("CADDY_PROFILE_TOKEN","OPENAI_API_KEY","CODEX_AUTH_JSON"): self.assertNotIn(credential_name+"=",proxy_env)
  self.assertFalse(any("codex-auth" in json.dumps(m) for m in proxy_inspect["Mounts"]))
  self.assertEqual([e for e in helper_inspect["Config"]["Env"] if e.startswith("CADDY_PROFILE_TOKEN=")],["CADDY_PROFILE_TOKEN="+token])
  self.assertEqual(helper_inspect["Config"]["Cmd"],["/profile_helper.py","--profile","zulip"])
  logs=subprocess.check_output([DOCKER,"logs",helper_name],stderr=subprocess.STDOUT,text=True)
  for secret in (token,email,key): self.assertNotIn(secret,logs)
  # Admission is tested against the actual Unix helper, not a fixture that
  # blindly accepts whatever Authorization Caddy sends it.
  for path,method in (("/api/v1/messages","GET"),("/ready","GET")):
   for authorization in (None,"Bearer wrong","Bearer "+"x"*4090):
    with self.subTest(path=path,authorization_class="missing" if authorization is None else "invalid"):
     self.control("reset"); self.request({"target":"actual-caddy","method":method,"path":path,"body":"" if method=="GET" else "fixture-request-secret","authorization":authorization})
     result=self.wait_client(); self.assert_normalized(result,401); self.assertEqual(result["application"],[])
  self.control("reset"); self.request({"target":"actual-caddy","method":"GET","path":"/ready","body":"","authorization":"Bearer "+token})
  result=self.wait_client(); self.assert_normalized(result,204); self.assertEqual(result["application"],[])
  self.control("reset"); self.request({"target":"actual-caddy","authorization":"Bearer "+token})
  result=self.wait_client(); self.assertEqual(result["clients"][0]["status"],200); self.assertEqual(len(result["application"]),1)
  self.assertEqual(result["application"][0]["authorization"],"Basic "+base64.b64encode((email+":"+key).encode()).decode()); self.assertEqual(result["application"][0]["account"],"")
  logs=subprocess.check_output([DOCKER,"logs",helper_name],stderr=subprocess.STDOUT,text=True)
  for secret in (token,email,key): self.assertNotIn(secret,logs)

 @staticmethod
 def tar_entry(name,data,mode):
  import io, tarfile
  output=io.BytesIO()
  with tarfile.open(fileobj=output,mode="w") as archive:
   info=tarfile.TarInfo(name); info.size=len(data); info.mode=mode; archive.addfile(info,io.BytesIO(data))
  return output.getvalue()

if __name__=="__main__": unittest.main()
