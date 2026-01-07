import argparse
import base64
import io
import re
import sys
import struct
import fcntl
import termios

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


def render_latex_to_png(latex_str, dpi=200, fontsize=14, color="#eeeeee"):
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
            pad_inches=0.0,
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


def display_image_kitty(png_bytes, inline=False, cell_h=20):
    """
    Display image using Kitty graphics protocol.
    Returns (image_sequence, rows_needed) for block images,
    or just image_sequence for inline images.
    """
    if not png_bytes:
        return ("", 0) if not inline else ""

    if inline:
        # For inline: use regular transmission
        cmd = {
            "a": "T",
            "f": "100",
            "C": "1",  # Do not move cursor
        }
        return serialize_gr_command(cmd, png_bytes)
    else:
        # For block math, calculate how many terminal rows the image takes
        w, h = get_png_dimensions(png_bytes)
        rows_needed = max(1, int((h / cell_h) + 0.5))  # Round to nearest, minimum 1

        cmd = {
            "a": "T",
            "f": "100",
            "C": "1",  # Don't move cursor automatically
        }
        return serialize_gr_command(cmd, png_bytes), rows_needed


def parse_input(text):
    # Regex to capture $$block$$ or $inline$
    pattern = r"(\$\$.*?\$\$|\$(?!\$).*?\$)"
    parts = re.split(pattern, text, flags=re.DOTALL)
    return [p for p in parts if p]


def main():
    parser = argparse.ArgumentParser(description="Render LaTeX to terminal.")
    parser.add_argument("text", help="Input text with LaTeX.")
    args = parser.parse_args()

    segments = parse_input(args.text)

    # Get terminal metrics once
    cell_w, cell_h = get_terminal_cell_dims()

    for seg in segments:
        # --- BLOCK MATH ($$...$$) ---
        if seg.startswith("$$") and seg.endswith("$$") and len(seg) > 4:
            latex_content = seg[2:-2]

            # Big and spacious for block math
            png_bytes = render_latex_to_png(
                f"${latex_content}$", dpi=200, fontsize=24, color="#eeeeee"
            )

            if png_bytes:
                img_seq, rows_needed = display_image_kitty(png_bytes, inline=False, cell_h=cell_h)

                # Strategy for block math:
                # 1. Output newline to start fresh line
                # 2. Reserve space by writing newlines for all rows needed
                # 3. Move cursor back up to where we started
                # 4. Draw the image
                # 5. Move cursor back down to after the reserved space

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
            target_dpi = 200
            target_fontsize = (cell_h * 72) / target_dpi

            png_bytes = render_latex_to_png(
                latex_wrapped,
                dpi=target_dpi,
                fontsize=target_fontsize,
                color="#eeeeee",
            )

            if png_bytes:
                w, h = get_png_dimensions(png_bytes)

                # Estimate number of spaces needed.
                num_spaces = int(w / cell_w) + 1

                # Strategy: write spaces, move cursor back, display image
                spaces = " " * num_spaces
                sys.stdout.write(spaces)
                sys.stdout.flush()

                # Move cursor back to start of spaces
                sys.stdout.write(f"\033[{num_spaces}D")
                sys.stdout.flush()

                # Display the image at this position (inline mode doesn't need row calculation)
                img_seq = display_image_kitty(png_bytes, inline=True, cell_h=cell_h)
                sys.stdout.write(img_seq)
                sys.stdout.flush()

                # Move cursor forward past the image
                sys.stdout.write(f"\033[{num_spaces}C")
                sys.stdout.flush()
            else:
                sys.stdout.write(seg)

        # --- PLAIN TEXT ---
        else:
            sys.stdout.write(seg)

        # Flush immediately to keep order correct
        sys.stdout.flush()

    sys.stdout.write("\n")


if __name__ == "__main__":
    main()