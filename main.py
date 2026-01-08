import argparse
import base64
import io
import re
import sys
import os
import struct
import fcntl
import termios
import math

import matplotlib

# Force non-interactive backend
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --- FIX: Switch from 'cm' to 'stix' or 'dejavusans' to fix missing symbol errors ---
# 'stix' is a high-quality font set that looks like LaTeX but has better symbol support than 'cm'
try:
    matplotlib.rcParams["mathtext.fontset"] = "stix"
    matplotlib.rcParams["font.family"] = "STIXGeneral"
except Exception:
    # Fallback to default if STIX is not found
    matplotlib.rcParams["mathtext.fontset"] = "dejavusans"
    matplotlib.rcParams["font.family"] = "sans-serif"

# Constants
CHUNK_SIZE = 4096


def get_terminal_cell_dims():
    """
    Attempts to get the terminal cell width and height in pixels using ioctl.
    Returns (width, height). Defaults to (10, 20) if it fails.
    """
    try:
        buf = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b'\0' * 8)
        ws_row, ws_col, ws_xpixel, ws_ypixel = struct.unpack('HHHH', buf)

        if ws_col > 0 and ws_row > 0 and ws_xpixel > 0 and ws_ypixel > 0:
            return ws_xpixel / ws_col, ws_ypixel / ws_row
    except Exception:
        pass
    return 10, 20


def get_png_dimensions(data):
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    w, h = struct.unpack('>LL', data[16:24])
    return w, h


def render_latex_to_png(latex_str, dpi=200, fontsize=14, color="#eeeeee", padding=0.0):
    buf = io.BytesIO()

    # Create figure
    fig = plt.figure(figsize=(0.01, 0.01), dpi=dpi)

    # Add text
    text = fig.text(
        0.5, 0.5, latex_str, fontsize=fontsize, color=color, ha="center", va="center"
    )

    try:
        fig.savefig(
            buf,
            format="png",
            dpi=dpi,
            transparent=True,
            bbox_inches="tight",
            pad_inches=padding,
        )
    except Exception as e:
        # Fallback: If 'stix' failed on specific symbols, try standard sans-serif once
        try:
            plt.close(fig)
            matplotlib.rcParams["mathtext.fontset"] = "dejavusans"
            fig = plt.figure(figsize=(0.01, 0.01), dpi=dpi)
            fig.text(0.5, 0.5, latex_str, fontsize=fontsize, color=color, ha="center", va="center")
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=dpi, transparent=True, bbox_inches="tight", pad_inches=padding)
            # Restore stix for next run
            matplotlib.rcParams["mathtext.fontset"] = "stix"
        except Exception:
            return None
    finally:
        plt.close(fig)

    buf.seek(0)
    return buf.getvalue()


def serialize_gr_command(cmd, payload=None):
    cmd_str = ",".join(f"{k}={v}" for k, v in cmd.items())

    if payload:
        b64_data = base64.standard_b64encode(payload)
        output = []
        while len(b64_data) > 0:
            chunk = b64_data[:CHUNK_SIZE]
            b64_data = b64_data[CHUNK_SIZE:]
            m_val = 1 if len(b64_data) > 0 else 0
            header = f"m={m_val};" if output else f"{cmd_str},m={m_val};"
            chunk_str = chunk.decode("ascii")
            ST = chr(27) + chr(92)
            output.append("\x1b_G" + header + chunk_str + ST)
        return "".join(output)
    else:
        ST = chr(27) + chr(92)
        return f"\x1b_G{cmd_str};{ST}"


def display_image_kitty(png_bytes, inline=False, cell_h=20, cols=None, rows=None, y_offset=0):
    if not png_bytes:
        return ("", 0) if not inline else ""

    w, h = get_png_dimensions(png_bytes)
    cmd = {"a": "T", "f": "100", "C": "1"}
    if cols is not None: cmd["c"] = cols
    if rows is not None: cmd["r"] = rows
    if y_offset != 0: cmd["Y"] = int(y_offset)

    if inline:
        return serialize_gr_command(cmd, png_bytes)
    else:
        rows_needed = max(1, math.ceil(h / cell_h))
        return serialize_gr_command(cmd, png_bytes), rows_needed


def parse_input(text):
    pattern = r"(\$\$.*?\$\$|\$(?!\$).*?\$)"
    parts = re.split(pattern, text, flags=re.DOTALL)
    return [p for p in parts if p]


def sanitize_latex(content):
    r"""
    Fixes common Matplotlib parsing issues.
    1. Removes newlines (fixes wrapping).
    2. Converts \le to \leq and \ge to \geq (fixes 'Unknown symbol').
    """
    # Remove newlines
    content = content.replace('\n', ' ')

    # Robust replacement for \le -> \leq, ensuring we don't break \left or \length
    # Regex checks that \le is followed by a non-word character or end of string
    content = re.sub(r'\\le(?![a-zA-Z])', r'\\leq', content)
    content = re.sub(r'\\ge(?![a-zA-Z])', r'\\geq', content)

    return content


def print_buffered_line(line_buffer, cell_w, cell_h):
    if not line_buffer:
        return

    rendered_items = []
    max_rows_up = 0
    max_rows_down = 0

    for item_type, content in line_buffer:
        if item_type == 'text':
            rendered_items.append({'type': 'text', 'content': content})

        elif item_type == 'math':
            scale_factor = 1.0
            target_dpi = 200
            target_fontsize = (cell_h * scale_factor * 72) / target_dpi

            # Sanitize content inside the delimiters
            inner_math = content[1:-1]
            clean_math = sanitize_latex(inner_math)
            latex_wrapped = f"${clean_math}$"

            png_bytes = render_latex_to_png(
                latex_wrapped, dpi=target_dpi, fontsize=target_fontsize,
                color="#eeeeee", padding=0.0
            )

            if png_bytes:
                w, h = get_png_dimensions(png_bytes)
                y_offset = (cell_h - h) // 2
                overflow_threshold = cell_h * 0.2

                rows_up = 0
                if y_offset < 0:
                    abs_overflow_up = abs(y_offset)
                    if abs_overflow_up > overflow_threshold:
                        rows_up = math.ceil(abs_overflow_up / cell_h)

                bottom_y = h + y_offset
                rows_down = 0
                if bottom_y > cell_h:
                    overflow_down = bottom_y - cell_h
                    if overflow_down > overflow_threshold:
                        rows_down = math.ceil(overflow_down / cell_h)

                max_rows_up = max(max_rows_up, rows_up)
                max_rows_down = max(max_rows_down, rows_down)

                rendered_items.append({
                    'type': 'math', 'png': png_bytes, 'w': w, 'y_offset': y_offset
                })
            else:
                rendered_items.append({'type': 'text', 'content': content})

    if max_rows_up > 0:
        sys.stdout.write('\n' * max_rows_up)

    for item in rendered_items:
        if item['type'] == 'text':
            sys.stdout.write(item['content'])
        elif item['type'] == 'math':
            w = item['w']
            png = item['png']
            y_offset = item['y_offset']
            num_spaces = int(w / cell_w) + 1
            spaces = " " * num_spaces

            sys.stdout.write(spaces)
            sys.stdout.write(f"\033[{num_spaces}D")

            if y_offset < 0:
                rows_up_cmd = math.ceil(-y_offset / cell_h)
                final_y_offset = y_offset + (rows_up_cmd * cell_h)
                sys.stdout.write("\0337")
                sys.stdout.write(f"\033[{rows_up_cmd}A")
                sys.stdout.write(display_image_kitty(png, inline=True, cell_h=cell_h, y_offset=final_y_offset))
                sys.stdout.write("\0338")
            else:
                sys.stdout.write(display_image_kitty(png, inline=True, cell_h=cell_h, y_offset=y_offset))

            sys.stdout.write(f"\033[{num_spaces}C")

    sys.stdout.write('\n')
    if max_rows_down > 0:
        sys.stdout.write('\n' * max_rows_down)

    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Render LaTeX to terminal.")
    parser.add_argument("input", nargs="?", help="Input text with LaTeX or path to file.")
    args = parser.parse_args()

    content = ""
    if not sys.stdin.isatty():
        content = sys.stdin.read()
    elif args.input:
        if os.path.isfile(args.input):
            try:
                with open(args.input, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception as e:
                sys.stderr.write(f"Error reading file: {e}\n")
                sys.exit(1)
        else:
            content = args.input
    else:
        sys.stderr.write("Error: No input provided.\n")
        sys.exit(1)

    segments = parse_input(content)
    cell_w, cell_h = get_terminal_cell_dims()
    current_line_buffer = []

    for seg in segments:
        if seg.startswith("$$") and seg.endswith("$$") and len(seg) > 4:
            if current_line_buffer:
                print_buffered_line(current_line_buffer, cell_w, cell_h)
                current_line_buffer = []

            # Sanitize block math
            clean_content = sanitize_latex(seg[2:-2])

            png_bytes = render_latex_to_png(
                f"${clean_content}$", dpi=200, fontsize=24, color="#eeeeee", padding=0.1
            )

            if png_bytes:
                img_seq, rows_needed = display_image_kitty(png_bytes, inline=False, cell_h=cell_h)
                sys.stdout.write("\n")
                for _ in range(rows_needed): sys.stdout.write("\n")
                sys.stdout.flush()
                if rows_needed > 0: sys.stdout.write(f"\033[{rows_needed}A")
                sys.stdout.write("\r")
                sys.stdout.write(img_seq)
                if rows_needed > 0: sys.stdout.write(f"\033[{rows_needed}B")
                sys.stdout.write("\r\n")
            else:
                sys.stdout.write(seg + "\n")

        elif seg.startswith("$") and seg.endswith("$") and len(seg) > 2:
            current_line_buffer.append(('math', seg))
        else:
            parts = seg.split('\n')
            for i, part in enumerate(parts):
                if i > 0:
                    print_buffered_line(current_line_buffer, cell_w, cell_h)
                    current_line_buffer = []
                if part:
                    current_line_buffer.append(('text', part))

    if current_line_buffer:
        print_buffered_line(current_line_buffer, cell_w, cell_h)


if __name__ == "__main__":
    main()