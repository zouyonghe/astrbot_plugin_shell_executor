# ShellExecutor 插件
## 概述
`ShellExecutor` 是一个基于 Astrbot 平台开发的插件，用于通过 SSH 执行远程 Shell 命令。本插件支持以下功能：
- 远程连接服务器（支持密码认证和密钥认证）。
- 在远程服务器上执行自定义 Shell 命令。
- 在 Arch 系统上通过 `paru` 命令更新系统及软件包。

## 功能列表
1. **验证 SSH 连接**：检查配置的 SSH 主机是否可用。
2. **执行 Shell 命令**：通过机器人发送指定命令到远程主机执行。
3. **更新 Arch 系统**：在远程 Arch Linux 系统上执行 `paru -Syu --noconfirm`，可自动更新系统至最新状态。

## 安装与配置
### 依赖
使用AstrBot的python库安装功能，安装 `paramiko` 库。

### 配置项
在插件运行前，请将以下配置项添加到插件的配置文件中：
- `ssh_host`：远程 SSH 主机地址，默认值为 `127.0.0.1`。
- `ssh_port`：远程 SSH 端口，默认值为 `22`。
- `username`：SSH 登录用户名，默认值为 `root`。
- `password`：SSH 密码（如果使用密码认证时需要设置）。
- `private_key_path`：SSH 私钥路径，默认值为 `~/.ssh/id_rsa`。
- `passphrase`：用于解锁私钥的密码（如果密钥加密）。
- `timeout`：连接超时时间，默认值为 `60 秒`。

## 使用方法
### 1. 验证连接
通过以下命令验证是否可以成功连接到远程服务器：
``` 
shell check
```

### 2. 执行shell命令（暂不支持）
存在安全风险，尚需评估

### 2. 更新 Arch 系统
在 Arch 系统上运行 `paru` 自动更新软件包：
``` 
shell paru
```
