import re
text = r'Formula: $\sum_{i=0}^n i$ is now readable. Block math: $$\int x dx$$'
pattern = r'(\$\$.*?\$\$|\$(?!\$).*?\$)'
parts = re.split(pattern, text, flags=re.DOTALL)
print(f"Parts: {parts}")
