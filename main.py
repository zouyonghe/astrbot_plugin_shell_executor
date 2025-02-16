import logging

import paramiko  # 依赖 Paramiko 实现 SSH 功能

from astrbot.api.all import *
from astrbot.api.event.filter import *

logger = logging.getLogger("astrbot")

@register("shell_executor", "buding", "用于远程shell命令执行的插件", "0.0.1",
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

            if error:
                yield event.plain_result(f"命令执行出错: {error}")
            yield event.plain_result(f"命令执行成功: {output}")
        except Exception as e:
            yield event.plain_result(f"执行命令失败: {str(e)}")

    @permission_type(PermissionType.ADMIN)
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
            yield event.plain_result(f"成功连接到 {self.ssh_host}:{self.ssh_port}")
        except Exception as e:
            yield event.plain_result(f"无法连接到 {self.ssh_host}:{self.ssh_port} - {str(e)}")

    @permission_type(PermissionType.ADMIN)
    @shell.command("paru")
    async def arch_paru(self, event: AstrMessageEvent):
        """
        在远程 Arch 系统上执行 paru -Syu --noconfirm 命令以更新系统。
        """
        cmd = "paru -Syu --noconfirm"  # 设置更新命令

        try:
            # 调用 _run_command 方法执行更新命令
            async for result in self._run_command(event, cmd):
                yield result
        except Exception as e:
            yield event.plain_result(f"系统更新失败: {str(e)}")

