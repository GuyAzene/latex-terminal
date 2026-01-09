"""
Configuration settings for LaTeX Terminal Renderer.
Adjust these values to customize the appearance of rendered equations.
"""

# --- Inline Math Settings ( $...$ ) ---
# Padding adds transparent space around the image to prevent clipping of tall/wide symbols (like arrows).
INLINE_MATH_PADDING = 0.1

# Vertical margins add empty newlines above/below the line containing the math.
# Useful if the math is tall and overlaps with lines above/below.
INLINE_MATH_MARGIN_TOP = 0
INLINE_MATH_MARGIN_BOTTOM = 0

# Scale factor for inline math size relative to line height.
# 1.05 is slightly larger than text, often improving readability.
INLINE_MATH_SCALE_FACTOR = 1.05

# Resolution for inline math images.
INLINE_MATH_DPI = 200


# --- Block Math Settings ( $$...$$ ) ---
# Padding around the block equation image.
BLOCK_MATH_PADDING = 0.1

# Font size for block equations (usually larger than inline).
BLOCK_MATH_FONT_SIZE = 24

# Vertical margins (in newlines) reserved around the block equation.
BLOCK_MATH_MARGIN_TOP = 1
BLOCK_MATH_MARGIN_BOTTOM = 1

# Resolution for block math images.
BLOCK_MATH_DPI = 200
