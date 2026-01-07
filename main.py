import argparse
import base64
import io
import re
import sys
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
    Attempts to get the terminal cell width and height in pixels.
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
    fig = plt.figure(figsize=(0.01, 0.01), dpi=dpi)

    # va='center' ensures the math is vertically centered in the image
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
        sys.stderr.write(f"Error rendering latex: {e}\n")
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

    cmd = {
        "a": "T",
        "f": "100",
        "C": "1",  # Do not move cursor
    }

    if cols is not None: cmd["c"] = cols
    if rows is not None: cmd["r"] = rows
    if y_offset != 0:    cmd["Y"] = int(y_offset)

    if inline:
        return serialize_gr_command(cmd, png_bytes)
    else:
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
            # Render Logic
            target_dpi = 200
            target_fontsize = (cell_h * 1.0 * 72) / target_dpi
            latex_wrapped = f"${content[1:-1]}$"

            png_bytes = render_latex_to_png(
                latex_wrapped, dpi=target_dpi, fontsize=target_fontsize,
                color="#eeeeee", padding=0.05
            )

            if png_bytes:
                w, h = get_png_dimensions(png_bytes)

                # Center relative to line height
                y_offset = (cell_h - h) // 2

                # Calculate Overflow UP (Negative y_offset)
                # If y_offset is -30 and cell_h is 20, we are 30px UP.
                # rows_up = ceil(30/20) = 2.
                rows_up = 0
                if y_offset < 0:
                    rows_up = math.ceil(-y_offset / cell_h)

                # Calculate Overflow DOWN
                # Bottom pixel location relative to top of line
                bottom_y = h + y_offset
                rows_occupied = math.ceil(bottom_y / cell_h)
                rows_down = max(0, rows_occupied - 1)

                max_rows_up = max(max_rows_up, rows_up)
                max_rows_down = max(max_rows_down, rows_down)

                rendered_items.append({
                    'type': 'math',
                    'png': png_bytes,
                    'w': w,
                    'y_offset': y_offset
                })
            else:
                # Fallback to text if render fails
                rendered_items.append({'type': 'text', 'content': content})

    # 2. Print Top Padding (Push the baseline down)
    if max_rows_up > 0:
        sys.stdout.write('\n' * max_rows_up)

    # 3. Print the Line Content
    for item in rendered_items:
        if item['type'] == 'text':
            sys.stdout.write(item['content'])

        elif item['type'] == 'math':
            # Logic similar to before, but now we know we have clearance
            w = item['w']
            png = item['png']
            y_offset = item['y_offset']

            num_spaces = int(w / cell_w) + 1
            spaces = " " * num_spaces

            sys.stdout.write(spaces)
            sys.stdout.write(f"\033[{num_spaces}D")  # Move back

            # Adjust y_offset for cursor movement if needed
            # (Kitty handles relative Y, so standard calculation applies)

            # Handle negative y_offset cursor jump
            if y_offset < 0:
                rows_up_cmd = math.ceil(-y_offset / cell_h)
                # Note: We added blank lines ABOVE, so moving cursor up is safe.
                # We need to account for the fact that we might be drawing INTO those blank lines.

                final_y_offset = y_offset + (rows_up_cmd * cell_h)

                sys.stdout.write("\0337")  # Save cursor
                sys.stdout.write(f"\033[{rows_up_cmd}A")  # Move Up
                sys.stdout.write(display_image_kitty(png, inline=True, cell_h=cell_h, y_offset=final_y_offset))
                sys.stdout.write("\0338")  # Restore cursor
            else:
                sys.stdout.write(display_image_kitty(png, inline=True, cell_h=cell_h, y_offset=y_offset))

            sys.stdout.write(f"\033[{num_spaces}C")  # Move forward

    # 4. End the line and Print Bottom Padding
    sys.stdout.write('\n')
    if max_rows_down > 0:
        sys.stdout.write('\n' * max_rows_down)

    sys.stdout.flush()


def main():
    parser = argparse.ArgumentParser(description="Render LaTeX to terminal with padding.")
    parser.add_argument("text", help="Input text with LaTeX.")
    args = parser.parse_args()

    segments = parse_input(args.text)
    cell_w, cell_h = get_terminal_cell_dims()

    # Buffer to hold atoms for the current line
    # List of tuples: ('text', 'string') or ('math', 'latex_string')
    current_line_buffer = []

    for seg in segments:
        # --- BLOCK MATH ($$...$$) ---
        if seg.startswith("$$") and seg.endswith("$$") and len(seg) > 4:
            # 1. Flush any pending inline text
            if current_line_buffer:
                print_buffered_line(current_line_buffer, cell_w, cell_h)
                current_line_buffer = []

            # 2. Render Block Math (Existing Logic)
            latex_content = seg[2:-2]
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