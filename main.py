import argparse
import base64
import io
import re
import sys

import matplotlib

# Force non-interactive backend
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# Set Font to Computer Modern (LaTeX standard)
matplotlib.rcParams["mathtext.fontset"] = "cm"
matplotlib.rcParams["font.family"] = "serif"

# Constants
CHUNK_SIZE = 4096


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


def display_image_kitty(png_bytes, inline=False):
    if not png_bytes:
        return ""

    if inline:
        # For inline: use regular transmission
        # The trick is to write spaces FIRST, then overlay the image
        cmd = {
            "a": "T",
            "f": "100",
            "C": "1",  # Do not move cursor
        }
        return serialize_gr_command(cmd, png_bytes)
    else:
        # For block math, standard display
        cmd = {
            "a": "T",
            "f": "100",
        }
        return serialize_gr_command(cmd, png_bytes)


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

    for seg in segments:
        # --- BLOCK MATH ($$...$$) ---
        if seg.startswith("$$") and seg.endswith("$$") and len(seg) > 4:
            latex_content = seg[2:-2]

            # Big and spacious for block math
            png_bytes = render_latex_to_png(
                f"${latex_content}$", dpi=200, fontsize=24, color="#eeeeee"
            )

            if png_bytes:
                img_seq = display_image_kitty(png_bytes, inline=False)
                sys.stdout.write(f"\n{img_seq}\n")
            else:
                sys.stdout.write(seg)

        # --- INLINE MATH ($...$) ---
        elif seg.startswith("$") and seg.endswith("$") and len(seg) > 2:
            content = seg[1:-1]
            latex_wrapped = f"${content}$"

            # High DPI (sharpness) + Small Font (Physical Size)
            # This combo keeps the image height low (preventing line breaks)
            # but the pixel density high (readable).
            png_bytes = render_latex_to_png(
                latex_wrapped,
                dpi=250,  # Very high sharpness
                fontsize=13,  # Small "physical" size to fit line
                color="#eeeeee",
            )

            if png_bytes:
                # Strategy: write spaces, move cursor back, display image
                spaces = "      "  # 6 spaces for the image
                sys.stdout.write(spaces)
                # Move cursor back to start of spaces
                sys.stdout.write(
                    f"\033[{len(spaces)}D"
                )  # Move left by number of spaces
                
                # Save cursor position
                sys.stdout.write("\0337")
                
                # Now display the image at this position
                img_seq = display_image_kitty(png_bytes, inline=True)
                sys.stdout.write(img_seq)
                
                # Restore cursor position
                sys.stdout.write("\0338")

                # Move cursor forward past the image
                sys.stdout.write(f"\033[{len(spaces)}C")  # Move right
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
