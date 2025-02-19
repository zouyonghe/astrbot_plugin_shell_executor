import asyncio
import logging
import threading
import time

import paramiko  # 依赖 Paramiko 实现 SSH 功能

from astrbot.api.all import *
from astrbot.api.event.filter import *

logger = logging.getLogger("astrbot")

@register("shell_executor", "buding", "用于远程shell命令执行的插件", "1.0.0",
          "https://github.com/zouyonghe/astrbot_plugin_shell_executor")
class ShellExecutor(Star):
    def __init__(self, context: Context, config: dict):
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

        # 存储当前PTY会话
        self.pty_sessions = {}

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

    def check_illegal_command(self, cmd: str) -> bool:
        """
        检测命令中是否存在可能造成系统损害的非法命令
        """
        illegal_keywords = [
            # 文件操作
            "rm", "dd", "cp", "mv", "rmdir",

            # 网络操作
            "curl", "wget", "scp", "ftp", "rsync",

            # 系统管理
            "reboot", "shutdown", "kill",

            # 包管理
            #"pacman", "paru", "yay", "makepkg",

            # 危险符号
            "|", "&&", ";",

            # 高权限操作
            "sudo", "su",

            # 磁盘管理工具
            "fdisk", "parted", "cfdisk", "sfdisk",

            # 格式化工具
            "mkfs", "mkswap",

            # 磁盘复制与设备操作工具
            "dd", "blkdiscard", "wipefs",

            # 挂载与卸载
            "mount", "umount",

            # RAID 和分区管理工具
            "mdadm", "vgcreate", "lvcreate", "pvcreate",

            # 文件权限相关
            "chmod", "chown", "chgrp",

            # 用户管理相关
            "usermod", "userdel", "groupmod", "groupdel", "passwd",

        ]
        return any(keyword in cmd for keyword in illegal_keywords)

    @command_group("shell")
    def shell(self):
        pass

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

    @shell.group("pty")
    def pty(self):
        pass

    @permission_type(PermissionType.ADMIN)
    @pty.command("new")
    async def start_interactive_pty(self, event: AstrMessageEvent):
        """
        启动伪终端会话。
        """
        session_id = event.get_sender_id()

        # 如果用户会话已存在，则提示会话已激活
        if session_id in self.pty_sessions:
            yield event.plain_result("⚠️ 已有一个活动的PTY会话，输入 /shell pty exit 以关闭会话。")
            return

        try:
            # 建立 SSH 客户端
            client = self.connect_client()
            transport = client.get_transport()

            # 打开伪终端
            channel = transport.open_session()
            channel.get_pty()
            channel.invoke_shell()

            # 在全局会话中记录伪终端会话
            self.pty_sessions[session_id] = {
                "client": client,
                "channel": channel,
            }

            yield event.plain_result(
                f"✅ 已启动PTY会话 (主机: {self.ssh_host}:{self.ssh_port})。\n使用 /shell pty exec <command> 发送命令，输入 /shell pty exit 结束会话。")
        except Exception as e:
            logger.error(f"启动PTY失败: {e}")
            yield event.plain_result(f"❌ 无法启动PTY: {e}")

    @permission_type(PermissionType.ADMIN)
    @pty.command("exec")
    async def execute_command_in_pty(self, event: AstrMessageEvent, arg1: str, arg2: str=None, arg3: str=None, arg4: str=None, arg5: str=None):
        """
        在伪终端执行命令。
        """
        session_id = event.get_sender_id()
        cmd = " ".join(str(arg) for arg in [arg1, arg2, arg3, arg4, arg5] if arg is not None)

        if self.check_illegal_command(cmd):
            yield event.plain_result("⚠️ 非法命令，将不会被执行！")
            logger.error(f"已拒绝非法命令执行请求，命令： {cmd}，发送者： {event.get_sender_id()}")
            return

        # 检查会话是否存在
        if session_id not in self.pty_sessions:
            yield event.plain_result("⚠️ 当前没有活跃的PTY会话，请先使用 /shell pty new 启动会话。")
            return

        session = self.pty_sessions[session_id]
        channel = session["channel"]

        try:
            channel.send(cmd + "\n")  # 发送命令
            output = ""

            timeout = 5  # 超时阈值（秒）
            start_time = time.time()

            while True:
                if channel.recv_ready():  # 如果有数据准备好
                    data = channel.recv(4096).decode("utf-8")  # 接收数据，解码
                    output += data  # 将新接收到的数据追加到缓存中
                    start_time = time.time()  # 换新开始时间

                if channel.exit_status_ready():  # 如果命令执行完成，退出循环
                    break

                if time.time() - start_time > timeout:  # 检查是否超时
                    yield event.plain_result("⚠️ 超时未收到响应，命令可能已完成或无输出。")
                    break

                time.sleep(0.1)  # 防止忙等
            yield event.plain_result(output)

        except Exception as e:
            logger.error(f"PTY命令执行失败: {e}")
            yield event.plain_result(f"❌ 命令执行失败: {e}")

    @permission_type(PermissionType.ADMIN)
    @pty.command("exit")
    async def close_interactive_pty(self, event: AstrMessageEvent):
        """
        关闭当前用户的伪终端会话。
        """
        session_id = event.get_sender_id()

        # 检查会话是否存在
        if session_id not in self.pty_sessions:
            yield event.plain_result("⚠️ 当前没有活跃的PTY会话。")
            return

        try:
            # 获取会话信息并关闭
            session = self.pty_sessions.pop(session_id)
            session["channel"].close()
            session["client"].close()

            yield event.plain_result("✅ PTY会话已关闭。")
        except Exception as e:
            logger.error(f"关闭伪终端失败: {e}")
            yield event.plain_result(f"❌ PTY关闭失败: {e}")

