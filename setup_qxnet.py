#!/usr/bin/env python3
"""
QXNet Setup Script — Initialize QXPULL environment

Supports both local (~/.qxnet) and production (/var/qxnet) deployments.
Handles directory creation, API key setup, file permissions, and validation.

Usage:
    python3 setup_qxnet.py                    # Interactive mode
    python3 setup_qxnet.py --mode local       # Setup local only
    python3 setup_qxnet.py --mode production  # Setup production only
    python3 setup_qxnet.py --api-key YOUR_KEY  # Provide key via CLI
"""

import os
import sys
import stat
import argparse
import getpass
from pathlib import Path
from typing import Optional, Tuple

# Color codes for terminal output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

def print_header(text):
    """Print a formatted header."""
    print(f"\n{Colors.HEADER}{Colors.BOLD}{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}{Colors.ENDC}\n")

def print_success(text):
    """Print success message."""
    print(f"{Colors.OKGREEN}✓ {text}{Colors.ENDC}")

def print_warning(text):
    """Print warning message."""
    print(f"{Colors.WARNING}⚠ {text}{Colors.ENDC}")

def print_error(text):
    """Print error message."""
    print(f"{Colors.FAIL}✗ {text}{Colors.ENDC}")

def print_info(text):
    """Print info message."""
    print(f"{Colors.OKBLUE}ℹ {text}{Colors.ENDC}")

def prompt_yes_no(question: str) -> bool:
    """Prompt user for yes/no answer."""
    while True:
        response = input(f"\n{Colors.BOLD}{question} (yes/no): {Colors.ENDC}").strip().lower()
        if response in ('yes', 'y'):
            return True
        elif response in ('no', 'n'):
            return False
        else:
            print_error("Please answer 'yes' or 'no'")

def prompt_choice(message: str, options: list) -> str:
    """Prompt user to choose from options."""
    print(f"\n{Colors.BOLD}{message}{Colors.ENDC}")
    for i, option in enumerate(options, 1):
        print(f"  {i}. {option}")
    
    while True:
        try:
            choice = int(input(f"{Colors.BOLD}Enter choice (1-{len(options)}): {Colors.ENDC}"))
            if 1 <= choice <= len(options):
                return options[choice - 1].lower()
            else:
                print_error(f"Please enter a number between 1 and {len(options)}")
        except ValueError:
            print_error("Invalid input. Please enter a number")

def prompt_input(prompt_text: str, default: Optional[str] = None, mask: bool = False) -> str:
    """Prompt user for input with optional default."""
    if default:
        prompt_text = f"{prompt_text} [{default}]"
    else:
        prompt_text = f"{prompt_text}"
    
    prompt_text = f"{Colors.BOLD}{prompt_text}: {Colors.ENDC}"
    
    if mask:
        value = getpass.getpass(prompt_text)
    else:
        value = input(prompt_text).strip()
    
    return value if value else default

def create_directories(base_dir: Path) -> Tuple[bool, str]:
    """Create required directory structure."""
    try:
        directories = [
            (base_dir, "Base directory"),
            (base_dir / "data", "Data files directory"),
            (base_dir / "archive", "Archive directory"),
        ]
        
        for dir_path, description in directories:
            dir_path.mkdir(parents=True, exist_ok=True)
            print_success(f"Created {description}: {dir_path}")
        
        return True, "Directories created successfully"
    except PermissionError as e:
        return False, f"Permission denied creating directories: {e}"
    except Exception as e:
        return False, f"Error creating directories: {e}"

def masked_input(prompt_text):
    import sys
    import os

    # Windows version (uses msvcrt)
    if os.name == "nt":
        import msvcrt
        print(prompt_text, end="", flush=True)
        chars = []
        while True:
            ch = msvcrt.getch()
            if ch in {b"\r", b"\n"}:
                print()
                break
            elif ch == b"\x03":  # Ctrl-C
                print("\nOperation cancelled.")
                return ""
            elif ch in {b"\x08", b"\x7f"}:  # Backspace
                if chars:
                    chars.pop()
                    print("\b \b", end="", flush=True)
            else:
                chars.append(ch.decode("utf-8", errors="ignore"))
                print("*", end="", flush=True)
        return "".join(chars)

    # POSIX version (Linux/macOS)
    else:
        import tty
        import termios

        print(prompt_text, end="", flush=True)
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            chars = []
            while True:
                ch = sys.stdin.read(1)
                if ch in ("\n", "\r"):
                    print()
                    break
                elif ch == "\x03":  # Ctrl-C
                    print("\nOperation cancelled.")
                    return ""
                elif ch in ("\x7f", "\x08"):  # Backspace
                    if chars:
                        chars.pop()
                        print("\b \b", end="", flush=True)
                else:
                    chars.append(ch)
                    print("*", end="", flush=True)
            return "".join(chars)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

def setup_api_key(base_dir: Path, api_key: Optional[str] = None) -> Tuple[bool, str]:
    """Setup FRED API key."""
    api_key_file = base_dir / "fred_api_key.txt"
    
    print_header("FRED API Key Setup")
    
    if api_key_file.exists():
        print_warning(f"API key file already exists: {api_key_file}")
        if not prompt_yes_no("Overwrite existing API key?"):
            print_info("Keeping existing API key")
            return True, "API key setup skipped"
    
    if not api_key:
        print_info("You'll need a FRED API key to continue.")
        print_info("Get one free at: https://fred.stlouisfed.org/docs/api/api_key.html")
        print_info("Input will be masked with * characters.")
        api_key = masked_input("Enter your FRED API key: ")

    if not api_key or len(api_key) < 10:
        return False, "Invalid API key (too short or empty)"
    
    try:
        # Write API key with restricted permissions
        with open(api_key_file, "w") as f:
            f.write(api_key.strip())
        
        # Set file permissions to 600 (owner read/write only)
        api_key_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        print_success(f"API key saved to {api_key_file}")
        print_success(f"File permissions set to 0600 (secure)")
        
        return True, "API key setup completed"
    except PermissionError as e:
        return False, f"Permission denied writing API key: {e}"
    except Exception as e:
        return False, f"Error writing API key: {e}"

def setup_config_file(base_dir: Path, is_production: bool) -> Tuple[bool, str]:
    """Setup optional config file for production mode."""
    if not is_production:
        return True, "Config file skipped (local mode)"
    
    config_file = base_dir / "config.txt"
    
    print_header("Production Configuration File (Optional)")
    print_info("You can create a unified config file with all settings.")
    print_info("Or use just the API key file (simpler).")
    
    if not prompt_yes_no("Create config.txt?"):
        print_info("Skipping config.txt (using fred_api_key.txt is fine)")
        return True, "Config file setup skipped"
    
    try:
        api_key = prompt_input("FRED API Key (leave blank to skip)", mask=True)
        retain_days = prompt_input("Retain days (files older moved to archive)", "30")
        archive_days = prompt_input("Archive days (archived files older deleted)", "365")
        
        config_content = f"""# QXNet Configuration
# Generated by setup_qxnet.py

# FRED API Key (optional if using separate fred_api_key.txt)
{"FRED_API_KEY=" + api_key if api_key else "# FRED_API_KEY=your_key_here"}

# File retention policy
RETAIN_DAYS={retain_days}
ARCHIVE_DAYS={archive_days}
"""
        
        with open(config_file, "w") as f:
            f.write(config_content)
        
        # Set file permissions to 600
        config_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        print_success(f"Config file created: {config_file}")
        print_success(f"File permissions set to 0600 (secure)")
        
        return True, "Config file setup completed"
    except PermissionError as e:
        return False, f"Permission denied writing config file: {e}"
    except Exception as e:
        return False, f"Error writing config file: {e}"

def validate_setup(base_dir: Path, is_production: bool) -> Tuple[bool, list]:
    """Validate the setup."""
    print_header("Validating Setup")
    
    issues = []
    
    # Check directories
    for dir_name in ["data", "archive"]:
        dir_path = base_dir / dir_name
        if not dir_path.exists():
            issues.append(f"Missing directory: {dir_path}")
        else:
            print_success(f"Directory exists: {dir_path}")
    
    # Check API key file
    api_key_file = base_dir / "fred_api_key.txt"
    if not api_key_file.exists():
        issues.append(f"Missing API key file: {api_key_file}")
    else:
        print_success(f"API key file exists: {api_key_file}")
        
        # Check permissions
        perms = oct(api_key_file.stat().st_mode)[-3:]
        if perms == "600":
            print_success(f"API key file permissions: {perms} (secure)")
        else:
            print_warning(f"API key file permissions: {perms} (consider running: chmod 600 {api_key_file})")
        
        # Check content
        with open(api_key_file, "r") as f:
            key = f.read().strip()
        if key and len(key) >= 10:
            print_success(f"API key file contains valid key ({len(key)} chars)")
        else:
            issues.append(f"API key file is empty or invalid")
    
    # Check config file (optional for production)
    if is_production:
        config_file = base_dir / "config.txt"
        if config_file.exists():
            print_success(f"Config file exists: {config_file}")
        else:
            print_info(f"Config file not created (optional): {config_file}")
    
    return len(issues) == 0, issues

def check_python_dependencies() -> bool:
    """Check for required Python packages and optionally auto-install them."""
    print_header("Checking Python Dependencies")

    required = [
        "pandas",
        "yfinance",
        "requests",
    ]

    missing = []

    # Check imports
    for pkg in required:
        try:
            __import__(pkg)
            print_success(f"Dependency OK: {pkg}")
        except ImportError:
            missing.append(pkg)
            print_error(f"Missing: {pkg}")

    # All good
    if not missing:
        print_success("All required Python packages are installed")
        return True

    # Missing packages detected
    print_warning("Some required Python packages are missing")
    print_info("Missing packages:")
    for pkg in missing:
        print_error(f"  - {pkg}")

    # Ask user whether to auto-install
    if not prompt_yes_no("Would you like to auto-install the missing packages now"):
        print_error("Cannot continue without required dependencies")
        print_info("Install them manually with:")
        print(f"  pip install {' '.join(missing)}")
        return False

    # Auto-install
    print_info("Installing missing packages...")

    try:
        import subprocess
        import sys

        cmd = [sys.executable, "-m", "pip", "install"] + missing
        result = subprocess.run(cmd)

        if result.returncode != 0:
            print_error("Automatic installation failed")
            print_info("Try installing manually:")
            print(f"  pip install {' '.join(missing)}")
            return False

        print_success("All missing packages installed successfully")
        return True

    except Exception as e:
        print_error(f"Error during installation: {e}")
        print_info("Install manually with:")
        print(f"  pip install {' '.join(missing)}")
        return False

def setup_local_mode(api_key: Optional[str] = None) -> bool:
    """Setup local development mode (~/.qxnet)."""
    print_header("QXNet Local Development Setup")
    
    # Check Python dependencies
    if not check_python_dependencies():
        return False
    
    base_dir = Path.home() / "qxnet"
    
    print_info(f"Base directory: {base_dir}")
    print_info("This setup creates ~/.qxnet with all necessary files")
    print_info("No system permissions required")
    
    # Create directories
    success, message = create_directories(base_dir)
    if not success:
        print_error(message)
        return False
    
    # Setup API key
    success, message = setup_api_key(base_dir, api_key)
    if not success:
        print_error(message)
        return False
    
    # Skip config file for local mode
    print_info("Config file: Not needed for local mode")
    
    # Validate
    success, issues = validate_setup(base_dir, is_production=False)
    
    if issues:
        print_error("Validation found issues:")
        for issue in issues:
            print_error(f"  - {issue}")
        return False
    
    print_header("Local Setup Complete ✓")
    print_info(f"Base directory: {base_dir}")
    print_info(f"Data files will be saved to: {base_dir}/data")
    print_info(f"Archive files will be saved to: {base_dir}/archive")
    print_info(f"Log file: {base_dir}/qxpull.log")
    print_info("\nRun QXPULL with:")
    print(f"  {Colors.OKGREEN}python3 QXPULL_Coherent_06022026.py{Colors.ENDC}")
    
    return True

def setup_production_mode(api_key: Optional[str] = None) -> bool:
    """Setup production mode (/var/qxnet)."""
    print_header("QXNet Production Setup")
    
    # Check Python dependencies
    if not check_python_dependencies():
        return False
    
    base_dir = Path("/var/qxnet")
    
    print_warning("This setup modifies /var/qxnet (requires elevated permissions)")
    print_info("You may be prompted for your password")
    
    # Check if we have permission to write to /var/qxnet
    var_dir = Path("/var")
    if not os.access(var_dir, os.W_OK):
        print_error("You do not have write permission to /var")
        print_info("Run with sudo: sudo python3 setup_qxnet.py --mode production")
        return False
    
    print_info(f"Base directory: {base_dir}")
    print_info(f"Data directory: {base_dir}/data")
    print_info(f"Archive directory: {base_dir}/archive")
    
    # Create directories
    success, message = create_directories(base_dir)
    if not success:
        print_error(message)
        print_info("Try running with sudo: sudo python3 setup_qxnet.py --mode production")
        return False
    
    # Setup API key
    success, message = setup_api_key(base_dir, api_key)
    if not success:
        print_error(message)
        return False
    
    # Setup config file (optional)
    success, message = setup_config_file(base_dir, is_production=True)
    if not success:
        print_error(message)
        return False
    
    # Validate
    success, issues = validate_setup(base_dir, is_production=True)
    
    if issues:
        print_error("Validation found issues:")
        for issue in issues:
            print_error(f"  - {issue}")
        return False
    
    print_header("Production Setup Complete ✓")
    print_info(f"Base directory: {base_dir}")
    print_info(f"Data files will be saved to: {base_dir}/data")
    print_info(f"Archive files will be saved to: {base_dir}/archive")
    print_info(f"Log file: {base_dir}/qxpull.log")
    print_info("\nRun QXPULL with:")
    print(f"  {Colors.OKGREEN}QXNET_ENV=production /usr/bin/python3 /opt/qxnet/qxpull.py{Colors.ENDC}")
    print_info("\nCron setup (runs daily at 6 AM):")
    print(f"  {Colors.OKGREEN}0 6 * * * QXNET_ENV=production /usr/bin/python3 /opt/qxnet/qxpull.py{Colors.ENDC}")
    
    return True

def setup_both_modes(api_key: Optional[str] = None) -> bool:
    """Setup both local and production modes."""
    print_header("QXNet Dual Setup")
    print_info("Setting up both local (~/.qxnet) and production (/var/qxnet)")
    
    # Local setup
    print("\n" + "="*60)
    print_info("Starting local setup...")
    print("="*60)
    local_success = setup_local_mode(api_key)
    
    if not local_success:
        print_error("Local setup failed. Aborting production setup.")
        return False
    
    # Production setup
    print("\n" + "="*60)
    print_info("Starting production setup...")
    print("="*60)
    prod_success = setup_production_mode(api_key)
    
    if prod_success:
        print_header("Dual Setup Complete ✓")
        print_success("Both local and production environments are ready")
        return True
    else:
        print_warning("Local setup succeeded, but production setup failed")
        return False

def interactive_mode(api_key: Optional[str] = None) -> bool:
    """Interactive setup mode."""
    print_header("QXNet Setup Wizard")
    print_info("This wizard will help you set up QXPULL")
    print_info("Version: 06/02/2026")
    
    # Choose setup mode
    mode = prompt_choice(
        "Which environment would you like to set up?",
        ["Local (~/.qxnet) - Development on this machine",
         "Production (/var/qxnet) - System-wide deployment",
         "Both - Local development + Production ready"]
    )
    
    if mode == "local (~/.qxnet) - development on this machine":
        return setup_local_mode(api_key)
    elif mode == "production (/var/qxnet) - system-wide deployment":
        return setup_production_mode(api_key)
    elif mode == "both - local development + production ready":
        return setup_both_modes(api_key)
    else:
        print_error("Invalid choice")
        return False

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="QXNet Setup Script — Initialize QXPULL environment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 setup_qxnet.py                              # Interactive mode
  python3 setup_qxnet.py --mode local                 # Setup local only
  python3 setup_qxnet.py --mode production            # Setup production (may need sudo)
  python3 setup_qxnet.py --mode both                  # Setup both
  python3 setup_qxnet.py --mode local --api-key KEY   # Provide API key via CLI
        """
    )
    
    parser.add_argument(
        "--mode",
        choices=["local", "production", "both"],
        help="Setup mode (local, production, or both)"
    )
    
    parser.add_argument(
        "--api-key",
        help="FRED API key (will prompt if not provided)"
    )
    
    args = parser.parse_args()
    
    try:
        if args.mode:
            # Non-interactive mode
            if args.mode == "local":
                success = setup_local_mode(args.api_key)
            elif args.mode == "production":
                success = setup_production_mode(args.api_key)
            elif args.mode == "both":
                success = setup_both_modes(args.api_key)
        else:
            # Interactive mode
            success = interactive_mode(args.api_key)
        
        return 0 if success else 1
    
    except KeyboardInterrupt:
        print("\n")
        print_warning("Setup cancelled by user")
        return 1
    except Exception as e:
        print("\n")
        print_error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
