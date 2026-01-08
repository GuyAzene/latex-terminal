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
import subprocess
import shutil
import tempfile

import matplotlib

# Force non-interactive backend
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# --- FIX: Switch from 'cm' to 'stix' or 'dejavusans' to fix missing symbol errors ---
try:
    matplotlib.rcParams["mathtext.fontset"] = "stix"
    matplotlib.rcParams["font.family"] = "STIXGeneral"
except Exception:
    matplotlib.rcParams["mathtext.fontset"] = "dejavusans"
    matplotlib.rcParams["font.family"] = "sans-serif"

# Configuration
INLINE_MATH_PADDING = 0.0
INLINE_MATH_MARGIN_TOP = 0
INLINE_MATH_MARGIN_BOTTOM = 0
INLINE_MATH_SCALE_FACTOR = 1.0
INLINE_MATH_DPI = 200

BLOCK_MATH_PADDING = 0.1
BLOCK_MATH_MARGIN_TOP = 1
BLOCK_MATH_MARGIN_BOTTOM = 1
BLOCK_MATH_FONT_SIZE = 24
BLOCK_MATH_DPI = 200

# Constants
CHUNK_SIZE = 4096


def get_terminal_cell_dims():
    """
    Attempts to get the terminal cell width and height in pixels using ioctl.
    Returns (cell_w, cell_h, cols, rows). Defaults to (10, 20, 80, 24) if it fails.
    """
    try:
        buf = fcntl.ioctl(sys.stdout.fileno(), termios.TIOCGWINSZ, b'\0' * 8)
        ws_row, ws_col, ws_xpixel, ws_ypixel = struct.unpack('HHHH', buf)

        if ws_col > 0 and ws_row > 0 and ws_xpixel > 0 and ws_ypixel > 0:
            return ws_xpixel / ws_col, ws_ypixel / ws_row, ws_col, ws_row
    except Exception:
        pass
    return 10, 20, 80, 24


def get_png_dimensions(data):
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        return None
    w, h = struct.unpack('>LL', data[16:24])
    return w, h


def render_latex_fallback(latex_str, dpi=200, fontsize=14, color="#eeeeee", padding=0.0):
    """
    Fallback rendering using system pdflatex and ImageMagick's convert.
    Used for complex LaTeX that Matplotlib cannot handle.
    """
    if not shutil.which("pdflatex") or not shutil.which("convert"):
        return None

    color_val = color.lstrip('#')
    
    # Strip wrapping $ to check for environments
    inner = latex_str.strip()
    if inner.startswith('$') and inner.endswith('$'):
        inner = inner[1:-1]
    if inner.startswith('$') and inner.endswith('$'): # Double dollar case
        inner = inner[1:-1]
        
    # Check for display math environments and suppress numbering
    # We convert align -> align*, equation -> equation*, etc.
    # This prevents equation numbers (1, 2, 3...) which cause wide images and bad scaling.
    env_pattern = r"\\begin\{(align|equation|gather|dmath|multline|eqnarray)\}"
    
    def replacer(match):
        env_name = match.group(1)
        return f"\\begin{{{env_name}*}}"

    if re.search(env_pattern, inner):
        # Replace \begin{env} with \begin{env*}
        final_latex = re.sub(env_pattern, replacer, inner)
        # Replace \end{env} with \end{env*}
        final_latex = re.sub(r"\\end\{(align|equation|gather|dmath|multline|eqnarray)\}", lambda m: f"\\end{{{m.group(1)}*}}", final_latex)
    else:
        final_latex = inner
    
    # Use standalone to get tight bounding box
    # \fontsize{sz}{skip} sets the font size
    # Add common color names support
    tex_content = r"""
\documentclass[preview]{standalone}
\usepackage{amsmath}
\usepackage{amssymb}
\usepackage[dvipsnames,svgnames,x11names]{xcolor}
\usepackage{graphicx}
\begin{document}
\fontsize{%f}{%f}\selectfont
\definecolor{currcolor}{HTML}{%s}
\color{currcolor}
%s
\end{document}
""" % (fontsize, fontsize * 1.2, color_val, final_latex)

    with tempfile.TemporaryDirectory() as temp_dir:
        tex_path = os.path.join(temp_dir, "equation.tex")
        pdf_path = os.path.join(temp_dir, "equation.pdf")
        png_path = os.path.join(temp_dir, "equation.png")

        with open(tex_path, "w", encoding="utf-8") as f:
            f.write(tex_content)

        # Run pdflatex
        # We allow it to fail (non-zero exit) as long as PDF is generated
        # because of minor errors like undefined colors (which fallback to black) or font warnings.
        subprocess.run(
            ["pdflatex", "-interaction=nonstopmode", "-output-directory", temp_dir, tex_path],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )

        if not os.path.exists(pdf_path):
            return None

        # Convert PDF to PNG
        pad_px = int(padding * dpi)
        cmd = ["convert", "-density", str(dpi), "-background", "none"]
        if pad_px > 0:
            cmd.extend(["-bordercolor", "none", "-border", str(pad_px)])
        cmd.extend([pdf_path, png_path])

        try:
            subprocess.run(
                cmd,
                check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError:
            return None

        if os.path.exists(png_path):
            with open(png_path, "rb") as f:
                return f.read()
    return None


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
    except Exception:
        # Fallback 1: System LaTeX
        fallback = render_latex_fallback(latex_str, dpi, fontsize, color, padding)
        if fallback:
            plt.close(fig)
            return fallback

        # Fallback 2: Dejavu Sans (for simple missing symbols in MPL)
        try:
            plt.close(fig)
            matplotlib.rcParams["mathtext.fontset"] = "dejavusans"
            fig = plt.figure(figsize=(0.01, 0.01), dpi=dpi)
            fig.text(0.5, 0.5, latex_str, fontsize=fontsize, color=color, ha="center", va="center")
            buf = io.BytesIO()
            fig.savefig(buf, format="png", dpi=dpi, transparent=True, bbox_inches="tight", pad_inches=padding)
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


def display_image_kitty(png_bytes, inline=False, cell_h=20, cols=None, rows=None, y_offset=0, cell_w=10):
    if not png_bytes:
        return ("", 0) if not inline else ""

    w, h = get_png_dimensions(png_bytes)
    cmd = {"a": "T", "f": "100", "C": "1"}
    
    # Calculate dimensions
    rows_needed = 0
    if inline:
         # Inline logic remains mostly the same, usually 1:1 or fitted
         pass
    else:
        # Block display logic
        if cols is not None:
            cmd["c"] = cols
            # Calculate expected height if width is constrained/scaled
            # We assume aspect ratio is preserved by the terminal unless 'r' is also set.
            # However, to reserve lines, we need to know the scaled height.
            # Scale factor = (target_cols * cell_w) / img_w
            
            # If we are scaling UP or DOWN to fit a specific column width:
            target_px_w = cols * cell_w
            scale = target_px_w / w
            scaled_h = h * scale
            rows_needed = max(1, math.ceil(scaled_h / cell_h))
        else:
            # Native size
            rows_needed = max(1, math.ceil(h / cell_h))

    if rows is not None: cmd["r"] = rows
    if y_offset != 0: cmd["Y"] = int(y_offset)

    if inline:
        return serialize_gr_command(cmd, png_bytes)
    else:
        return serialize_gr_command(cmd, png_bytes), rows_needed


def parse_input(text):
    pattern = r"(\$\$.*?\$\$|\$(?!\\$).*?\$)"
    parts = re.split(pattern, text, flags=re.DOTALL)
    return [p for p in parts if p]


def sanitize_latex(content):
    r"""
    Fixes common Matplotlib parsing issues.
    1. Removes newlines (fixes wrapping).
    2. Converts \le to \leq and \ge to \geq (fixes 'Unknown symbol').
    3. Converts \lvert and \rvert to | (fixes 'Unknown symbol').
    """
    # Remove newlines
    content = content.replace('\n', ' ')

    # Robust replacement for \le -> \leq, ensuring we don't break \left or \length
    # Regex checks that \le is followed by a non-word character or end of string
    content = re.sub(r'\\le(?![a-zA-Z])', r'\\leq', content)
    content = re.sub(r'\\ge(?![a-zA-Z])', r'\\geq', content)

    # Fix absolute values for Matplotlib
    content = content.replace(r'\left\lvert', r'\left|')
    content = content.replace(r'\right\rvert', r'\right|')
    content = content.replace(r'\lvert', '|')
    content = content.replace(r'\rvert', '|')

    return content


def print_buffered_line(line_buffer, cell_w, cell_h):
    if not line_buffer:
        return

    rendered_items = []
    max_rows_up = 0
    max_rows_down = 0
    has_math = False

    for item_type, content in line_buffer:
        if item_type == 'text':
            rendered_items.append({'type': 'text', 'content': content})

        elif item_type == 'math':
            has_math = True
            scale_factor = INLINE_MATH_SCALE_FACTOR
            target_dpi = INLINE_MATH_DPI
            target_fontsize = (cell_h * scale_factor * 72) / target_dpi

            # Sanitize content inside the delimiters
            inner_math = content[1:-1]
            clean_math = sanitize_latex(inner_math)
            latex_wrapped = f"${clean_math}$"

            png_bytes = render_latex_to_png(
                latex_wrapped, dpi=target_dpi, fontsize=target_fontsize,
                color="#eeeeee", padding=INLINE_MATH_PADDING
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

    if has_math:
        max_rows_up += INLINE_MATH_MARGIN_TOP
        max_rows_down += INLINE_MATH_MARGIN_BOTTOM

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
                sys.stdout.write(display_image_kitty(png, inline=True, cell_h=cell_h, y_offset=final_y_offset, cell_w=cell_w))
                sys.stdout.write("\0338")
            else:
                sys.stdout.write(display_image_kitty(png, inline=True, cell_h=cell_h, y_offset=y_offset, cell_w=cell_w))

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
    cell_w, cell_h, term_cols, term_rows = get_terminal_cell_dims()
    term_px_width = term_cols * cell_w
    current_line_buffer = []

    for seg in segments:
        if seg.startswith("$$") and seg.endswith("$$") and len(seg) > 4:
            if current_line_buffer:
                print_buffered_line(current_line_buffer, cell_w, cell_h)
                current_line_buffer = []

            # Sanitize block math
            clean_content = sanitize_latex(seg[2:-2])

            png_bytes = render_latex_to_png(
                f"${clean_content}$", dpi=BLOCK_MATH_DPI, fontsize=BLOCK_MATH_FONT_SIZE, 
                color="#eeeeee", padding=BLOCK_MATH_PADDING
            )

            if png_bytes:
                # Calculate if scaling is needed
                w, h = get_png_dimensions(png_bytes)
                display_cols = None
                
                # Check if image width exceeds terminal width
                if w > term_px_width:
                    display_cols = term_cols
                
                # Optional: "Stretch to full width" interpretation
                # If the user strictly wants it to stretch even if smaller:
                # display_cols = term_cols
                # But typically "rendering partially" implies clipping, so 'fit to width' is safe.
                
                img_seq, rows_needed = display_image_kitty(
                    png_bytes, inline=False, cell_h=cell_h, 
                    cols=display_cols, cell_w=cell_w
                )
                
                # Top Margin
                for _ in range(BLOCK_MATH_MARGIN_TOP): sys.stdout.write("\n")

                # Reserve space for image
                for _ in range(rows_needed): sys.stdout.write("\n")
                sys.stdout.flush()

                # Move cursor up to start of image space
                if rows_needed > 0: sys.stdout.write(f"\033[{rows_needed}A")
                sys.stdout.write("\r")
                sys.stdout.write(img_seq)

                # Move cursor down to end of image space
                if rows_needed > 0: sys.stdout.write(f"\033[{rows_needed}B")
                
                # Bottom Margin
                sys.stdout.write("\r")
                for _ in range(BLOCK_MATH_MARGIN_BOTTOM): sys.stdout.write("\n")
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
