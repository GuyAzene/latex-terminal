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

def render_latex_to_png(latex_str, dpi=200, fontsize=28, color='#eeeeee', pad_inches=0.0):
    """
    Renders a LaTeX string to a PNG buffer using Matplotlib.
    Returns the bytes of the PNG file.
    """
    buf = io.BytesIO()
    
    # Create a figure. We use a small size and rely on bbox_inches='tight'
    fig = plt.figure(figsize=(0.01, 0.01), dpi=dpi)
    
    # Render text.
    # va='center' creates an image where the content is roughly centered vertically.
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
    
    cmd = {
        'a': 'T',
        'f': '100',
    }
    cmd.update(kwargs)
    
    return serialize_gr_command(cmd, png_bytes)

def parse_input(text):
    """
    Splits text into:
    - Block Math ($$...$$)
    - Inline Math ($...$)
    - Plain Text
    """
    # Regex explanation:
    # 1. (\$\$.*?\$\$)  -> Match double dollars (Block).
    # 2. (\$(?!\$).*?\$) -> Match single dollar (Inline).
    # We must escape dollars in regex: \$\$ and \$
    pattern = r'(\$\$.*?\$\$|\$(?!\$).*?\$)'
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
            # Render Block - Large, with padding
            png_bytes = render_latex_to_png(f"${latex_content}$", dpi=args.dpi, fontsize=32, color='#eeeeee', pad_inches=0.1)
            
            if png_bytes:
                img_seq = display_image_kitty(png_bytes)
                sys.stdout.write(f"\n{img_seq}\n")
            else:
                sys.stdout.write(seg)
                
        # Check for Inline Math
        elif seg.startswith('$') and seg.endswith('$') and len(seg) > 2:
            content = seg[1:-1]
            latex_wrapped = f"${content}$"
            
            # Render Inline
            # Use natural height to ensure readability (no r=1 squashing).
            # Padding helps center the symbol in the image.
            # Terminals usually align the bottom of the image to the baseline.
            png_bytes = render_latex_to_png(latex_wrapped, dpi=150, fontsize=28, color='#eeeeee', pad_inches=0.02)
            if png_bytes:
                img_seq = display_image_kitty(png_bytes)
                sys.stdout.write(img_seq)
            else:
                sys.stdout.write(seg)
                
        # Plain Text
        else:
            sys.stdout.write(seg)
            
    sys.stdout.write("\n")

if __name__ == "__main__":
    main()
