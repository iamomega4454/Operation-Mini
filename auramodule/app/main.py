
import asyncio
import logging
import os
import platform
import select
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO, Any, Dict, List, Optional

import psutil
from dotenv import load_dotenv

load_dotenv()

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

from app.services.camera import camera_service
from app.services.discovery import discovery_service
from app.services.backend_client import init_backend_client
from app.services.microphone import continuous_mic
from app.services.conversation import summarize_conversation
from app.ws_server import start_server, shutdown_streams, _get_local_ip
from app.core.config import settings
from app.core.pairing_store import (
    apply_pairing_config_to_settings,
    load_pairing_config,
    normalize_backend_url,
)


GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"


#------This Function resolves module update interval-------
def _get_update_interval_seconds() -> int:
    raw_value = os.getenv("AURAMODULE_UPDATE_CHECK_INTERVAL_SECONDS", "300")
    try:
        interval_seconds = int(raw_value)
    except ValueError:
        interval_seconds = 300
    return max(interval_seconds, 60)


UPDATE_CHECK_INTERVAL = _get_update_interval_seconds()
AUTO_GIT_UPDATE_ENABLED = os.getenv("AURAMODULE_AUTO_UPDATE_ENABLED", "true").lower() == "true"
AUTO_RESTART_ON_UPDATE = os.getenv("AURAMODULE_AUTO_RESTART_ON_UPDATE", "true").lower() == "true"
MODULE_ROOT = Path(__file__).resolve().parents[1]
UPDATE_LOCK_PATH = Path("/tmp/aura_repo_update.lock")

_system_info: Dict[str, Any] = {}
_update_monitor_thread: Optional[threading.Thread] = None
_update_monitor_stop_event = threading.Event()
_update_monitor_lock = threading.Lock()


#------This Function acquires process-level update lock-------
def _acquire_process_update_lock() -> Optional[IO[str]]:
    if fcntl is None:
        return None
    lock_file = open(UPDATE_LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return lock_file
    except OSError:
        lock_file.close()
        return None


#------This Function releases process-level update lock-------
def _release_process_update_lock(lock_file: Optional[IO[str]]) -> None:
    if fcntl is None or lock_file is None:
        return
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
    finally:
        lock_file.close()


#------This Class handles the System Hardware Detection---------
def detect_hardware() -> Dict[str, Any]:
    info = {
        "platform": platform.system(),
        "architecture": platform.machine(),
        "processor": platform.processor(),
        "is_raspberry_pi": False,
        "pi_model": None,
        "cpu_cores": os.cpu_count() or 1,
        "has_gpu": False,
        "gpu_info": None,
    }
    
    if Path("/proc/device-tree/model").exists():
        try:
            with open("/proc/device-tree/model", "r") as f:
                model = f.read().strip()
                if "Raspberry Pi" in model:
                    info["is_raspberry_pi"] = True
                    if "Pi 5" in model:
                        info["pi_model"] = "5"
                    elif "Pi 4" in model:
                        info["pi_model"] = "4"
                    elif "Pi 3" in model:
                        info["pi_model"] = "3"
                    elif "Pi 2" in model:
                        info["pi_model"] = "2"
        except Exception:
            pass
    
    try:
        result = subprocess.run(
            ["vcgencmd", "get_config", "int"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            info["has_gpu"] = True
            info["gpu_info"] = "Broadcom VideoCore"
    except FileNotFoundError:
        pass
    
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            info["has_gpu"] = True
            info["gpu_info"] = result.stdout.strip()
    except FileNotFoundError:
        pass
    
    return info


#------This Function checks system resources---------
def check_system_resources() -> Dict[str, Any]:
    resources = {
        "disk_space_gb": 0,
        "memory_total_gb": 0,
        "memory_available_gb": 0,
        "cpu_usage_percent": 0,
        "ok": True,
    }
    
    try:
        _, _, free = shutil.disk_usage(Path.cwd())
        resources["disk_space_gb"] = round(free / (1024 ** 3), 1)
        resources["ok"] = resources["disk_space_gb"] >= 2
    except Exception:
        pass
    
    try:
        memory_info = psutil.virtual_memory()
        resources["memory_total_gb"] = round(memory_info.total / (1024 ** 3), 1)
        resources["memory_available_gb"] = round(memory_info.available / (1024 ** 3), 1)
    except Exception:
        pass
    
    try:
        resources["cpu_usage_percent"] = round(psutil.cpu_percent(interval=1), 1)
    except Exception:
        pass
    
    return resources


#------This Function checks/installs pip---------
def check_pip():
    print_section("Python Package Manager")
    
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            current_version = result.stdout.strip().split()[1]
            print_status("â—", f"pip installed: {CYAN}{current_version}{RESET}")
            return True
    except Exception as e:
        print_status("â—", f"pip check failed: {e}", YELLOW)
    return False


#------This Function handles the Logging Setup---------
def setup_logging():
    log_level = logging.DEBUG if settings.demo_mode else logging.INFO
    
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    
    
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("zeroconf").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


#------This Function displays banner with system info-------
def show_banner(system_info: Dict[str, Any] = None):
    pi_info = ""
    if system_info and system_info.get("is_raspberry_pi"):
        model = system_info.get("pi_model", "unknown")
        gpu = " + GPU" if system_info.get("has_gpu") else ""
        pi_info = f" [Raspberry Pi {model}{gpu}]"
    
    print(f"""
{CYAN}{BOLD}â•”â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•—
â•‘          A . U . R . A    M O D U L E   2026{pi_info}          â•‘
â•‘                   IoT Device Hub                             â•‘
â•šâ•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•{RESET}
    """)


#------This Function prints status-------
def print_status(icon, text, color=GREEN):
    print(f"  {icon} {color}{text}{RESET}")


#------This Function prints section-------
def print_section(title):
    print(f"\n{BLUE}{BOLD}â”€â”€ {title} â”€â”€{RESET}\n")


#------This Function checks if patient UID is configured---------
def is_configured_patient_uid(patient_uid: str) -> bool:
    normalized = (patient_uid or "").strip()
    return bool(normalized and normalized != "your_patient_uid_here")


#------This Function finds an available service port---------
def resolve_available_service_port(preferred_port: int, max_attempts: int = 30) -> int:
    # Try the requested port first, then scan a small range.
    for offset in range(0, max_attempts + 1):
        candidate_port = preferred_port + offset
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("0.0.0.0", candidate_port))
            return candidate_port
        except OSError:
            continue
        finally:
            sock.close()
    return preferred_port


#------This Function checks whether terminal is interactive---------
def is_interactive_terminal() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


#------This Function gets installed ollama models---------
def get_installed_ollama_models() -> List[str]:
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []

        models: List[str] = []
        for line in result.stdout.splitlines():
            clean_line = line.strip()
            if not clean_line or clean_line.upper().startswith("NAME"):
                continue
            model_name = clean_line.split()[0]
            if model_name and model_name not in models:
                models.append(model_name)
        return models
    except Exception:
        return []


#------This Function prompts user for ollama model---------
def prompt_ollama_model_selection(installed_models: List[str]) -> Optional[str]:
    if not is_interactive_terminal():
        return None

    print_section("Ollama Model Selection")
    if installed_models:
        print_status("â—", "Installed models detected:", CYAN)
        for idx, model in enumerate(installed_models, start=1):
            print(f"  {idx}. {model}")
        print(f"  n. Pull new model from Ollama")
        print(f"  s. Skip for now")
        choice = input("Select model number, 'n', or 's' [s]: ").strip().lower()
        if not choice or choice == "s":
            return None
        if choice.isdigit():
            index = int(choice) - 1
            if 0 <= index < len(installed_models):
                return installed_models[index]
            return None
        if choice != "n":
            return None

    model_to_pull = input(
        f"Enter model to pull from Ollama (example: {settings.ollama_model}): "
    ).strip()
    if not model_to_pull:
        return None

    confirm = input(f"Pull '{model_to_pull}' now? [y/N]: ").strip().lower()
    if confirm != "y":
        return None

    if pull_model_with_progress(model_to_pull):
        return model_to_pull

    return None


#------This Function checks/installs PyAudio----------
def check_pyaudio():
    print_section("Audio Dependencies")
    try:
        import pyaudio
        print_status("â—", f"PyAudio installed")
        return True
    except ImportError:
        pass

    auto_install = os.environ.get("AUTO_INSTALL_DEPS", "false").lower() == "true"
    if not auto_install:
        print_status("â—", "PyAudio not found - auto-install disabled", YELLOW)
        print(f"  {CYAN}â†’{RESET} To enable, run with: AUTO_INSTALL_DEPS=true python -m app.main")
        return False
    
    print(f"  {CYAN}â†’{RESET} Installing PyAudio...")
    
    try:
        if sys.platform == "darwin":
            subprocess.run(["brew", "install", "portaudio"], check=True, timeout=300)
        elif sys.platform == "linux":
            if Path("/etc/arch-release").exists():
                print(f"  {BLUE}â€º{RESET} Detected Arch Linux")
                subprocess.run(["sudo", "pacman", "-S", "--noconfirm", "portaudio"], check=False, timeout=300)
            elif Path("/etc/fedora-release").exists():
                print(f"  {BLUE}â€º{RESET} Detected Fedora")
                subprocess.run(["sudo", "dnf", "install", "-y", "portaudio-devel"], check=False, timeout=300)
            elif Path("/etc/debian_version").exists() or Path("/etc/ubuntu_version").exists():
                print(f"  {BLUE}â€º{RESET} Detected Debian/Ubuntu")
                subprocess.run(["sudo", "apt-get", "install", "-y", "portaudio19-dev"], check=False, timeout=300)
            else:
                print(f"  {BLUE}â€º{RESET} Unknown distro, trying pip...")
        
        subprocess.run([sys.executable, "-m", "pip", "install", "pyaudio"], check=True, timeout=300)
        print_status("â—", "PyAudio installed successfully")
        return True
        
    except Exception as e:
        print_status("â—", f"PyAudio installation failed: {e}", RED)
        print(f"  {RED}!{RESET} Microphone will run in demo mode")
        return False


#------This Function streams ollama pull with progress----------
def stream_ollama_pull(model_name: str, timeout: int = 600) -> bool:
    print(f"  {CYAN}â†’{RESET} Downloading {model_name}...")
    
    try:
        process = subprocess.Popen(
            ["ollama", "pull", model_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        
        total_layers = 0
        downloaded_layers = 0
        start_time = time.time()
        last_update = time.time()
        
        spinner = ['|', '/', '-', '\\']
        spinner_idx = 0
        
        message_counts = {}
        last_message = None
        last_count = 0
        
        while True:
            if time.time() - start_time > timeout:
                print(f"\n  {RED}!{RESET} Download timed out after {timeout}s")
                process.terminate()
                return False
            
            ready = select.select([process.stdout], [], [], 1.0)
            if ready[0]:
                line = process.stdout.readline()
                if not line:
                    break
                line = line.strip()
            else:
                continue
            
            if "pulling manifest" in line.lower():
                msg = "Pulling manifest..."
                if msg != last_message:
                    if last_message and last_count > 1:
                        print(f"  {BLUE}â€º{RESET} {last_message}(x{last_count})")
                    print(f"  {BLUE}â€º{RESET} {msg}")
                    last_message = msg
                    last_count = 1
                else:
                    last_count += 1
            elif "downloading" in line.lower():
                if "layer" in line.lower():
                    if "/" in line:
                        try:
                            parts = line.split("/")
                            for p in parts:
                                if "(" in p and ")" in p:
                                    nums = p.replace("(", "").replace(")", "").split("/")
                                    if len(nums) == 2:
                                        total_layers = max(total_layers, int(nums[1]))
                                        downloaded_layers = int(nums[0])
                        except Exception:
                            pass
                    
                    # downloaded_layers += 1
                    
                    elapsed = time.time() - start_time
                    speed = downloaded_layers / elapsed if elapsed > 0 else 0
                    
                    spinner_idx = (spinner_idx + 1) % 4
                    
                    if total_layers > 0:
                        percent = (downloaded_layers / total_layers) * 100
                        print(f"\r  {spinner[spinner_idx]} Progress: {percent:.1f}% ({downloaded_layers}/{total_layers} layers) - {speed:.1f} layers/s    ", end="", flush=True)
                    else:
                        print(f"\r  {spinner[spinner_idx]} Downloading... {speed:.1f} layers/s    ", end="", flush=True)
                    
                    last_update = time.time()
                    
            elif "verifying" in line.lower():
                msg = "Verifying checksum..."
                if msg != last_message:
                    if last_message and last_count > 1:
                        print(f"  {BLUE}â€º{RESET} {last_message}(x{last_count})")
                    print(f"  {BLUE}â€º{RESET} {msg}")
                    last_message = msg
                    last_count = 1
                else:
                    last_count += 1
            elif "writing" in line.lower():
                msg = "Writing to model storage..."
                if msg != last_message:
                    if last_message and last_count > 1:
                        print(f"  {BLUE}â€º{RESET} {last_message}(x{last_count})")
                    print(f"  {BLUE}â€º{RESET} {msg}")
                    last_message = msg
                    last_count = 1
                else:
                    last_count += 1
        
        if last_message and last_count > 1:
            print(f"  {BLUE}â€º{RESET} {last_message}(x{last_count})")
            
        retcode = process.wait(timeout=timeout)
        print()  
        
        if retcode == 0:
            print_status("â—", f"{model_name} downloaded successfully")
            return True
        return False
        
    except Exception as e:
        print(f"\n  {RED}!{RESET} Error: {e}")
        return False


#------This Function pulls model with progress wrapper----------
def pull_model_with_progress(model_name: str) -> bool:
    return stream_ollama_pull(model_name)


#------This Function updates Ollama model automatically----------
def update_ollama_model(model_name: str) -> bool:
    print(f"  {CYAN}â†’{RESET} Updating {model_name}...")
    
    try:
        process = subprocess.Popen(
            ["ollama", "pull", model_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        
        start_time = time.time()
        for line in process.stdout:
            line = line.strip()
            if "already up to date" in line.lower():
                print_status("â—", f"{model_name} is up to date")
                process.terminate()
                return True
            elif "downloading" in line.lower():
                elapsed = time.time() - start_time
                print(f"\r  {CYAN}â–“{RESET} Downloading... {elapsed:.1f}s    ", end="", flush=True)
        
        process.wait()
        print()
        
        if process.returncode == 0:
            print_status("â—", f"{model_name} updated successfully")
            return True
        return False
        
    except Exception as e:
        print(f"\n  {RED}!{RESET} Update error: {e}")
        return False


#------This Function checks/installs Ollama with auto-update--------
def check_ollama():
    print_section("Ollama Installation")
    auto_install = os.environ.get("AUTO_INSTALL_DEPS", "false").lower() == "true"
    prompt_model = os.environ.get("AURAMODULE_PROMPT_OLLAMA_MODEL", "true").lower() == "true"
    if auto_install:
        check_pip()
    
    try:
        result = subprocess.run(
            ["ollama", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            print_status("â—", f"Ollama installed: {CYAN}{result.stdout.strip()}{RESET}")

            installed_models = get_installed_ollama_models()
            if settings.ollama_model in installed_models:
                print_status("â—", f"{settings.ollama_model} model installed")
                if not auto_install:
                    print_status("â—", "Auto model updates disabled (AUTO_INSTALL_DEPS=false)", YELLOW)
                else:
                    if settings.auto_update_models:
                        print(f"\n  {BLUE}â€º{RESET} Checking for model updates...")
                        if update_ollama_model(settings.ollama_model):
                            print_status("â—", f"{settings.ollama_model} is up to date")
                return True

            print_status(
                "â—",
                f"Configured model '{settings.ollama_model}' is not installed",
                YELLOW,
            )
            if not auto_install:
                if prompt_model:
                    selected_model = prompt_ollama_model_selection(installed_models)
                    if selected_model:
                        settings.ollama_model = selected_model
                        print_status("â—", f"Using model: {CYAN}{settings.ollama_model}{RESET}")
                        return True
                print_status("â—", "No model selected. Orito features may be unavailable", YELLOW)
                return False

            print(f"\n  {BLUE}â€º{RESET} Checking {settings.ollama_model} model...")
            model_result = subprocess.run(
                ["ollama", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            
            model_found = settings.ollama_model.split(":")[0] in model_result.stdout
            
            if model_found:
                print_status("â—", f"{settings.ollama_model} model installed")
                
                if settings.auto_update_models:
                    print(f"\n  {BLUE}â€º{RESET} Checking for model updates...")
                    if update_ollama_model(settings.ollama_model):
                        print_status("â—", f"{settings.ollama_model} is up to date")
            else:
                print_status("â—", f"{settings.ollama_model} model not found", YELLOW)
                print(f"  {CYAN}â†’{RESET} Pulling {settings.ollama_model} model...")
                
                if pull_model_with_progress(settings.ollama_model):
                    print_status("â—", f"{settings.ollama_model} model downloaded successfully")
                else:
                    print_status("â—", "Failed to pull model", RED)
                    return False
            
            return True
            
    except FileNotFoundError:
        pass
    except subprocess.TimeoutExpired:
        print_status("â—", "Ollama check timed out", RED)
        return False
    except Exception as e:
        print_status("â—", f"Error checking Ollama: {e}", RED)
        return False
    
    print_status("â—", "Ollama not installed", YELLOW)
    if not auto_install:
        print_status("â—", "Auto-install disabled (AUTO_INSTALL_DEPS=false)", YELLOW)
        print(f"  {CYAN}â†’{RESET} Install manually or run once with AUTO_INSTALL_DEPS=true")
        return False
    print(f"  {CYAN}â†’{RESET} Installing Ollama...")
    
    max_retries = 3
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            install_cmd = "curl -fsSL https://ollama.com/install.sh | sh"
            install_result = subprocess.run(
                install_cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            
            if install_result.returncode != 0:
                print_status("â—", f"Ollama installation failed", RED)
                print(f"  {RED}!{RESET} {install_result.stderr}")
                retry_count += 1
                if retry_count < max_retries:
                    print(f"  {YELLOW}â†’{RESET} Retrying in 5 seconds... ({retry_count}/{max_retries})")
                    time.sleep(5)
                    continue
                return False
            
            print_status("â—", "Ollama installed successfully")
            
            print(f"\n  {BLUE}â€º{RESET} Pulling {settings.ollama_model} model...")
            if pull_model_with_progress(settings.ollama_model):
                print_status("â—", f"{settings.ollama_model} model downloaded successfully")
            else:
                print_status("â—", "Model pull failed - will retry on first use", YELLOW)
            
            return True
            
        except subprocess.TimeoutExpired:
            print_status("â—", "Ollama installation timed out", RED)
            retry_count += 1
            if retry_count < max_retries:
                print(f"  {YELLOW}â†’{RESET} Retrying in 10 seconds... ({retry_count}/{max_retries})")
                time.sleep(10)
                continue
            return False
        except Exception as e:
            print_status("â—", f"Installation error: {e}", RED)
            retry_count += 1
            if retry_count < max_retries:
                print(f"  {YELLOW}â†’{RESET} Retrying in 5 seconds... ({retry_count}/{max_retries})")
                time.sleep(5)
                continue
            return False
    
    return False


#------This Function checks InsightFace model----------
def check_models() -> bool:
    print_section("ML Models")
    print(f"  {BLUE}â€º{RESET} Checking InsightFace/buffalo_l...")
    
    try:
        from insightface.app import FaceAnalysis
        
        print(f"  {CYAN}â†’{RESET} Initializing buffalo_l model (first run may download weights)...")
        app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=0, det_size=(640, 640))
        print_status("â—", "buffalo_l face recognition model ready")
        return True
        
    except ImportError:
        print_status("â—", "InsightFace not installed", YELLOW)
        auto_install = os.environ.get("AUTO_INSTALL_DEPS", "false").lower() == "true"
        if not auto_install:
            print(f"  {CYAN}â†’{RESET} To enable, run with: AUTO_INSTALL_DEPS=true python -m app.main")
            return False

        print(f"  {CYAN}â†’{RESET} Installing InsightFace and dependencies...")
        
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "insightface", "onnxruntime"],
                check=True,
                timeout=300,
            )
            print_status("â—", "InsightFace installed successfully")
            
            print(f"  {CYAN}â†’{RESET} Initializing buffalo_l model...")
            from insightface.app import FaceAnalysis
            app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
            app.prepare(ctx_id=0, det_size=(640, 640))
            print_status("â—", "buffalo_l face recognition model ready")
            return True
            
        except Exception as e:
            print_status("â—", f"InsightFace installation failed: {e}", RED)
            print(f"  {RED}!{RESET} Face recognition will be disabled")
            return False
        
    except Exception as e:
        print_status("â—", f"Model not ready: {e}", YELLOW)
        
        print(f"  {CYAN}â†’{RESET} Attempting to reinstall and setup...")
        
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "insightface", "onnxruntime"],
                check=True,
                timeout=300,
            )
            print(f"  {CYAN}â†’{RESET} Reinitializing buffalo_l model...")
            from insightface.app import FaceAnalysis
            app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
            app.prepare(ctx_id=0, det_size=(640, 640))
            print_status("â—", "buffalo_l face recognition model ready")
            return True
        except Exception as e2:
            print_status("â—", f"Setup failed: {e2}", RED)
            print(f"  {RED}!{RESET} Face recognition will be disabled")
            return False


#------This Function runs git commands for auto-update-------
def _run_git_command(args: List[str], timeout: int = 20) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(
            ["git"] + args,
            cwd=str(MODULE_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        logging.getLogger(__name__).warning("[UPDATE] git executable not found")
    except subprocess.TimeoutExpired:
        logging.getLogger(__name__).warning("[UPDATE] git command timed out: git %s", " ".join(args))
    except Exception as exc:
        logging.getLogger(__name__).warning("[UPDATE] git command failed: git %s (%s)", " ".join(args), exc)
    return None


#------This Function checks whether module runs inside a git repository-------
def _is_git_repository() -> bool:
    result = _run_git_command(["rev-parse", "--is-inside-work-tree"])
    if result is None or result.returncode != 0:
        return False
    return result.stdout.strip() == "true"


#------This Function resolves the upstream tracking branch-------
def _get_tracking_branch() -> Optional[str]:
    result = _run_git_command(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"])
    if result is None or result.returncode != 0:
        return None
    branch = result.stdout.strip()
    return branch if branch else None


#------This Function checks whether local working tree is clean-------
def _is_work_tree_clean() -> bool:
    result = _run_git_command(["status", "--porcelain"])
    if result is None or result.returncode != 0:
        return False
    return result.stdout.strip() == ""


#------This Function checks git for updates-------
def check_for_updates() -> bool:
    tracking_branch = _get_tracking_branch()
    if tracking_branch is None:
        logging.getLogger(__name__).debug("[UPDATE] Upstream tracking branch is not configured")
        return False

    fetch_result = _run_git_command(["fetch", "--prune", "--quiet"])
    if fetch_result is None or fetch_result.returncode != 0:
        error_text = fetch_result.stderr.strip() if fetch_result else "unknown fetch error"
        logging.getLogger(__name__).warning("[UPDATE] Failed to fetch remote updates: %s", error_text)
        return False

    local_head_result = _run_git_command(["rev-parse", "HEAD"])
    remote_head_result = _run_git_command(["rev-parse", tracking_branch])
    if (
        local_head_result is None
        or remote_head_result is None
        or local_head_result.returncode != 0
        or remote_head_result.returncode != 0
    ):
        return False

    local_sha = local_head_result.stdout.strip()
    remote_sha = remote_head_result.stdout.strip()
    return bool(local_sha and remote_sha and local_sha != remote_sha)


#------This Function restarts the module to apply updates-------
def _restart_after_update() -> None:
    if not AUTO_RESTART_ON_UPDATE:
        print_status("â—", "Updates pulled. Restart the module to apply changes.", YELLOW)
        logging.getLogger(__name__).warning("[UPDATE] Auto-restart disabled; manual restart required")
        return

    print(f"\n{GREEN}{BOLD}Restarting module to apply updates...{RESET}\n")
    logging.getLogger(__name__).info("[UPDATE] Restarting process with os.execv")
    os.execv(sys.executable, [sys.executable] + sys.argv)


#------This Function pulls git updates-------
def pull_updates() -> bool:
    if not _is_work_tree_clean():
        print_status("â—", "Local changes detected; skipping auto-update pull", YELLOW)
        logging.getLogger(__name__).warning("[UPDATE] Working tree is dirty; pull skipped")
        return False

    pull_result = _run_git_command(["pull", "--ff-only"], timeout=60)
    if pull_result is None:
        return False

    if pull_result.returncode == 0:
        print_status("â—", "Updates applied successfully")
        return True

    error_text = pull_result.stderr.strip() or pull_result.stdout.strip() or "unknown pull error"
    print_status("â—", f"Update failed: {error_text}", RED)
    logging.getLogger(__name__).error("[UPDATE] git pull failed: %s", error_text)
    return False


#------This Function update monitor thread-------
def update_monitor() -> None:
    logger = logging.getLogger(__name__)
    while not _update_monitor_stop_event.wait(UPDATE_CHECK_INTERVAL):
        try:
            with _update_monitor_lock:
                lock_file = _acquire_process_update_lock()
                if fcntl is not None and lock_file is None:
                    logger.debug("[UPDATE] Another process is running an update cycle; skipping this interval")
                    continue
                try:
                    logger.info("[UPDATE] Checking for updates...")
                    if not check_for_updates():
                        continue

                    print(f"\n\n{YELLOW}{BOLD}â•â•â• UPDATE AVAILABLE â•â•â•{RESET}")
                    print_status("â—", "New commits detected - updating...")
                    if pull_updates():
                        _restart_after_update()
                finally:
                    _release_process_update_lock(lock_file)
        except Exception as exc:
            logger.warning("[UPDATE] Update monitor cycle failed: %s", exc)


#------This Function starts update monitor thread-------
def start_update_monitor() -> bool:
    global _update_monitor_thread

    if not AUTO_GIT_UPDATE_ENABLED:
        logging.getLogger(__name__).info("[UPDATE] Auto-update monitor disabled (AURAMODULE_AUTO_UPDATE_ENABLED=false)")
        return False

    if not _is_git_repository():
        logging.getLogger(__name__).warning("[UPDATE] Auto-update monitor disabled: module is not inside a git repository")
        return False

    if _get_tracking_branch() is None:
        logging.getLogger(__name__).warning("[UPDATE] Auto-update monitor disabled: no upstream tracking branch configured")
        return False

    if _update_monitor_thread and _update_monitor_thread.is_alive():
        return True

    _update_monitor_stop_event.clear()
    _update_monitor_thread = threading.Thread(
        target=update_monitor,
        name="auramodule-update-monitor",
        daemon=True,
    )
    _update_monitor_thread.start()
    return True


#------This Function stops update monitor thread-------
def stop_update_monitor() -> None:
    if _update_monitor_thread and _update_monitor_thread.is_alive():
        _update_monitor_stop_event.set()
        _update_monitor_thread.join(timeout=2)


#------This Function handles the Main Application----------
async def main():
    global _system_info

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    
    _system_info = detect_hardware()
    show_banner(_system_info)
    
    print(f"{CYAN}Initializing system checks...{RESET}\n")
    
    print_section("System Information")
    print_status("â—", f"Platform: {CYAN}{_system_info['platform']}{RESET}")
    print_status("â—", f"Architecture: {CYAN}{_system_info['architecture']}{RESET}")
    print_status("â—", f"CPU Cores: {CYAN}{_system_info['cpu_cores']}{RESET}")
    
    if _system_info.get("is_raspberry_pi"):
        print_status("â—", f"Hardware: {CYAN}Raspberry Pi {_system_info['pi_model']}{RESET}")
        print_status("â—", f"GPU: {CYAN}{_system_info.get('gpu_info', 'None')}{RESET}")
    else:
        print_status("â—", f"Processor: {CYAN}{_system_info.get('processor', 'Unknown')[:50]}{RESET}")
        print_status("â—", f"GPU: {CYAN}{_system_info.get('gpu_info', 'None')}{RESET}")
    
    print()
    resources = check_system_resources()
    print_section("System Resources")
    print_status("â—", f"Disk Space: {CYAN}{resources['disk_space_gb']} GB{RESET}")
    print_status("â—", f"Memory: {CYAN}{resources['memory_available_gb']} GB available / {resources['memory_total_gb']} GB total{RESET}")
    print_status("â—", f"CPU Usage: {CYAN}{resources['cpu_usage_percent']}%{RESET}")
    
    if not resources["ok"]:
        print_status("â—", "Low disk space! At least 2GB recommended", YELLOW)
    
    check_pyaudio()
    ollama_ok = check_ollama()
    check_models()

    apply_pairing_config_to_settings(overwrite_existing=False)
    pairing_state = load_pairing_config()
    pairing_completed = bool(
        (pairing_state.get("patient_uid", "") or "").strip()
        and normalize_backend_url(pairing_state.get("backend_url", "") or "")
    )
    runtime_config_ready = bool(
        pairing_completed
        and
        is_configured_patient_uid(settings.patient_uid)
        and normalize_backend_url(settings.backend_url or "")
    )
    
    print_section("Environment Configuration")
    
    backend_url = settings.backend_url
    patient_uid = settings.patient_uid
    auth_token = (settings.backend_auth_token or "").strip()
    
    if backend_url and backend_url != "http://localhost:8000":
        print_status("â—", f"BACKEND_URL: {CYAN}{backend_url}{RESET}")
    else:
        print_status("â—", "BACKEND_URL not configured", RED)
    
    if is_configured_patient_uid(patient_uid) and pairing_completed:
        print_status("â—", f"PATIENT_UID: {CYAN}{patient_uid[:8]}...{RESET}")
    else:
        print_status("â—", "PATIENT_UID not configured", RED)
        print_status("â—", "Waiting for paired device to provide patient UID", YELLOW)
    
    if auth_token:
        print_status("â—", "BACKEND_AUTH_TOKEN present")
    else:
        print_status("â—", "BACKEND_AUTH_TOKEN missing", YELLOW)

    print(f"\n{BLUE}{BOLD}â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•{RESET}")
    print(f"{BLUE}{BOLD}  Status Summary{RESET}")
    print(f"{BLUE}{BOLD}â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•{RESET}")
    
    print_status("â—", "Environment")
    print_status("â—" if ollama_ok else "â—", "Ollama + Models", GREEN if ollama_ok else YELLOW)
    
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("[AURA] Startup diagnostics")
    logger.info("Backend URL: %s", settings.backend_url or "")
    logger.info(
        "Patient UID: %s",
        "configured" if is_configured_patient_uid(settings.patient_uid) else "NOT CONFIGURED",
    )
    logger.info(
        "Auth token: %s",
        "present" if (settings.backend_auth_token or "").strip() else "missing",
    )

    if start_update_monitor():
        print_status("â—", "Update monitor running in background")
    else:
        print_status("â—", "Update monitor disabled", YELLOW)

    if not is_configured_patient_uid(settings.patient_uid):
        logger.warning("Device running in unpaired mode. Backend registration will be skipped.")

    if not runtime_config_ready:
        logger.warning(
            "[AURA] Starting in unpaired mode. "
            "Connect from paired app to push patient_uid and backend_url."
        )
        print_status("â—", "Running in unpaired mode", YELLOW)
        print_status("â—", "Backend registration will wait until pairing is completed", YELLOW)

    preferred_port = settings.http_port
    resolved_port = resolve_available_service_port(preferred_port)
    if resolved_port != preferred_port:
        logger.warning(
            "[AURA] Port %s is busy. Falling back to %s",
            preferred_port,
            resolved_port,
        )
        settings.http_port = resolved_port
        settings.ws_port = resolved_port
        print_status("â—", f"Port {preferred_port} busy, using {resolved_port}", YELLOW)
    
    print_section("Starting Services")
    
    print_status(
        "â—",
        f"Patient UID: {settings.patient_uid[:8]}..."
        if is_configured_patient_uid(settings.patient_uid)
        else "Patient UID: NOT SET (awaiting pairing)",
    )
    print_status("â—", f"Server port: {settings.http_port}")
    print_status("â—", f"Camera index: {settings.camera_index}")
    print_status("â—", f"Whisper model: {settings.whisper_model} ({settings.whisper_model_size})")
    print_status("â—", f"Ollama: {settings.ollama_url} ({settings.ollama_model})")
    print_status("â—", f"Streaming: {settings.ollama_streaming}")
    print_status("â—", f"VAD: {settings.enable_vad}")
    print_status("â—", f"Backend: {settings.backend_url}")
    print_status("â—", f"Demo mode: {settings.demo_mode}")
    print()
    
    logger.info("[AURA] Pre-loading machine learning models...")
    logger.info("[AURA] This may take a few minutes on first run (downloading models)...")
    print()

    try:
        from app.services.face_recognition import get_face_app

        logger.info("[AURA] Loading face recognition model (buffalo_l)...")
        get_face_app()
        print_status("â—", "Face recognition model ready")
    except Exception as e:
        logger.error(f"[AURA] Failed to load face recognition model: {e}")
        logger.error(
            "[AURA] Install optional face/audio deps with: "
            "python -m pip install -r requirements.optional.txt"
        )
        if settings.demo_mode:
            logger.warning("[AURA] Continuing in demo mode without face recognition")
        else:
            logger.warning("[AURA] Continuing with face recognition disabled")
            logger.warning(
                "[AURA] Set DEMO_MODE=true if you want full demo-mode behavior"
            )

    try:
        from app.services.speech import get_whisper_model

        logger.info("[AURA] Preloading Whisper STT model...")
        get_whisper_model()
        print_status("â—", "Whisper STT model ready")
    except Exception as e:
        logger.error(f"[AURA] Failed to preload Whisper model: {e}")
        logger.warning("[AURA] Continuing; live transcription may be delayed on first decode")

    
    backend_client = init_backend_client(settings.patient_uid)

    local_ip = _get_local_ip()

    if runtime_config_ready:
        logger.info(f"[AURA] Registering with backend at {settings.backend_url}...")
        print_status("â—", f"Registering with backend at {settings.backend_url}...")
        registered = await backend_client.register(local_ip, settings.http_port)
        
        if not registered:
            logger.warning("[AURA] Failed to register with backend")
            print_status("â—", "Failed to register with backend", YELLOW)
            print(f"  {YELLOW}!{RESET} Module will continue running but some features may not work")
        else:
            await backend_client.start_heartbeat()
            print_status("â—", f"Heartbeat task started (every {settings.heartbeat_interval}s)")
    else:
        logger.info("[AURA] Backend registration deferred until pairing config is received")
        print_status("â—", "Backend registration deferred until pairing", YELLOW)

    camera_service.start()
    print_status("â—", "Camera started (always-on mode)")

    async def on_summarize(transcripts):
        if not is_configured_patient_uid(settings.patient_uid):
            logger.info("[AURA] Skipping summarization: pairing not completed yet")
            return
        logger.info(f"[AURA] Summarization triggered with {len(transcripts)} transcripts")
        try:
            summary = await summarize_conversation(
                transcripts=transcripts,
                patient_uid=settings.patient_uid,
            )
            if summary:
                logger.info(f"[AURA] Summary generated: {summary[:80]}...")
            else:
                logger.warning("[AURA] Failed to generate summary")
        except Exception as e:
            logger.error(f"[AURA] Error in summarization callback: {e}")
    
    from app.services.microphone import ContinuousMicrophone
    continuous_microphone = ContinuousMicrophone(
        on_summarize=on_summarize,
        event_loop=asyncio.get_running_loop(),
    )
    print_status("â—", "Continuous microphone deferred until face recognition", YELLOW)

    discovery_service.start()
    print_status("â—", "mDNS discovery broadcasting")

    
    server_runner = await start_server()
    print_status("â—", f"Unified HTTP+WS server running on 0.0.0.0:{settings.http_port}")
    print_status("â—", f"Video stream available at: http://{local_ip}:{settings.http_port}/video_feed")

    
    stop = asyncio.Event()
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("[AURA] Shutdown signal received")
        stop.set()

    if platform.system() == "Windows":
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda _sig, _frame: signal_handler())
    else:
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, signal_handler)

    print(f"\n{BLUE}{BOLD}â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•{RESET}")
    print_status("â—", "Module ready. Waiting for connections...")
    print(f"{BLUE}{BOLD}â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•{RESET}\n")
    
    await stop.wait()

    print("\n" + YELLOW + "Shutting down..." + RESET)

    stop_update_monitor()

    await backend_client.stop_heartbeat()

    await shutdown_streams()

    camera_service.stop()

    continuous_microphone.stop()

    discovery_service.stop()

    await server_runner.cleanup()
    
    print_status("â—", "Goodbye")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n" + BLUE + "Â»" + RESET + " Module stopped by user")
    except Exception as e:
        logging.error(f"[AURA] Fatal error: {type(e).__name__}: {e}")
        sys.exit(1)
