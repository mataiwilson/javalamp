"""Live system stats collector for the server kiosk footer.

Reads system metrics from /proc, /sys, pynvml, and the Docker socket.
All reads are non-blocking and fault-tolerant — if a source is unavailable,
that stat is simply omitted from the output.

Stats are cached and refreshed on a configurable interval (default 2s for
lightweight /proc reads, 60s for the ZFS subprocess).
"""

from __future__ import annotations

import socket
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# pynvml is optional — GPU stats are skipped if not available.
try:
    import warnings

    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", category=FutureWarning)
        import pynvml

    _NVML_AVAILABLE = True
except ImportError:
    _NVML_AVAILABLE = False


@dataclass
class SystemStats:
    """Snapshot of system metrics."""

    uptime_seconds: Optional[float] = None
    cpu_load_1m: Optional[float] = None
    cpu_temp_c: Optional[float] = None
    ram_percent: Optional[float] = None
    gpu_temp_c: Optional[int] = None
    gpu_load_percent: Optional[int] = None
    docker_running: Optional[int] = None
    docker_total: Optional[int] = None
    zfs_pool_state: Optional[str] = None
    zfs_capacity_percent: Optional[int] = None


@dataclass
class _CacheEntry:
    value: object = None
    updated_at: float = 0.0


class SysInfoCollector:
    """Collects and caches system stats from various sources."""

    def __init__(
        self,
        fast_interval: float = 2.0,
        zfs_interval: float = 60.0,
        docker_interval: float = 10.0,
    ) -> None:
        self._fast_interval = fast_interval
        self._zfs_interval = zfs_interval
        self._docker_interval = docker_interval
        self._cache: dict[str, _CacheEntry] = {}
        self._nvml_initialized = False
        self._nvml_handle = None

    def _is_stale(self, key: str, max_age: float) -> bool:
        entry = self._cache.get(key)
        if entry is None:
            return True
        return (time.monotonic() - entry.updated_at) >= max_age

    def _store(self, key: str, value: object) -> None:
        if key not in self._cache:
            self._cache[key] = _CacheEntry()
        self._cache[key].value = value
        self._cache[key].updated_at = time.monotonic()

    def _get(self, key: str) -> object:
        entry = self._cache.get(key)
        return entry.value if entry else None

    # -- /proc readers --------------------------------------------------------

    def _read_uptime(self) -> Optional[float]:
        try:
            text = Path("/proc/uptime").read_text()
            return float(text.split()[0])
        except (OSError, ValueError, IndexError):
            return None

    def _read_cpu_load(self) -> Optional[float]:
        try:
            text = Path("/proc/loadavg").read_text()
            return float(text.split()[0])
        except (OSError, ValueError, IndexError):
            return None

    def _read_cpu_temp(self) -> Optional[float]:
        """Read CPU temp from hwmon. Searches for coretemp or k10temp."""
        try:
            hwmon_base = Path("/sys/class/hwmon")
            if not hwmon_base.exists():
                return None
            for hwmon_dir in hwmon_base.iterdir():
                name_file = hwmon_dir / "name"
                if not name_file.exists():
                    continue
                name = name_file.read_text().strip()
                if name in ("coretemp", "k10temp", "zenpower"):
                    # Read the package/die temp (temp1) or first core temp
                    for label_candidate in ("temp1_input", "temp2_input"):
                        temp_file = hwmon_dir / label_candidate
                        if temp_file.exists():
                            val = int(temp_file.read_text().strip())
                            return val / 1000.0  # millidegrees -> degrees
            return None
        except (OSError, ValueError):
            return None

    def _read_ram(self) -> Optional[float]:
        try:
            info: dict[str, int] = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                parts = line.split()
                if len(parts) >= 2:
                    key = parts[0].rstrip(":")
                    info[key] = int(parts[1])
            total = info.get("MemTotal", 0)
            available = info.get("MemAvailable", 0)
            if total == 0:
                return None
            return ((total - available) / total) * 100.0
        except (OSError, ValueError):
            return None

    # -- NVIDIA GPU -----------------------------------------------------------

    def _init_nvml(self) -> bool:
        if self._nvml_initialized:
            return self._nvml_handle is not None
        self._nvml_initialized = True
        if not _NVML_AVAILABLE:
            return False
        try:
            pynvml.nvmlInit()
            self._nvml_handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            return True
        except Exception:
            self._nvml_handle = None
            return False

    def _read_gpu(self) -> tuple[Optional[int], Optional[int]]:
        """Returns (temp_c, utilization_percent)."""
        if not self._init_nvml():
            return None, None
        try:
            temp = pynvml.nvmlDeviceGetTemperature(
                self._nvml_handle, pynvml.NVML_TEMPERATURE_GPU
            )
            util = pynvml.nvmlDeviceGetUtilizationRates(self._nvml_handle)
            return temp, util.gpu
        except Exception:
            return None, None

    # -- Docker socket --------------------------------------------------------

    def _read_docker(self) -> tuple[Optional[int], Optional[int]]:
        """Query Docker daemon via Unix socket. Returns (running, total)."""
        sock_path = "/var/run/docker.sock"
        if not Path(sock_path).exists():
            return None, None
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(2.0)
            sock.connect(sock_path)
            request = (
                b"GET /containers/json?all=true HTTP/1.1\r\n"
                b"Host: localhost\r\n"
                b"Connection: close\r\n"
                b"\r\n"
            )
            sock.sendall(request)
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
            sock.close()

            # Parse the HTTP response body (JSON array of containers).
            body_start = response.find(b"\r\n\r\n")
            if body_start == -1:
                return None, None
            body = response[body_start + 4:]
            # Handle chunked transfer encoding.
            if b"Transfer-Encoding: chunked" in response[:body_start]:
                body = self._decode_chunked(body)
            import json
            containers = json.loads(body)
            total = len(containers)
            running = sum(1 for c in containers if c.get("State") == "running")
            return running, total
        except Exception:
            return None, None

    @staticmethod
    def _decode_chunked(data: bytes) -> bytes:
        """Decode HTTP chunked transfer encoding."""
        result = b""
        while data:
            # Find the chunk size line.
            crlf = data.find(b"\r\n")
            if crlf == -1:
                break
            size_str = data[:crlf].strip()
            try:
                chunk_size = int(size_str, 16)
            except ValueError:
                break
            if chunk_size == 0:
                break
            start = crlf + 2
            result += data[start : start + chunk_size]
            data = data[start + chunk_size + 2:]  # skip trailing \r\n
        return result

    # -- ZFS ------------------------------------------------------------------

    def _read_zfs_state(self) -> Optional[str]:
        """Read pool health from /proc/spl/kstat/zfs/julia/state."""
        try:
            state_file = Path("/proc/spl/kstat/zfs/julia/state")
            if state_file.exists():
                return state_file.read_text().strip().upper()
            return None
        except OSError:
            return None

    def _read_zfs_capacity(self) -> Optional[int]:
        """Read pool capacity via subprocess (cached for 60s)."""
        import subprocess

        try:
            result = subprocess.run(
                ["zpool", "list", "-Hp", "-o", "cap", "julia"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                return int(result.stdout.strip().rstrip("%"))
            return None
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return None

    # -- public API -----------------------------------------------------------

    def collect(self) -> SystemStats:
        """Collect all stats, using cache where fresh enough."""
        now = time.monotonic()
        stats = SystemStats()

        # Fast stats (every 2s) — /proc and /sys file reads.
        if self._is_stale("fast", self._fast_interval):
            self._store("uptime", self._read_uptime())
            self._store("cpu_load", self._read_cpu_load())
            self._store("cpu_temp", self._read_cpu_temp())
            self._store("ram", self._read_ram())
            gpu_temp, gpu_load = self._read_gpu()
            self._store("gpu_temp", gpu_temp)
            self._store("gpu_load", gpu_load)
            self._store("fast", True)

        # Docker (every 10s).
        if self._is_stale("docker", self._docker_interval):
            running, total = self._read_docker()
            self._store("docker_running", running)
            self._store("docker_total", total)
            self._store("docker", True)

        # ZFS (state from /proc every 2s, capacity every 60s).
        if self._is_stale("zfs_state", self._fast_interval):
            self._store("zfs_state", self._read_zfs_state())
        if self._is_stale("zfs_cap", self._zfs_interval):
            self._store("zfs_cap", self._read_zfs_capacity())

        stats.uptime_seconds = self._get("uptime")
        stats.cpu_load_1m = self._get("cpu_load")
        stats.cpu_temp_c = self._get("cpu_temp")
        stats.ram_percent = self._get("ram")
        stats.gpu_temp_c = self._get("gpu_temp")
        stats.gpu_load_percent = self._get("gpu_load")
        stats.docker_running = self._get("docker_running")
        stats.docker_total = self._get("docker_total")
        stats.zfs_pool_state = self._get("zfs_state")
        stats.zfs_capacity_percent = self._get("zfs_cap")

        return stats

    def format_footer(self, stats: SystemStats) -> str:
        """Format stats into a compact single-line string."""
        parts: list[str] = []

        # Uptime.
        if stats.uptime_seconds is not None:
            days = int(stats.uptime_seconds // 86400)
            hours = int((stats.uptime_seconds % 86400) // 3600)
            if days > 0:
                parts.append(f"▲ {days}d {hours}h")
            else:
                mins = int((stats.uptime_seconds % 3600) // 60)
                parts.append(f"▲ {hours}h {mins}m")

        # CPU.
        cpu_parts: list[str] = []
        if stats.cpu_load_1m is not None:
            cpu_parts.append(f"{stats.cpu_load_1m:.1f}")
        if stats.cpu_temp_c is not None:
            cpu_parts.append(f"{stats.cpu_temp_c:.0f}°C")
        if cpu_parts:
            parts.append(f"CPU {' '.join(cpu_parts)}")

        # GPU.
        gpu_parts: list[str] = []
        if stats.gpu_load_percent is not None:
            gpu_parts.append(f"{stats.gpu_load_percent}%")
        if stats.gpu_temp_c is not None:
            gpu_parts.append(f"{stats.gpu_temp_c}°C")
        if gpu_parts:
            parts.append(f"GPU {' '.join(gpu_parts)}")

        # RAM.
        if stats.ram_percent is not None:
            parts.append(f"RAM {stats.ram_percent:.0f}%")

        # Docker.
        if stats.docker_running is not None and stats.docker_total is not None:
            parts.append(f"🐳 {stats.docker_running}/{stats.docker_total}")

        # ZFS.
        zfs_parts: list[str] = []
        if stats.zfs_capacity_percent is not None:
            zfs_parts.append(f"{stats.zfs_capacity_percent}%")
        if stats.zfs_pool_state is not None:
            state = stats.zfs_pool_state
            # Shorten ONLINE to OK for space.
            if state == "ONLINE":
                state = "OK"
            zfs_parts.append(state)
        if zfs_parts:
            parts.append(f"ZFS {' '.join(zfs_parts)}")

        return " │ ".join(parts)

    def shutdown(self) -> None:
        """Clean up resources."""
        if self._nvml_initialized and _NVML_AVAILABLE:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
