import sys
import argparse
import re
import io
import base64
import matplotlib.pyplot as plt
# We don't strictly need mathtext if we use figure text, but it's part of mpl
from matplotlib import mathtext

# Constants
# Kitty protocol chunk size limit is 4096 bytes of data per chunk.
CHUNK_SIZE = 4096

def render_latex_to_png(latex_str, dpi=200, fontsize=18, color='white'):
    """
    Renders a LaTeX string to a PNG buffer using Matplotlib.
    Returns the bytes of the PNG file.
    """
    buf = io.BytesIO()
    fig = plt.figure(figsize=(0.1, 0.1), dpi=dpi)
    
    # Text config
    # We want transparent background and 'color' foreground.
    text = fig.text(0.5, 0.5, latex_str, fontsize=fontsize, color=color,
                    ha='center', va='center')
    
    plt.axis('off')
    ax = fig.gca()
    ax.axis('off')
    
    try:
        fig.savefig(buf, format='png', dpi=dpi, transparent=True, bbox_inches='tight', pad_inches=0.02)
    except Exception as e:
        sys.stderr.write(f"Error rendering latex: {e}\n")
        return None
    finally:
        plt.close(fig)
        
    buf.seek(0)
    return buf.getvalue()

def serialize_gr_command(cmd, payload=None):
    """
    Serialize a kitty graphics command.
    cmd: dict of keys (a, f, t, etc.)
    payload: bytes (optional)
    """
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
            
            # Use explicit hex to avoid f-string backslash confusion
            chunk_str = chunk.decode('ascii')
            # ST = ESC + Backslash
            ST = chr(27) + chr(92)
            full_seq = "\x1b_G" + header + chunk_str + ST
            output.append(full_seq)
            
        return "".join(output)
    else:
        ST = chr(27) + chr(92)
        return f"\x1b_G{cmd_str};{ST}"

def display_image_kitty(png_bytes):
    """
    Returns the escape sequence to display the PNG bytes inline using Kitty protocol.
    """
    if not png_bytes:
        return ""
    
    cmd = {
        'a': 'T',
        'f': '100',
    }
    
    return serialize_gr_command(cmd, png_bytes)

def parse_input(text):
    """Splits text into plain text and latex segments ($...$)."""
    # Split by $...$
    parts = re.split(r'(\$.*?\$)', text)
    return [p for p in parts if p]

def main():
    parser = argparse.ArgumentParser(description="Render LaTeX to terminal using Kitty Graphics Protocol.")
    parser.add_argument("text", help="Text containing $latex$.")
    parser.add_argument("--dpi", type=int, default=150, help="DPI for rendering.")
    args = parser.parse_args()
    
    segments = parse_input(args.text)
    
    for seg in segments:
        if seg.startswith('$') and seg.endswith('$') and len(seg) > 1:
            # Render Latex
            png_bytes = render_latex_to_png(seg, dpi=args.dpi, color='#eeeeee')
            if png_bytes:
                img_seq = display_image_kitty(png_bytes)
                sys.stdout.write(img_seq)
            else:
                sys.stdout.write(seg)
        else:
            sys.stdout.write(seg)
            
    sys.stdout.write("\n")

if __name__ == "__main__":
    main()