# ShellExecutor 插件

## 概述

`ShellExecutor` 是一个基于 Astrbot 平台开发的插件，用于通过 SSH 执行远程 Shell 命令。本插件支持以下功能：

- 管理 SSH 连接：支持密码认证和密钥认证。
- 执行远程 Shell 命令，支持基础系统管理、软件包更新和服务操作。
- 提供 Docker 管理功能，如拉取镜像、启动/停止容器、查看日志等。
- 在 Arch 系统上通过 `paru` 命令更新系统及软件包。
- 使用 `cpupower`、`inxi` 等工具查询系统状态。
- 支持基于 `systemctl` 的服务管理和系统重启功能。

## 功能列表

1. **验证 SSH 连接**：检查配置的远程 SSH 主机是否可用。
2. **执行 Shell 命令**：
    - 支持在远程主机上运行自定义命令。
    - 基于工具（如 `paru`、`inxi`）查看和管理系统状态。
3. **Docker 容器管理**：
    - 启动和停止 Docker 容器。
    - 删除容器、拉取镜像、查看容器日志。
    - 列出运行中的容器。
4. **系统服务管理（基于 systemctl）**：
    - 启动、停止、启用、禁用服务。
    - 查看服务状态或最近的日志。
5. **系统更新与特定功能**：
    - 远程执行重启或切换系统等命令。
    - 提供针对 Arch Linux 的系统更新功能。

## 安装与配置

### 依赖

本插件依赖 `paramiko` 实现 SSH 连接功能。在 AstrBot 安装环境中可通过如下方式安装依赖：

```bash
pip install paramiko
```

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

### 1. SSH 验证连接

通过以下命令验证是否可以成功连接到远程服务器：

``` 
shell check
```

### 2. 系统更新命令（针对 Arch 系统）

在 Arch 系统上运行 `paru` 命令更新软件包：

``` 
shell paru
```

### 3. 系统状态查询命令

支持以下查询命令：

- **概览系统状态**：
  ``` 
  shell inxi
  ```
- **查询完整系统状态**：
  ``` 
  shell inxi-full
  ```
- **查看 NVIDIA 显卡状态**：
  ``` 
  shell nvidia-smi
  ```
- **查询 CPU 状态**：
  ``` 
  shell cpupower
  ```

### 4. 系统服务管理命令 (基于 `systemctl`)

支持以下操作：

- **启动服务**：
  ``` 
  shell systemctl start <服务名>
  ```
- **停止服务**：
  ``` 
  shell systemctl stop <服务名>
  ```
- **查看服务状态**：
  ```
  shell systemctl status <服务名>
  ```
- **启用服务**：
  ``` 
  shell systemctl enable <服务名>
  ```
- **禁用服务**：
  ``` 
  shell systemctl disable <服务名>
  ```
- **查看服务日志**：
  ``` 
  shell systemctl logs <服务名>
  ```

### 5. Docker 容器管理命令

支持以下操作：

- **列出运行中的容器**：
  ``` 
  shell docker ps
  ```
- **查看容器的日志**：
  ``` 
  shell docker logs <容器名>
  ```
- **启动容器**：
  ``` 
  shell docker start <容器名>
  ```
- **停止容器**：
  ``` 
  shell docker stop <容器名>
  ```
- **删除容器**：
  ``` 
  shell docker rm <容器名>
  ```
- **运行新容器**：
  ``` 
  shell docker run <镜像名> [选项1] [选项2] ...
  ```
- **拉取镜像**：
  ``` 
  shell docker pull <镜像名>
  ```

### 6. 系统维护命令

- **重启系统**：
  ``` 
  shell reboot
  ```
- **切换到 Windows 系统**：
  ``` 
  shell rewin
  ```
