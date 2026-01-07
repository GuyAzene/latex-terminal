import re

def parse_input(text):
    # Regex to capture $$block$$ or $inline$
    pattern = r"(\$\$.*?\$\$|\$(?!\$).*?\$)"
    parts = re.split(pattern, text, flags=re.DOTALL)
    return [p for p in parts if p]

print(parse_input("Hello $x$ world"))
