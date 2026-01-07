import argparse
import base64
import io
import re
import sys
import os  # Added for file checking
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
    # IHDR is the first chunk.
    # Offset 16: Width (4 bytes)
    # Offset 20: Height (4 bytes)
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


def main():
    parser = argparse.ArgumentParser(description="Render LaTeX to terminal.")
    parser.add_argument("input", help="Input text with LaTeX or path to file.")
    args = parser.parse_args()

    # --- FILE HANDLING START ---
    content = ""
    # Check if input is a valid file path
    if os.path.isfile(args.input):
        try:
            with open(args.input, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            sys.stderr.write(f"Error reading file: {e}\n")
            sys.exit(1)
    else:
        # Treat as raw text
        content = args.input
    # --- FILE HANDLING END ---

    segments = parse_input(content)

    # Get terminal metrics once
    cell_w, cell_h = get_terminal_cell_dims()
    
    # Track extra rows needed for the current line to clear tall inline images
    current_line_extra_rows = 0

    for seg in segments:
        # --- BLOCK MATH ($$...$$) ---
        if seg.startswith("$$") and seg.endswith("$$") and len(seg) > 4:
            # Before starting block math, ensure we clear any pending extra rows from previous inline math
            if current_line_extra_rows > 0:
                sys.stdout.write("\n" * current_line_extra_rows)
                current_line_extra_rows = 0
                
            latex_content = seg[2:-2]

            # Big and spacious for block math
            # Added padding to prevent overlap
            png_bytes = render_latex_to_png(
                f"${latex_content}$", dpi=200, fontsize=24, color="#eeeeee", padding=0.1
            )

            if png_bytes:
                img_seq, rows_needed = display_image_kitty(png_bytes, inline=False, cell_h=cell_h)

                sys.stdout.write("\n")  # Start on new line
                sys.stdout.flush()

                # Reserve space - write blank lines
                for _ in range(rows_needed):
                    sys.stdout.write("\n")
                sys.stdout.flush()

                # Move cursor back up to draw the image
                if rows_needed > 0:
                    sys.stdout.write(f"\033[{rows_needed}A")  # Move up
                sys.stdout.write("\r")  # Move to column 0
                sys.stdout.flush()

                # Draw the image
                sys.stdout.write(img_seq)
                sys.stdout.flush()

                # Move cursor back down to after the reserved space
                if rows_needed > 0:
                    sys.stdout.write(f"\033[{rows_needed}B")  # Move down
                sys.stdout.write("\r")  # Move to column 0
                sys.stdout.flush()
            else:
                sys.stdout.write(seg)

        # --- INLINE MATH ($...$) ---
        elif seg.startswith("$") and seg.endswith("$") and len(seg) > 2:
            content = seg[1:-1]
            latex_wrapped = f"${content}$"

            # Calculate optimal fontsize to match line height
            # We aim for the image height to match the line height (cell_h)
            # using a fixed high DPI.
            # Factor 0.9 for compromise between size and fit (centering vs overlap)
            target_dpi = 200
            target_fontsize = (cell_h * 0.9 * 72) / target_dpi

            # Padding 0.05
            png_bytes = render_latex_to_png(
                latex_wrapped,
                dpi=target_dpi,
                fontsize=target_fontsize,
                color="#eeeeee",
                padding=0.05
            )

            if png_bytes:
                w, h = get_png_dimensions(png_bytes)

                # Estimate number of spaces needed.
                num_spaces = int(w / cell_w) + 1
                
                # Calculate centered offset
                centered_offset = (cell_h - h) // 2
                
                # Clamp offset to prevent excessive top overlap
                # Allow at most 15% of cell height overlap upwards
                max_up_overlap = int(cell_h * 0.15)
                y_offset = max(centered_offset, -max_up_overlap)
                
                # Calculate if this image is taller than the line (considering the offset)
                # We only care about how much it extends *downwards* for the extra newlines
                bottom_y = h + y_offset
                rows_occupied = math.ceil(bottom_y / cell_h)
                extra_rows = max(0, rows_occupied - 1)
                current_line_extra_rows = max(current_line_extra_rows, extra_rows)

                # Strategy: write spaces, move cursor back, display image
                spaces = " " * num_spaces
                sys.stdout.write(spaces)
                sys.stdout.flush()

                # Move cursor back to start of spaces
                sys.stdout.write(f"\033[{num_spaces}D")
                sys.stdout.flush()

                # Handle negative y_offset by moving cursor up manually
                # This avoids potential issues with negative Y in some terminal implementations
                if y_offset < 0:
                    rows_up = math.ceil(-y_offset / cell_h)
                    final_y_offset = y_offset + (rows_up * cell_h)
                    
                    # Save cursor, move up, display image, restore cursor
                    sys.stdout.write("\0337") # Save cursor (DEC)
                    sys.stdout.write(f"\033[{rows_up}A") # Move up
                    sys.stdout.flush()
                    
                    img_seq = display_image_kitty(png_bytes, inline=True, cell_h=cell_h, y_offset=final_y_offset)
                    sys.stdout.write(img_seq)
                    sys.stdout.flush()
                    
                    sys.stdout.write("\0338") # Restore cursor (DEC)
                    sys.stdout.flush()
                else:
                    img_seq = display_image_kitty(png_bytes, inline=True, cell_h=cell_h, y_offset=y_offset)
                    sys.stdout.write(img_seq)
                    sys.stdout.flush()

                # Move cursor forward past the image
                sys.stdout.write(f"\033[{num_spaces}C")
                sys.stdout.flush()
            else:
                sys.stdout.write(seg)

        # --- PLAIN TEXT ---
        else:
            # Split by newline to handle line tracking
            parts = seg.split('\n')
            for i, part in enumerate(parts):
                sys.stdout.write(part)
                sys.stdout.flush()
                
                # If this is not the last part, we have a newline
                if i < len(parts) - 1:
                    sys.stdout.write('\n')
                    # Apply clearance if needed
                    if current_line_extra_rows > 0:
                        sys.stdout.write('\n' * current_line_extra_rows)
                        current_line_extra_rows = 0
                    sys.stdout.flush()

    # Final newline and clearance
    sys.stdout.write("\n")
    if current_line_extra_rows > 0:
        sys.stdout.write('\n' * current_line_extra_rows)
    sys.stdout.flush()


if __name__ == "__main__":
    main()
