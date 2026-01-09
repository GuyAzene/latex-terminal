import re

# Symbols that are known to render poorly (clipping, missing) in Matplotlib's engine.
# If these are detected, we force the use of the system LaTeX renderer (pdflatex).
FORCE_FALLBACK_SYMBOLS = {
    r"\Longleftarrow", r"\Longrightarrow", r"\Longleftrightarrow",
    r"\impliedby", r"\implies", r"\iff"
}

def requires_system_fallback(latex_str):
    """
    Checks if the LaTeX string contains symbols that require the system renderer.
    """
    return any(sym in latex_str for sym in FORCE_FALLBACK_SYMBOLS)

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
    content = re.sub(r'\\le(?![a-zA-Z])', r'\\leq', content)
    content = re.sub(r'\\ge(?![a-zA-Z])', r'\\geq', content)

    # 3. Fix Absolute Values
    # Matplotlib's mathtext does not always render \lvert and \rvert correctly.
    # We use single backslashes in the raw strings.
    content = content.replace(r'\left\lvert', r'\left|')
    content = content.replace(r'\right\rvert', r'\right|')
    content = content.replace(r'\lvert', '|')
    content = content.replace(r'\rvert', '|')

    # 4. Map Arrows to Prevent Clipping
    # We map semantic names to standard ones and add a zero-width rule for height.
    # \impliedby (<==)
    content = content.replace(r'\impliedby', r'\Longleftarrow\rule{0pt}{2.5ex}')
    # \implies (==>)
    content = content.replace(r'\implies', r'\Longrightarrow\rule{0pt}{2.5ex}')
    # \iff (<==>)
    content = content.replace(r'\iff', r'\Longleftrightarrow\rule{0pt}{2.5ex}')

    return content


def sanitize_for_fallback(latex_str):
    """
    Prepares LaTeX for the system fallback renderer (pdflatex).
    """
    inner = latex_str.strip()
    
    # Strip wrapping $ signs
    if inner.startswith('$') and inner.endswith('$'):
        inner = inner[1:-1]
    if inner.startswith('$') and inner.endswith('$'): 
        inner = inner[1:-1]
        
    # Suppress numbering
    env_pattern = r"\\begin{(align|equation|gather|dmath|multline|eqnarray)}"
    
    def replacer(match):
        env_name = match.group(1)
        return f"\\begin{{{env_name}*}}"

    if re.search(env_pattern, inner):
        final_latex = re.sub(env_pattern, replacer, inner)
        final_latex = re.sub(r"\\end{(align|equation|gather|dmath|multline|eqnarray)}", lambda m: f"\\end{{{m.group(1)}*}}", final_latex)
    else:
        final_latex = inner
        
    return final_latex