import logging

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
            output = []
            warnings = []
            errors = []

            client = self.connect_client()
            stdin, stdout, stderr = client.exec_command(cmd)

            for line in stdout:
                output.append(line.strip())
            for line in stderr:
                if line.startswith("warning:"):
                    warnings.append(line)  # 将警告单独记录
                else:
                    errors.append(line)  # 将非警告视为真正的错误
            # output = stdout.read().decode()
            # error = stderr.read().decode()
            # client.close()
            #
            # # 过滤 stderr 中的警告信息
            # warnings = []
            # errors = []
            # for line in error.splitlines():
            #     if line.startswith("warning:"):
            #         warnings.append(line)  # 将警告单独记录
            #     else:
            #         errors.append(line)  # 将非警告视为真正的错误

            if errors:
                # 如果有真正的错误，抛出错误信息
                yield event.plain_result("❌ Error:\n" + "\n".join(errors))
            if warnings:
                yield event.plain_result("⚠️ Warning:\n" + "\n".join(warnings))
            if output:
                yield event.plain_result("✅ Result:\n" + "\n".join(warnings))
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
    async def inxi(self, event: AstrMessageEvent):
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
        cmd = "cpupower -c all frequency-info" # cpupower -c all frequency-info

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

    @shell.group("pty")
    def pty(self):
        pass

    @permission_type(PermissionType.ADMIN)
    @pty.command("test")
    async def test_pty(self, event: AstrMessageEvent, arg1: str, arg2: str=None, arg3: str=None, arg4: str=None, arg5: str=None):
        cmd = " ".join(str(arg) for arg in [arg1, arg2, arg3, arg4, arg5] if arg is not None)

        yield event.plain_result(f"cmd: {cmd}")

    # @permission_type(PermissionType.ADMIN)
    # @pty.command("new")
    # async def start_interactive_pty(self, event: AstrMessageEvent):
    #     """
    #     启动伪终端会话。
    #     """
    #     session_id = event.get_sender_id()
    #
    #     # 如果用户会话已存在，则提示会话已激活
    #     if session_id in self.pty_sessions:
    #         yield event.plain_result("⚠️ 已有一个活动的伪终端会话，输入 /shell pty exit 以关闭会话。")
    #         return
    #
    #     try:
    #         # 建立 SSH 客户端
    #         client = self.connect_client()
    #         transport = client.get_transport()
    #
    #         # 打开伪终端
    #         channel = transport.open_session()
    #         channel.get_pty()
    #         channel.invoke_shell()
    #
    #         # 在全局会话中记录伪终端会话
    #         self.pty_sessions[session_id] = {
    #             "client": client,
    #             "channel": channel,
    #         }
    #
    #         yield event.plain_result(
    #             f"✅ 已启动伪终端会话 (主机: {self.ssh_host}:{self.ssh_port})。使用 /shell pty exec <command> 发送命令，输入 /shell pty exit 结束会话。")
    #     except Exception as e:
    #         logger.error(f"启动伪终端失败: {e}")
    #         yield event.plain_result(f"❌ 无法启动伪终端: {e}")
    #
    # @permission_type(PermissionType.ADMIN)
    # @pty.command("exec")
    # async def execute_command_in_pty(self, event: AstrMessageEvent, arg1: str, arg2: str=None, arg3: str=None, arg4: str=None, arg5: str=None):
    #     """
    #     在伪终端执行命令。
    #     """
    #     session_id = event.get_sender_id()
    #     cmd = " ".join(str(arg) for arg in [arg1, arg2, arg3, arg4, arg5] if arg is not None)
    #
    #     if self.check_illegal_command(cmd):
    #         yield event.plain_result("⚠️ 非法命令，将不会被执行！")
    #         logger.error(f"发些非法命令： {cmd}，发送者： {event.get_sender_id()}")
    #         return
    #
    #     # 检查会话是否存在
    #     if session_id not in self.pty_sessions:
    #         yield event.plain_result("⚠️ 当前没有活跃的伪终端会话，请先使用 /shell pty new 启动会话。")
    #         return
    #
    #     session = self.pty_sessions[session_id]
    #     channel = session["channel"]
    #
    #     try:
    #         # 发送命令到伪终端
    #         channel.send(cmd + "\n")
    #         output = ""
    #
    #         # 获取返回结果
    #         while True:
    #             if channel.recv_ready():
    #                 data = channel.recv(1024).decode("utf-8")
    #                 output += data
    #                 if not data:
    #                     break
    #             else:
    #                 break
    #
    #         yield event.plain_result(output.strip())
    #     except Exception as e:
    #         logger.error(f"伪终端命令执行失败: {e}")
    #         yield event.plain_result(f"❌ 命令执行失败: {e}")
    #
    # @permission_type(PermissionType.ADMIN)
    # @pty.command("exit")
    # async def close_interactive_pty(self, event: AstrMessageEvent):
    #     """
    #     关闭当前用户的伪终端会话。
    #     """
    #     session_id = event.get_sender_id()
    #
    #     # 检查会话是否存在
    #     if session_id not in self.pty_sessions:
    #         yield event.plain_result("⚠️ 当前没有活跃的伪终端会话。")
    #         return
    #
    #     try:
    #         # 获取会话信息并关闭
    #         session = self.pty_sessions.pop(session_id)
    #         session["channel"].close()
    #         session["client"].close()
    #
    #         yield event.plain_result("✅ 伪终端会话已关闭。")
    #     except Exception as e:
    #         logger.error(f"关闭伪终端失败: {e}")
    #         yield event.plain_result(f"❌ 伪终端关闭失败: {e}")

