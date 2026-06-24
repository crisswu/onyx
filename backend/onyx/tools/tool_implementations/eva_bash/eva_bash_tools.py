from __future__ import annotations

import datetime
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any
from typing import ClassVar

from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CustomToolArgs
from onyx.server.query_and_chat.streaming_models import CustomToolDelta
from onyx.server.query_and_chat.streaming_models import CustomToolStart
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException
from onyx.tools.models import ToolResponse

MAX_LLM_FACING_RESPONSE_CHARS = 8000

ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

BLOCKED_PATTERNS = [
    r"rm\s+(-[a-zA-Z]*)*\s*-rf\s+/(?!\w)",
    r"rm\s+(-[a-zA-Z]*)*\s*-rf\s+~/?$",
    r"rm\s+(-[a-zA-Z]*)*\s*-rf\s+\*",
    r"rm\s+(-[a-zA-Z]*)*\s*-rf\s+/home\s*$",
    r"mkfs\.",
    r"dd\s+.*of=/dev/[sh]d",
    r">\s*/dev/[sh]d[a-z]?",
    r"^\s*sudo\s+",
    r"^\s*su\s+",
    r"curl.*\|\s*(?:ba)?sh",
    r"wget.*\|\s*(?:ba)?sh",
    r"curl.*\|\s*python",
    r"^\s*reboot\b",
    r"^\s*shutdown\b",
    r"^\s*init\s+[06]",
    r"^\s*poweroff\b",
    r":\(\)\s*\{\s*:\|:&\s*\}\s*;:",
    r">\s*/etc/passwd",
    r">\s*/etc/shadow",
    r">\s*/etc/sudoers",
]

DANGEROUS_SUDO_PATTERNS = [
    (r"mkfs\.", "禁止格式化磁盘"),
    (r"dd\s+.*of=/dev/[shnv][dvhma]", "禁止覆写磁盘设备"),
    (r">\s*/dev/[shnv][dvhma][a-z0-9]?", "禁止重定向到磁盘设备"),
    (r"rm\s+.*-rf.*\s+/\s*$", "禁止 rm -rf 根目录"),
    (r"rm\s+.*-rf.*\s+/home\s*$", "禁止 rm -rf /home"),
    (r"rm\s+(-[a-zA-Z]*\s+)*-rf\s+~\s*$", "禁止 rm -rf 家目录"),
    (r"rm\s+(-[a-zA-Z]*\s+)*-rf\s+\*", "禁止 rm -rf *"),
    (r"systemctl\s+(stop|disable)\s+(ssh|sshd)\b", "禁止关停 SSH 服务"),
    (
        r"systemctl\s+(stop|disable)\s+(networking|network-manager|NetworkManager)\b",
        "禁止关停网络服务",
    ),
    (r"service\s+(ssh|sshd|networking)\s+stop\b", "禁止停止关键网络服务"),
    (r"apt[- ]?(get\s+)?(purge|remove)\s+.*openssh-server", "禁止卸载 SSH 服务"),
    (r"apt[- ]?(get\s+)?(purge|remove)\s+.*linux-image", "禁止删除内核镜像"),
    (
        r"apt[- ]?(get\s+)?(purge|remove)\s+.*(grub|grub2|grub-pc|grub-efi)\b",
        "禁止删除引导器",
    ),
    (r"apt[- ]?(get\s+)?(purge|remove)\s+systemd\b", "禁止删除 systemd"),
    (r"apt[- ]?(get\s+)?(purge|remove)\s+libc6\b", "禁止删除 C 运行库"),
    (r">\s*/etc/passwd", "禁止覆写 /etc/passwd"),
    (r">\s*/etc/shadow", "禁止覆写 /etc/shadow"),
    (r">\s*/etc/sudoers", "禁止覆写 /etc/sudoers"),
    (r"\btee\s+/etc/passwd\b", "禁止 tee 写入 /etc/passwd"),
    (r"\btee\s+/etc/shadow\b", "禁止 tee 写入 /etc/shadow"),
    (r"\btee\s+/etc/sudoers\b", "禁止 tee 写入 /etc/sudoers"),
    (r"curl.*\|\s*(ba)?sh", "禁止 curl 管道执行 shell"),
    (r"wget.*\|\s*(ba)?sh", "禁止 wget 管道执行 shell"),
    (r"curl.*\|\s*python", "禁止 curl 管道执行 Python"),
    (r":\(\)\s*\{\s*:\|:&", "禁止 Fork 炸弹"),
    (r"\bsudo\s+sudo\b", "禁止 sudo 嵌套"),
    (r"\bsudo\s+visudo\b", "禁止通过 visudo 修改 sudoers"),
]

RESOURCE_LIMITS = {
    "max_output_bytes": 51200,
    "max_command_length": 2000,
}


def _env_flag(name: str, *, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _coerce_timeout(value: Any) -> int:
    try:
        timeout = int(value)
    except (TypeError, ValueError):
        timeout = 60
    return min(max(timeout, 1), 300)


def _truncate_for_llm(text: str, limit: int = MAX_LLM_FACING_RESPONSE_CHARS) -> str:
    if len(text) <= limit:
        return text
    return (
        text[:limit].rstrip()
        + f"\n\n...（命令输出过长，已截断给模型读取，原始长度 {len(text)} 字符）"
    )


def _preprocess_args(kwargs: dict[str, Any]) -> dict[str, Any]:
    if len(kwargs) == 1:
        value = next(iter(kwargs.values()))
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
    return kwargs


class SudoValidator:
    @classmethod
    def validate_sudo_command(cls, command: str) -> tuple[bool, str]:
        command = command.strip()
        blocked_reason = cls._check_blacklist(command)
        if blocked_reason:
            cls._log_audit(command, "BLOCKED", blocked_reason)
            return False, f"检测到危险操作: {blocked_reason}"

        cls._log_audit(command, "ALLOWED", None)
        return True, "验证通过"

    @classmethod
    def _check_blacklist(cls, command: str) -> str | None:
        reason = cls._match_patterns(command)
        if reason:
            return reason

        sub_commands = re.split(r"&&|\|\||\s;\s|;", command)
        for sub_command in sub_commands:
            sub_command = sub_command.strip()
            if not sub_command:
                continue
            reason = cls._match_patterns(sub_command)
            if reason:
                return reason
        return None

    @classmethod
    def _match_patterns(cls, command: str) -> str | None:
        for pattern, reason in DANGEROUS_SUDO_PATTERNS:
            if re.search(pattern, command, re.IGNORECASE):
                return reason
        return None

    @classmethod
    def _log_audit(cls, command: str, result: str, reason: str | None) -> None:
        try:
            log_file = Path(
                os.environ.get(
                    "EVA_BASH_AUDIT_LOG_PATH",
                    "/app/file-system/eva_bash_sudo_audit.log",
                )
            )
            log_file.parent.mkdir(parents=True, exist_ok=True)
            log_entry = {
                "timestamp": datetime.datetime.now().isoformat(),
                "command": command,
                "mode": "passwordless_sudo_token_removed",
                "result": result,
                "reason": reason,
            }
            with log_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
            try:
                os.chmod(log_file, 0o600)
            except OSError:
                pass
        except Exception:
            pass


class ExecuteBashTool(Tool[None]):
    NAME = "execute_bash"
    DISPLAY_NAME = "执行命令"
    DESCRIPTION = """在 Linux 系统中执行 Bash 命令，复刻 EVA 的“执行命令”工具能力。

环境说明：
- 默认工作目录由 EVA_BASH_DEFAULT_WORKSPACE 配置，当前部署默认为 /home/criss/onyx。
- 支持查看文件、运行脚本、数据处理、服务排查、Docker/系统命令等常见运维操作。
- 支持 &&、;、管道等复合命令。
- 需要 sudo 的操作会走 sudo 安全校验；前提是目标环境支持无交互 sudo。

安全限制：
- 禁止格式化磁盘、覆写磁盘设备、Fork 炸弹。
- 禁止 rm -rf /、rm -rf ~、rm -rf /home、rm -rf * 等破坏性删除。
- 禁止关停 SSH/网络服务、删除内核/引导器/openssh-server/systemd/libc6。
- 禁止覆写 /etc/passwd、/etc/shadow、/etc/sudoers。
- 禁止 curl/wget 管道直接执行 shell/python。

使用建议：
- 简单查询直接执行，例如 ls、cat、rg、ps、df、docker ps。
- 修改系统或项目文件前，先读取现状再执行最小必要命令。
- 命令输出最多保留约 50KB，失败时优先保留尾部输出。"""
    PARAMETERS: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要执行的 Bash 命令，如 'ls -la' 或 'cat file.txt'",
            },
            "timeout": {
                "type": "integer",
                "description": "命令超时时间，单位秒，默认 60，最大 300",
            },
            "working_dir": {
                "type": "string",
                "description": "工作目录，可选；相对路径会基于默认工作目录解析",
            },
        },
        "required": ["command"],
    }

    def __init__(self, tool_id: int, emitter: Emitter) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self.default_workspace = Path(
            os.environ.get("EVA_BASH_DEFAULT_WORKSPACE", "/home/criss/onyx")
        ).expanduser()

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @override
    @classmethod
    def is_available(cls, db_session: Any) -> bool:  # noqa: ARG003
        return _env_flag("EVA_BASH_ENABLED", default=True)

    def tool_definition(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.PARAMETERS,
            },
        }

    def emit_start(self, placement: Placement) -> None:
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolStart(tool_name=self.name, tool_id=self.id),
            )
        )

    @override
    def run(
        self, placement: Placement, override_kwargs: None, **llm_kwargs: Any
    ) -> ToolResponse:
        args = _preprocess_args(dict(llm_kwargs))
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolArgs(tool_name=self.name, tool_args=args),
            )
        )

        command = str(args.get("command") or "").strip()
        if not command:
            raise ToolCallException("Missing command", "执行失败：缺少 command 参数")

        timeout = _coerce_timeout(args.get("timeout"))
        working_dir = args.get("working_dir")
        result = self._run_command(
            command=command,
            timeout=timeout,
            working_dir=str(working_dir).strip() if working_dir else None,
        )
        llm_facing_response = _truncate_for_llm(result)
        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CustomToolDelta(
                    tool_name=self.name,
                    tool_id=self.id,
                    response_type="text",
                    data=result,
                ),
            )
        )
        return ToolResponse(
            rich_response=llm_facing_response,
            llm_facing_response=llm_facing_response,
        )

    def _run_command(
        self,
        *,
        command: str,
        timeout: int,
        working_dir: str | None,
    ) -> str:
        command = self._strip_legacy_sudo_annotations(command)
        if len(command) > RESOURCE_LIMITS["max_command_length"]:
            return f"命令过长，最大允许 {RESOURCE_LIMITS['max_command_length']} 字符"

        if self._command_uses_sudo(command):
            is_safe, error = SudoValidator.validate_sudo_command(command)
            if not is_safe:
                return f"Sudo 命令验证失败: {error}"
        else:
            is_safe, error = self._validate_command(command)
            if not is_safe:
                return f"安全检查失败: {error}"

        cwd = self._resolve_working_dir(working_dir)
        if not cwd.exists():
            return f"工作目录不存在: {cwd}"

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=self._get_safe_env(),
            )
            return self._format_output(result, command)
        except subprocess.TimeoutExpired:
            return f"命令执行超时（{timeout} 秒）"
        except Exception as e:
            return f"执行错误: {str(e)}"

    def _strip_legacy_sudo_annotations(self, command: str) -> str:
        patterns = [
            r"(?:^|\s)(?:密令|密码|授权码|token)[：:]\s*[A-Za-z0-9]{4,8}(?=$|\s)",
        ]
        for pattern in patterns:
            command = re.sub(pattern, " ", command, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", command).strip()

    def _command_uses_sudo(self, command: str) -> bool:
        return bool(re.search(r"(^|[;&|]\s*)sudo\b", command or "", re.IGNORECASE))

    def _validate_command(self, command: str) -> tuple[bool, str]:
        command_stripped = command.strip()
        if not command_stripped:
            return False, "命令不能为空"

        for pattern in BLOCKED_PATTERNS:
            if re.search(pattern, command_stripped, re.IGNORECASE):
                return False, "检测到危险命令模式，已拦截"
        return True, ""

    def _resolve_working_dir(self, working_dir: str | None) -> Path:
        if working_dir:
            path = Path(working_dir).expanduser()
            return path if path.is_absolute() else self.default_workspace / path
        return self.default_workspace

    def _get_safe_env(self) -> dict[str, str]:
        env = os.environ.copy()
        standard_paths = [
            "/usr/local/sbin",
            "/usr/local/bin",
            "/usr/sbin",
            "/usr/bin",
            "/sbin",
            "/bin",
        ]
        current_path = env.get("PATH", "")
        path_parts = current_path.split(":") if current_path else []
        for std_path in standard_paths:
            if std_path not in path_parts:
                path_parts.append(std_path)
        env["PATH"] = ":".join(path_parts)

        for unsafe_var in ("LD_PRELOAD", "LD_LIBRARY_PATH", "PYTHONPATH"):
            env.pop(unsafe_var, None)
        return env

    def _strip_ansi(self, text: str) -> str:
        return ANSI_ESCAPE_RE.sub("", text or "")

    def _truncate_stream_output(
        self, text: str, limit: int, *, prefer_tail: bool = False
    ) -> str:
        cleaned = self._strip_ansi(text)
        if len(cleaned) <= limit:
            return cleaned
        if prefer_tail:
            tail = cleaned[-limit:].lstrip()
            return f"... [输出已截断，保留最后 {limit} 字符]\n{tail}"
        return cleaned[:limit] + f"\n\n... [输出已截断，超过 {limit // 1024}KB]"

    def _format_output(
        self, result: subprocess.CompletedProcess[str], command: str = ""
    ) -> str:
        max_bytes = RESOURCE_LIMITS["max_output_bytes"]
        failure_mode = result.returncode != 0
        output_parts: list[str] = []

        if failure_mode:
            output_parts.append(f"退出码: {result.returncode}")

        if result.stdout:
            stdout = self._truncate_stream_output(
                result.stdout,
                max_bytes,
                prefer_tail=failure_mode,
            )
            if failure_mode:
                output_parts.append(f"标准输出:\n{stdout}")
            else:
                output_parts.append(stdout)

        if result.stderr:
            stderr = self._strip_ansi(result.stderr)
            is_progress_info = self._is_progress_stderr(
                result.returncode, stderr, command
            )
            stderr = self._truncate_stream_output(
                stderr,
                max_bytes // 2,
                prefer_tail=failure_mode and not is_progress_info,
            )
            if is_progress_info:
                output_parts.append(f"执行信息:\n{stderr}")
            else:
                output_parts.append(f"错误输出:\n{stderr}")

        if not output_parts:
            return "命令执行成功（无输出）"
        return "\n".join(output_parts)

    def _is_progress_stderr(self, returncode: int, stderr: str, command: str) -> bool:
        if returncode != 0:
            return False

        stderr_lower = stderr.lower()
        lines = [line.strip() for line in stderr_lower.splitlines() if line.strip()]
        if lines:
            warning_prefixes = (
                "warning:",
                "debconf:",
                "dpkg-preconfigure:",
                "invoke-rc.d:",
                "policy-rc.d:",
            )
            fatal_indicators = (
                "error:",
                "failed",
                "failure",
                "exception",
                "traceback",
                "denied",
                "permission denied",
                "unmet dependencies",
                "dependency problems",
                "could not",
                "not found",
                "unable to locate package",
                "没有那个文件或目录",
                "未能满足的依赖关系",
            )
            if all(line.startswith(warning_prefixes) for line in lines):
                if not any(indicator in stderr_lower for indicator in fatal_indicators):
                    return True

        progress_commands = ["wget", "curl", "rsync", "scp", "git"]
        command_lower = command.lower()
        if not any(cmd in command_lower for cmd in progress_commands):
            return False

        success_indicators = [
            "saved",
            "已保存",
            "100%",
            "complete",
            "完成",
            "下载完成",
            "downloaded",
            "success",
        ]
        error_indicators = [
            "error",
            "failed",
            "失败",
            "错误",
            "exception",
            "denied",
            "拒绝",
        ]
        return any(ind in stderr_lower for ind in success_indicators) and not any(
            ind in stderr_lower for ind in error_indicators
        )
