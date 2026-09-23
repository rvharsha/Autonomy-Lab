"""Real Docker boundary checks using the same agent image and container restrictions."""

import json
import subprocess
import uuid

from autonomy_lab.harness import save
from autonomy_lab.isolated_runtime import build_agent_image, container_args
from autonomy_lab.kubernetes import ROOT


def main():
    output = ROOT / "artifacts" / ("isolation-" + uuid.uuid4().hex[:8])
    output.mkdir(parents=True, mode=0o700)
    image = build_agent_image()
    forbidden = output / "controller-secret"
    forbidden.write_text(uuid.uuid4().hex)
    probe = '''import json,os,socket
from pathlib import Path
results={}
for name,path in {'controller_file':FORBIDDEN,'kubernetes_credentials':'/var/run/secrets/kubernetes.io/serviceaccount/token','broker_journal':'/workspace/../operations.sqlite','fixtures':'/app/fixtures/expectations.json','docker_socket':'/var/run/docker.sock'}.items():
 try:
  Path(path).read_bytes(); results[name]=False
 except OSError:
  results[name]=True
for name,path in {'immutable_code':'/app/autonomy_lab/agent.py','root_filesystem':'/forbidden-write'}.items():
 try:
  with open(path,'a') as f: f.write('unauthorized')
  results[name]=False
 except OSError:
  results[name]=True
for host,port in [('1.1.1.1',443),('169.254.169.254',80),('172.17.0.1',2375)]:
 try:
  with socket.create_connection((host,port),timeout=2): pass
  results['network_'+host]=False
 except OSError:
  results['network_'+host]=True
results['no_credentials']=not any(os.environ.get(k) for k in ('GEMINI_API_KEY','GOOGLE_API_KEY','ANTHROPIC_API_KEY','KUBECONFIG'))
results['non_root']=os.getuid()!=0
status=Path('/proc/self/status').read_text()
results['no_capabilities']='CapEff:\\t0000000000000000' in status
results['no_privilege_escalation']='NoNewPrivs:\\t1' in status
Path('/workspace/checkpoint-test').write_text('durable write permitted')
results['workspace_writable']=True
print(json.dumps(results))
'''.replace('FORBIDDEN', repr(str(forbidden)))
    args = container_args(image, output / "workspace", "autolab-agent-" + uuid.uuid4().hex[:12])
    # The probe executes inside precisely the same restriction set; it does not
    # substitute output or infer enforcement from Docker flags.
    args = args[:-1] + ["--entrypoint", "python", args[-1], "-c", probe]
    run = subprocess.run(args, text=True, capture_output=True, timeout=60)
    (output / "stderr.log").write_text(run.stderr)
    result = {"image_id": image, "returncode": run.returncode,
              "checks": json.loads(run.stdout) if run.returncode == 0 else {}}
    result["status"] = "passed" if run.returncode == 0 and result["checks"] and all(result["checks"].values()) else "failed"
    save(output / "result.json", result)
    print(output)
    if result["status"] != "passed":
        raise SystemExit(1)


if __name__ == '__main__':
    main()
