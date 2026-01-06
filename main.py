import sys
import argparse
import re
import io
import base64
import matplotlib
import matplotlib.pyplot as plt

# 1. Set Font to Computer Modern (LaTeX standard)
matplotlib.rcParams['mathtext.fontset'] = 'cm'
matplotlib.rcParams['font.family'] = 'serif'

# Constants
CHUNK_SIZE = 4096

def render_latex_to_png(latex_str, dpi=200, fontsize=20, color='white', pad_inches=0.0, mode='inline'):
    """
    Renders a LaTeX string to a PNG buffer using Matplotlib.
    Returns the bytes of the PNG file.
    """
    buf = io.BytesIO()
    
    fig = plt.figure(figsize=(0.01, 0.01), dpi=dpi)
    
    # Text config
    # Strut for vertical alignment consistency
    if mode == 'inline':
        # Use a strut to define the vertical extent of the line.
        # This ensures that 'a' and 'g' and '\sum' all are rendered relative to this height.
        # When we squash the final image into 1 row (r=1), the baseline should be consistent.
        # alpha=0.0 makes it invisible but it affects the bbox.
        fig.text(0.5, 0.5, "Ag)", fontsize=fontsize, color='white',
                 ha='center', va='center', alpha=0.0)
    
    # Render the actual math
    text = fig.text(0.5, 0.5, latex_str, fontsize=fontsize, color=color,
                    ha='center', va='center')
    
    plt.axis('off')
    ax = fig.gca()
    ax.axis('off')
    
    try:
        fig.savefig(buf, format='png', dpi=dpi, transparent=True, bbox_inches='tight', pad_inches=pad_inches)
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
            
            chunk_str = chunk.decode('ascii')
            ST = chr(27) + chr(92)
            full_seq = "\x1b_G" + header + chunk_str + ST
            output.append(full_seq)
            
        return "".join(output)
    else:
        ST = chr(27) + chr(92)
        return f"\x1b_G{cmd_str};{ST}"

def display_image_kitty(png_bytes, **kwargs):
    if not png_bytes:
        return ""
    
    # Defaults
    cmd = {
        'a': 'T', # Transmit and display
        'f': '100', # PNG
    }
    # Merge kwargs (e.g., r=1)
    cmd.update(kwargs)
    
    return serialize_gr_command(cmd, png_bytes)

def parse_input(text):
    """
    Splits text into:
    - Block Math ($$...$$)
    - Inline Math ($...$)
    - Plain Text
    """
    # Escaped dollars: \$\$
    pattern = r'(\$\$.*?\$\$|\$.*?\$)'
    parts = re.split(pattern, text, flags=re.DOTALL)
    return [p for p in parts if p]

def main():
    parser = argparse.ArgumentParser(description="Render LaTeX to terminal using Kitty Graphics Protocol.")
    parser.add_argument("text", help="Text containing $latex$ or $$latex$$.")
    parser.add_argument("--dpi", type=int, default=150, help="DPI for rendering.")
    args = parser.parse_args()
    
    segments = parse_input(args.text)
    
    for seg in segments:
        # Check for Block Math
        if seg.startswith('$$') and seg.endswith('$$') and len(seg) > 4:
            latex_content = seg[2:-2]
            # Render Block
            # fontsize 24, high dpi.
            png_bytes = render_latex_to_png(f"${latex_content}$", dpi=args.dpi, fontsize=24, color='#eeeeee', pad_inches=0.1, mode='block')
            
            if png_bytes:
                # Block math: displayed as-is (native size or scaled by terminal if huge)
                # We can enforce a height if we want, but usually native is fine for block.
                img_seq = display_image_kitty(png_bytes)
                sys.stdout.write(f"\n{img_seq}\n")
            else:
                sys.stdout.write(seg)
                
        # Check for Inline Math
        elif seg.startswith('$') and seg.endswith('$') and len(seg) > 2:
            content = seg[1:-1]
            latex_wrapped = f"${content}$"
            # Render Inline
            # Use r=1 to force it into a single row height, preventing line breaks.
            # We use high DPI/fontsize in generation to keep it crisp when scaled down.
            png_bytes = render_latex_to_png(latex_wrapped, dpi=200, fontsize=24, color='#eeeeee', pad_inches=0.0, mode='inline')
            if png_bytes:
                # r=1 means 1 row height.
                img_seq = display_image_kitty(png_bytes, r=1)
                sys.stdout.write(img_seq)
            else:
                sys.stdout.write(seg)
                
        # Plain Text
        else:
            sys.stdout.write(seg)
            
    # Trailing newline
    sys.stdout.write("\n")

if __name__ == "__main__":
    main()
