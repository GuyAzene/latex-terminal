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

# Set Font to Computer Modern (LaTeX standard)
matplotlib.rcParams["mathtext.fontset"] = "cm"
matplotlib.rcParams["font.family"] = "serif"

# Constants
CHUNK_SIZE = 4096


def get_terminal_cell_dims():
    """
    Attempts to get the terminal cell width and height in pixels using ioctl.
    Returns (width, height). Defaults to (10, 20) if it fails.
    """
    try:
        # struct winsize { unsigned short ws_row; unsigned short ws_col; unsigned short ws_xpixel; unsigned short ws_ypixel; };
        buf = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b'\0' * 8)
        ws_row, ws_col, ws_xpixel, ws_ypixel = struct.unpack('HHHH', buf)

        if ws_col > 0 and ws_row > 0 and ws_xpixel > 0 and ws_ypixel > 0:
            return ws_xpixel / ws_col, ws_ypixel / ws_row
    except Exception:
        pass
    return 10, 20


def get_png_dimensions(data):
    """
    Parses the PNG header to get width and height.
    """
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    w, h = struct.unpack('>LL', data[16:24])
    return w, h


def render_latex_to_png(latex_str, dpi=200, fontsize=14, color="#eeeeee", padding=0.0):
    """
    Renders a LaTeX string to a PNG buffer.
    High DPI + Small Font = Sharp image that fits in the line.
    """
    buf = io.BytesIO()

    # Setup Figure
    # We use a tiny figure size and let bbox_inches='tight' expand it.
    fig = plt.figure(figsize=(0.01, 0.01), dpi=dpi)

    # Render text centered.
    # 'va' (vertical alignment) is center to ensure equal padding on top/bottom
    text = fig.text(
        0.5, 0.5, latex_str, fontsize=fontsize, color=color, ha="center", va="center"
    )

    try:
        # Save with transparent background and tight bounding box
        # pad_inches=0 is CRITICAL to remove the "box" around the math
        fig.savefig(
            buf,
            format="png",
            dpi=dpi,
            transparent=True,
            bbox_inches="tight",
            pad_inches=padding,
        )
    except Exception:
        # SILENT FAILURE:
        # If rendering fails (e.g., unknown symbol), return None.
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

            if output:
                header = f"m={m_val};"
            else:
                header = f"{cmd_str},m={m_val};"

            chunk_str = chunk.decode("ascii")
            ST = chr(27) + chr(92)
            full_seq = "\x1b_G" + header + chunk_str + ST
            output.append(full_seq)

        return "".join(output)
    else:
        ST = chr(27) + chr(92)
        return f"\x1b_G{cmd_str};{ST}"


def display_image_kitty(png_bytes, inline=False, cell_h=20, cols=None, rows=None, y_offset=0):
    """
    Display image using Kitty graphics protocol.
    Returns (image_sequence, rows_needed) for block images,
    or just image_sequence for inline images.
    """
    if not png_bytes:
        return ("", 0) if not inline else ""

    w, h = get_png_dimensions(png_bytes)

    cmd = {
        "a": "T",
        "f": "100",
        "C": "1",  # Do not move cursor
    }

    if cols is not None:
        cmd["c"] = cols
    if rows is not None:
        cmd["r"] = rows
    if y_offset != 0:
        cmd["Y"] = int(y_offset)

    if inline:
        return serialize_gr_command(cmd, png_bytes)
    else:
        # For block math, calculate how many terminal rows the image takes
        # Use ceil to ensure we reserve enough space
        rows_needed = max(1, math.ceil(h / cell_h))

        return serialize_gr_command(cmd, png_bytes), rows_needed


def parse_input(text):
    # Regex to capture $$block$$ or $inline$
    pattern = r"(\$\$.*?\$\$|\$(?!\$).*?\$)"
    parts = re.split(pattern, text, flags=re.DOTALL)
    return [p for p in parts if p]


def print_buffered_line(line_buffer, cell_w, cell_h):
    """
    Analyzes a line (mix of text and math), calculates top/bottom padding required,
    and prints it.
    """
    if not line_buffer:
        return

    # 1. Pre-Render and Calculate Dimensions
    rendered_items = []
    max_rows_up = 0
    max_rows_down = 0

    for item_type, content in line_buffer:
        if item_type == 'text':
            rendered_items.append({'type': 'text', 'content': content})

        elif item_type == 'math':
            # UPDATED: Scale factor increased to 0.85 for readability
            scale_factor = 1
            target_dpi = 200
            target_fontsize = (cell_h * scale_factor * 72) / target_dpi

            latex_wrapped = f"${content[1:-1]}$"

            # Use 0.0 padding for tight bounding box
            png_bytes = render_latex_to_png(
                latex_wrapped, dpi=target_dpi, fontsize=target_fontsize,
                color="#eeeeee", padding=0.0
            )

            if png_bytes:
                w, h = get_png_dimensions(png_bytes)

                # Center relative to line height
                y_offset = (cell_h - h) // 2

                # Threshold: Only add padding if overflow is > 20% of line height
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
                    'type': 'math',
                    'png': png_bytes,
                    'w': w,
                    'y_offset': y_offset
                })
            else:
                # Fallback to raw text if render fails
                rendered_items.append({'type': 'text', 'content': content})

    # 2. Print Top Padding (if needed)
    if max_rows_up > 0:
        sys.stdout.write('\n' * max_rows_up)

    # 3. Print the Line Content
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
            sys.stdout.write(f"\033[{num_spaces}D")  # Move cursor back

            # If y_offset is negative (image goes up), we may need to adjust cursor
            if y_offset < 0:
                rows_up_cmd = math.ceil(-y_offset / cell_h)
                final_y_offset = y_offset + (rows_up_cmd * cell_h)

                sys.stdout.write("\0337")  # Save cursor position
                sys.stdout.write(f"\033[{rows_up_cmd}A")  # Move cursor Up
                sys.stdout.write(display_image_kitty(png, inline=True, cell_h=cell_h, y_offset=final_y_offset))
                sys.stdout.write("\0338")  # Restore cursor position
            else:
                sys.stdout.write(display_image_kitty(png, inline=True, cell_h=cell_h, y_offset=y_offset))

            sys.stdout.write(f"\033[{num_spaces}C")  # Move cursor forward

    # 4. End the line and Print Bottom Padding (if needed)
    sys.stdout.write('\n')
    if max_rows_down > 0:
        sys.stdout.write('\n' * max_rows_down)

    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Render LaTeX to terminal.")
    # CHANGE 1: make "input" optional (nargs='?') so the script doesn't fail if called without args
    parser.add_argument("input", nargs="?", help="Input text with LaTeX or path to file.")
    args = parser.parse_args()

    content = ""

    # CHANGE 2: Check if data is being piped into stdin
    if not sys.stdin.isatty():
        content = sys.stdin.read()

    # CHANGE 3: If not piped, check if an argument was provided
    elif args.input:
        if os.path.isfile(args.input):
            try:
                with open(args.input, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception as e:
                sys.stderr.write(f"Error reading file: {e}\n")
                sys.exit(1)
        else:
            # Treat argument as raw text
            content = args.input

    else:
        # No input from pipe OR arguments
        sys.stderr.write("Error: No input provided. Please pipe text or provide an argument.\n")
        parser.print_help()
        sys.exit(1)

    # --- PROCESSING LOGIC (Remains unchanged) ---
    segments = parse_input(content)
    cell_w, cell_h = get_terminal_cell_dims()

    # Buffer to hold atoms for the current line
    current_line_buffer = []

    for seg in segments:
        # --- BLOCK MATH ($$...$$) ---
        if seg.startswith("$$") and seg.endswith("$$") and len(seg) > 4:
            # Flush any pending inline text first
            if current_line_buffer:
                print_buffered_line(current_line_buffer, cell_w, cell_h)
                current_line_buffer = []

            latex_content = seg[2:-2]
            # Block math gets 1.0 scale and slightly more padding
            png_bytes = render_latex_to_png(
                f"${latex_content}$", dpi=200, fontsize=24, color="#eeeeee", padding=0.1
            )

            if png_bytes:
                img_seq, rows_needed = display_image_kitty(png_bytes, inline=False, cell_h=cell_h)

                # Make space
                sys.stdout.write("\n")
                for _ in range(rows_needed): sys.stdout.write("\n")
                sys.stdout.flush()

                # Draw
                if rows_needed > 0: sys.stdout.write(f"\033[{rows_needed}A")
                sys.stdout.write("\r")
                sys.stdout.write(img_seq)
                if rows_needed > 0: sys.stdout.write(f"\033[{rows_needed}B")
                sys.stdout.write("\r\n")
            else:
                sys.stdout.write(seg + "\n")

        # --- INLINE MATH ($...$) ---
        elif seg.startswith("$") and seg.endswith("$") and len(seg) > 2:
            current_line_buffer.append(('math', seg))

        # --- TEXT ---
        else:
            # Text might contain newlines, which split the buffer
            parts = seg.split('\n')
            for i, part in enumerate(parts):
                if i > 0:
                    # We hit a newline in the text -> Flush current buffer
                    print_buffered_line(current_line_buffer, cell_w, cell_h)
                    current_line_buffer = []

                if part:
                    current_line_buffer.append(('text', part))

    # Flush any remaining buffer at end of input
    if current_line_buffer:
        print_buffered_line(current_line_buffer, cell_w, cell_h)


if __name__ == "__main__":
    main()