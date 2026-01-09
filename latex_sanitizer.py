import re

def sanitize_latex(content):
    """
    Sanitizes LaTeX content to ensure compatibility with Matplotlib's mathtext engine
    and to fix common rendering issues (like clipping or missing symbols).
    """
    
    # 1. Remove newlines
    # Matplotlib's single-line rendering doesn't handle newlines well in inline math.
    content = content.replace('\n', ' ')

    # 2. Robust replacements for inequalities
    # Matplotlib sometimes struggles with the short forms \le and \ge if not followed by space.
    # We replace them with the full \leq and \geq versions.
    # Regex lookahead (?![a-zA-Z]) ensures we don't accidentally replace commands like \left.
    content = re.sub(r'\\le(?![a-zA-Z])', r'\\leq', content)
    content = re.sub(r'\\ge(?![a-zA-Z])', r'\\geq', content)

    # 3. Fix Absolute Values
    # Matplotlib's mathtext does not always render \lvert and \rvert correctly or finds them missing.
    # We replace them with the standard pipe character '|', preserving sizing commands.
    content = content.replace(r'\\left\\lvert', r'\\left|')
    content = content.replace(r'\\right\\rvert', r'\\right|')
    content = content.replace(r'\\lvert', '|')
    content = content.replace(r'\\rvert', '|')

    # 4. Map Arrows to Prevent Clipping and Ensure Support
    # The 'implies' family of arrows often gets clipped at the top by Matplotlib's tight bounding box
    # because the glyphs are exceptionally wide and flat, confusing the auto-cropper.
    # We map them to their standard arrow equivalents AND append a vertical phantom (\vphantom{A}).
    # \vphantom{A} adds an invisible character with the height of 'A' to the equation.
    # This forces the bounding box to be taller, ensuring the top of the arrow is not cut off.
    
    # \impliedby (<==)
    content = content.replace(r'\\impliedby', r'\\Longleftarrow\\vphantom{A}')
    
    # \implies (==>)
    content = content.replace(r'\\implies', r'\\Longrightarrow\\vphantom{A}')
    
    # \iff (<==>)
    content = content.replace(r'\\iff', r'\\Longleftrightarrow\\vphantom{A}')

    return content


def sanitize_for_fallback(latex_str):
    """
    Prepares LaTeX for the system fallback renderer (pdflatex).
    Primarily focuses on removing equation numbering which causes layout issues.
    """
    inner = latex_str.strip()
    
    # Strip wrapping $ signs to expose the inner environment
    if inner.startswith('$') and inner.endswith('$'):
        inner = inner[1:-1]
    if inner.startswith('$') and inner.endswith('$'): # Handle double dollars $$...$$
        inner = inner[1:-1]
        
    # Check for display math environments and suppress numbering.
    # We convert numbered environments (like 'align') to their starred versions (like 'align*').
    # Numbered equations produce (1), (2) on the right side, creating a very wide image
    # that scales down poorly in the terminal.
    env_pattern = r"\\begin\{(align|equation|gather|dmath|multline|eqnarray)"}
    
    def replacer(match):
        env_name = match.group(1)
        return f"\\begin{{{env_name}*}}"

    if re.search(env_pattern, inner):
        # Replace \begin{env} with \begin{env*}
        final_latex = re.sub(env_pattern, replacer, inner)
        # Replace \end{env} with \end{env*}
        final_latex = re.sub(r"\\end\{(align|equation|gather|dmath|multline|eqnarray)", lambda m: f"\\end{{{m.group(1)}*}}", final_latex)
    else:
        final_latex = inner
        
    return final_latex
