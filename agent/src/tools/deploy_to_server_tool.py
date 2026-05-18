"""SSH-based remote server deployment for live strategies.

Rsyncs the strategy's run_dir to the remote host and starts the appropriate
runner process with nohup. Credentials from env vars or explicit params.

Env vars:
    VIBE_DEPLOY_HOST   — remote hostname or IP
    VIBE_DEPLOY_USER   — SSH user (default: current user)
    VIBE_DEPLOY_KEY    — path to SSH private key
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from src.agent.tools import BaseTool
from src.tools.path_utils import safe_run_dir

try:
    from live.deployment_registry import get_registry

    _AVAILABLE = True
except Exception:
    _AVAILABLE = False


class DeployToServerTool(BaseTool):
    """Push a deployment's strategy package to a remote server and start the runner."""

    name = "deploy_to_server"
    description = (
        "SSH-deploy a strategy to a remote server (e.g. AWS EC2). "
        "Rsyncs run_dir, installs deps, and starts the live_runner as a nohup "
        "background process. Stores remote PID in deployment_registry. "
        "Credentials from VIBE_DEPLOY_HOST/USER/KEY env vars or explicit params."
    )
    parameters = {
        "type": "object",
        "properties": {
            "deployment_id": {"type": "string", "description": "The deployment to push remotely"},
            "host": {"type": "string", "description": "Remote host (overrides VIBE_DEPLOY_HOST)"},
            "user": {"type": "string", "description": "SSH user (overrides VIBE_DEPLOY_USER)"},
            "key_path": {"type": "string", "description": "SSH key path (overrides VIBE_DEPLOY_KEY)"},
            "remote_base": {
                "type": "string",
                "description": "Remote base directory (default ~/vibe-strategies)",
                "default": "~/vibe-strategies",
            },
        },
        "required": ["deployment_id"],
    }
    repeatable = True
    is_readonly = False

    @classmethod
    def check_available(cls) -> bool:
        return _AVAILABLE

    def execute(self, **kwargs) -> str:
        deployment_id = kwargs["deployment_id"]
        host = kwargs.get("host") or os.environ.get("VIBE_DEPLOY_HOST", "")
        user = kwargs.get("user") or os.environ.get("VIBE_DEPLOY_USER", os.environ.get("USER", ""))
        key_path = kwargs.get("key_path") or os.environ.get("VIBE_DEPLOY_KEY", "")
        remote_base = kwargs.get("remote_base", "~/vibe-strategies")

        if not host:
            return json.dumps({
                "status": "error",
                "error": "host is required. Set VIBE_DEPLOY_HOST or pass host parameter.",
            })

        try:
            with get_registry() as reg:
                record = reg.get(deployment_id)
        except Exception as exc:
            return json.dumps({"status": "error", "error": str(exc)})

        if record is None:
            return json.dumps({"status": "error", "error": f"Deployment {deployment_id!r} not found"})

        run_dir = Path(record.run_dir)
        ssh_target = f"{user}@{host}" if user else host
        ssh_opts = ["-o", "StrictHostKeyChecking=no", "-o", "BatchMode=yes"]
        if key_path:
            ssh_opts += ["-i", str(Path(key_path).expanduser())]

        remote_dir = f"{remote_base}/{deployment_id}"
        runner_module = "live.async_live_runner" if record.cadence == "intraday" else "live.live_runner"

        agent_root = Path(__file__).resolve().parents[2]

        # 1. Create remote directory
        mkdir_cmd = ["ssh"] + ssh_opts + [ssh_target, f"mkdir -p {remote_dir}"]
        result = subprocess.run(mkdir_cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return json.dumps({"status": "error", "error": f"SSH mkdir failed: {result.stderr}"})

        # 2. Rsync run_dir
        rsync_cmd = [
            "rsync", "-avz", "--delete",
            "-e", "ssh " + " ".join(ssh_opts),
            str(run_dir) + "/",
            f"{ssh_target}:{remote_dir}/run_dir/",
        ]
        result = subprocess.run(rsync_cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            return json.dumps({"status": "error", "error": f"rsync failed: {result.stderr}"})

        # 3. Rsync agent/live + agent/backtest (minimal deps)
        for subdir in ["live", "backtest"]:
            src = str(agent_root / subdir) + "/"
            dst = f"{ssh_target}:{remote_dir}/{subdir}/"
            result = subprocess.run(
                ["rsync", "-avz", "-e", "ssh " + " ".join(ssh_opts), src, dst],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode != 0:
                return json.dumps({"status": "error", "error": f"rsync {subdir} failed: {result.stderr}"})

        # 4. Install Python deps on remote + start runner
        start_script = (
            f"cd {remote_dir} && "
            f"python3 -m pip install -q --user alpaca-py apscheduler pandas numpy scipy anthropic && "
            f"VIBE_TRADING_DEPLOYMENTS_PATH={remote_dir}/deployments.db "
            f"nohup python3 -m {runner_module} {deployment_id} "
            f"> {remote_dir}/runner.log 2>&1 & echo $!"
        )
        ssh_start = ["ssh"] + ssh_opts + [ssh_target, start_script]
        result = subprocess.run(ssh_start, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            return json.dumps({"status": "error", "error": f"Remote start failed: {result.stderr}"})

        remote_pid = result.stdout.strip().split("\n")[-1]

        try:
            with get_registry() as reg:
                reg.update_pid(deployment_id, int(remote_pid) if remote_pid.isdigit() else None, remote_host=host)
        except Exception:
            pass

        return json.dumps({
            "status": "ok",
            "deployment_id": deployment_id,
            "remote_host": host,
            "remote_dir": remote_dir,
            "remote_pid": remote_pid,
            "log_path": f"{remote_dir}/runner.log",
            "note": f"Runner started on {host}. Monitor logs: ssh {ssh_target} tail -f {remote_dir}/runner.log",
        }, ensure_ascii=False)
