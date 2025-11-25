import html
import os
import re
import shlex
from datetime import datetime

import paramiko  # 依赖 Paramiko 实现 SSH 功能

from astrbot.api.all import *
from astrbot.api.event.filter import *


@register("shell_executor", "buding", "用于远程shell命令执行的插件", "1.0.2",
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
        self.fetch_command = self.config.get("status_fetch_command", "neofetch --stdout")

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

    def _exec(self, client: paramiko.SSHClient, cmd: str):
        """在已经建立的 SSH 连接上执行命令并返回输出"""
        stdin, stdout, stderr = client.exec_command(cmd, timeout=self.timeout)
        output = stdout.read().decode(errors="ignore").strip()
        error = stderr.read().decode(errors="ignore").strip()
        return output, error

    def _safe_run(self, client: paramiko.SSHClient, cmd: str) -> str:
        """执行命令，记录错误但不中断收集流程"""
        try:
            output, error = self._exec(client, cmd)
            if error:
                logger.warning(f"[命令警告] {cmd}: {error}")
            return output
        except Exception as e:
            logger.error(f"[命令失败] {cmd}: {e}")
            return ""

    def _parse_cpu_usage(self, top_line: str) -> dict | None:
        """从 top 输出中提取 CPU 使用率及分布"""
        if not top_line:
            return None

        metrics: dict[str, float] = {}
        for val, label in re.findall(r"([\d.]+)\s*%?\s*([a-zA-Z]+)", top_line):
            try:
                metrics[label.lower()] = float(val)
            except ValueError:
                continue

        if not metrics:
            return None

        idle = metrics.get("id") or metrics.get("idle")

        def r(v: float | None) -> float | None:
            return round(v, 1) if v is not None else None

        total = r(100 - idle) if idle is not None else None
        return {
            "total": total,
            "user": r(metrics.get("us") or metrics.get("user")),
            "system": r(metrics.get("sy") or metrics.get("sys")),
            "iowait": r(metrics.get("wa")),
            "idle": r(idle),
        }

    def _parse_mem_speed_value(self, text: str) -> float | None:
        """将带单位的频率字符串转换为 MT/s"""
        if not text:
            return None
        match = re.search(r"([\d.]+)\s*([A-Za-z/]+)?", text)
        if not match:
            return None
        try:
            num = float(match.group(1))
        except ValueError:
            return None
        unit = (match.group(2) or "").lower()
        if "mt" in unit:
            factor = 1
        elif "ghz" in unit:
            factor = 2000  # GHz -> MHz -> MT/s (x2)
        elif "mhz" in unit:
            factor = 2    # MHz -> MT/s (x2)
        else:
            factor = 2    # 无单位时按 MHz -> MT/s
        return num * factor

    def _get_memory_speed(self, client: paramiko.SSHClient) -> str | None:
        """尝试获取预设/配置的内存速度（MT/s），主要依赖 dmidecode"""
        dmidecode_cmds = [
            r"sudo -n dmidecode -t memory 2>/dev/null | awk -F: '/Configured Memory Speed|Configured Clock Speed|Speed/ {gsub(/^[ \t]+/,\"\",$2); if($2!=\"Unknown\" && $2!=\"0 MT\\/s\" && $2!=\"0 MHz\" && $2!=\"0\") print $1 \":\" $2}'",
            r"PATH=$PATH:/usr/sbin:/sbin dmidecode -t memory 2>/dev/null | awk -F: '/Configured Memory Speed|Configured Clock Speed|Speed/ {gsub(/^[ \t]+/,\"\",$2); if($2!=\"Unknown\" && $2!=\"0 MT\\/s\" && $2!=\"0 MHz\" && $2!=\"0\") print $1 \":\" $2}'",
        ]

        def best_from_dmidecode(cmds: list[str]) -> float | None:
            configured_best = None
            current_best = None
            for cmd in cmds:
                out = (self._safe_run(client, cmd) or "").strip()
                if not out:
                    continue
                for line in out.splitlines():
                    if ":" not in line:
                        continue
                    key, val = line.split(":", 1)
                    parsed = self._parse_mem_speed_value(val)
                    if parsed is None:
                        continue
                    key_lower = key.lower()
                    if "configured" in key_lower:
                        if configured_best is None or parsed > configured_best:
                            configured_best = parsed
                    else:
                        if current_best is None or parsed > current_best:
                            current_best = parsed
            return configured_best or current_best

        best_mt = best_from_dmidecode(dmidecode_cmds)
        if best_mt:
            return f"{int(round(best_mt))} MT/s"

        # 兜底尝试 lshw
        lshw_cmds = [
            r"sudo -n lshw -C memory 2>/dev/null | awk '/clock/ {print $2 $3}'",
            r"PATH=$PATH:/usr/sbin:/sbin lshw -C memory 2>/dev/null | awk '/clock/ {print $2 $3}'",
        ]
        for cmd in lshw_cmds:
            out = (self._safe_run(client, cmd) or "").strip()
            if not out:
                continue
            for line in out.splitlines():
                val = self._parse_mem_speed_value(line)
                if val:
                    return f"{int(round(val))} MT/s"
        return None

    def _ansi_to_html(self, text: str) -> str:
        """将 ANSI 颜色序列转换为简单的 HTML span 样式"""
        if not text:
            return ""

        ansi_re = re.compile(r"\x1b\[([\d;]*)m")
        color_map = {
            30: "#111827", 31: "#ef4444", 32: "#22c55e", 33: "#eab308",
            34: "#3b82f6", 35: "#a855f7", 36: "#06b6d4", 37: "#f3f4f6",
            90: "#6b7280", 91: "#f87171", 92: "#86efac", 93: "#fcd34d",
            94: "#93c5fd", 95: "#d8b4fe", 96: "#67e8f9", 97: "#ffffff",
        }

        def color_for(code: int) -> str | None:
            if 30 <= code <= 37 or 90 <= code <= 97:
                return color_map.get(code)
            if 40 <= code <= 47:
                return color_map.get(code - 10)
            if 100 <= code <= 107:
                return color_map.get(code - 60)
            return None

        state = {"fg": None, "bg": None, "bold": False, "dim": False}
        open_style = None
        out_parts = []
        last = 0

        def style_to_str(s: dict) -> str:
            parts = []
            if s["fg"]:
                parts.append(f"color:{s['fg']}")
            if s["bg"]:
                parts.append(f"background:{s['bg']}")
            if s["bold"]:
                parts.append("font-weight:700")
            if s["dim"]:
                parts.append("opacity:0.85")
            return ";".join(parts)

        for match in ansi_re.finditer(text):
            out_parts.append(html.escape(text[last:match.start()]))
            codes_raw = match.group(1)
            codes = [int(c) for c in codes_raw.split(";") if c] if codes_raw else [0]
            for code in codes:
                if code == 0:
                    state = {"fg": None, "bg": None, "bold": False, "dim": False}
                elif code == 1:
                    state["bold"] = True
                elif code == 2:
                    state["dim"] = True
                elif code == 22:
                    state["bold"] = False
                    state["dim"] = False
                elif code == 39:
                    state["fg"] = None
                elif code == 49:
                    state["bg"] = None
                else:
                    clr = color_for(code)
                    if clr:
                        if 30 <= code <= 37 or 90 <= code <= 97:
                            state["fg"] = clr
                        else:
                            state["bg"] = clr
            style = style_to_str(state)
            if style != open_style:
                if open_style:
                    out_parts.append("</span>")
                if style:
                    out_parts.append(f"<span style=\"{style}\">")
                open_style = style
            last = match.end()

        out_parts.append(html.escape(text[last:]))
        if open_style:
            out_parts.append("</span>")
        return "".join(out_parts)


    def _collect_remote_status(self) -> dict:
        """
        收集远程主机的基础状态信息，供图片渲染使用。
        尽量在单个 SSH 连接中完成，以减少握手开销。
        """
        client = self.connect_client()
        status = {}
        try:
            status["host"] = self.ssh_host
            status["hostname"] = self._safe_run(client, "hostname") or self.ssh_host
            status["os"] = self._safe_run(
                client,
                '. /etc/os-release 2>/dev/null && echo "$NAME $VERSION" || uname -sr',
            )
            status["kernel"] = self._safe_run(client, "uname -sr")
            status["uptime"] = self._safe_run(client, "uptime -p").replace("up ", "")
            status["load_avg"] = self._safe_run(
                client, "cat /proc/loadavg | awk '{print $1\" \" $2\" \" $3}'"
            )

            cpu_model = self._safe_run(
                client, "grep 'model name' /proc/cpuinfo | head -n 1 | cut -d: -f2"
            )
            status["cpu_model"] = cpu_model.strip() if cpu_model else "Unknown CPU"
            cpu_freq = self._safe_run(
                client, "awk '/cpu MHz/ {print $4; exit}' /proc/cpuinfo"
            )
            cpu_freq_max = self._safe_run(
                client, "lscpu 2>/dev/null | awk -F: '/CPU max MHz/ {gsub(/^[ \\t]+/, \"\", $2); print $2; exit}'"
            )
            status["cpu_freq"] = cpu_freq.strip() if cpu_freq else None
            status["cpu_freq_max"] = cpu_freq_max.strip() if cpu_freq_max else None
            cpu_line = self._safe_run(client, "LANG=C top -bn1 | grep \"Cpu(s)\"")
            cpu_usage_detail = self._parse_cpu_usage(cpu_line)
            status["cpu_usage_detail"] = cpu_usage_detail
            status["cpu_usage"] = (
                cpu_usage_detail.get("total") if isinstance(cpu_usage_detail, dict) else None
            )
            status["mem_speed"] = self._get_memory_speed(client)

            mem_output = self._safe_run(client, "LANG=C free -m")
            mem_total = mem_used = swap_total = swap_used = None
            if mem_output:
                for line in mem_output.splitlines():
                    if line.lower().startswith("mem:"):
                        parts = line.split()
                        if len(parts) >= 3:
                            try:
                                mem_total = int(parts[1])
                                mem_used = int(parts[2])
                            except ValueError:
                                logger.warning(f"[解析内存失败] free 输出: {line}")
                    if line.lower().startswith("swap:"):
                        parts = line.split()
                        if len(parts) >= 3:
                            try:
                                swap_total = int(parts[1])
                                swap_used = int(parts[2])
                            except ValueError:
                                logger.warning(f"[解析 Swap 失败] free 输出: {line}")
            mem_free = mem_total - mem_used if mem_total is not None and mem_used is not None else None
            status["mem_total"] = mem_total
            status["mem_used"] = mem_used
            status["mem_free"] = mem_free
            status["swap_total"] = swap_total
            status["swap_used"] = swap_used
            if swap_total is None and not status.get("swap_used"):
                swap_info = self._safe_run(client, "cat /proc/swaps 2>/dev/null | tail -n +2 | awk '{s+=$3; u+=$4} END {print s, u}'")
                if swap_info:
                    try:
                        size_kb, used_kb = [int(x) for x in swap_info.split()[:2]]
                        status["swap_total"] = round(size_kb / 1024)
                        status["swap_used"] = round(used_kb / 1024)
                    except (ValueError, IndexError):
                        pass
            if mem_total and mem_total > 0 and mem_used is not None:
                status["mem_percent"] = round(mem_used / mem_total * 100, 1)

            def _size_to_mb(val: str) -> float | None:
                match = re.match(r"([\d.]+)\s*([KMGTP]?)(i?B)?", val, re.IGNORECASE)
                if not match:
                    return None
                num, unit, _ = match.groups()
                try:
                    num = float(num)
                except ValueError:
                    return None
                unit = unit.upper()
                factor = {
                    "": 1 / 1024,
                    "K": 1 / 1024,
                    "M": 1,
                    "G": 1024,
                    "T": 1024 * 1024,
                    "P": 1024 * 1024 * 1024,
                }.get(unit, None)
                return num * factor if factor is not None else None

            df_output = self._safe_run(
                client,
                "df -h --output=target,used,size,pcent -x tmpfs -x devtmpfs | tail -n +2 | head -n 6",
            )
            disks = []
            for line in df_output.splitlines():
                parts = line.split()
                if len(parts) == 4:
                    mount, used, size, percent = parts
                    total_mb = _size_to_mb(size)
                    if total_mb is not None and total_mb < 100:
                        continue
                    try:
                        percent_num = int(re.sub(r"[^0-9]", "", percent) or 0)
                    except ValueError:
                        percent_num = 0
                    disks.append(
                        {
                            "mount": mount,
                            "used": used,
                            "size": size,
                            "percent": percent_num,
                        }
                    )
            status["disks"] = disks

            gpu_output = self._safe_run(
                client,
                "nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu,clocks.gr,clocks.mem --format=csv,noheader",
            )
            gpus = []
            for line in gpu_output.splitlines():
                fields = [f.strip() for f in line.split(",")]
                if len(fields) >= 7:
                    def num(val: str) -> str:
                        return re.sub(r"[^0-9.]", "", val)

                    gpus.append(
                        {
                            "name": fields[0],
                            "mem_used": num(fields[1]),
                            "mem_total": num(fields[2]),
                            "util": num(fields[3]),
                            "temp": num(fields[4]),
                            "clock_core": num(fields[5]),
                            "clock_mem": num(fields[6]),
                        }
                    )
            status["gpus"] = gpus

            status["timestamp"] = self._safe_run(
                client, "date '+%Y-%m-%d %H:%M:%S %Z'"
            ) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            status["summary_text"] = self._build_summary_text(status)
            return status
        finally:
            client.close()

    def _build_summary_text(self, status: dict) -> str:
        """构建用于降级返回的纯文本摘要"""
        parts = [
            f"主机: {status.get('hostname', self.ssh_host)} ({status.get('host', self.ssh_host)})",
            f"系统: {status.get('os') or status.get('kernel')}",
            f"运行: {status.get('uptime', '-')}",
        ]
        cpu_line = status.get("cpu_usage")
        if cpu_line is not None:
            parts.append(f"CPU: {status.get('cpu_model', '-')}, 负载 {cpu_line}%")
        if status.get("mem_total") and status.get("mem_used") is not None:
            parts.append(
                f"内存: {status['mem_used']} / {status['mem_total']} MiB ({status.get('mem_percent','-')}%)"
            )
        if status.get("load_avg"):
            parts.append(f"平均负载: {status['load_avg']}")
        return "\n".join(parts)

    def _build_status_html(self, status: dict) -> str:
        """使用简单的 HTML/CSS 将状态渲染为图片"""
        def esc(val):
            return html.escape(str(val)) if val is not None else "-"

        mem_total = status.get("mem_total")
        mem_used = status.get("mem_used")
        mem_percent = status.get("mem_percent")
        mem_free = status.get("mem_free")
        mem_speed = status.get("mem_speed")
        mem_line = "-"
        mem_free_line = "-"
        if mem_total and mem_used is not None:
            mem_line = f"{mem_used} / {mem_total} MiB"
            if mem_free is not None:
                mem_free_line = f"{mem_free} MiB 可用"
        mem_speed_line = mem_speed or "-"
        load_avg = esc(status.get("load_avg", "-"))
        disks_html = ""
        for disk in status.get("disks", []):
            percent = disk.get("percent", 0)
            disks_html += f"""
            <div class="disk-row">
                <div class="disk-mount" title="{esc(disk.get("mount"))}">{esc(disk.get("mount"))}</div>
                <div class="disk-usage" title="{esc(disk.get("used"))} / {esc(disk.get("size"))}">{esc(disk.get("used"))} / {esc(disk.get("size"))}</div>
                <div class="bar"><span style="width:{percent}%"></span></div>
                <div class="disk-percent">{percent}%</div>
            </div>
            """
        if not disks_html:
            disks_html = "<div class='disk-row muted'>未获取到磁盘信息</div>"

        gpus_html = ""
        for gpu in status.get("gpus", []):
            mem_used = gpu.get("mem_used")
            mem_total = gpu.get("mem_total")
            mem_percent = "-"
            try:
                used_val = float(mem_used)
                total_val = float(mem_total)
                if total_val > 0:
                    mem_percent = round(used_val / total_val * 100)
            except (TypeError, ValueError):
                pass

            util_percent = "-"
            try:
                util_percent = round(float(gpu.get("util")))
            except (TypeError, ValueError):
                pass

            mem_display = f"{esc(mem_used)} / {esc(mem_total)} MiB"
            util_display = f"{esc(gpu.get('util'))}%"
            core_clock = gpu.get("clock_core")
            mem_clock = gpu.get("clock_mem")
            core_display = f"{esc(core_clock)} MHz" if core_clock else "-"
            mem_clock_display = f"{esc(mem_clock)} MHz" if mem_clock else "-"
            temp_display = f"{esc(gpu.get('temp'))}℃" if gpu.get("temp") else "-"
            gpus_html += f"""
            <div class="gpu-row">
                <div class="gpu-head">
                    <div class="gpu-name">{esc(gpu.get("name"))}</div>
                    <div class="gpu-meta">温度 {temp_display}</div>
                </div>
                <div class="gpu-meta small">核心频率 {core_display} · 显存频率 {mem_clock_display}</div>
                <div class="gpu-bar">
                    <div class="gpu-label">显存</div>
                    <div class="bar"><span style="width:{mem_percent if mem_percent != '-' else 0}%"></span></div>
                    <div class="gpu-value">{mem_display}{f' ({mem_percent}%)' if mem_percent != '-' else ''}</div>
                </div>
                <div class="gpu-bar">
                    <div class="gpu-label">负载</div>
                    <div class="bar"><span style="width:{util_percent if util_percent != '-' else 0}%"></span></div>
                    <div class="gpu-value">{util_display}</div>
                </div>
            </div>
            """
        if not gpus_html:
            gpus_html = "<div class='gpu-row muted'>GPU 信息不可用或无显卡</div>"

        cpu_usage = status.get("cpu_usage")
        cpu_usage_display = f"{cpu_usage}%" if cpu_usage is not None else "-"
        mem_percent_display = f"{mem_percent}%" if mem_percent is not None else "-"
        cpu_freq = status.get("cpu_freq")
        cpu_freq_max = status.get("cpu_freq_max")
        cpu_freq_line = ""
        if cpu_freq:
            freq_val = cpu_freq
            try:
                freq_val_num = float(cpu_freq)
                freq_val = f"{round(freq_val_num, 1)}"
            except (TypeError, ValueError):
                pass
            max_part = ""
            if cpu_freq_max:
                try:
                    max_val_num = float(cpu_freq_max)
                    max_part = f" / {round(max_val_num, 1)}"
                except (TypeError, ValueError):
                    max_part = f" / {cpu_freq_max}"
            cpu_freq_line = f"频率: {freq_val}{max_part} MHz"

        return f"""
        <html>
        <head>
            <meta charset="UTF-8" />
            <style>
                * {{ box-sizing: border-box; }}
                body {{
                    margin: 0;
                    padding: 12px 14px;
                    min-height: 100vh;
                    font-family: "JetBrains Mono","SFMono-Regular",Menlo,Consolas,"Liberation Mono",monospace;
                    background: radial-gradient(circle at 18% 18%, #0f172a 0, #0f2747 35%, #0b3c66 70%, #0a2551 100%);
                    color: #eef3fb;
                    display: flex;
                    justify-content: center;
                    align-items: center;
                }}
                .card {{
                    width: min(1100px, 100%);
                    margin: 0 auto;
                    background: rgba(15, 38, 72, 0.85);
                    border: 1px solid rgba(255, 255, 255, 0.14);
                    border-radius: 16px;
                    box-shadow: 0 18px 52px rgba(0, 0, 0, 0.55);
                    padding: 16px 18px 18px 18px;
                    backdrop-filter: blur(12px);
                }}
                .header {{
                    display: flex;
                    justify-content: space-between;
                    align-items: flex-start;
                    border-bottom: 1px solid rgba(255, 255, 255, 0.14);
                    padding-bottom: 14px;
                    margin-bottom: 14px;
                }}
                .title-block {{
                    max-width: 70%;
                }}
                .title {{
                    font-size: 24px;
                    font-weight: 700;
                    letter-spacing: 0.5px;
                    color: #f9fbff;
                }}
                .subtitle {{
                    color: #b7c8e6;
                    margin-top: 6px;
                    font-size: 14px;
                }}
                .meta {{
                    text-align: right;
                    font-size: 12px;
                    color: #c1d4ef;
                }}
                .section {{
                    margin-top: 12px;
                    display: grid;
                    gap: 12px;
                }}
                .triple-grid {{
                    display: grid;
                    grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                    gap: 12px;
                }}
                .panel {{
                    background: rgba(255, 255, 255, 0.06);
                    border: 1px solid rgba(255, 255, 255, 0.12);
                    border-radius: 12px;
                    padding: 12px 14px;
                }}
                .panel h3 {{
                    margin: 0 0 8px 0;
                    font-size: 14px;
                    color: #d9e5f9;
                    letter-spacing: 0.2px;
                }}
                .value-row {{
                    display: flex;
                    align-items: baseline;
                    gap: 8px;
                    flex-wrap: wrap;
                }}
                .value {{
                    font-size: 20px;
                    font-weight: 700;
                    color: #f8fafc;
                }}
                .pill {{
                    padding: 2px 8px;
                    background: rgba(255, 255, 255, 0.14);
                    border: 1px solid rgba(255, 255, 255, 0.16);
                    border-radius: 999px;
                    color: #e7edfa;
                    font-size: 12px;
                    line-height: 1.4;
                }}
                .bar-row {{
                    display: flex;
                    align-items: center;
                    gap: 12px;
                    margin-top: 8px;
                }}
                .bar-value {{
                    text-align: right;
                    color: #e5e7eb;
                    font-variant-numeric: tabular-nums;
                    min-width: 160px;
                }}
                .muted {{
                    color: #a9bad4;
                }}
                .disk-row {{
                    display: grid;
                    grid-template-columns: minmax(90px, 180px) minmax(150px, 220px) 1fr 70px;
                    align-items: center;
                    gap: 10px;
                    font-size: 13px;
                    margin-bottom: 6px;
                }}
                .gpu-row {{
                    display: flex;
                    flex-direction: column;
                    gap: 8px;
                    font-size: 13px;
                    margin-bottom: 8px;
                }}
                .bar {{
                    width: 100%;
                    height: 10px;
                    background: rgba(255, 255, 255, 0.16);
                    border-radius: 4px;
                    overflow: hidden;
                }}
                .bar span {{
                    display: block;
                    height: 100%;
                    background: linear-gradient(90deg, #22d3ee, #60a5fa);
                }}
                .disk-mount {{
                    min-width: 80px;
                    font-weight: 600;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }}
                .disk-usage {{
                    min-width: 150px;
                    color: #cbd5e1;
                    white-space: nowrap;
                    overflow: hidden;
                    text-overflow: ellipsis;
                }}
                .disk-percent {{
                    min-width: 48px;
                    text-align: right;
                    color: #f8fafc;
                    font-weight: 600;
                }}
                .gpu-name {{
                    font-weight: 600;
                    color: #e0f2fe;
                }}
                .gpu-meta {{
                    color: #cbd5e1;
                }}
                .gpu-meta.small {{
                    color: #9ca3af;
                }}
                .gpu-head {{
                    width: 100%;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                    gap: 8px;
                }}
                .gpu-bar {{
                    width: 100%;
                    display: grid;
                    grid-template-columns: 64px 1fr 130px;
                    align-items: center;
                    gap: 10px;
                }}
                .gpu-label {{
                    width: 64px;
                    color: #9ca3af;
                }}
                .gpu-value {{
                    width: 130px;
                    text-align: right;
                    color: #e5e7eb;
                    font-variant-numeric: tabular-nums;
                }}
                @media (max-width: 780px) {{
                    .disk-row {{
                        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                    }}
                    .gpu-bar {{
                        grid-template-columns: 80px 1fr;
                    }}
                    .gpu-value {{
                        width: auto;
                        justify-self: end;
                    }}
                    .bar-row {{
                        flex-direction: column;
                        align-items: flex-start;
                    }}
                    .bar-value {{
                        min-width: 0;
                        width: 100%;
                        text-align: left;
                    }}
                }}
                .fetch-panel pre {{
                    margin: 8px 0 0 0;
                    font-size: 13px;
                    line-height: 1.1;
                    white-space: pre;
                    overflow: auto;
                    color: #e5e7eb;
                    background: rgba(255, 255, 255, 0.02);
                    border: 1px solid rgba(255, 255, 255, 0.05);
                    border-radius: 10px;
                    padding: 10px;
                }}
                .fetch-header {{
                    display: flex;
                    justify-content: space-between;
                    align-items: baseline;
                    gap: 8px;
                }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="header">
                    <div class="title-block">
                        <div class="title">{esc(status.get("hostname"))}</div>
                        <div class="subtitle">{esc(status.get("os"))}</div>
                    </div>
                    <div class="meta">
                        <div>连接: {esc(status.get("host"))}:{esc(self.ssh_port)}</div>
                        <div>时间: {esc(status.get("timestamp"))}</div>
                    </div>
                </div>
                <div class="section triple-grid">
                    <div class="panel">
                        <h3>CPU</h3>
                        <div class="value-row">
                            <div class="value">{cpu_usage_display}</div>
                            <div class="pill">总占用</div>
                        </div>
                        <div class="muted" style="margin-top:4px;">{esc(status.get("cpu_model"))}</div>
                        <div class="muted" style="margin-top:4px;">{cpu_freq_line or '频率: 未获取'}</div>
                        <div class="muted" style="margin-top:4px;">平均负载: {load_avg}</div>
                    </div>
                    <div class="panel">
                        <h3>内存</h3>
                        <div class="value-row">
                            <div class="value">{mem_percent_display}</div>
                            <div class="pill">内存占用</div>
                        </div>
                        <div class="bar-row">
                            <div class="bar"><span style="width:{mem_percent if mem_percent is not None else 0}%"></span></div>
                            <div class="bar-value">{mem_line}</div>
                        </div>
                        <div class="muted" style="margin-top:4px;">{mem_free_line}</div>
                        <div class="muted" style="margin-top:4px;">内存频率: {esc(mem_speed_line)}</div>
                    </div>
                    <div class="panel">
                        <h3>运行时间</h3>
                        <div class="value">{esc(status.get("uptime", "-"))}</div>
                        <div class="muted">内核 {esc(status.get("kernel"))}</div>
                    </div>
                </div>
                <div class="section">
                    <div class="panel">
                        <h3>GPU</h3>
                        {gpus_html}
                    </div>
                </div>
                <div class="section">
                    <div class="panel">
                        <h3>磁盘</h3>
                        {disks_html}
                    </div>
                </div>
            </div>
        </body>
        </html>
        """

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
            "- `/shell status`：生成远程服务器运行状态图片。",
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
    @shell.command("status")
    async def render_status(self, event: AstrMessageEvent):
        """
        以图片展示远程服务器状态。
        """
        try:
            status = self._collect_remote_status()
        except Exception as e:
            logger.error(f"收集远程状态失败: {e}")
            yield event.plain_result("❌ 获取远程状态失败，请检查 SSH 配置或日志。")
            return

        html_doc = self._build_status_html(status)
        try:
            options = {
                "type": "jpeg",
                "quality": 90,
                "full_page": True,
                "device_scale_factor_level": "ultra",
            }
            image_url = await self.html_render(html_doc, {}, return_url=True, options=options)
            yield event.image_result(image_url)
        except Exception as e:
            logger.error(f"渲染状态图片失败: {e}")
            fallback = status.get("summary_text", "渲染失败，请检查后台日志。")
            yield event.plain_result(fallback)

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
    @shell.command("ip")
    async def ip(self, event: AstrMessageEvent):
        """
        查看网卡信息。
        """
        cmd = "ip a"

        async for result in self._run_command(event, cmd):
            yield result

    @permission_type(PermissionType.ADMIN)
    @shell.command("lspci")
    async def lspci(self, event: AstrMessageEvent):
        """
        查看网卡信息。
        """
        cmd = "lspci"

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
    async def docker_run(self, event: AstrMessageEvent, opt1: str, opt2: str = None, opt3: str = None, opt4: str = None, opt5: str = None):
        """
        运行一个新的 Docker 容器。
        """
        options = [shlex.quote(opt) for opt in [opt1, opt2, opt3, opt4, opt5] if opt is not None]
        cmd = f"docker run {' '.join(options)}"
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
