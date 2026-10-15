"""
GeoChip Interactive CLI UI Module.
Provides modern, interactive terminal UI selection (arrow keys, colors, formatting)
similar to Antigravity and Claude Code CLI tools.
"""

import os
import sys
import shutil

# ANSI Color Codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
CYAN = "\033[36m"
BRIGHT_CYAN = "\033[96m"
GREEN = "\033[32m"
BRIGHT_GREEN = "\033[92m"
YELLOW = "\033[33m"
BRIGHT_YELLOW = "\033[93m"
RED = "\033[31m"
MAGENTA = "\033[35m"
WHITE = "\033[97m"
BG_CYAN = "\033[46m"
BG_BLUE = "\033[44m"


def enable_windows_ansi():
    """Enable ANSI virtual terminal processing and UTF-8 encoding on Windows consoles."""
    if os.name == "nt":
        try:
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            if hasattr(sys.stderr, "reconfigure"):
                sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            kernel32.GetConsoleMode(handle, ctypes.byref(mode))
            mode.value |= 0x0004  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
            kernel32.SetConsoleMode(handle, mode)
        except Exception:
            pass


enable_windows_ansi()


def print_banner():
    """Display the GeoChip ASCII banner with rich gradient styling."""
    banner = f"""
{BRIGHT_CYAN}  ██████╗ ███████╗ ██████╗  ██████╗██╗  ██╗██╗██████╗ 
 ██╔════╝ ██╔════╝██╔═══██╗██╔════╝██║  ██║██║██╔══██╗
 ██║  ███╗█████╗  ██║   ██║██║     ███████║██║██████╔╝
 ██║   ██║██╔══╝  ██║   ██║██║     ██╔══██║██║██╔═══╝ 
 ╚██████╔╝███████╗╚██████╔╝╚██████╗██║  ██║██║██║     
  ╚═════╝ ╚══════╝ ╚═════╝  ╚═════╝╚═╝  ╚═╝╚═╝╚═╝     {RESET}
  {BOLD}{WHITE}Geospatial Earth Observation Pipeline & Roboflow Ingestion{RESET}
  {DIM}Interactive CLI Engine v2.0{RESET}
"""
    print(banner)


def clear_lines(n):
    """Clear n terminal lines upwards."""
    for _ in range(n):
        sys.stdout.write("\033[F\033[K")
    sys.stdout.flush()


def _get_key_windows():
    """Read a keypress on Windows via msvcrt."""
    import msvcrt
    ch = msvcrt.getch()
    if ch in (b"\x00", b"\xe0"):  # Special key prefix
        ch2 = msvcrt.getch()
        if ch2 == b"H":
            return "UP"
        elif ch2 == b"P":
            return "DOWN"
        elif ch2 == b"K":
            return "LEFT"
        elif ch2 == b"M":
            return "RIGHT"
    elif ch == b"\r":
        return "ENTER"
    elif ch == b"\x1b":
        return "ESC"
    elif ch == b"\x03":
        raise KeyboardInterrupt
    return ch.decode("utf-8", errors="ignore")


def _get_key_posix():
    """Read a keypress on POSIX via termios and tty."""
    import termios
    import tty
    fd = sys.stdin.fileno()
    old_settings = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                ch3 = sys.stdin.read(1)
                if ch3 == "A":
                    return "UP"
                elif ch3 == "B":
                    return "DOWN"
                elif ch3 == "C":
                    return "RIGHT"
                elif ch3 == "D":
                    return "LEFT"
            return "ESC"
        elif ch == "\r" or ch == "\n":
            return "ENTER"
        elif ch == "\x03":
            raise KeyboardInterrupt
        return ch
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def read_key():
    """Read a single keypress cross-platform."""
    if os.name == "nt":
        return _get_key_windows()
    else:
        return _get_key_posix()


def _fit_text(text, max_len):
    """Truncate text to max_len with ellipsis if it exceeds width."""
    if not text:
        return ""
    if len(text) > max_len:
        return text[:max(0, max_len - 3)] + "..."
    return text


def select(title, choices, default_index=0, help_text="Use ↑/↓ arrow keys to navigate, press ENTER to confirm"):
    """
    Interactive select menu with arrow keys, highlight cursor, and clean re-rendering.
    Falls back to numbered input if running in non-interactive environment.
    """
    if not sys.stdin.isatty():
        # Fallback to standard numbered prompt
        print(f"\n{BOLD}{CYAN}? {title}{RESET}")
        for idx, item in enumerate(choices, 1):
            label = item if isinstance(item, str) else item.get("name", str(item))
            print(f"  [{idx}] {label}")
        while True:
            try:
                raw = input(f"Select [1-{len(choices)}] (default {default_index+1}): ").strip()
                if not raw:
                    return default_index
                val = int(raw) - 1
                if 0 <= val < len(choices):
                    return val
            except (ValueError, KeyboardInterrupt):
                pass
            print(f"{RED}Invalid choice, please try again.{RESET}")

    current_idx = default_index
    num_choices = len(choices)
    has_any_desc = any(isinstance(c, dict) and bool(c.get("desc")) for c in choices)

    # Initial render
    print(f"\n{BOLD}{BRIGHT_CYAN}? {title}{RESET}")
    if help_text:
        print(f"  {DIM}{help_text}{RESET}")

    # Lines to clear: 1 per choice, plus 2 lines for description area if applicable
    lines_to_clear = num_choices + (2 if has_any_desc else 0)

    # Hide cursor while interactive menu is active
    sys.stdout.write("\033[?25l")
    sys.stdout.flush()

    try:
        while True:
            cols = shutil.get_terminal_size(fallback=(80, 24)).columns
            # Ensure label never exceeds terminal width (leaving margin for prefix "  ❯ [99] ")
            max_label_width = max(20, cols - 12)

            # Print choices (guaranteed strictly <= cols - 2 printable chars to prevent any wrapping)
            for idx, item in enumerate(choices):
                if isinstance(item, dict):
                    raw_label = item.get("name", str(item))
                else:
                    raw_label = str(item)

                label = _fit_text(raw_label, max_label_width)

                if idx == current_idx:
                    prefix = f"  {BRIGHT_CYAN}❯ [{idx+1}]{RESET} {BOLD}{WHITE}{label}{RESET}"
                else:
                    prefix = f"  {DIM}  [{idx+1}] {label}{RESET}"
                print(prefix)

            # Print dedicated description status line for the selected choice
            if has_any_desc:
                max_desc_width = max(20, cols - 8)
                curr_item = choices[current_idx]
                raw_desc = curr_item.get("desc", "") if isinstance(curr_item, dict) else ""
                desc = _fit_text(raw_desc, max_desc_width) if raw_desc else ""
                print()  # Empty line separator
                if desc:
                    print(f"  {CYAN}ℹ {desc}{RESET}")
                else:
                    print(f"  {DIM}ℹ (No additional description){RESET}")

            # Wait for key
            try:
                key = read_key()
            except KeyboardInterrupt:
                print("\n")
                sys.exit(0)

            if key in ("UP", "k", "K"):
                current_idx = (current_idx - 1) % num_choices
                clear_lines(lines_to_clear)
            elif key in ("DOWN", "j", "J"):
                current_idx = (current_idx + 1) % num_choices
                clear_lines(lines_to_clear)
            elif key == "ENTER":
                clear_lines(lines_to_clear)
                # Print final selection cleanly
                chosen = choices[current_idx]
                chosen_label = chosen if isinstance(chosen, str) else chosen.get("name", str(chosen))
                print(f"  {BRIGHT_GREEN}✔ Selected: {BOLD}{chosen_label}{RESET}")
                return current_idx
            elif key.isdigit():
                digit = int(key) - 1
                if 0 <= digit < num_choices:
                    current_idx = digit
                    clear_lines(lines_to_clear)
                    chosen = choices[current_idx]
                    chosen_label = chosen if isinstance(chosen, str) else chosen.get("name", str(chosen))
                    print(f"  {BRIGHT_GREEN}✔ Selected: {BOLD}{chosen_label}{RESET}")
                    return current_idx
                clear_lines(lines_to_clear)
            else:
                clear_lines(lines_to_clear)
    finally:
        # Always restore cursor visibility
        sys.stdout.write("\033[?25h")
        sys.stdout.flush()


def prompt_input(message, default=None, validator=None):
    """Prompt user for text input with optional default value and validator function."""
    prompt_str = f"{BOLD}{CYAN}? {message}{RESET}"
    if default is not None:
        prompt_str += f" {DIM}(default: {default}){RESET}"
    prompt_str += ": "

    while True:
        try:
            val = input(prompt_str).strip()
            if not val and default is not None:
                val = str(default)
            if validator:
                ok, err = validator(val)
                if not ok:
                    print(f"  {RED}✖ {err}{RESET}")
                    continue
            return val
        except KeyboardInterrupt:
            print("\n")
            sys.exit(0)


def prompt_number(message, default=None, min_val=None, max_val=None, is_float=False):
    """Prompt user for a valid integer or float number."""
    def validator(v):
        try:
            num = float(v) if is_float else int(v)
            if min_val is not None and num < min_val:
                return False, f"Minimum allowed value is {min_val}"
            if max_val is not None and num > max_val:
                return False, f"Maximum allowed value is {max_val}"
            return True, ""
        except ValueError:
            return False, "Input must be a valid number"

    raw = prompt_input(message, default=default, validator=validator)
    return float(raw) if is_float else int(raw)


def prompt_confirm(message, default=True):
    """Prompt user for Yes/No confirmation."""
    def_str = "Y/n" if default else "y/N"
    raw = prompt_input(f"{message} [{def_str}]", default="y" if default else "n").lower()
    return raw in ("y", "yes")


def print_step(title):
    """Print a visually distinct workflow step banner."""
    print(f"\n{BOLD}{BG_BLUE}{WHITE}  {title.upper()}  {RESET}\n")


def print_success(message):
    """Print success message."""
    print(f"{BRIGHT_GREEN}✔ {message}{RESET}")


def print_error(message):
    """Print error message."""
    print(f"{RED}✖ {message}{RESET}")


def print_warning(message):
    """Print warning message."""
    print(f"{BRIGHT_YELLOW}⚠ {message}{RESET}")


def print_info(message):
    """Print informative message."""
    print(f"{CYAN}ℹ {message}{RESET}")
