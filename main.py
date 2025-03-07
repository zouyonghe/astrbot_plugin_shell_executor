import paramiko  # 依赖 Paramiko 实现 SSH 功能

from astrbot.api.all import *
from astrbot.api.event.filter import *

@register("shell_executor", "buding", "用于远程shell命令执行的插件", "1.0.1",
          "https://github.com/zouyonghe/astrbot_plugin_shell_executor")
class ShellExecutor(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        """
        初始化插件，加载配置项和命令列表
        """
        super().__init__(context)
        # 加载配置文件
        self.config = config
        
        # 初始化实例变量
        self.ssh_host = self.config.get("ssh_host", "127.0.0.1")
        self.ssh_port = self.config.get("ssh_port", 22)
        self.username = self.config.get("username", "root")
        self.password = self.config.get("password", "")
        self.private_key_path = self.config.get("private_key_path", "~/.ssh/id_rsa")
        self.passphrase = self.config.get("passphrase", "")
        self.timeout = self.config.get("timeout", 60)

    def connect_client(self):
        """
        创建并返回一个已连接的 SSH 客户端
        """
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        try:
            # 根据配置选择密钥或密码认证方式
            if self.private_key_path and os.path.exists(os.path.expanduser(self.private_key_path)):
                private_key = paramiko.RSAKey.from_private_key_file(
                    os.path.expanduser(self.private_key_path),
                    password=self.passphrase or None
                )
                client.connect(
                    hostname=self.ssh_host,
                    port=self.ssh_port,
                    username=self.username,
                    pkey=private_key,
                    timeout=self.timeout
                )
                logger.info(f"[连接成功] 使用密钥认证连接到主机 {self.ssh_host}:{self.ssh_port}")
            else:
                client.connect(
                    hostname=self.ssh_host,
                    port=self.ssh_port,
                    username=self.username,
                    password=self.password,
                    timeout=self.timeout
                )
                logger.info(f"[连接成功] 使用密码认证连接到主机 {self.ssh_host}:{self.ssh_port}")

            return client
        except Exception as e:
            logger.error(f"[连接失败] 无法连接到 {self.ssh_host}:{self.ssh_port}, 错误: {e}")
            raise e

    # 可能存在安全风险，暂不启用自定义执行命令指令
    async def _run_command(self, event: AstrMessageEvent, cmd: str):
        """
        执行单条 Shell 命令
        """
        try:
            client = self.connect_client()
            stdin, stdout, stderr = client.exec_command(cmd)

            output = stdout.read().decode()
            error = stderr.read().decode()
            client.close()

            # 过滤 stderr 中的警告信息
            warnings = []
            errors = []
            for line in error.splitlines():
                if line.startswith("warning:"):
                    warnings.append(line)  # 将警告单独记录
                else:
                    errors.append(line)  # 将非警告视为真正的错误

            if errors:
                # 如果有真正的错误，抛出错误信息
                yield event.plain_result("❌ Error:\n" + "\n".join(errors))
            if warnings:
                yield event.plain_result("⚠️ Warning:\n" + "\n".join(warnings))
            if output:
                yield event.plain_result("✅ Result:\n" + output)
        except Exception as e:
            logger.error(f"执行命令 {cmd} 时失败: {str(e)}")

    @command_group("shell")
    def shell(self):
        pass

    @permission_type(PermissionType.ADMIN)
    @shell.command("help")
    async def show_help(self, event: AstrMessageEvent):
        """
        显示插件帮助信息。
        """
        help_msg = [
            "🖥️ Shell Executor 插件帮助",
            "",
            "📜 **主要指令列表**:",
            "- `/shell check`：验证与远程服务器的连接是否有效。",
            "- `/shell reboot`：重启远程系统。",
            "- `/shell rewin`：重启到 Windows 系统。（双系统自用）",
            "- `/shell cpupower`：查看 CPU 功率信息。",
            "- `/shell nvidia-smi`：查看 NVIDIA 图形卡状态。",
            "",
            "🔧 **系统服务控制**（`/shell systemctl` 子命令）:",
            "- `start [服务名]`：启动指定的服务，例如 `/shell systemctl start nginx`。",
            "- `status [服务名]`：查看指定服务的状态，例如 `/shell systemctl status sshd`。",
            "- `stop [服务名]`：停止指定的服务。",
            "- `enable [服务名]`：设置服务为开机启动。",
            "- `disable [服务名]`：设置服务为开机禁用。",
            "- `logs [服务名]`：查看最近 100 条服务日志。",
            "",
            "🛠️ **Docker 容器管理**（`/shell docker` 子命令）:",
            "- `logs [容器名]`：查看 Docker 容器日志，例如 `/shell docker logs my_container`。",
            "- `start [容器名]`：启动指定的容器。",
            "- `stop [容器名]`：停止指定的容器。",
            "- `run [镜像] [选项...]`：运行一个新的容器。",
            "- `pull [镜像]`：拉取指定 Docker 镜像。",
            "- `ps`：列出所有运行中的 Docker 容器。",
            "- `rm [容器名]`：删除指定的容器。",
        ]
        yield event.plain_result("\n".join(help_msg))

    @permission_type(PermissionType.ADMIN)
    @shell.command("check")
    async def check_connection(self, event: AstrMessageEvent):
        """
        验证连接是否成功
        """
        try:
            client = self.connect_client()
            client.close()
            yield event.plain_result(f"✅ 成功连接到 {self.ssh_host}:{self.ssh_port}")
        except Exception as e:
            yield event.plain_result(f"❌ 无法连接到 {self.ssh_host}:{self.ssh_port} - {str(e)}")


    @permission_type(PermissionType.ADMIN)
    @shell.command("paru")
    async def arch_paru(self, event: AstrMessageEvent):
        """
        在远程 Arch 系统上执行 paru -Syu --noconfirm 命令以更新系统。
        """
        cmd = "paru -Syu --noconfirm"  # 设置更新命令

        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @shell.command("inxi")
    async def inxi(self, event: AstrMessageEvent):
        """
        使用 inxi 工具查询精简系统状态。
        """
        cmd = "inxi -c"

        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @shell.command("inxi-full")
    async def inxi_full(self, event: AstrMessageEvent):
        """
        使用 inxi 工具查询完整系统状态。
        """
        cmd = "inxi -F"

        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @shell.command("nvidia-smi")
    async def nvidia_smi(self, event: AstrMessageEvent):
        """
        查看nvidia显卡状态
        """
        cmd = "nvidia-smi --query-gpu=name,power.draw,power.limit,fan.speed,clocks.gr,clocks.mem --format=csv,noheader"

        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @shell.command("cpupower")
    async def cpupower(self, event: AstrMessageEvent):
        """
        使用cpupower查看cpu状态
        """
        cmd = "cpupower frequency-info" # cpupower -c all frequency-info

        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @shell.command("reboot")
    async def reboot(self, event: AstrMessageEvent):
        """
        重启远程系统
        """
        cmd = "sudo reboot"

        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @shell.command("rewin")
    async def rewin(self, event: AstrMessageEvent):
        """
        重启到windows系统
        """
        cmd = "sudo rewin"

        async for result in self._run_command(event, cmd):
            yield result
    
    @shell.group("systemctl")
    def systemctl(self):
        pass

    @permission_type(PermissionType.ADMIN)
    @systemctl.command("start")
    async def systemctl_start(self, event: AstrMessageEvent, service: str):
        """
        启动指定的系统服务
        """
        cmd = f"sudo systemctl start {service}"
        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @systemctl.command("status")
    async def systemctl_status(self, event: AstrMessageEvent, service: str):
        """
        查看指定系统服务的状态
        """
        cmd = f"sudo systemctl status {service}"
        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @systemctl.command("stop")
    async def systemctl_stop(self, event: AstrMessageEvent, service: str):
        """
        停止指定的系统服务
        """
        cmd = f"sudo systemctl stop {service}"
        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @systemctl.command("enable")
    async def systemctl_enable(self, event: AstrMessageEvent, service: str):
        """
        启用指定的系统服务
        """
        cmd = f"sudo systemctl enable {service}"
        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @systemctl.command("disable")
    async def systemctl_disable(self, event: AstrMessageEvent, service: str):
        """
        禁用指定的系统服务
        """
        cmd = f"sudo systemctl disable {service}"
        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @systemctl.command("logs")
    async def journalctl_logs(self, event: AstrMessageEvent, service: str):
        """
        查看指定服务的最近 100 条日志
        """
        cmd = f"journalctl -u {service} -n 100 --no-pager"
        async for result in self._run_command(event, cmd):
            yield result

    @shell.group("docker")
    def docker(self):
        pass

    @permission_type(PermissionType.ADMIN)
    @docker.command("logs")
    async def docker_logs(self, event: AstrMessageEvent, container: str):
        """
        查看指定 Docker 容器的日志。
        """
        cmd = f"docker logs {container}"
        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @docker.command("start")
    async def docker_start(self, event: AstrMessageEvent, container: str):
        """
        启动指定的 Docker 容器。
        """
        cmd = f"docker start {container}"
        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @docker.command("stop")
    async def docker_stop(self, event: AstrMessageEvent, container: str):
        """
        停止指定的 Docker 容器。
        """
        cmd = f"docker stop {container}"
        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @docker.command("run")
    async def docker_run(self, event: AstrMessageEvent, image: str, opt1: str = None, opt2: str = None, opt3: str = None):
        """
        运行一个新的 Docker 容器。
        """
        options = " ".join(str(opt) for opt in [opt1, opt2, opt3] if opt is not None)
        cmd = f"docker run {options} {image}"
        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @docker.command("pull")
    async def docker_pull(self, event: AstrMessageEvent, image: str):
        """
        拉取指定的 Docker 镜像。
        """
        cmd = f"docker pull {image}"
        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @docker.command("ps")
    async def docker_ps(self, event: AstrMessageEvent):
        """
        列出所有运行中的 Docker 容器。
        """
        cmd = "docker ps"
        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @docker.command("rm")
    async def docker_rm(self, event: AstrMessageEvent, container: str):
        """
        删除指定的 Docker 容器。
        """
        cmd = f"docker rm {container}"
        async for result in self._run_command(event, cmd):
            yield result